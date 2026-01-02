"""Tests for LSTM model."""

import torch
import pytest


def test_model_forward_shape():
    """Model output should have correct shape."""
    from src.model import TrendLSTM

    model = TrendLSTM(input_size=5, hidden_size=64, num_layers=2, num_classes=3)
    x = torch.randn(32, 60, 5)  # batch=32, seq=60, features=5

    output = model(x)

    assert output.shape == (32, 3), f"Expected (32, 3), got {output.shape}"


def test_model_inference_mode():
    """Model should work in eval mode without gradients."""
    from src.model import TrendLSTM

    model = TrendLSTM()
    model.eval()
    x = torch.randn(1, 60, 5)

    with torch.no_grad():
        output = model(x)
        probs = torch.softmax(output, dim=1)

    assert probs.sum().item() == pytest.approx(1.0, abs=1e-5)


def test_model_small_config():
    """Model should accept different configurations."""
    from src.model import TrendLSTM

    model = TrendLSTM(hidden_size=32, num_layers=1, dropout=0.0)
    x = torch.randn(8, 60, 5)

    output = model(x)

    assert output.shape == (8, 3)
