"""Tests for TreeModelWrapper — XGBoost/LightGBM wrapper with predict_proba interface."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from trading.strategies.components.tree_model_wrapper import TreeModelWrapper


def _require_xgboost():
    return pytest.importorskip("xgboost")


def _require_lightgbm():
    return pytest.importorskip("lightgbm")


class TestTreeModelWrapperLoad:
    """Test model loading and type detection."""

    def test_load_xgboost_from_json(self, tmp_path):
        """Loading .json file should use XGBoost Booster."""
        xgb = _require_xgboost()

        # Create a minimal XGBoost model
        X = np.random.randn(100, 36).astype(np.float32)
        y = np.random.randint(0, 3, 100)
        dtrain = xgb.DMatrix(X, label=y)
        params = {
            "objective": "multi:softprob",
            "num_class": 3,
            "max_depth": 2,
            "n_estimators": 5,
        }
        booster = xgb.train(params, dtrain, num_boost_round=5)

        model_path = tmp_path / "model.json"
        booster.save_model(str(model_path))

        wrapper = TreeModelWrapper.load(str(model_path))
        assert wrapper._model_type == "xgboost"

    def test_load_lightgbm_from_txt(self, tmp_path):
        """Loading .txt file should use LightGBM Booster."""
        lgb = _require_lightgbm()

        # Create a minimal LightGBM model
        X = np.random.randn(100, 36).astype(np.float32)
        y = np.random.randint(0, 3, 100)
        dtrain = lgb.Dataset(X, label=y)
        params = {
            "objective": "multiclass",
            "num_class": 3,
            "max_depth": 2,
            "num_leaves": 4,
            "verbose": -1,
        }
        booster = lgb.train(params, dtrain, num_boost_round=5)

        model_path = tmp_path / "model.txt"
        booster.save_model(str(model_path))

        wrapper = TreeModelWrapper.load(str(model_path))
        assert wrapper._model_type == "lightgbm"

    def test_load_unsupported_extension(self, tmp_path):
        """Unsupported extension should raise ValueError."""
        model_path = tmp_path / "model.pkl"
        model_path.write_text("fake")

        with pytest.raises(ValueError, match="Unsupported model file extension"):
            TreeModelWrapper.load(str(model_path))

    def test_load_missing_file(self):
        """Missing file should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            TreeModelWrapper.load("/nonexistent/model.json")

    def test_eval_returns_self(self):
        """eval() should return self (no-op)."""
        wrapper = TreeModelWrapper(model=MagicMock(), model_type="xgboost")
        result = wrapper.eval()
        assert result is wrapper


class TestTreeModelWrapperPredict:
    """Test predict_proba interface for both XGBoost and LightGBM."""

    @pytest.fixture
    def xgb_wrapper(self, tmp_path):
        """Create a real XGBoost wrapper for testing."""
        xgb = _require_xgboost()

        X = np.random.randn(200, 36).astype(np.float32)
        y = np.random.randint(0, 3, 200)
        dtrain = xgb.DMatrix(X, label=y)
        params = {
            "objective": "multi:softprob",
            "num_class": 3,
            "max_depth": 3,
        }
        booster = xgb.train(params, dtrain, num_boost_round=10)

        model_path = tmp_path / "xgb_model.json"
        booster.save_model(str(model_path))
        return TreeModelWrapper.load(str(model_path))

    @pytest.fixture
    def lgb_wrapper(self, tmp_path):
        """Create a real LightGBM wrapper for testing."""
        lgb = _require_lightgbm()

        X = np.random.randn(200, 36).astype(np.float32)
        y = np.random.randint(0, 3, 200)
        dtrain = lgb.Dataset(X, label=y)
        params = {
            "objective": "multiclass",
            "num_class": 3,
            "max_depth": 3,
            "num_leaves": 8,
            "verbose": -1,
        }
        booster = lgb.train(params, dtrain, num_boost_round=10)

        model_path = tmp_path / "lgb_model.txt"
        booster.save_model(str(model_path))
        return TreeModelWrapper.load(str(model_path))

    def test_xgb_predict_proba_batch(self, xgb_wrapper):
        """XGBoost should return (N, 3) probability matrix."""
        X = np.random.randn(10, 36).astype(np.float32)
        probs = xgb_wrapper.predict_proba(X)

        assert probs.shape == (10, 3)
        # Probabilities should sum to ~1
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-5)
        # All probabilities should be non-negative
        assert (probs >= 0).all()

    def test_xgb_predict_proba_single(self, xgb_wrapper):
        """XGBoost should handle 1-D input (single sample)."""
        x = np.random.randn(36).astype(np.float32)
        probs = xgb_wrapper.predict_proba(x)

        assert probs.shape == (1, 3)
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-5)

    def test_lgb_predict_proba_batch(self, lgb_wrapper):
        """LightGBM should return (N, 3) probability matrix."""
        X = np.random.randn(10, 36).astype(np.float32)
        probs = lgb_wrapper.predict_proba(X)

        assert probs.shape == (10, 3)
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-5)
        assert (probs >= 0).all()

    def test_lgb_predict_proba_single(self, lgb_wrapper):
        """LightGBM should handle 1-D input (single sample)."""
        x = np.random.randn(36).astype(np.float32)
        probs = lgb_wrapper.predict_proba(x)

        assert probs.shape == (1, 3)
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-5)

    def test_xgb_accepts_torch_tensor(self, xgb_wrapper):
        """XGBoost wrapper should accept torch Tensor input."""
        import torch
        x = torch.randn(5, 36)
        probs = xgb_wrapper.predict_proba(x)

        assert isinstance(probs, np.ndarray)
        assert probs.shape == (5, 3)

    def test_lgb_accepts_torch_tensor(self, lgb_wrapper):
        """LightGBM wrapper should accept torch Tensor input."""
        import torch
        x = torch.randn(5, 36)
        probs = lgb_wrapper.predict_proba(x)

        assert isinstance(probs, np.ndarray)
        assert probs.shape == (5, 3)


