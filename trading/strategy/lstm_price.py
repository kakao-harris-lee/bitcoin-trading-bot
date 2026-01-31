"""Price forecasting LSTM predictor (minute60 -> next close)."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import numpy as np

if TYPE_CHECKING:
    import pandas as pd

_torch = None
_model_class = None


def _get_torch():
    global _torch
    if _torch is None:
        import torch
        _torch = torch
    return _torch


def _get_model_class():
    global _model_class
    if _model_class is None:
        from lstm_trainer.src.price_model import PriceLSTM

        _model_class = PriceLSTM
    return _model_class


class LSTMPricePredictor:
    """Predict next close price from a rolling OHLCV window."""

    def __init__(
        self,
        model_path: str | Path = "models/trading_lstm_price.pth",
        seq_len: int = 120,
        hidden_size: int = 96,
        num_layers: int = 2,
        dropout: float = 0.2,
    ):
        self.model_path = Path(model_path)
        self.seq_len = seq_len
        self.hidden_size = hidden_size
        self.num_layers = num_layers
        self.dropout = dropout
        self._model = None
        self._device = None

    def _load_model(self) -> None:
        if self._model is not None:
            return
        torch = _get_torch()
        Model = _get_model_class()
        self._device = torch.device("cpu")
        self._model = Model(
            input_size=5,
            hidden_size=self.hidden_size,
            num_layers=self.num_layers,
            dropout=self.dropout,
        )
        if not self.model_path.exists():
            raise FileNotFoundError(f"Model file not found: {self.model_path}")
        checkpoint = torch.load(self.model_path, map_location="cpu", weights_only=False)
        # Handle both checkpoint format (dict with model_state_dict) and direct state_dict
        if isinstance(checkpoint, dict) and "model_state_dict" in checkpoint:
            state = checkpoint["model_state_dict"]
        else:
            state = checkpoint
        self._model.load_state_dict(state)
        self._model.eval()

    def predict_price(self, df: "pd.DataFrame") -> float:
        """
        Predict next close.

        Args:
            df: DataFrame with at least seq_len rows and columns:
                open, high, low, close, volume

        Returns:
            Predicted next close (float). Returns NaN if insufficient data.
        """
        if len(df) < self.seq_len:
            return float("nan")

        self._load_model()
        torch = _get_torch()

        window = df.tail(self.seq_len)[["open", "high", "low", "close", "volume"]].values.astype(
            np.float32
        )
        base_close = window[0, 3]
        base_vol = window[:, 4].mean() + 1e-8

        norm = window.copy()
        norm[:, :4] = (window[:, :4] - base_close) / (base_close + 1e-8)
        norm[:, 4] = window[:, 4] / base_vol

        x = torch.tensor(norm, dtype=torch.float32).unsqueeze(0)  # (1, seq_len, 5)

        with torch.no_grad():
            pred_return = self._model(x).item()  # log-return

        # Convert log-return back to price
        pred_price = float(np.exp(pred_return) * base_close)
        return float(pred_price)
