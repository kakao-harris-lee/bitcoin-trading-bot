"""Unit tests for Focal Loss implementation."""

import pytest
import torch
import torch.nn.functional as F
import numpy as np

from mlp_trainer.src.focal_loss import (
    FocalLoss,
    FocalLossWithLogits,
    focal_loss,
    create_focal_loss_for_mlp,
    MLP_DIRECTION_ALPHA,
)


@pytest.fixture
def logits():
    """Sample logits for testing."""
    return torch.randn(32, 3)


@pytest.fixture
def labels():
    """Sample labels for testing."""
    return torch.randint(0, 3, (32,))


class TestFocalLoss:
    """Tests for FocalLoss class."""

    def test_default_initialization(self):
        """Test FocalLoss initializes with default parameters."""
        criterion = FocalLoss()
        assert criterion.gamma == 2.0
        assert criterion.reduction == "mean"
        assert criterion.alpha is None

    def test_custom_initialization(self):
        """Test FocalLoss with custom parameters."""
        criterion = FocalLoss(gamma=3.0, alpha=[0.25, 0.5, 0.5], reduction="sum")
        assert criterion.gamma == 3.0
        assert criterion.reduction == "sum"
        assert criterion.alpha is not None
        assert criterion.alpha.shape == (3,)

    def test_output_shape_mean(self, logits, labels):
        """Test loss output is scalar with mean reduction."""
        criterion = FocalLoss(gamma=2.0, reduction="mean")
        loss = criterion(logits, labels)
        assert loss.shape == ()
        assert loss.ndim == 0

    def test_output_shape_sum(self, logits, labels):
        """Test loss output is scalar with sum reduction."""
        criterion = FocalLoss(gamma=2.0, reduction="sum")
        loss = criterion(logits, labels)
        assert loss.shape == ()
        assert loss.ndim == 0

    def test_output_shape_none(self, logits, labels):
        """Test loss output shape with no reduction."""
        criterion = FocalLoss(gamma=2.0, reduction="none")
        loss = criterion(logits, labels)
        assert loss.shape == (32,)

    def test_loss_is_positive(self, logits, labels):
        """Test that loss is always positive."""
        criterion = FocalLoss(gamma=2.0)
        loss = criterion(logits, labels)
        assert loss.item() > 0

    def test_gamma_zero_equals_cross_entropy(self, logits, labels):
        """Test that gamma=0 gives cross entropy loss."""
        focal_criterion = FocalLoss(gamma=0.0, alpha=None, reduction="mean")
        focal_loss_val = focal_criterion(logits, labels)

        ce_loss = F.cross_entropy(logits, labels, reduction="mean")

        assert torch.allclose(focal_loss_val, ce_loss, atol=1e-5)

    def test_higher_gamma_lower_easy_loss(self):
        """Test that higher gamma reduces loss for easy examples."""
        # Create confident correct predictions
        batch_size = 32
        labels = torch.arange(3).repeat(batch_size // 3 + 1)[:batch_size]
        logits = torch.zeros(batch_size, 3)
        logits[torch.arange(batch_size), labels] = 10.0  # High confidence

        low_gamma = FocalLoss(gamma=1.0)
        high_gamma = FocalLoss(gamma=4.0)

        loss_low = low_gamma(logits, labels)
        loss_high = high_gamma(logits, labels)

        # Higher gamma should give lower loss for easy examples
        assert loss_high < loss_low

    def test_alpha_weighting(self, logits, labels):
        """Test that alpha weights affect loss."""
        # All same weight vs different weights
        uniform_criterion = FocalLoss(gamma=2.0, alpha=[1.0, 1.0, 1.0])
        weighted_criterion = FocalLoss(gamma=2.0, alpha=[0.1, 0.5, 0.9])

        uniform_loss = uniform_criterion(logits, labels)
        weighted_loss = weighted_criterion(logits, labels)

        # Losses should differ with different alpha
        assert not torch.allclose(uniform_loss, weighted_loss)

    def test_gradient_flow(self, logits, labels):
        """Test that gradients flow correctly."""
        logits.requires_grad = True
        criterion = FocalLoss(gamma=2.0)
        loss = criterion(logits, labels)
        loss.backward()

        assert logits.grad is not None
        assert not torch.isnan(logits.grad).any()
        assert not torch.isinf(logits.grad).any()

    def test_numerical_stability(self):
        """Test numerical stability with extreme values."""
        criterion = FocalLoss(gamma=2.0)

        # Very confident predictions
        labels = torch.tensor([0, 1, 2])
        logits_confident = torch.tensor([
            [100.0, -100.0, -100.0],
            [-100.0, 100.0, -100.0],
            [-100.0, -100.0, 100.0],
        ])

        loss = criterion(logits_confident, labels)
        assert not torch.isnan(loss)
        assert not torch.isinf(loss)
        assert loss >= 0

    def test_label_smoothing(self, logits, labels):
        """Test label smoothing option."""
        criterion_no_smooth = FocalLoss(gamma=2.0, label_smoothing=0.0)
        criterion_smooth = FocalLoss(gamma=2.0, label_smoothing=0.1)

        loss_no_smooth = criterion_no_smooth(logits, labels)
        loss_smooth = criterion_smooth(logits, labels)

        # Label smoothing typically increases loss slightly
        assert not torch.allclose(loss_no_smooth, loss_smooth)


class TestFocalLossWithLogits:
    """Tests for FocalLossWithLogits alias."""

    def test_is_subclass(self):
        """Test that FocalLossWithLogits is a FocalLoss subclass."""
        assert issubclass(FocalLossWithLogits, FocalLoss)

    def test_same_behavior(self, logits, labels):
        """Test that FocalLossWithLogits behaves same as FocalLoss."""
        focal = FocalLoss(gamma=2.0)
        focal_logits = FocalLossWithLogits(gamma=2.0)

        loss1 = focal(logits, labels)
        loss2 = focal_logits(logits, labels)

        assert torch.equal(loss1, loss2)


class TestFocalLossFunction:
    """Tests for focal_loss functional interface."""

    def test_basic_usage(self, logits, labels):
        """Test basic functional interface."""
        loss = focal_loss(logits, labels, gamma=2.0)
        assert loss.shape == ()
        assert loss.item() > 0

    def test_matches_class_interface(self, logits, labels):
        """Test functional interface matches class interface."""
        class_loss = FocalLoss(gamma=2.0, alpha=[0.25, 0.5, 0.5])(logits, labels)
        func_loss = focal_loss(logits, labels, gamma=2.0, alpha=[0.25, 0.5, 0.5])

        assert torch.allclose(class_loss, func_loss)


class TestCreateFocalLossForMLP:
    """Tests for create_focal_loss_for_mlp factory."""

    def test_default_config(self):
        """Test default MLP focal loss configuration."""
        criterion = create_focal_loss_for_mlp()

        assert criterion.gamma == 2.0
        assert criterion.alpha is not None
        assert torch.allclose(criterion.alpha, torch.tensor(MLP_DIRECTION_ALPHA))

    def test_custom_gamma(self):
        """Test custom gamma parameter."""
        criterion = create_focal_loss_for_mlp(gamma=3.0)
        assert criterion.gamma == 3.0

    def test_custom_alpha(self):
        """Test custom alpha parameter."""
        custom_alpha = [0.1, 0.4, 0.5]
        criterion = create_focal_loss_for_mlp(alpha=custom_alpha)

        assert torch.allclose(criterion.alpha, torch.tensor(custom_alpha))

    def test_reduction_is_mean(self):
        """Test that reduction is set to mean."""
        criterion = create_focal_loss_for_mlp()
        assert criterion.reduction == "mean"


class TestMLPDirectionAlpha:
    """Tests for MLP_DIRECTION_ALPHA constant."""

    def test_has_three_values(self):
        """Test alpha has 3 values for Hold/Buy/Sell."""
        assert len(MLP_DIRECTION_ALPHA) == 3

    def test_hold_lower_weight(self):
        """Test Hold class has lower weight (majority class)."""
        hold_weight = MLP_DIRECTION_ALPHA[0]
        buy_weight = MLP_DIRECTION_ALPHA[1]
        sell_weight = MLP_DIRECTION_ALPHA[2]

        assert hold_weight < buy_weight
        assert hold_weight < sell_weight

    def test_values_sum_reasonable(self):
        """Test alpha values are reasonable."""
        total = sum(MLP_DIRECTION_ALPHA)
        assert 0.5 < total < 2.0  # Reasonable range


class TestFocalLossDevices:
    """Tests for device handling."""

    def test_cpu_computation(self, logits, labels):
        """Test computation on CPU."""
        criterion = FocalLoss(gamma=2.0, alpha=[0.25, 0.5, 0.5])
        loss = criterion(logits.cpu(), labels.cpu())
        assert loss.device.type == "cpu"

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
    def test_cuda_computation(self, logits, labels):
        """Test computation on CUDA."""
        criterion = FocalLoss(gamma=2.0, alpha=[0.25, 0.5, 0.5])
        logits_cuda = logits.cuda()
        labels_cuda = labels.cuda()

        loss = criterion(logits_cuda, labels_cuda)
        assert loss.device.type == "cuda"

    @pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
    def test_alpha_moves_to_device(self, logits, labels):
        """Test alpha buffer moves to correct device."""
        criterion = FocalLoss(gamma=2.0, alpha=[0.25, 0.5, 0.5])
        logits_cuda = logits.cuda()
        labels_cuda = labels.cuda()

        # Should not raise device mismatch error
        loss = criterion(logits_cuda, labels_cuda)
        assert not torch.isnan(loss)
