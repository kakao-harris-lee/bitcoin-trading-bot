"""Hybrid LSTM model for price prediction with online learning support.

2-layer stacked LSTM that predicts:
1. Close price delta (regression) - primary output
2. Direction classification (UP/DOWN/SIDEWAYS) - auxiliary task
3. Hidden state - for RF noise filtering
"""

from __future__ import annotations

import torch
import torch.nn as nn


class HybridLSTM(nn.Module):
    """2-Layer Stacked LSTM for close price prediction with online learning."""

    def __init__(
        self,
        input_size: int = 22,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        num_classes: int = 3,
    ):
        """Initialize HybridLSTM.

        Args:
            input_size: Number of input features (scaled columns).
            hidden_size: LSTM hidden state dimension.
            num_layers: Number of stacked LSTM layers.
            dropout: Dropout rate between LSTM layers.
            num_classes: Number of direction classes (UP/DOWN/SIDEWAYS).
        """
        super().__init__()

        self.input_size = input_size
        self.hidden_size = hidden_size
        self.num_layers = num_layers

        # Stacked LSTM (2 layers as specified)
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        # Price prediction head (regression)
        self.price_head = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, 1),
        )

        # Direction classification head (auxiliary task)
        self.direction_head = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, num_classes),
        )

    def forward(self, x: torch.Tensor) -> dict[str, torch.Tensor]:
        """Forward pass.

        Args:
            x: Input tensor of shape (batch, seq_len, input_size).

        Returns:
            Dict with:
                - price_delta: Predicted price change (batch,)
                - direction_logits: Direction class logits (batch, 3)
                - hidden_state: Last hidden state for RF (batch, hidden_size)
        """
        # x: (batch, seq_len, features)
        lstm_out, (h_n, c_n) = self.lstm(x)

        # Take last timestep's output
        last_hidden = lstm_out[:, -1, :]  # (batch, hidden_size)

        # Price prediction (regression)
        price_delta = self.price_head(last_hidden).squeeze(-1)  # (batch,)

        # Direction classification (auxiliary)
        direction_logits = self.direction_head(last_hidden)  # (batch, 3)

        return {
            "price_delta": price_delta,
            "direction_logits": direction_logits,
            "hidden_state": last_hidden,
        }

    def predict_price(self, x: torch.Tensor) -> torch.Tensor:
        """Predict price delta only (for inference).

        Args:
            x: Input tensor of shape (batch, seq_len, input_size).

        Returns:
            Predicted price delta (batch,).
        """
        with torch.no_grad():
            output = self.forward(x)
            return output["price_delta"]

    def get_hidden_state(self, x: torch.Tensor) -> torch.Tensor:
        """Get hidden state for RF noise filtering.

        Args:
            x: Input tensor of shape (batch, seq_len, input_size).

        Returns:
            Hidden state (batch, hidden_size).
        """
        with torch.no_grad():
            output = self.forward(x)
            return output["hidden_state"]


class HybridLoss(nn.Module):
    """Combined loss for price prediction and direction classification."""

    def __init__(
        self,
        price_weight: float = 1.0,
        direction_weight: float = 0.3,
        direction_class_weights: torch.Tensor | None = None,
    ):
        """Initialize combined loss.

        Args:
            price_weight: Weight for price regression loss.
            direction_weight: Weight for direction classification loss.
            direction_class_weights: Class weights for direction loss.
        """
        super().__init__()
        self.price_weight = price_weight
        self.direction_weight = direction_weight

        self.price_loss = nn.MSELoss()
        self.direction_loss = nn.CrossEntropyLoss(weight=direction_class_weights)

    def forward(
        self,
        output: dict[str, torch.Tensor],
        price_target: torch.Tensor,
        direction_target: torch.Tensor,
    ) -> dict[str, torch.Tensor]:
        """Compute combined loss.

        Args:
            output: Model output dict with 'price_delta' and 'direction_logits'.
            price_target: Target price delta (batch,).
            direction_target: Target direction class (batch,).

        Returns:
            Dict with 'total', 'price', 'direction' losses.
        """
        price_loss = self.price_loss(output["price_delta"], price_target)
        direction_loss = self.direction_loss(output["direction_logits"], direction_target)

        total_loss = (
            self.price_weight * price_loss + self.direction_weight * direction_loss
        )

        return {
            "total": total_loss,
            "price": price_loss,
            "direction": direction_loss,
        }
