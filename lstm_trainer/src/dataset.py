"""PyTorch Dataset for LSTM training."""

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


class TrendDataset(Dataset):
    """Dataset for trend prediction with per-window normalization."""

    # Label mapping
    UP = 0
    DOWN = 1
    SIDEWAYS = 2

    def __init__(
        self,
        df: pd.DataFrame,
        seq_len: int = 60,
        threshold: float = 0.015,
    ):
        """
        Initialize dataset.

        Args:
            df: DataFrame with columns [timestamp, open, high, low, close, volume]
            seq_len: Sequence length for LSTM input
            threshold: Threshold for UP/DOWN classification (default +-1.5%)
        """
        self.seq_len = seq_len
        self.threshold = threshold

        # Extract OHLCV as numpy array
        self.data = df[["open", "high", "low", "close", "volume"]].values.astype(np.float32)
        self.closes = df["close"].values.astype(np.float32)

        # Valid indices: need seq_len candles + 1 for label
        self.valid_indices = list(range(seq_len, len(df) - 1))

    def __len__(self) -> int:
        return len(self.valid_indices)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        """Get normalized sequence and label."""
        end_idx = self.valid_indices[idx]
        start_idx = end_idx - self.seq_len

        # Extract window
        window = self.data[start_idx:end_idx].copy()

        # Normalize
        x = self._normalize_window(window)

        # Create label from next candle
        current_close = self.closes[end_idx]
        next_close = self.closes[end_idx + 1]
        label = self._make_label(current_close, next_close)

        return torch.from_numpy(x), label

    def _normalize_window(self, window: np.ndarray) -> np.ndarray:
        """Normalize OHLCV relative to first candle's close."""
        base_close = window[0, 3]  # First candle's close
        base_volume = window[:, 4].mean() + 1e-8  # Mean volume

        normalized = window.copy()
        # Normalize prices as % change from base
        normalized[:, :4] = (window[:, :4] - base_close) / (base_close + 1e-8)
        # Normalize volume as ratio to mean
        normalized[:, 4] = window[:, 4] / base_volume

        return normalized

    def _make_label(self, current_close: float, next_close: float) -> int:
        """Create label based on price change threshold."""
        pct_change = (next_close - current_close) / (current_close + 1e-8)

        if pct_change > self.threshold:
            return self.UP
        elif pct_change < -self.threshold:
            return self.DOWN
        else:
            return self.SIDEWAYS

    def get_class_weights(self) -> torch.Tensor:
        """Compute class weights for imbalanced data."""
        labels = [self[i][1] for i in range(len(self))]
        counts = np.bincount(labels, minlength=3)
        weights = 1.0 / (counts + 1e-8)
        weights = weights / weights.sum() * 3  # Normalize
        return torch.tensor(weights, dtype=torch.float32)
