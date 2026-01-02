"""Tests for dataset class."""

import numpy as np
import pandas as pd
import torch
import pytest


def test_dataset_length():
    """Dataset length should be data_length - seq_len."""
    from src.dataset import TrendDataset

    # Create dummy data
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="4h"),
        "open": np.random.randn(100).cumsum() + 100,
        "high": np.random.randn(100).cumsum() + 101,
        "low": np.random.randn(100).cumsum() + 99,
        "close": np.random.randn(100).cumsum() + 100,
        "volume": np.abs(np.random.randn(100)) * 1000,
    })

    dataset = TrendDataset(df, seq_len=60, threshold=0.015)

    # Should have 100 - 60 - 1 = 39 samples (need next candle for label)
    assert len(dataset) == 39


def test_dataset_item_shape():
    """Each item should have correct tensor shapes."""
    from src.dataset import TrendDataset

    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="4h"),
        "open": np.random.randn(100).cumsum() + 100,
        "high": np.random.randn(100).cumsum() + 101,
        "low": np.random.randn(100).cumsum() + 99,
        "close": np.random.randn(100).cumsum() + 100,
        "volume": np.abs(np.random.randn(100)) * 1000,
    })

    dataset = TrendDataset(df, seq_len=60)
    x, y = dataset[0]

    assert x.shape == (60, 5), f"Expected (60, 5), got {x.shape}"
    assert isinstance(y, int) and y in [0, 1, 2]


def test_label_distribution():
    """Labels should be 0 (UP), 1 (DOWN), or 2 (SIDEWAYS)."""
    from src.dataset import TrendDataset

    # Create trending data
    closes = [100 + i * 0.5 for i in range(100)]  # Uptrend
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="4h"),
        "open": closes,
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
        "volume": [1000] * 100,
    })

    dataset = TrendDataset(df, seq_len=60, threshold=0.005)

    labels = [dataset[i][1] for i in range(len(dataset))]
    assert all(l in [0, 1, 2] for l in labels)
