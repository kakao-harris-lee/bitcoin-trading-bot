"""Price forecasting LSTM (regression)."""

from __future__ import annotations

import torch
import torch.nn as nn


class PriceLSTM(nn.Module):
    """LSTM-based regressor that predicts next-close delta (normalized)."""

    def __init__(
        self,
        input_size: int = 5,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            dropout=dropout if num_layers > 1 else 0.0,
            batch_first=True,
        )
        self.head = nn.Linear(hidden_size, 1)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, input_size)
        out, _ = self.lstm(x)
        last = out[:, -1, :]  # (batch, hidden)
        return self.head(last).squeeze(-1)  # (batch,)
