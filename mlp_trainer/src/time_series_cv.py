"""
Time Series Cross-Validation for MLP Training.

Implements expanding window cross-validation that respects temporal ordering.
Prevents data leakage by ensuring validation data always comes after training data.

Key Features:
- Expanding window: Each fold includes more training data
- No shuffling: Maintains temporal order
- Gap support: Optional buffer between train/val to prevent look-ahead bias
"""

import numpy as np
from typing import Iterator, Optional, Tuple, List
from dataclasses import dataclass


@dataclass
class TimeSeriesCVConfig:
    """Configuration for Time Series CV."""

    n_splits: int = 5
    min_train_ratio: float = 0.3  # Minimum training data ratio for first fold
    gap: int = 0  # Number of samples to skip between train and val
    val_ratio: float = 0.1  # Validation ratio per fold


class TimeSeriesCV:
    """
    Expanding Window Time Series Cross-Validation.

    Example with n_splits=5:
        Fold 1: Train [====     ] Val [==]
        Fold 2: Train [======   ] Val [==]
        Fold 3: Train [========  ] Val [==]
        Fold 4: Train [========== ] Val [==]
        Fold 5: Train [============] Val [==]

    Each fold's validation set is the same size, but training set grows.
    """

    def __init__(
        self,
        n_splits: int = 5,
        min_train_ratio: float = 0.3,
        gap: int = 0,
        val_ratio: float = 0.1,
    ):
        """
        Initialize Time Series CV.

        Args:
            n_splits: Number of CV folds
            min_train_ratio: Minimum fraction of data for training in first fold
            gap: Number of samples to skip between train and val (prevents leakage)
            val_ratio: Fraction of data for validation in each fold
        """
        self.n_splits = n_splits
        self.min_train_ratio = min_train_ratio
        self.gap = gap
        self.val_ratio = val_ratio

    def split(
        self,
        X: np.ndarray,
        y: Optional[np.ndarray] = None,
        timestamps: Optional[np.ndarray] = None,
    ) -> Iterator[Tuple[np.ndarray, np.ndarray]]:
        """
        Generate train/val indices for each fold.

        Args:
            X: Features array of shape (n_samples, n_features)
            y: Labels array (optional, not used but kept for sklearn API compatibility)
            timestamps: Timestamp array (optional, for logging)

        Yields:
            Tuple of (train_indices, val_indices) for each fold
        """
        n_samples = len(X)

        # Calculate validation size (fixed for all folds)
        val_size = int(n_samples * self.val_ratio)

        # Calculate minimum training size
        min_train_size = int(n_samples * self.min_train_ratio)

        # Calculate step size between folds
        # Total data available after min_train: n_samples - min_train_size - val_size
        available = n_samples - min_train_size - val_size - self.gap
        if available <= 0 or self.n_splits <= 1:
            step = 0
        else:
            step = available // (self.n_splits - 1)

        for fold in range(self.n_splits):
            # Training ends at this index (exclusive)
            train_end = min_train_size + fold * step

            # Validation starts after gap
            val_start = train_end + self.gap

            # Validation ends
            val_end = min(val_start + val_size, n_samples)

            # Ensure we have enough validation samples
            if val_end - val_start < val_size // 2:
                break

            train_indices = np.arange(0, train_end)
            val_indices = np.arange(val_start, val_end)

            yield train_indices, val_indices

    def get_n_splits(self) -> int:
        """Return number of splits."""
        return self.n_splits


def time_series_cv_split(
    X: np.ndarray,
    y: np.ndarray,
    n_splits: int = 5,
    min_train_ratio: float = 0.3,
    gap: int = 0,
    val_ratio: float = 0.1,
) -> List[Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]]:
    """
    Functional interface for time series CV split.

    Args:
        X: Features array
        y: Labels array
        n_splits: Number of CV folds
        min_train_ratio: Minimum training data ratio
        gap: Gap between train and val
        val_ratio: Validation data ratio per fold

    Returns:
        List of (X_train, X_val, y_train, y_val) tuples for each fold
    """
    cv = TimeSeriesCV(
        n_splits=n_splits,
        min_train_ratio=min_train_ratio,
        gap=gap,
        val_ratio=val_ratio,
    )

    splits = []
    for train_idx, val_idx in cv.split(X, y):
        X_train, X_val = X[train_idx], X[val_idx]
        y_train, y_val = y[train_idx], y[val_idx]
        splits.append((X_train, X_val, y_train, y_val))

    return splits


def print_cv_info(
    X: np.ndarray,
    y: np.ndarray,
    n_splits: int = 5,
    timestamps: Optional[np.ndarray] = None,
) -> None:
    """
    Print information about CV splits.

    Args:
        X: Features array
        y: Labels array
        n_splits: Number of splits
        timestamps: Optional timestamp array for date range info
    """
    cv = TimeSeriesCV(n_splits=n_splits)

    print(f"\nTime Series CV Configuration:")
    print(f"  Total samples: {len(X):,}")
    print(f"  Number of splits: {n_splits}")
    print(f"  Min train ratio: {cv.min_train_ratio}")
    print(f"  Val ratio: {cv.val_ratio}")
    print(f"  Gap: {cv.gap}")
    print()

    for fold, (train_idx, val_idx) in enumerate(cv.split(X, y)):
        print(f"Fold {fold + 1}:")
        print(f"  Train: {len(train_idx):,} samples (indices 0-{train_idx[-1]})")
        print(f"  Val:   {len(val_idx):,} samples (indices {val_idx[0]}-{val_idx[-1]})")

        if timestamps is not None:
            train_start = timestamps[train_idx[0]]
            train_end = timestamps[train_idx[-1]]
            val_start = timestamps[val_idx[0]]
            val_end = timestamps[val_idx[-1]]
            print(f"  Train period: {train_start} to {train_end}")
            print(f"  Val period:   {val_start} to {val_end}")

        # Class distribution
        train_dist = np.bincount(y[train_idx], minlength=3)
        val_dist = np.bincount(y[val_idx], minlength=3)
        print(f"  Train dist: Hold={train_dist[0]}, Buy={train_dist[1]}, Sell={train_dist[2]}")
        print(f"  Val dist:   Hold={val_dist[0]}, Buy={val_dist[1]}, Sell={val_dist[2]}")
        print()


# Quick test
if __name__ == "__main__":
    print("Testing Time Series CV...")

    # Create sample data
    n_samples = 10000
    n_features = 36
    n_classes = 3

    X = np.random.randn(n_samples, n_features).astype(np.float32)
    y = np.random.randint(0, n_classes, n_samples).astype(np.int32)

    # Test CV
    cv = TimeSeriesCV(n_splits=5)

    print(f"\nSample size: {n_samples}")
    print(f"CV splits: {cv.n_splits}")
    print()

    for fold, (train_idx, val_idx) in enumerate(cv.split(X, y)):
        print(f"Fold {fold + 1}:")
        print(f"  Train: {len(train_idx):,} samples (idx: 0-{train_idx[-1]})")
        print(f"  Val:   {len(val_idx):,} samples (idx: {val_idx[0]}-{val_idx[-1]})")

        # Verify no overlap
        assert len(set(train_idx) & set(val_idx)) == 0, "Train/val overlap!"

        # Verify temporal order
        assert train_idx[-1] < val_idx[0], "Train data after val data!"

    print("\n✓ Time Series CV test passed!")
