"""Heterogeneous Ensemble Predictor — Soft-voting across MLP + tree models.

Loads multiple models (MLP, XGBoost, LightGBM) trained with different
bwin/fwin label windows and/or architectures, then averages their
probability outputs for more robust predictions.

Model type is auto-detected from file extension:
    - .pt → MLP (MLPDirectionClassifier)
    - .json → XGBoost (via TreeModelWrapper)
    - .txt → LightGBM (via TreeModelWrapper)
"""
# pylint: disable=broad-exception-caught

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

    # File extensions that indicate tree-based models
    _TREE_EXTENSIONS = {".json", ".txt"}

    def load(self, device: str = "cpu") -> bool:
        """Lazy-load all ensemble models.

        Auto-detects model type from file extension:
            - .pt → MLP (MLPDirectionClassifier)
            - .json → XGBoost (TreeModelWrapper)
            - .txt → LightGBM (TreeModelWrapper)

        Returns:
            True if at least one model loaded successfully.
        """
        if self._loaded:
            return self._available

        self._loaded = True

        mlp_cls = None
        tree_cls = None

        for cfg in self._configs:
            model_path = Path(cfg["model_path"])
            weight = cfg.get("weight", 1.0)

            if not model_path.exists():
                logger.warning("MLPEnsemble: Model not found: %s", model_path)
                continue

            try:
                if model_path.suffix.lower() in self._TREE_EXTENSIONS:
                    # Tree model (XGBoost / LightGBM)
                    if tree_cls is None:
                        from .tree_model_wrapper import TreeModelWrapper
                        tree_cls = TreeModelWrapper
                    model = tree_cls.load(str(model_path))
                    model_label = f"{model_path.parent.name}/{model_path.name}"
                else:
                    # MLP model (.pt)
                    if mlp_cls is None:
                        try:
                            from mlp_trainer.src.mlp_model import MLPDirectionClassifier
                            mlp_cls = MLPDirectionClassifier
                        except ImportError:
                            logger.error("MLPEnsemble: mlp_trainer not available")
                            continue
                    model = mlp_cls.load(
                        str(model_path), device=device, validate_path=True,
                    )
                    model_label = model_path.parent.name

                model.eval()
                self._models.append(model)
                self._weights.append(weight)
                logger.info("MLPEnsemble: Loaded %s (weight=%.2f)", model_label, weight)
            except Exception as e:
                logger.warning("MLPEnsemble: Failed to load %s: %s", model_path, e)

        self._available = len(self._models) > 0

        if self._available:
            logger.info(
                "MLPEnsemble: %d/%d models loaded",
                len(self._models),
                len(self._configs),
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

    @staticmethod
    def _to_numpy(probs) -> np.ndarray:
        """Convert model output (torch Tensor or ndarray) to numpy."""
        if hasattr(probs, "cpu"):
            return probs.detach().cpu().numpy()
        return np.asarray(probs)

    def _prepare_input(self, features: np.ndarray):
        """Prepare input suitable for both MLP (torch) and tree (numpy) models.

        MLP models need torch Tensor; TreeModelWrapper handles both torch/numpy
        internally. Using torch as the common input format works for all.
        """
        import torch
        x = torch.FloatTensor(np.asarray(features, dtype=np.float32))
        if x.ndim == 1:
            x = x.unsqueeze(0)
        return x

    def predict(self, features: np.ndarray) -> tuple[int, float, np.ndarray]:
        """Make ensemble prediction via weighted soft voting.

        Args:
            features: Feature array of shape (num_features,).

        Returns:
            Tuple of (predicted_class, confidence, averaged_probs).
        """
        import torch

        x = self._prepare_input(features)
        weighted_probs = np.zeros(3)
        total_weight = 0.0

        for model, weight in zip(self._models, self._weights):
            try:
                with torch.no_grad():
                    probs = self._to_numpy(model.predict_proba(x))[0]
                weighted_probs += weight * probs
                total_weight += weight
            except Exception as e:
                logger.warning("MLPEnsemble: Model inference failed: %s", e)

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
        x = self._prepare_input(features)
        weighted_probs = np.zeros((N, 3))
        total_weight = 0.0

        for model, weight in zip(self._models, self._weights):
            try:
                with torch.no_grad():
                    probs = self._to_numpy(model.predict_proba(x))
                weighted_probs += weight * probs
                total_weight += weight
            except Exception as e:
                logger.warning("MLPEnsemble: Batch inference failed: %s", e)

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
