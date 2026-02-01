"""Unit tests for MLP labeling algorithm."""

import pytest
import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from core.mlp_labeling import (
    compute_labels,
    compute_returns,
    get_label_distribution,
    compute_optimal_thresholds,
    balance_dataset,
    split_train_val_test,
    validate_labels,
    LABEL_HOLD,
    LABEL_BUY,
    LABEL_SELL,
    LabelingParams,
)


@pytest.fixture
def sample_price_df():
    """Create sample price DataFrame for testing."""
    # Use fixed seed for reproducibility
    rng = np.random.default_rng(seed=42)

    n = 200

    # Create trending price data
    base_price = 50000
    timestamps = [datetime(2024, 1, 1) + timedelta(hours=4 * i) for i in range(n)]

    # Mix of trending and flat periods
    close = np.zeros(n)
    close[0] = base_price

    for i in range(1, n):
        if i < 50:  # Uptrend
            close[i] = close[i - 1] * (1 + rng.uniform(0.01, 0.03))
        elif i < 100:  # Downtrend
            close[i] = close[i - 1] * (1 - rng.uniform(0.01, 0.03))
        else:  # Sideways
            close[i] = close[i - 1] * (1 + rng.uniform(-0.005, 0.005))

    # Generate open from close
    open_price = close * (1 + rng.uniform(-0.005, 0.005, n))

    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": open_price,
            "close": close,
        }
    )


@pytest.fixture
def simple_uptrend_df():
    """Create simple uptrending data for predictable tests."""
    n = 20
    open_prices = [100 + i * 5 for i in range(n)]  # Steady uptrend
    close_prices = [o * 1.05 for o in open_prices]  # 5% gain each bar

    return pd.DataFrame(
        {
            "open": open_prices,
            "close": close_prices,
        }
    )


@pytest.fixture
def simple_downtrend_df():
    """Create simple downtrending data for predictable tests."""
    n = 20
    open_prices = [200 - i * 5 for i in range(n)]  # Steady downtrend
    close_prices = [o * 0.95 for o in open_prices]  # 5% loss each bar

    return pd.DataFrame(
        {
            "open": open_prices,
            "close": close_prices,
        }
    )


class TestComputeLabels:
    """Tests for compute_labels function."""

    def test_output_shape(self, sample_price_df):
        """Test that output has correct shape."""
        labels = compute_labels(sample_price_df)
        assert len(labels) == len(sample_price_df)

    def test_valid_labels(self, sample_price_df):
        """Test that all labels are valid (0, 1, or 2)."""
        labels = compute_labels(sample_price_df)
        assert set(labels.unique()).issubset({LABEL_HOLD, LABEL_BUY, LABEL_SELL})

    def test_last_fwin_are_hold(self, sample_price_df):
        """Test that last fwin samples are Hold (no future data)."""
        fwin = 2
        labels = compute_labels(sample_price_df, fwin=fwin)

        # Last fwin samples should be Hold (default)
        assert (labels.iloc[-fwin:] == LABEL_HOLD).all()

    def test_uptrend_creates_buy_labels(self, simple_uptrend_df):
        """Test that uptrend creates Buy labels."""
        # Use small alpha to capture the 5% moves
        labels = compute_labels(
            simple_uptrend_df, fwin=1, alpha=0.01, beta=0.30, fee=0.001
        )

        # Should have some Buy labels
        buy_count = (labels == LABEL_BUY).sum()
        assert buy_count > 0

    def test_downtrend_creates_sell_labels(self, simple_downtrend_df):
        """Test that downtrend creates Sell labels."""
        labels = compute_labels(
            simple_downtrend_df, fwin=1, alpha=0.01, beta=0.30, fee=0.001
        )

        # Should have some Sell labels
        sell_count = (labels == LABEL_SELL).sum()
        assert sell_count > 0

    def test_alpha_threshold(self, sample_price_df):
        """Test that alpha threshold filters small moves."""
        # High alpha should result in more Hold labels
        labels_low_alpha = compute_labels(sample_price_df, alpha=0.01)
        labels_high_alpha = compute_labels(sample_price_df, alpha=0.10)

        hold_low = (labels_low_alpha == LABEL_HOLD).sum()
        hold_high = (labels_high_alpha == LABEL_HOLD).sum()

        assert hold_high >= hold_low

    def test_beta_threshold(self, sample_price_df):
        """Test that beta threshold filters large moves."""
        # Low beta should result in more Hold labels
        labels_low_beta = compute_labels(sample_price_df, beta=0.05)
        labels_high_beta = compute_labels(sample_price_df, beta=0.50)

        hold_low = (labels_low_beta == LABEL_HOLD).sum()
        hold_high = (labels_high_beta == LABEL_HOLD).sum()

        assert hold_low >= hold_high

    def test_fee_impact(self, simple_uptrend_df):
        """Test that higher fees result in fewer signals."""
        labels_low_fee = compute_labels(simple_uptrend_df, fee=0.0)
        labels_high_fee = compute_labels(simple_uptrend_df, fee=0.05)

        # Higher fees should reduce signals (more Hold)
        signals_low = (labels_low_fee != LABEL_HOLD).sum()
        signals_high = (labels_high_fee != LABEL_HOLD).sum()

        assert signals_high <= signals_low


