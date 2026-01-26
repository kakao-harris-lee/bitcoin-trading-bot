"""Online learning service for Hybrid LSTM model.

Provides incremental training capabilities:
1. Collects prediction results with actual outcomes
2. Updates LSTM with mini-batch SGD when batch is full
3. Periodically refits RF with recent prediction errors
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import torch
import torch.nn.functional as F

from .hybrid_predictor import HybridPredictor
from .noise_filter import NoiseFilterRF

logger = logging.getLogger(__name__)


@dataclass
class Experience:
    """Single prediction experience for online learning."""

    x: torch.Tensor  # Input sequence (seq_len, features)
    actual_delta: float  # Actual price delta
    predicted_delta: float  # LSTM predicted delta
    hidden_state: np.ndarray  # Hidden state for RF
    market_context: dict[str, Any]  # Market context
    timestamp: str  # Candle timestamp


class OnlineTrainer:
    """Background service for online learning updates.

    Collects prediction experiences and updates models incrementally:
    - LSTM: Mini-batch SGD update every N samples
    - RF: Periodic refit with accumulated errors
    """

    def __init__(
        self,
        predictor: HybridPredictor,
        lstm_batch_size: int = 32,
        rf_batch_size: int = 100,
        sgd_lr: float = 0.01,
        sgd_momentum: float = 0.9,
        max_buffer_size: int = 1000,
        device: str = "cpu",
    ):
        """Initialize OnlineTrainer.

        Args:
            predictor: HybridPredictor instance to update.
            lstm_batch_size: Batch size for LSTM SGD updates.
            rf_batch_size: Number of samples before RF refit.
            sgd_lr: SGD learning rate for online updates.
            sgd_momentum: SGD momentum.
            max_buffer_size: Maximum buffer size for RF training.
            device: Training device.
        """
        self.predictor = predictor
        self.lstm_batch_size = lstm_batch_size
        self.rf_batch_size = rf_batch_size
        self.device = torch.device(device)

        # LSTM optimizer (SGD for online learning)
        self.optimizer = torch.optim.SGD(
            predictor.lstm.parameters(),
            lr=sgd_lr,
            momentum=sgd_momentum,
            weight_decay=1e-4,
        )

        # Experience buffers
        self.lstm_buffer: list[Experience] = []
        self.rf_buffer: deque[Experience] = deque(maxlen=max_buffer_size)

        # Statistics
        self.lstm_updates = 0
        self.rf_updates = 0
        self.total_experiences = 0

    def add_experience(
        self,
        x: torch.Tensor,
        actual_delta: float,
        predicted_delta: float,
        hidden_state: np.ndarray,
        market_context: dict[str, Any],
        timestamp: str = "",
    ) -> dict[str, Any]:
        """Add new prediction experience.

        Args:
            x: Input sequence tensor (seq_len, features).
            actual_delta: Actual price change ratio.
            predicted_delta: Model's predicted delta.
            hidden_state: LSTM hidden state.
            market_context: Market context dict.
            timestamp: Candle timestamp.

        Returns:
            Dict with update status and statistics.
        """
        exp = Experience(
            x=x,
            actual_delta=actual_delta,
            predicted_delta=predicted_delta,
            hidden_state=hidden_state,
            market_context=market_context,
            timestamp=timestamp,
        )

        self.lstm_buffer.append(exp)
        self.rf_buffer.append(exp)
        self.total_experiences += 1

        result = {
            "lstm_updated": False,
            "rf_updated": False,
            "lstm_buffer_size": len(self.lstm_buffer),
            "rf_buffer_size": len(self.rf_buffer),
        }

        # Check if LSTM update needed
        if len(self.lstm_buffer) >= self.lstm_batch_size:
            lstm_loss = self._update_lstm()
            result["lstm_updated"] = True
            result["lstm_loss"] = lstm_loss

        # Check if RF update needed
        if len(self.rf_buffer) >= self.rf_batch_size:
            self._update_rf()
            result["rf_updated"] = True

        return result

    def _update_lstm(self) -> float:
        """Perform SGD update on LSTM with current buffer.

        Returns:
            Training loss value.
        """
        if not self.lstm_buffer:
            return 0.0

        # Prepare batch
        batch_x = torch.stack([exp.x for exp in self.lstm_buffer])
        batch_y = torch.tensor(
            [exp.actual_delta for exp in self.lstm_buffer],
            dtype=torch.float32,
        )

        batch_x = batch_x.to(self.device)
        batch_y = batch_y.to(self.device)

        # Training step
        self.predictor.lstm.train()
        self.optimizer.zero_grad()

        output = self.predictor.lstm(batch_x)
        loss = F.mse_loss(output["price_delta"], batch_y)

        loss.backward()
        torch.nn.utils.clip_grad_norm_(
            self.predictor.lstm.parameters(), max_norm=1.0
        )
        self.optimizer.step()

        self.predictor.lstm.eval()

        # Clear buffer
        self.lstm_buffer.clear()
        self.lstm_updates += 1

        loss_val = loss.item()
        logger.info(
            f"LSTM online update #{self.lstm_updates}: loss={loss_val:.6f}"
        )

        return loss_val

    def _update_rf(self) -> None:
        """Refit RandomForest with accumulated errors."""
        if len(self.rf_buffer) < 50:  # Minimum samples for RF
            return

        # Build RF training data
        rf_features = []
        rf_errors = []

        for exp in self.rf_buffer:
            features = self.predictor.rf.build_features(
                exp.predicted_delta,
                exp.hidden_state,
                exp.market_context,
            )
            error = abs(exp.predicted_delta - exp.actual_delta)

            rf_features.append(features)
            rf_errors.append(error)

        rf_features = np.array(rf_features)
        rf_errors = np.array(rf_errors)

        # Partial fit (refit with recent data)
        self.predictor.rf.partial_fit(rf_features, rf_errors)
        self.rf_updates += 1

        logger.info(
            f"RF online update #{self.rf_updates}: "
            f"samples={len(rf_features)}, mean_error={np.mean(rf_errors):.6f}"
        )

    def get_statistics(self) -> dict[str, Any]:
        """Get training statistics.

        Returns:
            Dict with training statistics.
        """
        return {
            "total_experiences": self.total_experiences,
            "lstm_updates": self.lstm_updates,
            "rf_updates": self.rf_updates,
            "lstm_buffer_size": len(self.lstm_buffer),
            "rf_buffer_size": len(self.rf_buffer),
        }

    def save_models(
        self,
        lstm_path: str | Path,
        rf_path: str | Path,
    ) -> None:
        """Save updated models to disk.

        Args:
            lstm_path: Path for LSTM model.
            rf_path: Path for RF model.
        """
        self.predictor.save(lstm_path, rf_path)
        logger.info(f"Saved updated models: LSTM={lstm_path}, RF={rf_path}")

    def force_lstm_update(self) -> float | None:
        """Force LSTM update regardless of buffer size.

        Returns:
            Loss value if update occurred, None otherwise.
        """
        if self.lstm_buffer:
            return self._update_lstm()
        return None

    def force_rf_update(self) -> None:
        """Force RF update regardless of buffer size."""
        if len(self.rf_buffer) >= 50:
            self._update_rf()


class OnlineLearningService:
    """Async service wrapper for online learning.

    Integrates with the trading engine to:
    1. Receive prediction results
    2. Wait for actual price to materialize
    3. Update models with new experience
    """

    def __init__(
        self,
        predictor: HybridPredictor,
        model_save_path: Path | None = None,
        save_interval: int = 100,
        **trainer_kwargs,
    ):
        """Initialize service.

        Args:
            predictor: HybridPredictor to update.
            model_save_path: Directory to save model checkpoints.
            save_interval: Save models every N experiences.
            **trainer_kwargs: Arguments passed to OnlineTrainer.
        """
        self.trainer = OnlineTrainer(predictor, **trainer_kwargs)
        self.model_save_path = model_save_path
        self.save_interval = save_interval
        self.pending_predictions: dict[str, dict] = {}  # timestamp -> prediction

    def record_prediction(
        self,
        timestamp: str,
        x: torch.Tensor,
        prediction: float,
        hidden_state: np.ndarray,
        market_context: dict[str, Any],
    ) -> None:
        """Record a prediction for later feedback.

        Args:
            timestamp: Candle timestamp.
            x: Input tensor.
            prediction: Predicted price delta.
            hidden_state: LSTM hidden state.
            market_context: Market context dict.
        """
        self.pending_predictions[timestamp] = {
            "x": x,
            "prediction": prediction,
            "hidden_state": hidden_state,
            "market_context": market_context,
        }

        # Cleanup old predictions (keep last 100)
        if len(self.pending_predictions) > 100:
            oldest = sorted(self.pending_predictions.keys())[:-100]
            for ts in oldest:
                del self.pending_predictions[ts]

    def provide_feedback(
        self,
        timestamp: str,
        actual_delta: float,
    ) -> dict[str, Any] | None:
        """Provide actual outcome for a prediction.

        Args:
            timestamp: Original prediction timestamp.
            actual_delta: Actual price change ratio.

        Returns:
            Update result dict or None if prediction not found.
        """
        if timestamp not in self.pending_predictions:
            return None

        pred_data = self.pending_predictions.pop(timestamp)

        result = self.trainer.add_experience(
            x=pred_data["x"],
            actual_delta=actual_delta,
            predicted_delta=pred_data["prediction"],
            hidden_state=pred_data["hidden_state"],
            market_context=pred_data["market_context"],
            timestamp=timestamp,
        )

        # Auto-save periodically
        if (
            self.model_save_path
            and self.trainer.total_experiences % self.save_interval == 0
        ):
            lstm_path = self.model_save_path / "hybrid_lstm_online.pth"
            rf_path = self.model_save_path / "noise_filter_rf_online.pkl"
            self.trainer.save_models(lstm_path, rf_path)

        return result

    def get_statistics(self) -> dict[str, Any]:
        """Get service statistics."""
        stats = self.trainer.get_statistics()
        stats["pending_predictions"] = len(self.pending_predictions)
        return stats
