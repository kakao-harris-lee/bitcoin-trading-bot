"""Live scaler for real-time LSTM input preparation.

Loads scaling parameters from database and applies the same transformations
used during training to live market data.
"""

from __future__ import annotations

import logging
import sqlite3
from collections import deque
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)


class LiveScaler:
    """Applies trained scaling transformations to live data.

    Loads global min/max from database and maintains rolling windows
    for rolling min-max scaling.
    """

    # Base columns to scale (fallback when no feature_columns provided)
    BASE_COLUMNS = ["open", "high", "low", "close"]

    def __init__(
        self,
        db_path: str | Path = "data/binance_bitcoin.db",
        rolling_window: int = 720,
        feature_columns: list[str] | None = None,
    ):
        """Initialize LiveScaler.

        Args:
            db_path: Path to database with scaling_params table.
            rolling_window: Window size for rolling min-max (default 720 = 30 days).
            feature_columns: Expected feature columns from model checkpoint.
        """
        self.db_path = Path(db_path)
        self.rolling_window = rolling_window
        self.feature_columns = feature_columns or []

        # Scaling parameters from database
        self.global_params: dict[str, dict[str, float]] = {}

        # Rolling window buffers per column
        self._rolling_buffers: dict[str, deque] = {}

        # Load global scaling params
        self._load_scaling_params()

    def _load_scaling_params(self) -> None:
        """Load global min/max from database."""
        if not self.db_path.exists():
            logger.warning(f"Database not found: {self.db_path}")
            return

        try:
            conn = sqlite3.connect(str(self.db_path))
            cursor = conn.cursor()

            # Check if scaling_params table exists
            cursor.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='scaling_params'"
            )
            if not cursor.fetchone():
                logger.warning("scaling_params table not found in database")
                conn.close()
                return

            # Load parameters
            cursor.execute("SELECT column_name, min_value, max_value FROM scaling_params")
            rows = cursor.fetchall()
            conn.close()

            for col, min_val, max_val in rows:
                self.global_params[col] = {
                    "min": float(min_val) if min_val is not None else 0.0,
                    "max": float(max_val) if max_val is not None else 1.0,
                }

            logger.info(f"Loaded scaling params for {len(self.global_params)} columns")

        except Exception as e:
            logger.error(f"Failed to load scaling params: {e}")

    def scale_row(self, row: dict[str, float]) -> dict[str, float]:
        """Scale a single data row.

        Applies the same recursive scaling chain used by the database:
        for any column X, derive X_scaled and X_scaled_rolling, and repeat
        this rule on derived columns as needed.

        Args:
            row: Dict with raw column values (open, high, low, close, etc).

        Returns:
            Dict with scaled columns matching feature_columns.
        """
        result: dict[str, float] = {}
        self._updated_this_row: set[str] = set()

        base_values: dict[str, float] = {}
        for key, value in row.items():
            if value is None:
                continue
            if isinstance(value, (int, float, np.floating, np.integer)):
                base_values[key] = float(value)

        target_cols = self._get_target_columns()
        for col in target_cols:
            val = self._compute_column(col, base_values, result)
            if val is not None:
                result[col] = val

        return result

    def _get_target_columns(self) -> list[str]:
        """Get the columns we should compute for scaling."""
        if self.feature_columns:
            return list(self.feature_columns)

        cols: list[str] = []
        for col in self.BASE_COLUMNS:
            cols.append(f"{col}_scaled")
            cols.append(f"{col}_scaled_rolling")
        return cols

    def _split_suffix(self, col_name: str) -> tuple[str, str | None]:
        """Split column name into base and suffix operation."""
        if col_name.endswith("_scaled_rolling"):
            return col_name[: -len("_scaled_rolling")], "_scaled_rolling"
        if col_name.endswith("_scaled"):
            return col_name[: -len("_scaled")], "_scaled"
        return col_name, None

    def _ensure_buffer_updated(self, col_name: str, value: float) -> None:
        """Ensure rolling buffer for a column includes the current value."""
        if col_name in self._updated_this_row:
            return
        buffer = self._rolling_buffers.setdefault(col_name, deque(maxlen=self.rolling_window))
        buffer.append(value)
        self._updated_this_row.add(col_name)

    def _global_scale(self, col_name: str, value: float) -> float:
        """Apply global min-max scaling using stored params."""
        params = self.global_params.get(col_name, {"min": 0.0, "max": 1.0})
        min_val = params.get("min", 0.0)
        max_val = params.get("max", 1.0)
        range_val = max_val - min_val
        if range_val <= 0:
            return 0.5
        return (value - min_val) / range_val

    def _rolling_scale(self, col_name: str, value: float) -> float:
        """Apply rolling min-max scaling using the column buffer."""
        self._ensure_buffer_updated(col_name, value)
        buffer = self._rolling_buffers[col_name]
        if len(buffer) < 2:
            return 0.5
        r_min = min(buffer)
        r_max = max(buffer)
        r_range = r_max - r_min
        if r_range <= 0:
            return 0.5
        return (value - r_min) / r_range

    def _compute_column(
        self,
        col_name: str,
        base_values: dict[str, float],
        cache: dict[str, float],
    ) -> float | None:
        """Compute a column value recursively from base values."""
        if col_name in cache:
            return cache[col_name]

        if col_name in base_values:
            value = base_values[col_name]
            self._ensure_buffer_updated(col_name, value)
            cache[col_name] = value
            return value

        base_name, op = self._split_suffix(col_name)
        if op is None:
            return None

        base_val = self._compute_column(base_name, base_values, cache)
        if base_val is None:
            return None

        if op == "_scaled":
            value = self._global_scale(base_name, base_val)
        else:
            value = self._rolling_scale(base_name, base_val)

        self._ensure_buffer_updated(col_name, value)
        cache[col_name] = value
        return value

    def prepare_sequence(
        self,
        history: list[dict[str, float]],
    ) -> pd.DataFrame | None:
        """Prepare scaled sequence for LSTM input.

        Args:
            history: List of OHLC dicts (oldest first).

        Returns:
            DataFrame with scaled columns or None if insufficient data.
        """
        if not history:
            return None

        # Reset rolling buffers for fresh sequence
        self._rolling_buffers.clear()

        # Scale each row in sequence
        scaled_rows = []
        for row in history:
            scaled = self.scale_row(row)
            scaled_rows.append(scaled)

        df = pd.DataFrame(scaled_rows)

        # Ensure all feature columns exist
        for col in self.feature_columns:
            if col not in df.columns:
                df[col] = 0.5  # Default value

        return df

    def get_feature_array(
        self,
        history: list[dict[str, float]],
    ) -> np.ndarray | None:
        """Get feature array ready for LSTM input.

        Args:
            history: List of OHLC dicts (oldest first).

        Returns:
            NumPy array (seq_len, n_features) or None.
        """
        df = self.prepare_sequence(history)
        if df is None:
            return None

        # Select feature columns in order
        available = [c for c in self.feature_columns if c in df.columns]
        if len(available) < len(self.feature_columns):
            logger.warning(
                f"Missing columns: {len(available)}/{len(self.feature_columns)}"
            )

        features = df[available].values
        return np.nan_to_num(features, nan=0.5).astype(np.float32)

    def scale_dataframe_vectorized(self, df: pd.DataFrame) -> pd.DataFrame:
        """Scale entire DataFrame using vectorized pandas operations.

        This is ~100x faster than row-by-row scaling for large DataFrames.
        Uses pandas rolling() for rolling min-max instead of deque loops.

        Args:
            df: DataFrame with OHLCV columns (lowercase).

        Returns:
            DataFrame with scaled columns matching feature_columns.
        """
        result = pd.DataFrame(index=df.index)

        # Normalize column names to lowercase
        col_map = {c: c.lower() for c in df.columns}
        df_norm = df.rename(columns=col_map)

        # Process each base column
        for col in self.BASE_COLUMNS:
            if col not in df_norm.columns:
                continue

            values = df_norm[col].astype(float)

            # Global scaling: (value - global_min) / (global_max - global_min)
            params = self.global_params.get(col, {"min": 0.0, "max": 1.0})
            g_min = params.get("min", 0.0)
            g_max = params.get("max", 1.0)
            g_range = g_max - g_min
            if g_range > 0:
                scaled = (values - g_min) / g_range
            else:
                scaled = pd.Series(0.5, index=df.index)
            result[f"{col}_scaled"] = scaled

            # Rolling scaling: (value - rolling_min) / (rolling_max - rolling_min)
            r_min = values.rolling(window=self.rolling_window, min_periods=1).min()
            r_max = values.rolling(window=self.rolling_window, min_periods=1).max()
            r_range = r_max - r_min
            # Avoid division by zero
            r_range = r_range.replace(0, np.nan)
            rolling_scaled = (values - r_min) / r_range
            rolling_scaled = rolling_scaled.fillna(0.5)
            result[f"{col}_scaled_rolling"] = rolling_scaled

        # Ensure all feature columns exist
        for col in self.feature_columns:
            if col not in result.columns:
                result[col] = 0.5

        return result

    def get_scaled_windows(
        self,
        scaled_df: pd.DataFrame,
        window_size: int = 720,
        indices: list[int] | None = None,
    ) -> dict[int, np.ndarray]:
        """Extract pre-scaled windows for batch LSTM input.

        Args:
            scaled_df: Pre-scaled DataFrame from scale_dataframe_vectorized().
            window_size: LSTM sequence length.
            indices: Specific row indices to extract windows for.
                    If None, extracts for all valid indices.

        Returns:
            Dict mapping row index to feature array (window_size, n_features).
        """
        windows = {}
        n_rows = len(scaled_df)

        # Select feature columns in order
        available = [c for c in self.feature_columns if c in scaled_df.columns]
        if not available:
            available = [c for c in scaled_df.columns]

        # Convert to numpy for faster slicing
        values = scaled_df[available].values.astype(np.float32)
        values = np.nan_to_num(values, nan=0.5)

        if indices is None:
            indices = list(range(window_size, n_rows))

        for i in indices:
            if i < window_size:
                continue
            start = i - window_size
            windows[i] = values[start:i]

        return windows
