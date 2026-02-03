"""Unit tests for MLP feature extraction module."""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from trading.indicators.mlp_features import (
    calculate_mlp_features,
    extract_single_features,
    calculate_bollinger_pct_b,
    calculate_ema_crossover,
    calculate_zscore,
    FEATURE_NAMES_SHAP,
    NUM_FEATURES_SHAP,
    FEATURE_SET_SHAP,
)


@pytest.fixture
def sample_ohlcv_df():
    """Create sample OHLCV DataFrame for testing."""
    np.random.seed(42)
    n = 200  # Enough for indicator warm-up

    # Generate realistic price data
    base_price = 50000
    returns = np.random.randn(n) * 0.02  # 2% daily volatility
    close = base_price * np.exp(np.cumsum(returns))

    # Generate OHLC from close
    high = close * (1 + np.abs(np.random.randn(n) * 0.01))
    low = close * (1 - np.abs(np.random.randn(n) * 0.01))
    open_price = close * (1 + np.random.randn(n) * 0.005)

    # Volume
    volume = np.random.uniform(100, 1000, n)

    # Timestamps (4H intervals)
    start = datetime(2024, 1, 1)
    timestamps = [start + timedelta(hours=4 * i) for i in range(n)]

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_price,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        }
    )


class TestCalculateMlpFeatures:
    """Tests for calculate_mlp_features function."""

    def test_output_shape(self, sample_ohlcv_df):
        """Test that output has correct shape."""
        features = calculate_mlp_features(sample_ohlcv_df, feature_set=FEATURE_SET_SHAP)

        assert features.shape[0] == len(sample_ohlcv_df)
        assert features.shape[1] == NUM_FEATURES_SHAP

    def test_output_columns(self, sample_ohlcv_df):
        """Test that output has all expected columns."""
        features = calculate_mlp_features(sample_ohlcv_df, feature_set=FEATURE_SET_SHAP)

        for col in FEATURE_NAMES_SHAP:
            assert col in features.columns, f"Missing column: {col}"

    def test_no_nan_after_warmup(self, sample_ohlcv_df):
        """Test that there are no NaN values after warm-up period."""
        features = calculate_mlp_features(sample_ohlcv_df, feature_set=FEATURE_SET_SHAP)

        # After 100 bars, all indicators should be valid
        features_after_warmup = features.iloc[100:]
        assert not features_after_warmup.isna().any().any()

    def test_bollinger_pct_b_range(self, sample_ohlcv_df):
        """Test Bollinger %B is in expected range."""
        features = calculate_mlp_features(sample_ohlcv_df, feature_set=FEATURE_SET_SHAP)
        bollinger = features["bollinger_pct_b"].dropna()

        # Should be clipped to [-0.5, 1.5]
        assert bollinger.min() >= -0.5
        assert bollinger.max() <= 1.5

    def test_rsi_range(self, sample_ohlcv_df):
        """Test RSI is normalized to 0-1."""
        features = calculate_mlp_features(sample_ohlcv_df, feature_set=FEATURE_SET_SHAP)
        rsi = features["rsi"].dropna()

        assert rsi.min() >= 0
        assert rsi.max() <= 1

    def test_zscore_range(self, sample_ohlcv_df):
        """Test Z-scores are normalized to -1 to 1."""
        features = calculate_mlp_features(sample_ohlcv_df, feature_set=FEATURE_SET_SHAP)

        price_zscore = features["price_zscore"].dropna()
        volume_zscore = features["volume_zscore"].dropna()

        assert price_zscore.min() >= -1
        assert price_zscore.max() <= 1
        assert volume_zscore.min() >= -1
        assert volume_zscore.max() <= 1

    def test_temporal_features(self, sample_ohlcv_df):
        """Test temporal features are correctly computed."""
        features = calculate_mlp_features(sample_ohlcv_df)

        hour = features["hour_of_day"]
        day = features["day_of_week"]
        month = features["month"]

        # Should be normalized to 0-1
        assert hour.min() >= 0
        assert hour.max() <= 1
        assert day.min() >= 0
        assert day.max() <= 1
        assert month.min() >= 0
        assert month.max() <= 1

    def test_ema_crossovers(self, sample_ohlcv_df):
        """Test EMA crossovers are computed correctly."""
        features = calculate_mlp_features(sample_ohlcv_df, feature_set=FEATURE_SET_SHAP)

        # EMA ratios should be around 1.0 for random walk
        # After fillna(0), check the values after warmup period
        for col in ["ema_cross_1_21", "ema_cross_21_50", "ema_cross_50_100", "ema_cross_1_50"]:
            # Get values after sufficient warmup (100+ bars for EMA100)
            crossover = features[col].iloc[110:].dropna()
            assert len(crossover) > 0  # Should have values
            assert crossover.mean() > 0.9  # Should be positive
            assert crossover.mean() < 1.1  # Should be around 1

    def test_without_temporal(self, sample_ohlcv_df):
        """Test features can be computed without temporal info."""
        features = calculate_mlp_features(
            sample_ohlcv_df,
            include_temporal=False,
            feature_set=FEATURE_SET_SHAP,
        )

        # Temporal features should be default 0.5
        assert features["hour_of_day"].iloc[-1] == 0.5
        assert features["day_of_week"].iloc[-1] == 0.5
        assert features["month"].iloc[-1] == 0.5


