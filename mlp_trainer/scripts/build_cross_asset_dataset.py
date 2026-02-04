#!/usr/bin/env python3
"""
Build Cross-Asset Feature Dataset for MLP Training.

This script builds the 44-feature dataset that includes:
- 36 paper features (candlestick patterns, indicators, temporal)
- 8 cross-asset features (BTC correlation, market momentum, etc.)

Uses multi-asset 4H data to train on diverse market conditions.
"""

import argparse
import numpy as np
import pandas as pd
from pathlib import Path
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from trading.indicators.mlp_features import (
    calculate_mlp_features,
    FEATURE_SET_CROSS,
    NUM_FEATURES_CROSS,
    FEATURE_NAMES_CROSS,
)


def load_multi_asset_data(data_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Load multi-asset training and validation data."""
    train_path = data_dir / "train_4h.parquet"
    val_path = data_dir / "validation_4h.parquet"

    if not train_path.exists():
        raise FileNotFoundError(f"Training data not found: {train_path}")
    if not val_path.exists():
        raise FileNotFoundError(f"Validation data not found: {val_path}")

    train_df = pd.read_parquet(train_path)
    val_df = pd.read_parquet(val_path)

    # Load BTC data from validation directory (separate file)
    btc_path = data_dir / "validation" / "BTCUSDT.parquet"
    if btc_path.exists():
        btc_full_df = pd.read_parquet(btc_path)
        btc_full_df["symbol"] = "BTCUSDT"
        print(f"Loaded BTC reference: {len(btc_full_df):,} rows")
    else:
        # Try to extract from val_df
        btc_full_df = val_df[val_df["symbol"] == "BTCUSDT"].copy()
        if len(btc_full_df) == 0:
            raise FileNotFoundError(f"BTC data not found")

    print(f"Loaded train: {len(train_df):,} rows, {train_df['symbol'].nunique()} symbols")
    print(f"Loaded val: {len(val_df):,} rows, {val_df['symbol'].nunique()} symbols")

    return train_df, val_df, btc_full_df


def prepare_btc_reference(btc_full_df: pd.DataFrame) -> pd.DataFrame:
    """Prepare BTC data for cross-asset feature calculation."""
    btc_df = btc_full_df.copy()
    if "timestamp" in btc_df.columns:
        btc_df["timestamp"] = pd.to_datetime(btc_df["timestamp"])
        btc_df = btc_df.set_index("timestamp").sort_index()
    return btc_df


def calculate_market_aggregates(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate market-wide aggregates for cross-asset features."""
    # Ensure timestamp is datetime
    df = df.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Group by timestamp to get market-wide metrics
    grouped = df.groupby("timestamp").agg({
        "close": ["mean", "std"],
        "volume": "mean",
    })
    grouped.columns = ["avg_close", "close_std", "avg_volume"]
    grouped = grouped.sort_index()

    # Calculate market return and volatility
    market_df = pd.DataFrame(index=grouped.index)
    market_df["avg_return"] = grouped["avg_close"].pct_change().fillna(0)
    market_df["avg_volatility"] = market_df["avg_return"].rolling(window=20, min_periods=1).std().fillna(0)
    market_df["avg_volume"] = grouped["avg_volume"]

    return market_df


def build_features_for_symbol(
    symbol_df: pd.DataFrame,
    btc_df: pd.DataFrame,
    market_df: pd.DataFrame,
    symbol: str,
    bwin: int = 5,
    fwin: int = 2,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build features and labels for a single symbol.

    Args:
        symbol_df: OHLCV data for the symbol
        btc_df: BTC OHLCV data (indexed by timestamp)
        market_df: Market aggregates (indexed by timestamp)
        symbol: Symbol name
        bwin: Backward window (not used for paper features)
        fwin: Forward window for label calculation

    Returns:
        Tuple of (features, labels, timestamps)
    """
    # Ensure sorted by timestamp
    symbol_df = symbol_df.sort_values("timestamp").reset_index(drop=True)

    # Align BTC data with symbol data
    symbol_timestamps = pd.to_datetime(symbol_df["timestamp"])
    btc_aligned = btc_df.reindex(symbol_timestamps)
    market_aligned = market_df.reindex(symbol_timestamps)

    # Calculate cross-asset features
    is_btc = symbol in ["BTCUSDT", "BTC", "BTCUSD"]

    features_df = calculate_mlp_features(
        symbol_df,
        feature_set=FEATURE_SET_CROSS,
        btc_df=None if is_btc else btc_aligned.reset_index(drop=True),
        market_df=market_aligned.reset_index(drop=True),
    )

    # Calculate labels (future return direction)
    close = symbol_df["close"].values
    future_returns = np.zeros(len(close))
    for i in range(len(close) - fwin):
        future_returns[i] = (close[i + fwin] - close[i]) / close[i]

    # Convert to 3-class labels: 0=Hold, 1=Buy, 2=Sell
    # Thresholds from paper: ±0.5% for 4H data
    threshold = 0.005
    labels = np.zeros(len(future_returns), dtype=np.int32)
    labels[future_returns > threshold] = 1  # Buy
    labels[future_returns < -threshold] = 2  # Sell

    # Trim the last fwin samples (no valid labels)
    valid_mask = np.arange(len(close)) < len(close) - fwin

    # Also need warmup period for indicators (100 bars)
    warmup = 100
    valid_mask[:warmup] = False

    features = features_df.values[valid_mask].astype(np.float32)
    labels = labels[valid_mask]
    timestamps = symbol_df["timestamp"].values[valid_mask]

    return features, labels, timestamps


def build_dataset(
    df: pd.DataFrame,
    btc_df: pd.DataFrame,
    market_df: pd.DataFrame,
    bwin: int = 5,
    fwin: int = 2,
    max_symbols: int | None = None,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Build complete dataset from multi-asset data.

    Args:
        df: Multi-asset OHLCV DataFrame
        btc_df: BTC data
        market_df: Market aggregates
        bwin: Backward window
        fwin: Forward window
        max_symbols: Maximum number of symbols to process (for testing)

    Returns:
        Tuple of (X, y, timestamps)
    """
    symbols = df["symbol"].unique()
    if max_symbols:
        symbols = symbols[:max_symbols]

    all_features = []
    all_labels = []
    all_timestamps = []

    print(f"\nProcessing {len(symbols)} symbols...")

    for i, symbol in enumerate(symbols):
        symbol_df = df[df["symbol"] == symbol].copy()

        if len(symbol_df) < 200:  # Skip symbols with insufficient data
            continue

        try:
            features, labels, timestamps = build_features_for_symbol(
                symbol_df, btc_df, market_df, symbol, bwin, fwin
            )

            if len(features) > 0:
                all_features.append(features)
                all_labels.append(labels)
                all_timestamps.append(timestamps)

                if (i + 1) % 20 == 0:
                    print(f"  Processed {i + 1}/{len(symbols)}: {symbol} ({len(features):,} samples)")

        except Exception as e:
            print(f"  Warning: Failed to process {symbol}: {e}")
            continue

    X = np.vstack(all_features)
    y = np.concatenate(all_labels)
    timestamps = np.concatenate(all_timestamps)

    print(f"\nTotal samples: {len(X):,}")
    print(f"Feature shape: {X.shape}")
    print(f"Label distribution: Hold={np.sum(y==0):,}, Buy={np.sum(y==1):,}, Sell={np.sum(y==2):,}")

    return X, y, timestamps


def balance_classes(
    X: np.ndarray,
    y: np.ndarray,
    timestamps: np.ndarray,
    random_state: int = 42,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Balance classes by undersampling majority class."""
    np.random.seed(random_state)

    # Find minimum class count
    class_counts = [np.sum(y == c) for c in range(3)]
    min_count = min(class_counts)

    print(f"\nBalancing classes to {min_count:,} samples each...")

    indices = []
    for c in range(3):
        class_indices = np.where(y == c)[0]
        selected = np.random.choice(class_indices, size=min_count, replace=False)
        indices.extend(selected)

    indices = np.array(sorted(indices))

    return X[indices], y[indices], timestamps[indices]


def main():
    parser = argparse.ArgumentParser(description="Build cross-asset feature dataset")
    parser.add_argument("--data-dir", type=str, default="data/multi_asset_4h",
                        help="Directory containing multi-asset parquet files")
    parser.add_argument("--output-dir", type=str, default="data/mlp_datasets",
                        help="Output directory for dataset")
    parser.add_argument("--bwin", type=int, default=5, help="Backward window")
    parser.add_argument("--fwin", type=int, default=2, help="Forward window")
    parser.add_argument("--max-symbols", type=int, default=None,
                        help="Max symbols to process (for testing)")
    parser.add_argument("--no-balance", action="store_true",
                        help="Don't balance classes")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    print("Loading multi-asset data...")
    train_df, val_df, btc_full_df = load_multi_asset_data(data_dir)

    # Prepare BTC reference data
    print("\nPreparing BTC reference data...")
    btc_df = prepare_btc_reference(btc_full_df)
    print(f"BTC data: {len(btc_df):,} rows")

    # Calculate market aggregates
    print("\nCalculating market aggregates...")
    market_df = calculate_market_aggregates(train_df)

    # Build training dataset
    print("\n" + "=" * 50)
    print("Building training dataset...")
    print("=" * 50)
    X_train, y_train, ts_train = build_dataset(
        train_df, btc_df, market_df,
        bwin=args.bwin, fwin=args.fwin,
        max_symbols=args.max_symbols,
    )

    # Build validation dataset (BTC/ETH only)
    print("\n" + "=" * 50)
    print("Building validation dataset (BTC/ETH)...")
    print("=" * 50)

    # For validation, use the same BTC reference (already from validation data)
    val_btc_df = btc_df  # Same BTC reference
    val_market_df = calculate_market_aggregates(val_df)

    X_val, y_val, ts_val = build_dataset(
        val_df, val_btc_df, val_market_df,
        bwin=args.bwin, fwin=args.fwin,
    )

    # Split training into train/test (90/10) BEFORE balancing
    n_total = len(X_train)
    n_test = int(n_total * 0.1)
    n_train_split = n_total - n_test

    # Time-based split (test is most recent data)
    sorted_indices = np.argsort(ts_train)
    train_indices = sorted_indices[:n_train_split]
    test_indices = sorted_indices[n_train_split:]

    X_train_split = X_train[train_indices]
    y_train_split = y_train[train_indices]
    ts_train_split = ts_train[train_indices]
    X_test = X_train[test_indices]
    y_test = y_train[test_indices]

    # Balance training set AFTER split
    if not args.no_balance:
        X_train_final, y_train_final, _ = balance_classes(X_train_split, y_train_split, ts_train_split)
    else:
        X_train_final = X_train_split
        y_train_final = y_train_split

    # Print final statistics
    print("\n" + "=" * 50)
    print("Final Dataset Statistics")
    print("=" * 50)
    print(f"Features: {NUM_FEATURES_CROSS} ({FEATURE_SET_CROSS})")
    print(f"Training: {len(X_train_final):,} samples")
    print(f"Test: {len(X_test):,} samples")
    print(f"Validation (BTC/ETH): {len(X_val):,} samples")
    print(f"\nTrain label dist: Hold={np.sum(y_train_final==0):,}, Buy={np.sum(y_train_final==1):,}, Sell={np.sum(y_train_final==2):,}")
    print(f"Test label dist: Hold={np.sum(y_test==0):,}, Buy={np.sum(y_test==1):,}, Sell={np.sum(y_test==2):,}")
    print(f"Val label dist: Hold={np.sum(y_val==0):,}, Buy={np.sum(y_val==1):,}, Sell={np.sum(y_val==2):,}")

    # Save dataset
    output_path = output_dir / f"mlp_dataset_cross44_bwin{args.bwin}_fwin{args.fwin}.npz"
    np.savez(
        output_path,
        X_train=X_train_final,
        y_train=y_train_final,
        X_test=X_test,
        y_test=y_test,
        X_val=X_val,
        y_val=y_val,
        feature_names=FEATURE_NAMES_CROSS,
    )
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