class TestTreeModelWrapperEnsembleCompatibility:
    """Test that TreeModelWrapper works within MLPEnsemblePredictor."""

    def test_mixed_ensemble_predict(self, tmp_path):
        """Ensemble should handle mix of MLP mock + real tree model."""
        import torch
        from trading.strategies.components.mlp_ensemble import MLPEnsemblePredictor
        xgb = _require_xgboost()

        # Create a real XGBoost model
        X = np.random.randn(100, 36).astype(np.float32)
        y = np.random.randint(0, 3, 100)
        dtrain = xgb.DMatrix(X, label=y)
        booster = xgb.train(
            {"objective": "multi:softprob", "num_class": 3, "max_depth": 2},
            dtrain, num_boost_round=5,
        )
        xgb_path = tmp_path / "model.json"
        booster.save_model(str(xgb_path))

        # Create mock MLP model
        mlp_mock = MagicMock()
        mlp_mock.eval = MagicMock(return_value=mlp_mock)
        mlp_mock.predict_proba = lambda x: np.array([[0.2, 0.6, 0.2]] * (x.shape[0] if hasattr(x, 'shape') and x.ndim > 1 else 1))

        # Load XGBoost wrapper
        xgb_wrapper = TreeModelWrapper.load(str(xgb_path))

        # Create ensemble manually
        ensemble = MLPEnsemblePredictor([])
        ensemble._models = [mlp_mock, xgb_wrapper]
        ensemble._weights = [0.5, 0.5]
        ensemble._loaded = True
        ensemble._available = True

        # Predict
        features = np.random.randn(36).astype(np.float32)
        pred_class, confidence, probs = ensemble.predict(features)

        assert probs.shape == (3,)
        assert 0 <= pred_class <= 2
        assert 0.0 < confidence <= 1.0
        np.testing.assert_allclose(probs.sum(), 1.0, atol=1e-4)

    def test_mixed_ensemble_batch_predict(self, tmp_path):
        """Batch prediction should work with mixed model types."""
        lgb = _require_lightgbm()
        from trading.strategies.components.mlp_ensemble import MLPEnsemblePredictor

        # Create a real LightGBM model
        X = np.random.randn(100, 36).astype(np.float32)
        y = np.random.randint(0, 3, 100)
        dtrain = lgb.Dataset(X, label=y)
        booster = lgb.train(
            {"objective": "multiclass", "num_class": 3, "max_depth": 2,
             "num_leaves": 4, "verbose": -1},
            dtrain, num_boost_round=5,
        )
        lgb_path = tmp_path / "model.txt"
        booster.save_model(str(lgb_path))

        lgb_wrapper = TreeModelWrapper.load(str(lgb_path))

        # Mock MLP
        mlp_mock = MagicMock()
        mlp_mock.eval = MagicMock(return_value=mlp_mock)
        mlp_mock.predict_proba = lambda x: np.tile([0.3, 0.4, 0.3], (x.shape[0], 1))

        ensemble = MLPEnsemblePredictor([])
        ensemble._models = [mlp_mock, lgb_wrapper]
        ensemble._weights = [0.6, 0.4]
        ensemble._loaded = True
        ensemble._available = True

        features = np.random.randn(20, 36).astype(np.float32)
        preds, confs, probs = ensemble.predict_batch(features)

        assert preds.shape == (20,)
        assert confs.shape == (20,)
        assert probs.shape == (20, 3)
        np.testing.assert_allclose(probs.sum(axis=1), 1.0, atol=1e-4)
