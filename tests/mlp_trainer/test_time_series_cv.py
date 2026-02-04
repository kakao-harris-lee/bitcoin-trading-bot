"""Unit tests for Time Series Cross-Validation."""

import pytest
import numpy as np

from mlp_trainer.src.time_series_cv import (
    TimeSeriesCV,
    TimeSeriesCVConfig,
    time_series_cv_split,
    print_cv_info,
)


@pytest.fixture
def sample_data():
    """Create sample data for testing."""
    n_samples = 1000
    n_features = 36
    n_classes = 3

    X = np.random.randn(n_samples, n_features).astype(np.float32)
    y = np.random.randint(0, n_classes, n_samples).astype(np.int32)
    return X, y


@pytest.fixture
def small_data():
    """Create small sample data for edge case testing."""
    n_samples = 100
    n_features = 10

    X = np.random.randn(n_samples, n_features).astype(np.float32)
    y = np.random.randint(0, 3, n_samples).astype(np.int32)
    return X, y


class TestTimeSeriesCVConfig:
    """Tests for TimeSeriesCVConfig dataclass."""

    def test_default_config(self):
        """Test default configuration values."""
        config = TimeSeriesCVConfig()

        assert config.n_splits == 5
        assert config.min_train_ratio == 0.3
        assert config.gap == 0
        assert config.val_ratio == 0.1

    def test_custom_config(self):
        """Test custom configuration."""
        config = TimeSeriesCVConfig(
            n_splits=3,
            min_train_ratio=0.4,
            gap=10,
            val_ratio=0.15,
        )

        assert config.n_splits == 3
        assert config.min_train_ratio == 0.4
        assert config.gap == 10
        assert config.val_ratio == 0.15


class TestTimeSeriesCV:
    """Tests for TimeSeriesCV class."""

    def test_default_initialization(self):
        """Test TimeSeriesCV initializes with default parameters."""
        cv = TimeSeriesCV()

        assert cv.n_splits == 5
        assert cv.min_train_ratio == 0.3
        assert cv.gap == 0
        assert cv.val_ratio == 0.1

    def test_custom_initialization(self):
        """Test TimeSeriesCV with custom parameters."""
        cv = TimeSeriesCV(n_splits=3, min_train_ratio=0.4, gap=5, val_ratio=0.15)

        assert cv.n_splits == 3
        assert cv.min_train_ratio == 0.4
        assert cv.gap == 5
        assert cv.val_ratio == 0.15

    def test_get_n_splits(self):
        """Test get_n_splits returns correct value."""
        cv = TimeSeriesCV(n_splits=7)
        assert cv.get_n_splits() == 7

    def test_split_yields_correct_number_of_folds(self, sample_data):
        """Test split yields the expected number of folds."""
        X, y = sample_data
        cv = TimeSeriesCV(n_splits=5)

        folds = list(cv.split(X, y))
        assert len(folds) == 5

    def test_no_train_val_overlap(self, sample_data):
        """Test that train and validation sets never overlap."""
        X, y = sample_data
        cv = TimeSeriesCV(n_splits=5)

        for train_idx, val_idx in cv.split(X, y):
            train_set = set(train_idx)
            val_set = set(val_idx)
            overlap = train_set & val_set

            assert len(overlap) == 0, "Train and validation sets should not overlap"

    def test_temporal_order_maintained(self, sample_data):
        """Test that training data always comes before validation data."""
        X, y = sample_data
        cv = TimeSeriesCV(n_splits=5)

        for train_idx, val_idx in cv.split(X, y):
            # Last training index should be less than first validation index
            assert train_idx[-1] < val_idx[0], "Training data should precede validation data"

    def test_expanding_window(self, sample_data):
        """Test that training set grows with each fold."""
        X, y = sample_data
        cv = TimeSeriesCV(n_splits=5)

        train_sizes = []
        for train_idx, val_idx in cv.split(X, y):
            train_sizes.append(len(train_idx))

        # Each fold should have more or equal training data
        for i in range(1, len(train_sizes)):
            assert train_sizes[i] >= train_sizes[i - 1], "Training set should grow or stay same"

    def test_validation_size_consistent(self, sample_data):
        """Test that validation size is approximately consistent across folds."""
        X, y = sample_data
        cv = TimeSeriesCV(n_splits=5, val_ratio=0.1)

        val_sizes = []
        for train_idx, val_idx in cv.split(X, y):
            val_sizes.append(len(val_idx))

        # All validation sets should be similar size (within 10% tolerance)
        avg_size = np.mean(val_sizes)
        for size in val_sizes:
            assert abs(size - avg_size) <= avg_size * 0.1 + 1

    def test_gap_parameter(self, sample_data):
        """Test that gap is maintained between train and val."""
        X, y = sample_data
        gap = 10
        cv = TimeSeriesCV(n_splits=5, gap=gap)

        for train_idx, val_idx in cv.split(X, y):
            # Gap should be at least 'gap' samples
            actual_gap = val_idx[0] - train_idx[-1] - 1
            assert actual_gap >= gap - 1, f"Gap should be at least {gap} samples"

    def test_min_train_ratio(self, sample_data):
        """Test that first fold has at least min_train_ratio data."""
        X, y = sample_data
        min_train_ratio = 0.3
        cv = TimeSeriesCV(n_splits=5, min_train_ratio=min_train_ratio)

        folds = list(cv.split(X, y))
        first_train_idx, _ = folds[0]

        min_expected = int(len(X) * min_train_ratio)
        assert len(first_train_idx) >= min_expected * 0.9  # Allow 10% tolerance

    def test_indices_are_contiguous(self, sample_data):
        """Test that indices are contiguous (no gaps within train or val)."""
        X, y = sample_data
        cv = TimeSeriesCV(n_splits=5)

        for train_idx, val_idx in cv.split(X, y):
            # Train indices should be 0, 1, 2, ..., n
            expected_train = np.arange(len(train_idx))
            assert np.array_equal(train_idx, expected_train)

            # Val indices should be contiguous
            expected_val = np.arange(val_idx[0], val_idx[-1] + 1)
            assert np.array_equal(val_idx, expected_val)

    def test_all_indices_valid(self, sample_data):
        """Test that all indices are within valid range."""
        X, y = sample_data
        cv = TimeSeriesCV(n_splits=5)

        for train_idx, val_idx in cv.split(X, y):
            assert train_idx.min() >= 0
            assert train_idx.max() < len(X)
            assert val_idx.min() >= 0
            assert val_idx.max() < len(X)


