"""MLP Ensemble Predictor — Soft-voting across multiple temporal-scale models.

Loads multiple MLP models (trained with different bwin/fwin label windows)
and averages their probability outputs for more robust predictions.

All models share the same feature set (paper_36); they differ only in what
temporal patterns they learned through different labeling windows.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class MLPEnsemblePredictor:
    """Soft-voting ensemble of multiple MLP Direction models.

    Each model was trained with a different bwin/fwin labeling window,
    capturing different temporal rhythms. Averaging their probability
    outputs reduces overfitting to any single temporal scale.

    Usage:
        predictor = MLPEnsemblePredictor(model_configs=[
            {"model_path": "models/.../bwin3/model_final.pt", "weight": 0.2},
            {"model_path": "models/.../bwin5/model_final.pt", "weight": 0.3},
        ])
        pred_class, confidence, probs = predictor.predict(features)
    """

    def __init__(self, model_configs: list[dict[str, Any]]):
        """Initialize ensemble with model configurations.

        Args:
            model_configs: List of dicts with keys:
                - model_path (str): Path to model checkpoint
                - weight (float): Voting weight for this model (default 1.0)
        """
        self._configs = model_configs
        self._models: list[Any] = []
        self._weights: list[float] = []
        self._loaded = False
        self._available = False

    def load(self, device: str = "cpu") -> bool:
        """Lazy-load all ensemble models.

        Returns:
            True if at least one model loaded successfully.
        """
        if self._loaded:
            return self._available

        self._loaded = True

        try:
            from mlp_trainer.src.mlp_model import MLPDirectionClassifier
        except ImportError:
            logger.error("MLPEnsemble: mlp_trainer not available")
            return False

        for cfg in self._configs:
            model_path = Path(cfg["model_path"])
            weight = cfg.get("weight", 1.0)

            if not model_path.exists():
                logger.warning(f"MLPEnsemble: Model not found: {model_path}")
                continue

            try:
                model = MLPDirectionClassifier.load(
                    str(model_path), device=device, validate_path=True,
                )
                model.eval()
                self._models.append(model)
                self._weights.append(weight)
                logger.info(
                    f"MLPEnsemble: Loaded {model_path.parent.name} "
                    f"(weight={weight:.2f})"
                )
            except Exception as e:
                logger.warning(f"MLPEnsemble: Failed to load {model_path}: {e}")

        self._available = len(self._models) > 0

        if self._available:
            logger.info(
                f"MLPEnsemble: {len(self._models)}/{len(self._configs)} "
                f"models loaded"
            )
        else:
            logger.error("MLPEnsemble: No models loaded")

        return self._available

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def num_models(self) -> int:
        return len(self._models)

    def predict(self, features: np.ndarray) -> tuple[int, float, np.ndarray]:
        """Make ensemble prediction via weighted soft voting.

        Args:
            features: Feature array of shape (num_features,).

        Returns:
            Tuple of (predicted_class, confidence, averaged_probs).
        """
        import torch

        x = torch.FloatTensor(features).unsqueeze(0)
        weighted_probs = np.zeros(3)
        total_weight = 0.0

        for model, weight in zip(self._models, self._weights):
            try:
                with torch.no_grad():
                    probs = model.predict_proba(x).cpu().numpy()[0]
                weighted_probs += weight * probs
                total_weight += weight
            except Exception as e:
                logger.warning(f"MLPEnsemble: Model inference failed: {e}")

        if total_weight <= 0:
            return 0, 0.0, np.array([1.0, 0.0, 0.0])

        weighted_probs /= total_weight
        pred_class = int(weighted_probs.argmax())
        confidence = float(weighted_probs[pred_class])

        return pred_class, confidence, weighted_probs

    def predict_batch(self, features: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
        """Batch ensemble prediction for backtest optimization.

        Args:
            features: Feature matrix of shape (N, num_features).

        Returns:
            Tuple of (predictions, confidences, probs_matrix) each of shape (N,), (N,), (N, 3).
        """
        import torch

        N = features.shape[0]
        x = torch.FloatTensor(features)
        weighted_probs = np.zeros((N, 3))
        total_weight = 0.0

        for model, weight in zip(self._models, self._weights):
            try:
                with torch.no_grad():
                    probs = model.predict_proba(x).cpu().numpy()
                weighted_probs += weight * probs
                total_weight += weight
            except Exception as e:
                logger.warning(f"MLPEnsemble: Batch inference failed: {e}")

        if total_weight <= 0:
            return (
                np.zeros(N, dtype=int),
                np.zeros(N),
                np.tile([1.0, 0.0, 0.0], (N, 1)),
            )

        weighted_probs /= total_weight
        predictions = weighted_probs.argmax(axis=1).astype(int)
        confidences = weighted_probs[np.arange(N), predictions]

        return predictions, confidences, weighted_probs
