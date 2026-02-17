"""
MLP Direction Strategy Labeling Algorithm.

Implements the parametric labeling strategy from Parente & Rizzuti (2025).

Key detail from Algorithm 1 / Fig. 3:
- The reference "open" price is computed as EMA(close, BWin),
  not the raw open price from OHLC.

The algorithm assigns Buy/Hold/Sell labels based on future returns:
- Buy: Return in [α, β] and positive
- Sell: Return in [-β, -α] and negative
- Hold: Return outside these ranges (too small or too volatile)

Reference: https://doi.org/10.1007/s00500-025-10980-7
"""

# pylint: disable=no-member

import numpy as np
import pandas as pd
from dataclasses import dataclass


# Label encoding
LABEL_HOLD = 0
LABEL_BUY = 1
LABEL_SELL = 2

LABEL_NAMES = {
    LABEL_HOLD: "Hold",
    LABEL_BUY: "Buy",
    LABEL_SELL: "Sell",
}


@dataclass
class LabelingParams:
    """Parameters for the labeling algorithm."""

    backward_window: int = 5  # BWin in paper
    forward_window: int = 2  # FWin in paper
    alpha: float = 0.038  # Minimum return threshold (3.8%)
    beta: float = 0.24  # Maximum return threshold (24%)
    fee: float = 0.001  # Trading fee (0.1%)
    beta_increment: float = 0.024  # Beta increases 2.4% per FWin step

    def get_adjusted_beta(self) -> float:
        """Get beta adjusted for forward window size."""
        return self.beta + (self.forward_window - 1) * self.beta_increment


def compute_labels(
    df: pd.DataFrame,
    bwin: int = 5,
    fwin: int = 2,
    alpha: float = 0.038,
    beta: float = 0.24,
    fee: float = 0.001,
) -> pd.Series:
    """
    Compute Buy/Hold/Sell labels using the paper's Algorithm 1.

    The labeling algorithm determines the class based on the return
    from opening a position at time t and closing at time t + fwin.

    Args:
    df: DataFrame with 'close' column (EMA reference is derived from close)
        bwin: Backward window size (EMA length)
        fwin: Forward window size (lookahead periods)
        alpha: Minimum return threshold to trigger Buy/Sell (default 3.8%)
        beta: Maximum return threshold (default 24%)
        fee: Trading fee per operation (default 0.1%)

    Returns:
        Series with labels: 0=Hold, 1=Buy, 2=Sell
    """
    close_prices = df["close"].values.astype(np.float64)
    n = len(df)

    labels = np.zeros(n, dtype=np.int32)  # Default: Hold (0)

    # EMA-based reference price (paper: EMA over Backward Window)
    try:
        import talib
        ema_ref = talib.EMA(close_prices, timeperiod=bwin)
    except Exception:  # pylint: disable=broad-exception-caught
        ema_ref = pd.Series(close_prices).ewm(span=bwin, adjust=False).mean().values

    # Adjust beta based on forward window
    # Paper: β increases by 10% (of original β) for each additional FWin step
    adjusted_beta = beta + (fwin - 1) * 0.024

    for t in range(n - fwin):
        # EMA reference price at time t
        current_open = ema_ref[t]
        if np.isnan(current_open) or current_open <= 0:
            continue

        # Future close price (at end of forward window)
        future_close = close_prices[t + fwin]

        # Calculate return including fees
        # R = ((1 - fee) * Close[t+fwin] - (1 + fee) * Open[t]) / Open[t]
        ret = ((1 - fee) * future_close - (1 + fee) * current_open) / current_open

        abs_ret = abs(ret)

        # Apply labeling rules (Figure 2 in paper)
        if alpha < abs_ret < adjusted_beta:
            if ret > 0:
                labels[t] = LABEL_BUY
            else:
                labels[t] = LABEL_SELL
        # else: labels[t] remains LABEL_HOLD

    return pd.Series(labels, index=df.index, name="label")


def compute_returns(
    df: pd.DataFrame,
    fwin: int = 2,
    fee: float = 0.001,
    bwin: int = 5,
) -> pd.Series:
    """
    Compute forward returns for each time point.

    Useful for analysis and threshold tuning.

    Args:
    df: DataFrame with 'close' column
        fwin: Forward window size
        fee: Trading fee per operation

    Returns:
        Series of returns (accounting for fees)
    """
    close_prices = df["close"].values.astype(np.float64)
    n = len(df)

    returns = np.full(n, np.nan)

    try:
        import talib
        ema_ref = talib.EMA(close_prices, timeperiod=bwin)
    except Exception:  # pylint: disable=broad-exception-caught
        ema_ref = pd.Series(close_prices).ewm(span=bwin, adjust=False).mean().values

    for t in range(n - fwin):
        current_open = ema_ref[t]
        if np.isnan(current_open) or current_open <= 0:
            continue
        future_close = close_prices[t + fwin]
        ret = ((1 - fee) * future_close - (1 + fee) * current_open) / current_open
        returns[t] = ret

    return pd.Series(returns, index=df.index, name="forward_return")


def get_label_distribution(labels: pd.Series) -> dict:
    """
    Get the distribution of labels.

    Args:
        labels: Series of labels (0, 1, 2)

    Returns:
        Dict with counts and percentages for each class
    """
    total = len(labels)
    counts = labels.value_counts().to_dict()

    distribution = {}
    for label_id, label_name in LABEL_NAMES.items():
        count = counts.get(label_id, 0)
        pct = count / total * 100 if total > 0 else 0
        distribution[label_name] = {"count": count, "percentage": pct}

    return distribution