class TestTimeSeriesCVEdgeCases:
    """Tests for edge cases."""

    def test_single_split(self, small_data):
        """Test with n_splits=1."""
        X, y = small_data
        cv = TimeSeriesCV(n_splits=1)

        folds = list(cv.split(X, y))
        assert len(folds) == 1

    def test_small_dataset(self):
        """Test with very small dataset."""
        X = np.random.randn(50, 10).astype(np.float32)
        y = np.random.randint(0, 3, 50).astype(np.int32)

        cv = TimeSeriesCV(n_splits=3, min_train_ratio=0.3, val_ratio=0.1)
        folds = list(cv.split(X, y))

        # Should still produce some folds
        assert len(folds) > 0

        # Verify no overlap
        for train_idx, val_idx in folds:
            assert len(set(train_idx) & set(val_idx)) == 0

    def test_large_val_ratio(self):
        """Test with large validation ratio."""
        X = np.random.randn(100, 10).astype(np.float32)
        y = np.random.randint(0, 3, 100).astype(np.int32)

        cv = TimeSeriesCV(n_splits=2, val_ratio=0.3)
        folds = list(cv.split(X, y))

        # Should produce folds even with large val ratio
        assert len(folds) > 0

    def test_zero_gap(self, sample_data):
        """Test with gap=0."""
        X, y = sample_data
        cv = TimeSeriesCV(n_splits=5, gap=0)

        for train_idx, val_idx in cv.split(X, y):
            # Val should start right after train
            assert val_idx[0] == train_idx[-1] + 1


