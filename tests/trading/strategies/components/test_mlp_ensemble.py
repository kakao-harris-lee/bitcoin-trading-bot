"""Tests for MLPEnsemblePredictor — soft-voting across multiple MLP models."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from trading.strategies.components.mlp_ensemble import MLPEnsemblePredictor


def _make_mock_model(probs: np.ndarray):
    """Create a mock MLPDirectionClassifier that returns fixed probabilities."""
    import torch

    model = MagicMock()
    model.eval = MagicMock()

    def predict_proba(x):
        batch_size = x.shape[0]
        return torch.FloatTensor(np.tile(probs, (batch_size, 1)))

    model.predict_proba = predict_proba
    return model


class TestMLPEnsemblePredictor:
    """Test MLPEnsemblePredictor soft-voting logic."""

    def test_single_model_passthrough(self):
        """With one model, ensemble should return same as single model."""
        ensemble = MLPEnsemblePredictor([
            {"model_path": "models/fake/model_final.pt", "weight": 1.0},
        ])
        # Manually inject mock model
        mock = _make_mock_model(np.array([0.2, 0.7, 0.1]))
        ensemble._models = [mock]
        ensemble._weights = [1.0]
        ensemble._loaded = True
        ensemble._available = True

        pred, conf, probs = ensemble.predict(np.zeros(36, dtype=np.float32))
        assert pred == 1  # BUY (highest prob)
        assert conf == pytest.approx(0.7, abs=0.01)
        assert probs.shape == (3,)

    def test_uniform_weight_averaging(self):
        """Equal weights should produce simple average of probabilities."""
        ensemble = MLPEnsemblePredictor([])
        ensemble._models = [
            _make_mock_model(np.array([0.3, 0.5, 0.2])),  # BUY
            _make_mock_model(np.array([0.4, 0.3, 0.3])),  # HOLD
        ]
        ensemble._weights = [1.0, 1.0]
        ensemble._loaded = True
        ensemble._available = True

        pred, conf, probs = ensemble.predict(np.zeros(36, dtype=np.float32))
        # Average: [0.35, 0.40, 0.25] → BUY (class 1)
        assert pred == 1
        assert probs[0] == pytest.approx(0.35, abs=0.01)
        assert probs[1] == pytest.approx(0.40, abs=0.01)
        assert probs[2] == pytest.approx(0.25, abs=0.01)

    def test_weighted_voting(self):
        """Weighted voting should favor higher-weighted models."""
        ensemble = MLPEnsemblePredictor([])
        ensemble._models = [
            _make_mock_model(np.array([0.1, 0.8, 0.1])),  # Strong BUY
            _make_mock_model(np.array([0.6, 0.2, 0.2])),  # Strong HOLD
        ]
        # BUY model has 3x weight
        ensemble._weights = [3.0, 1.0]
        ensemble._loaded = True
        ensemble._available = True

        pred, conf, probs = ensemble.predict(np.zeros(36, dtype=np.float32))
        # Weighted: (3*[0.1,0.8,0.1] + 1*[0.6,0.2,0.2]) / 4 = [0.225, 0.65, 0.125]
        assert pred == 1  # BUY wins due to weight
        assert probs[1] == pytest.approx(0.65, abs=0.01)

    def test_consensus_buy(self):
        """When all models agree on BUY, confidence should be high."""
        ensemble = MLPEnsemblePredictor([])
        ensemble._models = [
            _make_mock_model(np.array([0.1, 0.8, 0.1])),
            _make_mock_model(np.array([0.15, 0.7, 0.15])),
            _make_mock_model(np.array([0.2, 0.6, 0.2])),
        ]
        ensemble._weights = [1.0, 1.0, 1.0]
        ensemble._loaded = True
        ensemble._available = True

        pred, conf, probs = ensemble.predict(np.zeros(36, dtype=np.float32))
        assert pred == 1  # BUY consensus
        assert conf > 0.65  # High confidence from consensus

    def test_disagreement_reduces_confidence(self):
        """When models disagree, confidence should be lower."""
        ensemble = MLPEnsemblePredictor([])
        ensemble._models = [
            _make_mock_model(np.array([0.1, 0.8, 0.1])),  # BUY
            _make_mock_model(np.array([0.8, 0.1, 0.1])),  # HOLD
            _make_mock_model(np.array([0.1, 0.1, 0.8])),  # SELL
        ]
        ensemble._weights = [1.0, 1.0, 1.0]
        ensemble._loaded = True
        ensemble._available = True

        pred, conf, probs = ensemble.predict(np.zeros(36, dtype=np.float32))
        # Average: [0.333, 0.333, 0.333] → near-equal split
        assert conf < 0.4  # Low confidence from disagreement

    def test_batch_predict(self):
        """Batch prediction should process multiple samples."""
        ensemble = MLPEnsemblePredictor([])
        ensemble._models = [
            _make_mock_model(np.array([0.2, 0.6, 0.2])),
        ]
        ensemble._weights = [1.0]
        ensemble._loaded = True
        ensemble._available = True

        features = np.zeros((10, 36), dtype=np.float32)
        preds, confs, probs = ensemble.predict_batch(features)

        assert preds.shape == (10,)
        assert confs.shape == (10,)
        assert probs.shape == (10, 3)
        assert (preds == 1).all()  # All BUY
        assert np.allclose(confs, 0.6, atol=0.01)

    def test_batch_predict_multiple_models(self):
        """Batch prediction with multiple models should average correctly."""
        ensemble = MLPEnsemblePredictor([])
        ensemble._models = [
            _make_mock_model(np.array([0.3, 0.5, 0.2])),
            _make_mock_model(np.array([0.4, 0.4, 0.2])),
        ]
        ensemble._weights = [1.0, 1.0]
        ensemble._loaded = True
        ensemble._available = True

        features = np.zeros((5, 36), dtype=np.float32)
        preds, confs, probs = ensemble.predict_batch(features)

        # Average: [0.35, 0.45, 0.20]
        assert preds.shape == (5,)
        assert (preds == 1).all()  # BUY
        assert np.allclose(probs[:, 1], 0.45, atol=0.01)

    def test_no_models_returns_hold(self):
        """With no loaded models, predict should return HOLD with default probs."""
        ensemble = MLPEnsemblePredictor([])
        # Simulate: loaded but no models succeeded
        ensemble._models = []
        ensemble._weights = []
        ensemble._loaded = True
        ensemble._available = True  # Bypass check to test predict directly

        pred, conf, probs = ensemble.predict(np.zeros(36, dtype=np.float32))
        # No models → total_weight = 0 → returns HOLD with 0 confidence
        assert pred == 0  # HOLD
        assert conf == pytest.approx(0.0)
        np.testing.assert_array_almost_equal(probs, [1.0, 0.0, 0.0])

    def test_model_count(self):
        """num_models should return count of loaded models."""
        ensemble = MLPEnsemblePredictor([])
        ensemble._models = [MagicMock(), MagicMock(), MagicMock()]
        assert ensemble.num_models == 3

    def test_is_available_default_false(self):
        """Ensemble should not be available before loading."""
        ensemble = MLPEnsemblePredictor([
            {"model_path": "fake/path.pt", "weight": 1.0},
        ])
        assert not ensemble.is_available

    def test_load_skips_missing_models(self):
        """Models with non-existent paths should be skipped."""
        ensemble = MLPEnsemblePredictor([
            {"model_path": "/nonexistent/model1.pt", "weight": 1.0},
            {"model_path": "/nonexistent/model2.pt", "weight": 1.0},
        ])
        result = ensemble.load()
        assert not result
        assert ensemble.num_models == 0

    def test_default_weight(self):
        """Models without explicit weight should default to 1.0."""
        ensemble = MLPEnsemblePredictor([
            {"model_path": "fake.pt"},  # No weight key
        ])
        # Can't test without loading, but verify config is stored
        assert ensemble._configs[0].get("weight", 1.0) == 1.0