def compute_optimal_thresholds(
    df: pd.DataFrame,
    fwin: int = 2,
    fee: float = 0.001,
    bwin: int = 5,
    alpha_percentile: float = 85.0,
    beta_percentile: float = 99.7,
) -> tuple[float, float]:
    """
    Compute optimal alpha and beta thresholds from data distribution.

    The paper uses the 85th and 99.7th percentiles of absolute returns.

    Args:
        df: DataFrame with 'open' and 'close' columns
        fwin: Forward window size
        fee: Trading fee
        alpha_percentile: Percentile for alpha (default 85th)
        beta_percentile: Percentile for beta (default 99.7th)

    Returns:
        Tuple of (alpha, beta)
    """
    returns = compute_returns(df, fwin, fee, bwin=bwin)
    abs_returns = returns.abs().dropna()

    alpha = np.percentile(abs_returns, alpha_percentile)
    beta = np.percentile(abs_returns, beta_percentile)

    return alpha, beta


def balance_dataset(
    X: np.ndarray,
    y: np.ndarray,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Balance dataset using random undersampling of majority class.

    The paper notes that Hold class is often ~70% of data, causing
    imbalanced classification. This function downsamples to match
    the minority class size.

    Args:
        X: Feature array (n_samples, n_features)
        y: Label array (n_samples,)
        random_state: Random seed for reproducibility

    Returns:
        Tuple of (balanced_X, balanced_y)
    """
    np.random.seed(random_state)

    # Find class sizes
    unique_classes, counts = np.unique(y, return_counts=True)
    min_count = min(counts)

    balanced_indices = []

    for cls in unique_classes:
        cls_indices = np.where(y == cls)[0]

        if len(cls_indices) > min_count:
            # Random undersample
            selected = np.random.choice(cls_indices, size=min_count, replace=False)
        else:
            selected = cls_indices

        balanced_indices.extend(selected)

    # Shuffle
    balanced_indices = np.array(balanced_indices)
    np.random.shuffle(balanced_indices)

    return X[balanced_indices], y[balanced_indices]


def split_train_val_test(
    X: np.ndarray,
    y: np.ndarray,
    val_ratio: float = 0.15,
    test_ratio: float = 0.15,
    random_state: int = 42,
    stratify: bool = True,
    temporal: bool = False,
    gap: int = 0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """
    Split data into train/validation/test sets.

    Args:
        X: Feature array (must be sorted by time if temporal=True)
        y: Label array
        val_ratio: Validation set ratio
        test_ratio: Test set ratio
        random_state: Random seed (only used when temporal=False)
        stratify: Whether to use stratified sampling (only when temporal=False)
        temporal: If True, split by temporal order (no shuffle). Data must be
            pre-sorted by timestamp. Prevents data leakage for time series.
        gap: Number of samples to skip between splits when temporal=True.
            Should be >= fwin to prevent label leakage.

    Returns:
        Tuple of (X_train, X_val, X_test, y_train, y_val, y_test)
    """
    if temporal:
        return _temporal_split(X, y, val_ratio, test_ratio, gap)

    from sklearn.model_selection import train_test_split

    # First split: separate test set
    X_temp, X_test, y_temp, y_test = train_test_split(
        X,
        y,
        test_size=test_ratio,
        random_state=random_state,
        stratify=y if stratify else None,
    )

    if val_ratio <= 0:
        # No validation set requested
        X_train, y_train = X_temp, y_temp
        X_val = X_train[:0]
        y_val = y_train[:0]
    else:
        # Second split: separate validation from train
        val_adjusted = val_ratio / (1 - test_ratio)
        X_train, X_val, y_train, y_val = train_test_split(
            X_temp,
            y_temp,
            test_size=val_adjusted,
            random_state=random_state,
            stratify=y_temp if stratify else None,
        )

    return X_train, X_val, X_test, y_train, y_val, y_test


def _temporal_split(
    X: np.ndarray,
    y: np.ndarray,
    val_ratio: float,
    test_ratio: float,
    gap: int,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Split data by temporal order without shuffling.

    Layout: [train] [gap] [val] [gap] [test]
    """
    n = len(X)
    n_test = int(n * test_ratio)
    n_val = int(n * val_ratio)

    # Work backwards from end
    test_start = n - n_test
    val_end = test_start - gap
    val_start = val_end - n_val
    train_end = val_start - gap

    # Clamp to valid indices
    train_end = max(1, train_end)
    val_start = max(train_end + gap, val_start)
    val_end = max(val_start, val_end)
    test_start = max(val_end + gap, test_start)

    X_train, y_train = X[:train_end], y[:train_end]
    X_val, y_val = X[val_start:val_end], y[val_start:val_end]
    X_test, y_test = X[test_start:], y[test_start:]

    return X_train, X_val, X_test, y_train, y_val, y_test


def validate_labels(labels: pd.Series, df: pd.DataFrame) -> dict:
    """
    Validate label quality by checking actual returns for each class.

    Args:
        labels: Computed labels
        df: Original DataFrame

    Returns:
        Dict with validation statistics
    """
    returns = compute_returns(df, fwin=2, bwin=5)

    stats = {}
    for label_id, label_name in LABEL_NAMES.items():
        mask = labels == label_id
        class_returns = returns[mask].dropna()

        if len(class_returns) > 0:
            stats[label_name] = {
                "count": len(class_returns),
                "mean_return": class_returns.mean(),
                "median_return": class_returns.median(),
                "std_return": class_returns.std(),
                "positive_pct": (class_returns > 0).mean() * 100,
            }
        else:
            stats[label_name] = {"count": 0}

    return stats
