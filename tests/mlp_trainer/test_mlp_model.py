"""Unit tests for MLP model definition."""

import pytest
import torch
import numpy as np
import tempfile
import os

from mlp_trainer.src.mlp_model import (
    MLPDirectionClassifier,
    MLPConfig,
    EnsembleMLPClassifier,
    create_model,
)


@pytest.fixture
def model():
    """Create a model instance for testing."""
    return MLPDirectionClassifier()


@pytest.fixture
def batch_input():
    """Create sample batch input."""
    return torch.randn(32, 13)


@pytest.fixture
def single_input():
    """Create single sample input."""
    return torch.randn(1, 13)


class TestMLPDirectionClassifier:
    """Tests for MLPDirectionClassifier class."""

    def test_default_initialization(self, model):
        """Test model initializes with default parameters."""
        assert model.input_dim == 13
        assert model.hidden_dims == (128, 64, 32)
        assert model.num_classes == 3

    def test_custom_initialization(self):
        """Test model initializes with custom parameters."""
        model = MLPDirectionClassifier(
            input_dim=20,
            hidden_dims=(64, 32),
            num_classes=5,
            dropout=0.3,
        )

        assert model.input_dim == 20
        assert model.hidden_dims == (64, 32)
        assert model.num_classes == 5
        assert model.dropout_rate == 0.3

    def test_forward_output_shape(self, model, batch_input):
        """Test forward pass produces correct output shape."""
        output = model(batch_input)

        assert output.shape == (32, 3)

    def test_forward_single_sample(self, model, single_input):
        """Test forward pass works with single sample."""
        output = model(single_input)

        assert output.shape == (1, 3)

    def test_predict_proba_output_shape(self, model, batch_input):
        """Test predict_proba produces correct shape."""
        probs = model.predict_proba(batch_input)

        assert probs.shape == (32, 3)

    def test_predict_proba_sums_to_one(self, model, batch_input):
        """Test that probabilities sum to 1."""
        probs = model.predict_proba(batch_input)
        sums = probs.sum(dim=1)

        assert torch.allclose(sums, torch.ones(32), atol=1e-5)

    def test_predict_proba_range(self, model, batch_input):
        """Test that probabilities are in [0, 1]."""
        probs = model.predict_proba(batch_input)

        assert (probs >= 0).all()
        assert (probs <= 1).all()

    def test_predict_output_shape(self, model, batch_input):
        """Test predict produces correct shape."""
        preds = model.predict(batch_input)

        assert preds.shape == (32,)

    def test_predict_valid_classes(self, model, batch_input):
        """Test predict produces valid class indices."""
        preds = model.predict(batch_input)

        assert (preds >= 0).all()
        assert (preds <= 2).all()

    def test_predict_numpy_batch(self, model):
        """Test predict_numpy with batch input."""
        x = np.random.randn(32, 13).astype(np.float32)
        preds, probs = model.predict_numpy(x)

        assert preds.shape == (32,)
        assert probs.shape == (32, 3)

    def test_predict_numpy_single(self, model):
        """Test predict_numpy with single sample."""
        x = np.random.randn(13).astype(np.float32)
        preds, probs = model.predict_numpy(x)

        assert preds.shape == (1,)
        assert probs.shape == (1, 3)

    def test_count_parameters(self, model):
        """Test parameter count is reasonable."""
        num_params = model.count_parameters()

        # Should be around 15k-20k parameters
        assert 10000 < num_params < 50000

    def test_summary(self, model):
        """Test summary string is generated."""
        summary = model.summary()

        assert "MLPDirectionClassifier" in summary
        assert "Input dimension: 13" in summary
        assert "Output classes: 3" in summary


class TestModelSaveLoad:
    """Tests for model save/load functionality."""

    def test_save_load_roundtrip(self, model, batch_input):
        """Test that saved model can be loaded and produces same output."""
        # Set to eval mode for deterministic output
        model.eval()

        # Get output before save
        with torch.no_grad():
            original_output = model(batch_input)

        # Save and load
        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "model.pt")
            model.save(path)

            loaded_model = MLPDirectionClassifier.load(path, validate_path=False)

        # Compare outputs (loaded model is already in eval mode from load())
        with torch.no_grad():
            loaded_output = loaded_model(batch_input)

        assert torch.allclose(original_output, loaded_output, atol=1e-5)

    def test_load_preserves_config(self):
        """Test that loaded model has correct config."""
        model = MLPDirectionClassifier(
            input_dim=10,
            hidden_dims=(64, 32),
            num_classes=4,
            dropout=0.4,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "model.pt")
            model.save(path)

            loaded_model = MLPDirectionClassifier.load(path, validate_path=False)

        assert loaded_model.input_dim == 10
        assert loaded_model.hidden_dims == (64, 32)
        assert loaded_model.num_classes == 4

    def test_save_creates_directory(self):
        """Test that save creates parent directories."""
        model = MLPDirectionClassifier()

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "nested", "dir", "model.pt")
            model.save(path)

            assert os.path.exists(path)