class TestExtractSingleFeatures:
    """Tests for extract_single_features function."""

    def test_output_shape(self):
        """Test output has correct shape."""
        indicators = {
            "bollinger_pct_b": 0.5,
            "rsi": 0.5,
            "ultosc": 0.5,
        }
        market_data = {"close": 50000}

        features = extract_single_features(market_data, indicators)

        assert features.shape == (NUM_FEATURES_SHAP,)
        assert features.dtype == np.float32

    def test_default_values(self):
        """Test that missing indicators get default values."""
        indicators = {}
        market_data = {"close": 50000}

        features = extract_single_features(market_data, indicators)

        # RSI default is 0.5
        assert features[1] == 0.5
        # Bollinger default is 0.5
        assert features[0] == 0.5
        # EMA crossovers default to 1.0
        assert features[3] == 1.0


class TestHelperFunctions:
    """Tests for helper functions."""

    def test_calculate_bollinger_pct_b(self):
        """Test Bollinger %B calculation."""
        np.random.seed(42)
        close = np.cumsum(np.random.randn(100)) + 100

        pct_b = calculate_bollinger_pct_b(close, period=20)

        # Should have NaN for first ~20 values
        assert np.isnan(pct_b[:19]).all()
        # Rest should be valid
        assert not np.isnan(pct_b[25:]).any()

    def test_calculate_ema_crossover(self):
        """Test EMA crossover calculation."""
        np.random.seed(42)
        close = np.cumsum(np.random.randn(100)) + 100

        crossover = calculate_ema_crossover(close, fast=10, slow=20)

        # Should have NaN for first ~slow period values (20 in this case)
        # EMA needs warmup period
        assert np.isnan(crossover[:18]).all()  # EMA(20) needs 19+ bars
        # After warmup, should be valid and positive
        assert not np.isnan(crossover[30:]).any()
        assert (crossover[30:] > 0).all()

    def test_calculate_zscore(self):
        """Test Z-score calculation."""
        np.random.seed(42)
        values = np.random.randn(100) * 10 + 100

        zscore = calculate_zscore(values, period=30)

        # Should be normalized to [-1, 1]
        valid = zscore[~np.isnan(zscore)]
        assert valid.min() >= -1
        assert valid.max() <= 1


class TestFeatureImportance:
    """Tests for feature importance ranking."""

    def test_importance_sum(self):
        """Test that importance values sum to approximately 1."""
        from trading.indicators.mlp_features import get_feature_importance_ranking

        ranking = get_feature_importance_ranking()
        total = sum(importance for _, importance in ranking)

        # Should sum to approximately 1 (within rounding)
        assert 0.9 <= total <= 1.1

    def test_top_features(self):
        """Test that top features match paper's findings."""
        from trading.indicators.mlp_features import get_feature_importance_ranking

        ranking = get_feature_importance_ranking()

        # Bollinger should be first
        assert ranking[0][0] == "bollinger_pct_b"
        # RSI should be second
        assert ranking[1][0] == "rsi"
