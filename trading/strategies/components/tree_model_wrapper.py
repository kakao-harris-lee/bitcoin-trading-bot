"""Tree model wrapper for XGBoost/LightGBM with predict_proba() interface.

Provides the same interface as MLPDirectionClassifier so that tree-based
models can be used interchangeably within MLPEnsemblePredictor.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


class TreeModelWrapper:
    """XGBoost/LightGBM wrapper with predict_proba() interface.

    Matches the MLPDirectionClassifier API so the ensemble predictor
    can mix MLP and tree-based models transparently.

    Detects model type from file extension:
        - .json → XGBoost (Booster)
        - .txt  → LightGBM (Booster)
    """

    def __init__(self, model: Any, model_type: str, n_classes: int = 3):
        self._model = model
        self._model_type = model_type  # "xgboost" or "lightgbm"
        self._n_classes = n_classes

    @classmethod
    def load(cls, path: str, device: str = "cpu", **kwargs) -> "TreeModelWrapper":
        """Load a tree model from file.

        Args:
            path: Path to model file (.json for XGBoost, .txt for LightGBM).
            device: Ignored (tree models run on CPU only).

        Returns:
            TreeModelWrapper instance.
        """
        _ = device
        _ = kwargs
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(f"Model file not found: {path}")

        suffix = p.suffix.lower()

        if suffix == ".json":
            import xgboost as xgb
            model = xgb.Booster()
            model.load_model(str(p))
            model_type = "xgboost"
            logger.info("TreeModelWrapper: Loaded XGBoost model from %s", p)
        elif suffix == ".txt":
            import lightgbm as lgb
            model = lgb.Booster(model_file=str(p))
            model_type = "lightgbm"
            logger.info("TreeModelWrapper: Loaded LightGBM model from %s", p)
        else:
            raise ValueError(
                f"Unsupported model file extension: {suffix}. "
                f"Expected .json (XGBoost) or .txt (LightGBM)."
            )

        return cls(model=model, model_type=model_type)

    def eval(self) -> "TreeModelWrapper":
        """No-op for API compatibility with PyTorch models."""
        return self

    def predict_proba(self, x) -> "np.ndarray":
        """Predict class probabilities.

        Args:
            x: Input features. Can be numpy array or torch Tensor.
               Shape: (batch_size, n_features) or (n_features,).

        Returns:
            numpy ndarray of shape (batch_size, n_classes) with probabilities.
        """
        # Convert torch Tensor to numpy if needed
        if hasattr(x, "numpy"):
            x_np = x.detach().cpu().numpy()
        else:
            x_np = np.asarray(x)

        # Handle 1-D input
        if x_np.ndim == 1:
            x_np = x_np.reshape(1, -1)

        if self._model_type == "xgboost":
            import xgboost as xgb
            dmat = xgb.DMatrix(x_np)
            probs = self._model.predict(dmat)  # (N, n_classes)
        elif self._model_type == "lightgbm":
            raw = self._model.predict(x_np)  # (N, n_classes)
            probs = np.asarray(raw)
        else:
            raise RuntimeError(f"Unknown model type: {self._model_type}")

        # Ensure shape is (N, n_classes)
        if probs.ndim == 1:
            probs = probs.reshape(-1, self._n_classes)

        return probs
