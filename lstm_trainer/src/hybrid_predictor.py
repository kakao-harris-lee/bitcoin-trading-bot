"""Hybrid Predictor combining LSTM and RandomForest.

Unified inference class that:
1. Runs LSTM for price delta prediction
2. Uses RF to filter noisy predictions
3. Returns filtered prediction with confidence score
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

from .hybrid_model import HybridLSTM
from .noise_filter import NoiseFilterRF

logger = logging.getLogger(__name__)


class HybridPredictor:
    """Unified predictor combining LSTM and RF noise filter.

    Provides a single interface for:
    - Price delta prediction
    - Confidence scoring
    - Signal generation (BUY/SELL/HOLD)
    """

    # Direction class mapping
    DIRECTION_CLASSES = {0: "DOWN", 1: "SIDEWAYS", 2: "UP"}

    def __init__(
        self,
        model_path: str | Path | None = None,
        rf_path: str | Path | None = None,
        input_size: int = 22,
        hidden_size: int = 64,
        seq_len: int = 60,
        device: str = "cpu",
    ):
        """Initialize HybridPredictor.

        Args:
            model_path: Path to trained LSTM model (.pth).
            rf_path: Path to trained RF model (.pkl).
            input_size: Number of input features.
            hidden_size: LSTM hidden state dimension.
            seq_len: Sequence length for LSTM input.
            device: Device for inference ('cpu' or 'cuda').
        """
        self.input_size = input_size
        self.hidden_size = hidden_size
        self.seq_len = seq_len
        self.device = torch.device(device)

        # Initialize LSTM
        self.lstm = HybridLSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=2,
            dropout=0.0,  # No dropout in inference
        )
        self.lstm.to(self.device)
        self.lstm.eval()

        # Load LSTM weights if provided
        if model_path and Path(model_path).exists():
            self._load_lstm(model_path)

        # Initialize/load RF
        if rf_path and Path(rf_path).exists():
            self.rf = NoiseFilterRF.load(rf_path)
        else:
            self.rf = NoiseFilterRF()

        # Scaled column names (must match training)
        self.scaled_columns = self._get_scaled_columns()

    def _get_scaled_columns(self) -> list[str]:
        """Get list of scaled column names for input features.

        Returns the first N scaled columns sorted alphabetically,
        matching the training data column selection.
        """
        # These are dynamically selected at inference time from available columns
        # Return None to signal that columns should be discovered from data
        return None

    def _discover_scaled_columns(self, df: pd.DataFrame) -> list[str]:
        """Discover scaled columns from DataFrame.

        Args:
            df: DataFrame with scaled columns.

        Returns:
            List of scaled column names, sorted and limited to input_size.
        """
        scaled_cols = [c for c in df.columns if c.endswith("_scaled") or c.endswith("_scaled_rolling")]
        scaled_cols = sorted(scaled_cols)[:self.input_size]
        return scaled_cols

    def _load_lstm(self, path: str | Path) -> None:
        """Load LSTM weights from checkpoint.

        Args:
            path: Path to .pth file.
        """
        path = Path(path)
        checkpoint = torch.load(path, map_location=self.device, weights_only=False)

        if "model_state_dict" in checkpoint:
            self.lstm.load_state_dict(checkpoint["model_state_dict"])
        else:
            self.lstm.load_state_dict(checkpoint)

        logger.info(f"Loaded HybridLSTM from {path}")

    def prepare_input(self, df: pd.DataFrame) -> torch.Tensor | None:
        """Prepare input tensor from DataFrame.

        Args:
            df: DataFrame with scaled columns.

        Returns:
            Input tensor (1, seq_len, features) or None if insufficient data.
        """
        # Discover scaled columns from data
        if self.scaled_columns is None:
            self.scaled_columns = self._discover_scaled_columns(df)

        # Check for required columns
        available_cols = [c for c in self.scaled_columns if c in df.columns]
        if len(available_cols) < self.input_size:
            logger.warning(
                f"Missing scaled columns. Have {len(available_cols)}, need {self.input_size}"
            )
            return None

        # Get last seq_len rows
        if len(df) < self.seq_len:
            logger.warning(f"Insufficient data: {len(df)} rows, need {self.seq_len}")
            return None

        # Extract features
        features = df[available_cols].tail(self.seq_len).values

        # Handle NaN values
        if np.isnan(features).any():
            features = np.nan_to_num(features, nan=0.0)

        # Convert to tensor
        x = torch.tensor(features, dtype=torch.float32).unsqueeze(0)
        return x.to(self.device)

    def predict(
        self,
        df: pd.DataFrame,
        market_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Run hybrid prediction pipeline.

        Args:
            df: DataFrame with scaled OHLCV data.
            market_context: Dict with mfi, adx, volatility, regime, breakout_signal.

        Returns:
            Dict with:
                - prediction: Filtered price delta prediction
                - raw_prediction: Raw LSTM prediction (before filtering)
                - confidence: RF confidence score (0-1)
                - direction: Predicted direction (UP/DOWN/SIDEWAYS)
                - signal: Trading signal (BUY/SELL/HOLD)
        """
        # Prepare input
        x = self.prepare_input(df)
        if x is None:
            return self._empty_result()

        # Run LSTM
        with torch.no_grad():
            output = self.lstm(x)
            raw_pred = output["price_delta"].item()
            hidden_state = output["hidden_state"].cpu().numpy().flatten()
            direction_logits = output["direction_logits"]
            direction_idx = direction_logits.argmax(dim=1).item()

        # Run RF noise filter
        filtered_pred, confidence = self.rf.predict_confidence(
            lstm_pred=raw_pred,
            hidden_state=hidden_state,
            market_context=market_context,
        )

        # Determine signal
        signal = self._determine_signal(filtered_pred, confidence)

        return {
            "prediction": filtered_pred,
            "raw_prediction": raw_pred,
            "confidence": confidence,
            "direction": self.DIRECTION_CLASSES.get(direction_idx, "SIDEWAYS"),
            "direction_logits": direction_logits.cpu().numpy().flatten().tolist(),
            "signal": signal,
            "hidden_state": hidden_state,
        }

    def _determine_signal(
        self,
        prediction: float,
        confidence: float,
        pred_threshold: float = 0.01,
        conf_threshold: float = 0.6,
    ) -> str:
        """Determine trading signal from prediction and confidence.

        Args:
            prediction: Filtered price delta prediction.
            confidence: RF confidence score.
            pred_threshold: Minimum prediction magnitude for signal.
            conf_threshold: Minimum confidence for signal.

        Returns:
            Signal string: "BUY", "SELL", or "HOLD".
        """
        if confidence < conf_threshold:
            return "HOLD"

        if prediction > pred_threshold:
            return "BUY"
        elif prediction < -pred_threshold:
            return "SELL"
        else:
            return "HOLD"

    def _empty_result(self) -> dict[str, Any]:
        """Return empty result for failed predictions."""
        return {
            "prediction": 0.0,
            "raw_prediction": 0.0,
            "confidence": 0.0,
            "direction": "SIDEWAYS",
            "direction_logits": [0.0, 1.0, 0.0],
            "signal": "HOLD",
            "hidden_state": np.zeros(self.hidden_size),
        }

    def save(self, model_path: str | Path, rf_path: str | Path) -> None:
        """Save both LSTM and RF models.

        Args:
            model_path: Path to save LSTM model.
            rf_path: Path to save RF model.
        """
        model_path = Path(model_path)
        model_path.parent.mkdir(parents=True, exist_ok=True)

        torch.save(
            {
                "model_state_dict": self.lstm.state_dict(),
                "input_size": self.input_size,
                "hidden_size": self.hidden_size,
                "seq_len": self.seq_len,
            },
            model_path,
        )
        logger.info(f"Saved HybridLSTM to {model_path}")

        self.rf.save(rf_path)

    @classmethod
    def load(
        cls,
        model_path: str | Path,
        rf_path: str | Path,
        device: str = "cpu",
    ) -> "HybridPredictor":
        """Load predictor from saved models.

        Args:
            model_path: Path to LSTM model.
            rf_path: Path to RF model.
            device: Device for inference.

        Returns:
            Loaded HybridPredictor instance.
        """
        model_path = Path(model_path)
        if not model_path.exists():
            logger.warning(f"LSTM model not found at {model_path}")
            return cls(device=device)

        # Load checkpoint to get config
        checkpoint = torch.load(model_path, map_location=device, weights_only=False)

        input_size = checkpoint.get("input_size", 22)
        hidden_size = checkpoint.get("hidden_size", 64)
        seq_len = checkpoint.get("seq_len", 60)

        return cls(
            model_path=model_path,
            rf_path=rf_path,
            input_size=input_size,
            hidden_size=hidden_size,
            seq_len=seq_len,
            device=device,
        )