class TestModelTraining:
    """Tests for model training behavior."""

    def test_train_eval_mode(self, model, batch_input):
        """Test switching between train and eval modes."""
        # In train mode, dropout is active
        model.train()
        out1 = model(batch_input)
        out2 = model(batch_input)

        # Outputs may differ due to dropout
        # (though with same input, they could be same if dropout keeps same mask)

        # In eval mode, dropout is inactive
        model.eval()
        out3 = model(batch_input)
        out4 = model(batch_input)

        # Outputs should be identical in eval mode
        assert torch.allclose(out3, out4)

    def test_gradient_flow(self, model, batch_input):
        """Test that gradients flow through the network."""
        model.train()

        target = torch.randint(0, 3, (32,))
        output = model(batch_input)

        loss = torch.nn.functional.cross_entropy(output, target)
        loss.backward()

        # Check that gradients exist
        for param in model.parameters():
            if param.requires_grad:
                assert param.grad is not None
                assert not torch.isnan(param.grad).any()


class TestMLPConfig:
    """Tests for MLPConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = MLPConfig()

        assert config.input_dim == 13
        assert config.hidden_dims == (128, 64, 32)
        assert config.num_classes == 3
        assert config.dropout == 0.2

    def test_custom_config(self):
        """Test custom configuration."""
        config = MLPConfig(
            input_dim=20,
            hidden_dims=(256, 128),
            num_classes=5,
        )

        assert config.input_dim == 20
        assert config.hidden_dims == (256, 128)
        assert config.num_classes == 5


class TestCreateModel:
    """Tests for create_model factory function."""

    def test_create_default_model(self):
        """Test creating model with default config."""
        model = create_model()

        assert model.input_dim == 13
        assert model.num_classes == 3

    def test_create_custom_model(self):
        """Test creating model with custom config."""
        config = MLPConfig(input_dim=20, num_classes=5)
        model = create_model(config)

        assert model.input_dim == 20
        assert model.num_classes == 5

    def test_create_on_device(self):
        """Test creating model on specific device."""
        model = create_model(device="cpu")

        # Check parameters are on CPU
        for param in model.parameters():
            assert param.device.type == "cpu"


class TestEnsembleMLPClassifier:
    """Tests for EnsembleMLPClassifier class."""

    def test_ensemble_creation(self):
        """Test creating ensemble from multiple models."""
        models = [MLPDirectionClassifier() for _ in range(3)]
        ensemble = EnsembleMLPClassifier(models)

        assert len(ensemble.models) == 3

    def test_ensemble_forward(self):
        """Test ensemble forward pass."""
        models = [MLPDirectionClassifier() for _ in range(3)]
        ensemble = EnsembleMLPClassifier(models)

        x = torch.randn(32, 13)
        output = ensemble(x)

        assert output.shape == (32, 3)

    def test_ensemble_predict_proba(self):
        """Test ensemble predict_proba."""
        models = [MLPDirectionClassifier() for _ in range(3)]
        ensemble = EnsembleMLPClassifier(models)

        x = torch.randn(32, 13)
        probs = ensemble.predict_proba(x)

        assert probs.shape == (32, 3)
        assert torch.allclose(probs.sum(dim=1), torch.ones(32), atol=1e-5)

    def test_ensemble_load(self):
        """Test loading ensemble from multiple files."""
        models = [MLPDirectionClassifier() for _ in range(3)]

        with tempfile.TemporaryDirectory() as tmpdir:
            paths = []
            for i, model in enumerate(models):
                path = os.path.join(tmpdir, f"model_{i}.pt")
                model.save(path)
                paths.append(path)

            ensemble = EnsembleMLPClassifier.load_ensemble(paths, validate_path=False)

        assert len(ensemble.models) == 3


class TestModelNumericalStability:
    """Tests for numerical stability."""

    def test_extreme_inputs(self, model):
        """Test model handles extreme input values."""
        # Large values
        x_large = torch.ones(1, 13) * 1000
        out_large = model(x_large)
        assert not torch.isnan(out_large).any()
        assert not torch.isinf(out_large).any()

        # Small values
        x_small = torch.ones(1, 13) * 1e-6
        out_small = model(x_small)
        assert not torch.isnan(out_small).any()
        assert not torch.isinf(out_small).any()

        # Negative values
        x_neg = torch.ones(1, 13) * -100
        out_neg = model(x_neg)
        assert not torch.isnan(out_neg).any()
        assert not torch.isinf(out_neg).any()

    def test_zero_input(self, model):
        """Test model handles zero input."""
        x = torch.zeros(1, 13)
        out = model(x)

        assert not torch.isnan(out).any()
        assert not torch.isinf(out).any()

    def test_deterministic_eval(self, model, batch_input):
        """Test model is deterministic in eval mode."""
        model.eval()

        out1 = model(batch_input)
        out2 = model(batch_input)

        assert torch.equal(out1, out2)
