"""RF Probability Service for regime-aware strategies.

Provides RF (Random Forest) confidence scores from HybridPredictor (LSTM + RF)
to any strategy component that needs probability-based filtering.

Usage:
    service = RFProbabilityService.get_instance()
    result = service.get_probability(df, market_context)
    # result = {'confidence': 0.75, 'direction': 'UP', 'signal': 'BUY'}
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any
import threading

import pandas as pd

logger = logging.getLogger(__name__)

# Default model paths
DEFAULT_LSTM_PATH = "lstm_trainer/models/hybrid_lstm.pth"
DEFAULT_RF_PATH = "lstm_trainer/models/noise_filter_rf.pkl"


class RFProbabilityService:
    """Singleton service for RF probability calculation.

    Wraps HybridPredictor to provide RF confidence scores for regime filtering.
    Lazy-loads models on first use to avoid startup overhead.
    Thread-safe singleton pattern.
    """

    _instance: "RFProbabilityService | None" = None
    _lock = threading.Lock()

    def __init__(
        self,
        lstm_path: str = DEFAULT_LSTM_PATH,
        rf_path: str = DEFAULT_RF_PATH,
    ):
        """Initialize service (use get_instance() instead).

        Args:
            lstm_path: Path to LSTM model file.
            rf_path: Path to RF model file.
        """
        self.lstm_path = lstm_path
        self.rf_path = rf_path
        self._predictor = None
        self._available: bool | None = None
        self._scaler = None

    @classmethod
    def get_instance(
        cls,
        lstm_path: str = DEFAULT_LSTM_PATH,
        rf_path: str = DEFAULT_RF_PATH,
    ) -> "RFProbabilityService":
        """Get singleton instance of the service.

        Args:
            lstm_path: Path to LSTM model file.
            rf_path: Path to RF model file.

        Returns:
            Singleton RFProbabilityService instance.
        """
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(lstm_path, rf_path)
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        """Reset singleton instance (for testing)."""
        with cls._lock:
            cls._instance = None

    def _ensure_predictor(self) -> bool:
        """Lazy-load HybridPredictor on first use.

        Returns:
            True if predictor is available, False otherwise.
        """
        if self._available is not None:
            return self._available

        try:
            # Check if model files exist
            lstm_exists = Path(self.lstm_path).exists()
            rf_exists = Path(self.rf_path).exists()

            if not lstm_exists:
                logger.warning(f"LSTM model not found at {self.lstm_path}")
                self._available = False
                return False

            if not rf_exists:
                logger.warning(f"RF model not found at {self.rf_path}")
                self._available = False
                return False

            # Import and load HybridPredictor
            from lstm_trainer.src.hybrid_predictor import HybridPredictor

            self._predictor = HybridPredictor.load(
                model_path=self.lstm_path,
                rf_path=self.rf_path,
                device="cpu",
            )

            # Load LiveScaler for feature scaling with model's feature columns
            try:
                from lstm_trainer.src.live_scaler import LiveScaler

                # Get feature columns from predictor
                feature_cols = getattr(self._predictor, "scaled_columns", None)
                if feature_cols:
                    self._scaler = LiveScaler(
                        rolling_window=720,
                        feature_columns=feature_cols,
                    )
                    logger.info(
                        f"LiveScaler initialized with {len(feature_cols)} feature columns"
                    )
                else:
                    self._scaler = LiveScaler(rolling_window=720)
                    logger.info("LiveScaler initialized with default columns")
            except ImportError:
                logger.warning("LiveScaler not available, using raw features")
                self._scaler = None

            self._available = True
            logger.info(f"HybridPredictor loaded from {self.lstm_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to load HybridPredictor: {e}")
            self._available = False
            return False

    def get_probability(
        self,
        df: pd.DataFrame,
        mfi: float = 50.0,
        adx: float = 20.0,
        volatility: float = 0.02,
        regime: str = "SIDEWAYS_FLAT",
        breakout_signal: int = 0,
    ) -> dict[str, Any]:
        """Get RF probability for current market state.

        Args:
            df: DataFrame with OHLCV data (needs at least 60 rows).
            mfi: Money Flow Index value.
            adx: ADX value.
            volatility: ATR/close ratio.
            regime: Current regime classification.
            breakout_signal: 1 if VBS breakout, 0 otherwise.

        Returns:
            Dict with:
                - confidence: RF confidence score (0-1)
                - direction: Predicted direction (UP/DOWN/SIDEWAYS)
                - signal: Trading signal (BUY/SELL/HOLD)
                - available: True if RF model is available
        """
        # Default result (RF not available)
        default_result = {
            "confidence": 0.0,
            "direction": "SIDEWAYS",
            "signal": "HOLD",
            "available": False,
        }

        # Check if predictor is available
        if not self._ensure_predictor():
            return default_result

        try:
            # Prepare scaled data
            if self._scaler is not None:
                # Use LiveScaler to prepare features
                scaled_df = self._prepare_scaled_data(df)
                if scaled_df is None:
                    return default_result
            else:
                scaled_df = df

            # Build market context for RF
            market_context = {
                "mfi": mfi,
                "adx": adx,
                "volatility": volatility,
                "regime": regime,
                "breakout_signal": breakout_signal,
            }

            # Run prediction
            result = self._predictor.predict(scaled_df, market_context)

            return {
                "confidence": result.get("confidence", 0.0),
                "direction": result.get("direction", "SIDEWAYS"),
                "signal": result.get("signal", "HOLD"),
                "available": True,
            }

        except Exception as e:
            logger.debug(f"RF prediction failed: {e}")
            return default_result

    def _prepare_scaled_data(self, df: pd.DataFrame) -> pd.DataFrame | None:
        """Prepare scaled features for LSTM input.

        Args:
            df: Raw OHLCV DataFrame with columns: open, high, low, close, volume.

        Returns:
            DataFrame with scaled features, or None if insufficient data.
        """
        if self._scaler is None:
            return df

        try:
            # Need sufficient history for scaling
            if len(df) < 60:
                return None

            # Convert DataFrame to list of dicts for LiveScaler (vectorized)
            # LiveScaler expects: [{'open': x, 'high': y, 'low': z, 'close': w}, ...]
            # Normalize column names to lowercase
            col_map = {c: c.lower() for c in df.columns}
            df_norm = df.rename(columns=col_map)

            # Build history using to_dict (much faster than iterrows)
            cols = ['open', 'high', 'low', 'close']
            available_cols = [c for c in cols if c in df_norm.columns]
            history = df_norm[available_cols].to_dict('records')

            # Add volume if available
            if 'volume' in df_norm.columns:
                vol_values = df_norm['volume'].tolist()
                for i, h in enumerate(history):
                    h['volume'] = float(vol_values[i])

            # Use LiveScaler.prepare_sequence() to get scaled DataFrame
            scaled_df = self._scaler.prepare_sequence(history)
            return scaled_df

        except Exception as e:
            logger.debug(f"Failed to scale data: {e}")
            return None

    def is_available(self) -> bool:
        """Check if RF probability service is available.

        Returns:
            True if models are loaded and ready.
        """
        return self._ensure_predictor()

    def precompute_batch(
        self,
        df: pd.DataFrame,
        indicators_df: pd.DataFrame | None = None,
        window_size: int = 720,
        min_history: int = 60,
        sample_interval: int = 6,
    ) -> dict[int, dict[str, Any]]:
        """Pre-compute RF predictions for entire DataFrame (backtest optimization).

        Runs LSTM+RF at intervals and fills gaps with last known value.
        With sample_interval=6 (every 6 hours for hourly data), reduces
        43k inferences to ~7k, making backtest ~6x faster.

        Args:
            df: Full OHLCV DataFrame for backtest.
            indicators_df: DataFrame with indicators (mfi, adx, atr, regime, etc.).
                          If None, uses df directly.
            window_size: Rolling window size for LSTM input.
            min_history: Minimum rows needed before predictions start.
            sample_interval: Compute RF every N candles (default 6 = every 6 hours).

        Returns:
            Dict mapping row index to prediction result.
        """
        cache: dict[int, dict[str, Any]] = {}
        default_result = {
            "confidence": 0.0,
            "direction": "SIDEWAYS",
            "signal": "HOLD",
            "available": False,
        }

        if not self._ensure_predictor():
            logger.warning("RF predictor not available, returning empty cache")
            return cache

        ind_df = indicators_df if indicators_df is not None else df
        total_rows = len(df)
        logger.info(f"Pre-computing RF predictions for {total_rows:,} rows...")

        # Pre-scale all data once using vectorized operations
        try:
            if self._scaler is not None:
                # Normalize column names
                col_map = {c: c.lower() for c in df.columns}
                df_norm = df.rename(columns=col_map)
                cols = ['open', 'high', 'low', 'close']
                available_cols = [c for c in cols if c in df_norm.columns]
                full_history = df_norm[available_cols].to_dict('records')
                if 'volume' in df_norm.columns:
                    vol_values = df_norm['volume'].tolist()
                    for i, h in enumerate(full_history):
                        h['volume'] = float(vol_values[i])
            else:
                full_history = None
        except Exception as e:
            logger.warning(f"Failed to prepare history: {e}")
            full_history = None

        # Batch predict with subsampling for speed
        # Only compute at intervals, fill gaps with last known value
        sample_points = list(range(min_history, total_rows, sample_interval))
        num_samples = len(sample_points)
        logger.info(f"RF subsampling: {num_samples:,} samples (interval={sample_interval})")

        last_result = default_result
        last_log = 0

        for idx, i in enumerate(sample_points):
            # Progress logging every 10%
            progress = int((idx / num_samples) * 100)
            if progress >= last_log + 10:
                logger.info(f"RF batch progress: {progress}% ({idx:,}/{num_samples:,})")
                last_log = progress

            try:
                # Get window slice
                start_idx = max(0, i - window_size)

                if full_history is not None and self._scaler is not None:
                    # Use pre-computed history slice
                    history_slice = full_history[start_idx:i+1]
                    scaled_df = self._scaler.prepare_sequence(history_slice)
                else:
                    scaled_df = df.iloc[start_idx:i+1]

                if scaled_df is None or len(scaled_df) < min_history:
                    # Fill this sample point and gap with last result
                    for j in range(i, min(i + sample_interval, total_rows)):
                        cache[j] = last_result
                    continue

                # Get indicators for this row
                row = ind_df.iloc[i]
                close = float(row.get('close', row.get('Close', 0)))
                atr = float(row.get('atr', 0))
                volatility = atr / close if close > 0 else 0.0

                market_context = {
                    "mfi": float(row.get('mfi', 50.0)),
                    "adx": float(row.get('adx', 20.0)),
                    "volatility": volatility,
                    "regime": str(row.get('regime', 'SIDEWAYS_FLAT')),
                    "breakout_signal": int(row.get('breakout_signal', 0)),
                }

                result = self._predictor.predict(scaled_df, market_context)
                computed_result = {
                    "confidence": result.get("confidence", 0.0),
                    "direction": result.get("direction", "SIDEWAYS"),
                    "signal": result.get("signal", "HOLD"),
                    "available": True,
                }

                # Fill this sample point and subsequent gap with computed result
                for j in range(i, min(i + sample_interval, total_rows)):
                    cache[j] = computed_result

                last_result = computed_result

            except Exception as e:
                logger.debug(f"RF prediction failed at index {i}: {e}")
                # Fill gap with last known result
                for j in range(i, min(i + sample_interval, total_rows)):
                    cache[j] = last_result

        # Fill any remaining rows before min_history with default
        for i in range(min_history):
            cache[i] = default_result

        logger.info(f"RF batch complete: {len(cache):,} predictions cached ({num_samples} inferences)")
        return cache

    def get_cached_probability(
        self,
        cache: dict[int, dict[str, Any]],
        index: int,
    ) -> dict[str, Any]:
        """Get probability from pre-computed cache.

        Args:
            cache: Cache dict from precompute_batch().
            index: Row index to look up.

        Returns:
            Cached prediction result or default if not found.
        """
        return cache.get(index, {
            "confidence": 0.0,
            "direction": "SIDEWAYS",
            "signal": "HOLD",
            "available": False,
        })


# Convenience function for quick access
def get_rf_probability(
    df: pd.DataFrame,
    mfi: float = 50.0,
    adx: float = 20.0,
    volatility: float = 0.02,
    regime: str = "SIDEWAYS_FLAT",
    breakout_signal: int = 0,
) -> dict[str, Any]:
    """Get RF probability using singleton service.

    Convenience function that uses the singleton RFProbabilityService.

    Args:
        df: DataFrame with OHLCV data.
        mfi: Money Flow Index value.
        adx: ADX value.
        volatility: ATR/close ratio.
        regime: Current regime classification.
        breakout_signal: 1 if VBS breakout, 0 otherwise.

    Returns:
        Dict with confidence, direction, signal, available.
    """
    service = RFProbabilityService.get_instance()
    return service.get_probability(df, mfi, adx, volatility, regime, breakout_signal)
