"""
LSTM Trend Predictor for production inference.

This module provides CPU-only inference for the trained LSTM model.
The model predicts H4 trend direction (UP/DOWN/SIDEWAYS) based on
the last 60 H4 candles.

Usage:
    predictor = LSTMTrendPredictor("models/trading_lstm.pth")
    result = predictor.predict(df_h4)  # df with OHLCV columns
    # result = {"trend": "UP", "confidence": 0.75}
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

# Lazy import torch to avoid loading it when not needed
_torch = None
_model_class = None


def _get_torch():
    """Lazy import torch."""
    global _torch
    if _torch is None:
        import torch
        _torch = torch
    return _torch


def _get_model_class():
    """Lazy import TrendLSTM model class."""
    global _model_class
    if _model_class is None:
        import sys
        from pathlib import Path

        # Add lstm_trainer to path if needed
        lstm_trainer_path = Path(__file__).parent.parent.parent / "lstm_trainer" / "src"
        if str(lstm_trainer_path) not in sys.path:
            sys.path.insert(0, str(lstm_trainer_path))

        from model import TrendLSTM
        _model_class = TrendLSTM
    return _model_class


class LSTMTrendPredictor:
    """CPU-only LSTM trend predictor for production use."""

    LABELS = {0: "UP", 1: "DOWN", 2: "SIDEWAYS"}

    # Default model configuration (must match training)
    DEFAULT_CONFIG = {
        "input_size": 5,
        "hidden_size": 64,
        "num_layers": 2,
        "dropout": 0.2,
        "num_classes": 3,
    }

    def __init__(
        self,
        model_path: str | Path = "models/trading_lstm.pth",
        seq_len: int = 60,
        config: dict | None = None,
    ):
        """
        Initialize the LSTM trend predictor.

        Args:
            model_path: Path to the trained model file (.pth)
            seq_len: Sequence length (number of H4 candles). Default 60.
            config: Model configuration dict. Uses DEFAULT_CONFIG if None.
        """
        self.model_path = Path(model_path)
        self.seq_len = seq_len
        self.config = config or self.DEFAULT_CONFIG

        self._model = None
        self._device = None

    def _load_model(self) -> None:
        """Load the model lazily on first prediction."""
        if self._model is not None:
            return

        torch = _get_torch()
        TrendLSTM = _get_model_class()

        self._device = torch.device("cpu")
        self._model = TrendLSTM(**self.config)

        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")

        state_dict = torch.load(self.model_path, map_location="cpu", weights_only=True)
        self._model.load_state_dict(state_dict)
        self._model.eval()

    def _normalize_window(self, window: np.ndarray) -> np.ndarray:
        """
        Normalize OHLCV window relative to first candle.

        Args:
            window: Array of shape (seq_len, 5) with OHLCV data

        Returns:
            Normalized array of same shape
        """
        base_close = window[0, 3]  # First candle's close
        base_volume = window[:, 4].mean() + 1e-8  # Mean volume

        normalized = window.copy()
        normalized[:, :4] = (window[:, :4] - base_close) / (base_close + 1e-8)
        normalized[:, 4] = window[:, 4] / base_volume
        return normalized

    def predict(self, df: "pd.DataFrame") -> dict:
        """
        Predict trend direction from H4 candle data.

        Args:
            df: DataFrame with at least seq_len rows and columns:
                open, high, low, close, volume

        Returns:
            dict with keys:
                - trend: "UP", "DOWN", or "SIDEWAYS"
                - confidence: float between 0.0 and 1.0
        """
        # Check minimum data
        if len(df) < self.seq_len:
            return {"trend": "SIDEWAYS", "confidence": 0.0}

        # Load model on first call
        self._load_model()

        torch = _get_torch()

        # Extract last seq_len candles
        window = df.tail(self.seq_len)[["open", "high", "low", "close", "volume"]].values

        # Normalize
        x = self._normalize_window(window)
        x = torch.tensor(x, dtype=torch.float32).unsqueeze(0)  # (1, seq_len, 5)

        # Predict
        with torch.no_grad():
            logits = self._model(x)
            probs = torch.softmax(logits, dim=1)
            pred_class = torch.argmax(probs, dim=1).item()
            confidence = probs[0, pred_class].item()

        return {
            "trend": self.LABELS[pred_class],
            "confidence": round(confidence, 4),
        }

    def should_trade(
        self,
        df: "pd.DataFrame",
        min_confidence: float = 0.6,
    ) -> tuple[bool, str]:
        """
        Convenience method for trading decisions.

        Args:
            df: H4 candle DataFrame
            min_confidence: Minimum confidence threshold

        Returns:
            Tuple of (should_trade: bool, reason: str)
        """
        prediction = self.predict(df)

        if prediction["confidence"] < min_confidence:
            return False, f"LSTM uncertain ({prediction['confidence']:.1%})"

        if prediction["trend"] == "UP":
            return True, f"LSTM bullish ({prediction['confidence']:.1%})"
        elif prediction["trend"] == "DOWN":
            return False, f"LSTM bearish ({prediction['confidence']:.1%})"
        else:
            return False, f"LSTM sideways ({prediction['confidence']:.1%})"