class TestComputeReturns:
    """Tests for compute_returns function."""

    def test_output_shape(self, sample_price_df):
        """Test that output has correct shape."""
        returns = compute_returns(sample_price_df)
        assert len(returns) == len(sample_price_df)

    def test_last_fwin_are_nan(self, sample_price_df):
        """Test that last fwin samples are NaN."""
        fwin = 2
        returns = compute_returns(sample_price_df, fwin=fwin)
        assert returns.iloc[-fwin:].isna().all()

    def test_uptrend_positive_returns(self, simple_uptrend_df):
        """Test that uptrend produces positive returns."""
        returns = compute_returns(simple_uptrend_df, fwin=1, fee=0.0)
        valid_returns = returns.dropna()

        # Most returns should be positive in uptrend
        assert (valid_returns > 0).mean() > 0.8


class TestLabelDistribution:
    """Tests for get_label_distribution function."""

    def test_output_structure(self, sample_price_df):
        """Test that output has correct structure."""
        labels = compute_labels(sample_price_df)
        distribution = get_label_distribution(labels)

        assert "Hold" in distribution
        assert "Buy" in distribution
        assert "Sell" in distribution

        for stats in distribution.values():
            assert "count" in stats
            assert "percentage" in stats

    def test_percentages_sum_to_100(self, sample_price_df):
        """Test that percentages sum to 100."""
        labels = compute_labels(sample_price_df)
        distribution = get_label_distribution(labels)

        total_pct = sum(d["percentage"] for d in distribution.values())
        assert abs(total_pct - 100) < 0.1


class TestOptimalThresholds:
    """Tests for compute_optimal_thresholds function."""

    def test_alpha_less_than_beta(self, sample_price_df):
        """Test that alpha < beta always."""
        alpha, beta = compute_optimal_thresholds(sample_price_df)
        assert alpha < beta

    def test_positive_thresholds(self, sample_price_df):
        """Test that thresholds are positive."""
        alpha, beta = compute_optimal_thresholds(sample_price_df)
        assert alpha > 0
        assert beta > 0

    def test_percentile_impact(self, sample_price_df):
        """Test that higher percentiles give higher thresholds."""
        alpha1, beta1 = compute_optimal_thresholds(
            sample_price_df, alpha_percentile=80, beta_percentile=95
        )
        alpha2, beta2 = compute_optimal_thresholds(
            sample_price_df, alpha_percentile=90, beta_percentile=99
        )

        assert alpha2 > alpha1
        assert beta2 > beta1


class TestBalanceDataset:
    """Tests for balance_dataset function."""

    def test_balanced_classes(self):
        """Test that all classes have equal counts after balancing."""
        # Create imbalanced data
        X = np.random.randn(1000, 13)
        y = np.array([0] * 700 + [1] * 200 + [2] * 100)  # Imbalanced

        X_bal, y_bal = balance_dataset(X, y)

        _, counts = np.unique(y_bal, return_counts=True)
        assert len(set(counts)) == 1  # All counts equal

    def test_preserves_features(self):
        """Test that feature values are preserved."""
        X = np.random.randn(300, 5)
        y = np.array([0] * 100 + [1] * 100 + [2] * 100)

        X_bal, y_bal = balance_dataset(X, y)

        # All balanced samples should be from original
        for i in range(len(X_bal)):
            assert any(np.allclose(X_bal[i], X[j]) for j in range(len(X)))

    def test_reproducibility(self):
        """Test that same random_state gives same results."""
        X = np.random.randn(300, 5)
        y = np.array([0] * 150 + [1] * 100 + [2] * 50)

        X1, y1 = balance_dataset(X, y, random_state=42)
        X2, y2 = balance_dataset(X, y, random_state=42)

        np.testing.assert_array_equal(X1, X2)
        np.testing.assert_array_equal(y1, y2)


