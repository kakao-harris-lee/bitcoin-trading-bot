"""RandomForest noise filter for LSTM predictions.

Filters LSTM predictions by learning when the LSTM is likely to be wrong,
using the hidden state and market context as features.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import joblib
import numpy as np
from sklearn.ensemble import RandomForestRegressor

logger = logging.getLogger(__name__)


class NoiseFilterRF:
    """RandomForest that filters LSTM predictions based on market context.

    The RF learns to predict LSTM prediction errors, allowing it to:
    1. Estimate confidence in LSTM predictions
    2. Filter out noisy predictions
    3. Scale predictions based on expected accuracy
    """

    # Regime encoding for RF input
    REGIME_ENCODING = {
        "BULL_STRONG": 0,
        "BULL_MODERATE": 1,
        "SIDEWAYS_UP": 2,
        "SIDEWAYS_FLAT": 3,
        "SIDEWAYS_DOWN": 4,
        "BEAR_MODERATE": 5,
        "BEAR_STRONG": 6,
        "UNKNOWN": 3,  # Default to SIDEWAYS_FLAT
    }

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 10,
        min_samples_leaf: int = 20,
        random_state: int = 42,
    ):
        """Initialize NoiseFilterRF.

        Args:
            n_estimators: Number of trees in the forest.
            max_depth: Maximum depth of trees.
            min_samples_leaf: Minimum samples required at leaf node.
            random_state: Random seed for reproducibility.
        """
        self.rf = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            n_jobs=-1,
            random_state=random_state,
        )
        self.fitted = False
        self.feature_names: list[str] = []

    def build_features(
        self,
        lstm_pred: float,
        hidden_state: np.ndarray,
        market_context: dict[str, Any],
    ) -> np.ndarray:
        """Build feature vector for RF.

        Args:
            lstm_pred: LSTM predicted price delta.
            hidden_state: LSTM hidden state (64,).
            market_context: Dict with market indicators.

        Returns:
            Feature array (71,).
        """
        # Encode regime
        regime = market_context.get("regime", "UNKNOWN")
        regime_encoded = self.REGIME_ENCODING.get(regime, 3)

        # Base features (7)
        features = [
            lstm_pred,
            abs(lstm_pred),  # Prediction magnitude
            market_context.get("mfi", 50.0),
            market_context.get("adx", 20.0),
            market_context.get("volatility", 0.02),
            float(regime_encoded),
            float(market_context.get("breakout_signal", 0)),
        ]

        # Add hidden state (64)
        if hidden_state is not None:
            features.extend(hidden_state.flatten().tolist())
        else:
            features.extend([0.0] * 64)

        return np.array(features, dtype=np.float32)

    def predict_confidence(
        self,
        lstm_pred: float,
        hidden_state: np.ndarray,
        market_context: dict[str, Any],
    ) -> tuple[float, float]:
        """Predict confidence score and filter LSTM prediction.

        Args:
            lstm_pred: LSTM predicted price delta.
            hidden_state: LSTM hidden state (64,).
            market_context: Dict with market indicators.

        Returns:
            Tuple of (filtered_prediction, confidence_score).
        """
        if not self.fitted:
            # Before training, return raw prediction with neutral confidence
            return lstm_pred, 0.5

        features = self.build_features(lstm_pred, hidden_state, market_context)

        # RF predicts expected absolute error
        predicted_error = self.rf.predict(features.reshape(1, -1))[0]

        # Convert error to confidence (lower error = higher confidence)
        # Normalize: assume max reasonable error is 0.05 (5%)
        confidence = max(0.0, min(1.0, 1.0 - predicted_error / 0.05))

        # Filter prediction by confidence
        filtered_pred = lstm_pred * confidence

        return filtered_pred, confidence

    def fit(self, X: np.ndarray, y_errors: np.ndarray) -> None:
        """Train RF on LSTM prediction errors.

        Args:
            X: Feature matrix (n_samples, 71).
            y_errors: Absolute prediction errors (n_samples,).
        """
        logger.info(f"Training NoiseFilterRF on {len(X)} samples...")
        self.rf.fit(X, y_errors)
        self.fitted = True
        logger.info("NoiseFilterRF training complete")

    def partial_fit(self, X: np.ndarray, y_errors: np.ndarray) -> None:
        """Incremental training (refit with new + old data).

        Note: sklearn RF doesn't support true incremental learning,
        so this refits the entire model. For production, consider
        keeping a buffer of recent samples.

        Args:
            X: New feature samples.
            y_errors: New error samples.
        """
        # RF doesn't support incremental learning, so we just refit
        logger.info(f"Refitting NoiseFilterRF with {len(X)} new samples...")
        self.rf.fit(X, y_errors)
        self.fitted = True

    def save(self, path: str | Path) -> None:
        """Save model to disk.

        Args:
            path: Path to save the model.
        """
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "rf": self.rf,
                "fitted": self.fitted,
                "feature_names": self.feature_names,
            },
            path,
        )
        logger.info(f"Saved NoiseFilterRF to {path}")

    @classmethod
    def load(cls, path: str | Path) -> "NoiseFilterRF":
        """Load model from disk.

        Args:
            path: Path to load the model from.

        Returns:
            Loaded NoiseFilterRF instance.
        """
        path = Path(path)
        if not path.exists():
            logger.warning(f"NoiseFilterRF not found at {path}, creating new instance")
            return cls()

        data = joblib.load(path)
        instance = cls()
        instance.rf = data["rf"]
        instance.fitted = data["fitted"]
        instance.feature_names = data.get("feature_names", [])
        logger.info(f"Loaded NoiseFilterRF from {path}")
        return instance

    def get_feature_importances(self) -> dict[str, float]:
        """Get feature importance rankings.

        Returns:
            Dict mapping feature names to importance scores.
        """
        if not self.fitted:
            return {}

        # Default feature names if not set
        if not self.feature_names:
            self.feature_names = (
                ["lstm_pred", "lstm_pred_abs", "mfi", "adx", "volatility", "regime", "breakout"]
                + [f"hidden_{i}" for i in range(64)]
            )

        importances = self.rf.feature_importances_
        return dict(zip(self.feature_names, importances))
