"""Hybrid LSTM + RF Strategy for production trading.

Integrates HybridPredictor with the trading engine:
1. Generates entry signals based on LSTM predictions + RF confidence
2. Provides online learning updates when positions close
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pandas as pd
import torch

# Add lstm_trainer to path
PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from lstm_trainer.src.hybrid_predictor import HybridPredictor
from lstm_trainer.src.online_trainer import OnlineLearningService

if TYPE_CHECKING:
    from trading.strategies.components.models import MarketData

logger = logging.getLogger(__name__)


class HybridLSTMStrategy:
    """Production strategy using Hybrid LSTM + RF predictions.

    Designed to work alongside existing V35/Short strategies as an
    additional signal source or standalone entry condition.
    """

    def __init__(
        self,
        model_path: str | Path = "lstm_trainer/models/hybrid_lstm.pth",
        rf_path: str | Path = "lstm_trainer/models/noise_filter_rf.pkl",
        confidence_threshold: float = 0.6,
        prediction_threshold: float = 0.01,
        enable_online_learning: bool = True,
        device: str = "cpu",
    ):
        """Initialize HybridLSTMStrategy.

        Args:
            model_path: Path to trained LSTM model.
            rf_path: Path to trained RF model.
            confidence_threshold: Minimum confidence for entry signal.
            prediction_threshold: Minimum prediction magnitude for entry.
            enable_online_learning: Whether to update models with new data.
            device: Inference device.
        """
        self.confidence_threshold = confidence_threshold
        self.prediction_threshold = prediction_threshold
        self.enable_online_learning = enable_online_learning

        # Load predictor
        model_path = PROJECT_ROOT / model_path
        rf_path = PROJECT_ROOT / rf_path

        self.predictor = HybridPredictor.load(
            model_path=model_path,
            rf_path=rf_path,
            device=device,
        )

        # Setup online learning
        self.online_service: OnlineLearningService | None = None
        if enable_online_learning:
            self.online_service = OnlineLearningService(
                predictor=self.predictor,
                model_save_path=model_path.parent,
                lstm_batch_size=32,
                rf_batch_size=100,
                save_interval=100,
            )

        logger.info(
            f"HybridLSTMStrategy initialized: "
            f"conf_thresh={confidence_threshold}, pred_thresh={prediction_threshold}"
        )

    def should_enter(
        self,
        df: pd.DataFrame,
        market_context: dict[str, Any],
        symbol: str = "BTC",
    ) -> tuple[bool, str]:
        """Check if entry conditions are met.

        Args:
            df: DataFrame with scaled OHLCV data.
            market_context: Dict with mfi, adx, volatility, regime, breakout_signal.
            symbol: Trading symbol.

        Returns:
            Tuple of (should_enter, reason).
        """
        # Run prediction
        result = self.predictor.predict(df, market_context)

        prediction = result["prediction"]
        confidence = result["confidence"]
        signal = result["signal"]
        direction = result["direction"]

        # Record for online learning
        if self.online_service:
            x = self.predictor.prepare_input(df)
            if x is not None:
                timestamp = df.iloc[-1].get("timestamp", "")
                if isinstance(timestamp, pd.Timestamp):
                    timestamp = timestamp.isoformat()
                self.online_service.record_prediction(
                    timestamp=str(timestamp),
                    x=x.squeeze(0),
                    prediction=result["raw_prediction"],
                    hidden_state=result["hidden_state"],
                    market_context=market_context,
                )

        # Check confidence threshold
        if confidence < self.confidence_threshold:
            return False, (
                f"Low confidence: {confidence:.2f} < {self.confidence_threshold}"
            )

        # Check signal
        if signal == "BUY":
            return True, (
                f"Hybrid BUY: pred={prediction:.4f}, conf={confidence:.2f}, dir={direction}"
            )
        elif signal == "SELL":
            return False, (
                f"Hybrid SELL signal (short opportunity): pred={prediction:.4f}"
            )
        else:
            return False, f"No signal: pred={prediction:.4f}, conf={confidence:.2f}"

    def should_short(
        self,
        df: pd.DataFrame,
        market_context: dict[str, Any],
        symbol: str = "BTC",
    ) -> tuple[bool, str]:
        """Check if short entry conditions are met.

        Args:
            df: DataFrame with scaled OHLCV data.
            market_context: Market context dict.
            symbol: Trading symbol.

        Returns:
            Tuple of (should_short, reason).
        """
        result = self.predictor.predict(df, market_context)

        prediction = result["prediction"]
        confidence = result["confidence"]
        signal = result["signal"]
        direction = result["direction"]

        if confidence < self.confidence_threshold:
            return False, f"Low confidence: {confidence:.2f}"

        if signal == "SELL":
            return True, (
                f"Hybrid SHORT: pred={prediction:.4f}, conf={confidence:.2f}, dir={direction}"
            )

        return False, f"No short signal: pred={prediction:.4f}"

    def get_prediction(
        self,
        df: pd.DataFrame,
        market_context: dict[str, Any],
    ) -> dict[str, Any]:
        """Get raw prediction without signal logic.

        Args:
            df: DataFrame with scaled data.
            market_context: Market context dict.

        Returns:
            Full prediction result dict.
        """
        return self.predictor.predict(df, market_context)

    def update_with_outcome(
        self,
        timestamp: str,
        actual_delta: float,
    ) -> dict[str, Any] | None:
        """Provide actual outcome for online learning.

        Call this when a candle closes to update the model.

        Args:
            timestamp: Original prediction timestamp.
            actual_delta: Actual price change ratio.

        Returns:
            Update result or None if online learning disabled.
        """
        if not self.online_service:
            return None

        return self.online_service.provide_feedback(timestamp, actual_delta)

    def get_statistics(self) -> dict[str, Any]:
        """Get strategy statistics.

        Returns:
            Dict with model and learning statistics.
        """
        stats = {
            "confidence_threshold": self.confidence_threshold,
            "prediction_threshold": self.prediction_threshold,
            "online_learning_enabled": self.enable_online_learning,
        }

        if self.online_service:
            stats["online_stats"] = self.online_service.get_statistics()

        if self.predictor.rf.fitted:
            importances = self.predictor.rf.get_feature_importances()
            # Top 5 important features
            sorted_imp = sorted(importances.items(), key=lambda x: x[1], reverse=True)
            stats["top_features"] = sorted_imp[:5]

        return stats


def create_hybrid_strategy(config: dict[str, Any]) -> HybridLSTMStrategy:
    """Factory function to create HybridLSTMStrategy from config.

    Args:
        config: Strategy configuration dict.

    Returns:
        Configured HybridLSTMStrategy instance.
    """
    return HybridLSTMStrategy(
        model_path=config.get("model_path", "lstm_trainer/models/hybrid_lstm.pth"),
        rf_path=config.get("rf_path", "lstm_trainer/models/noise_filter_rf.pkl"),
        confidence_threshold=config.get("confidence_threshold", 0.6),
        prediction_threshold=config.get("prediction_threshold", 0.01),
        enable_online_learning=config.get("enable_online_learning", True),
        device=config.get("device", "cpu"),
    )