class TestSplitTrainValTest:
    """Tests for split_train_val_test function."""

    def test_correct_split_ratios(self):
        """Test that split ratios are approximately correct."""
        X = np.random.randn(1000, 5)
        y = np.random.randint(0, 3, 1000)

        X_train, X_val, X_test, y_train, y_val, y_test = split_train_val_test(
            X, y, val_ratio=0.15, test_ratio=0.15
        )

        total = len(X)
        assert abs(len(X_test) / total - 0.15) < 0.05
        assert abs(len(X_val) / total - 0.15) < 0.05
        assert abs(len(X_train) / total - 0.70) < 0.05

    def test_no_overlap(self):
        """Test that there's no overlap between splits."""
        X = np.arange(100).reshape(-1, 1)
        y = np.random.randint(0, 3, 100)

        X_train, X_val, X_test, _, _, _ = split_train_val_test(X, y)

        train_set = set(X_train.flatten())
        val_set = set(X_val.flatten())
        test_set = set(X_test.flatten())

        assert len(train_set & val_set) == 0
        assert len(train_set & test_set) == 0
        assert len(val_set & test_set) == 0


class TestValidateLabels:
    """Tests for validate_labels function."""

    def test_buy_labels_have_positive_returns(self, simple_uptrend_df):
        """Test that Buy labels have positive average returns."""
        labels = compute_labels(simple_uptrend_df, alpha=0.01, beta=0.50, fee=0.0)
        stats = validate_labels(labels, simple_uptrend_df)

        if stats["Buy"]["count"] > 0:
            assert stats["Buy"]["mean_return"] > 0

    def test_sell_labels_have_negative_returns(self, simple_downtrend_df):
        """Test that Sell labels have negative average returns."""
        labels = compute_labels(simple_downtrend_df, alpha=0.01, beta=0.50, fee=0.0)
        stats = validate_labels(labels, simple_downtrend_df)

        if stats["Sell"]["count"] > 0:
            assert stats["Sell"]["mean_return"] < 0


class TestLabelingParams:
    """Tests for LabelingParams dataclass."""

    def test_default_values(self):
        """Test default parameter values match paper."""
        params = LabelingParams()

        assert params.backward_window == 5
        assert params.forward_window == 2
        assert params.alpha == 0.038
        assert params.beta == 0.24
        assert params.fee == 0.001

    def test_adjusted_beta(self):
        """Test beta adjustment for different forward windows.

        Formula: beta + (forward_window - 1) * beta_increment
        where beta_increment = 0.024 (default)
        """
        params = LabelingParams(forward_window=1)
        # fwin=1: 0.24 + (1-1) * 0.024 = 0.24
        assert params.get_adjusted_beta() == 0.24

        params = LabelingParams(forward_window=2)
        # fwin=2: 0.24 + (2-1) * 0.024 = 0.264
        assert params.get_adjusted_beta() == 0.264

        params = LabelingParams(forward_window=3)
        # fwin=3: 0.24 + (3-1) * 0.024 = 0.288
        assert params.get_adjusted_beta() == 0.288


class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_empty_dataframe(self):
        """Test handling of empty DataFrame."""
        empty_df = pd.DataFrame({"open": [], "close": []})

        # Should return empty array without error
        labels = compute_labels(empty_df, alpha=0.038, beta=0.24)
        assert len(labels) == 0

    def test_single_row_dataframe(self):
        """Test handling of single-row DataFrame."""
        single_df = pd.DataFrame({"open": [100.0], "close": [105.0]})

        labels = compute_labels(single_df, alpha=0.038, beta=0.24, fwin=1)
        # Can't compute return with single row
        assert len(labels) == 1
        assert labels[0] == LABEL_HOLD

    def test_dataframe_smaller_than_fwin(self):
        """Test handling of DataFrame smaller than forward window."""
        small_df = pd.DataFrame({
            "open": [100.0, 101.0],
            "close": [100.5, 101.5],
        })

        # fwin=3 but only 2 rows
        labels = compute_labels(small_df, alpha=0.038, beta=0.24, fwin=3)
        # All should be HOLD since we can't compute forward returns
        assert len(labels) == 2
        assert all(label == LABEL_HOLD for label in labels)

    def test_nan_handling(self):
        """Test that NaN values are handled gracefully."""
        nan_df = pd.DataFrame({
            "open": [100.0, np.nan, 102.0, 103.0, 104.0],
            "close": [100.5, 101.5, np.nan, 103.5, 104.5],
        })

        # Should not raise error
        labels = compute_labels(nan_df, alpha=0.038, beta=0.24)
        assert len(labels) == 5