class TestTimeSeriesCVSplitFunction:
    """Tests for time_series_cv_split functional interface."""

    def test_basic_usage(self, sample_data):
        """Test basic functional interface."""
        X, y = sample_data
        splits = time_series_cv_split(X, y, n_splits=3)

        assert len(splits) == 3

        for X_train, X_val, y_train, y_val in splits:
            assert X_train.shape[1] == X.shape[1]
            assert X_val.shape[1] == X.shape[1]
            assert len(X_train) == len(y_train)
            assert len(X_val) == len(y_val)

    def test_returns_correct_data(self, sample_data):
        """Test that returned data matches original."""
        X, y = sample_data
        splits = time_series_cv_split(X, y, n_splits=3)

        for X_train, X_val, y_train, y_val in splits:
            # Verify data integrity
            assert X_train.dtype == X.dtype
            assert y_train.dtype == y.dtype

    def test_matches_class_interface(self, sample_data):
        """Test functional interface matches class interface."""
        X, y = sample_data

        # Class interface
        cv = TimeSeriesCV(n_splits=3, min_train_ratio=0.3, gap=5, val_ratio=0.1)
        class_splits = []
        for train_idx, val_idx in cv.split(X, y):
            class_splits.append((X[train_idx], X[val_idx], y[train_idx], y[val_idx]))

        # Functional interface
        func_splits = time_series_cv_split(X, y, n_splits=3, min_train_ratio=0.3, gap=5, val_ratio=0.1)

        assert len(class_splits) == len(func_splits)
        for (c_X_tr, c_X_v, c_y_tr, c_y_v), (f_X_tr, f_X_v, f_y_tr, f_y_v) in zip(class_splits, func_splits):
            assert np.array_equal(c_X_tr, f_X_tr)
            assert np.array_equal(c_X_v, f_X_v)
            assert np.array_equal(c_y_tr, f_y_tr)
            assert np.array_equal(c_y_v, f_y_v)


class TestPrintCVInfo:
    """Tests for print_cv_info function."""

    def test_runs_without_error(self, sample_data, capsys):
        """Test that print_cv_info runs without errors."""
        X, y = sample_data

        # Should not raise
        print_cv_info(X, y, n_splits=3)

        # Should produce output
        captured = capsys.readouterr()
        assert len(captured.out) > 0

    def test_output_contains_expected_info(self, sample_data, capsys):
        """Test that output contains expected information."""
        X, y = sample_data
        print_cv_info(X, y, n_splits=3)

        captured = capsys.readouterr()

        assert "Time Series CV Configuration" in captured.out
        assert "Total samples" in captured.out
        assert "Number of splits" in captured.out
        assert "Fold" in captured.out

    def test_with_timestamps(self, capsys):
        """Test print_cv_info with timestamps."""
        X = np.random.randn(100, 10).astype(np.float32)
        y = np.random.randint(0, 3, 100).astype(np.int32)
        timestamps = np.arange(100)

        print_cv_info(X, y, n_splits=3, timestamps=timestamps)

        captured = capsys.readouterr()
        # Should include timestamp range info
        assert "Train" in captured.out
        assert "Val" in captured.out


class TestTimeSeriesCVWithTimestamps:
    """Tests for CV with timestamp support."""

    def test_split_accepts_timestamps(self):
        """Test that split accepts timestamps parameter."""
        X = np.random.randn(100, 10).astype(np.float32)
        y = np.random.randint(0, 3, 100).astype(np.int32)
        timestamps = np.arange(100)

        cv = TimeSeriesCV(n_splits=3)

        # Should not raise
        folds = list(cv.split(X, y, timestamps=timestamps))
        assert len(folds) == 3


class TestTimeSeriesCVReproducibility:
    """Tests for reproducibility."""

    def test_deterministic_splits(self, sample_data):
        """Test that splits are deterministic."""
        X, y = sample_data

        cv1 = TimeSeriesCV(n_splits=5)
        cv2 = TimeSeriesCV(n_splits=5)

        splits1 = list(cv1.split(X, y))
        splits2 = list(cv2.split(X, y))

        for (train1, val1), (train2, val2) in zip(splits1, splits2):
            assert np.array_equal(train1, train2)
            assert np.array_equal(val1, val2)

    def test_consistent_with_different_y(self, sample_data):
        """Test that different y values don't affect indices."""
        X, y = sample_data
        y_different = np.random.randint(0, 10, len(y)).astype(np.int32)

        cv = TimeSeriesCV(n_splits=5)

        splits1 = list(cv.split(X, y))
        splits2 = list(cv.split(X, y_different))

        for (train1, val1), (train2, val2) in zip(splits1, splits2):
            assert np.array_equal(train1, train2)
            assert np.array_equal(val1, val2)
