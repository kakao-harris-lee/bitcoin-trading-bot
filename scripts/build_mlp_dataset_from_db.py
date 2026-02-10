#!/usr/bin/env python3
"""
Build MLP dataset from SQLite database.

Quick script to convert existing DB data to MLP training format.
"""

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
import sqlite3

from trading.indicators.mlp_features import (
    calculate_mlp_features,
    FEATURE_NAMES_PAPER,
    FEATURE_NAMES_SHAP,
    FEATURE_SET_PAPER,
    FEATURE_SET_SHAP,
)
from core.mlp_labeling import (
    compute_labels,
    balance_dataset,
    split_train_val_test,
    get_label_distribution,
)


def load_4h_data(db_path: str, start_date: str = "2019-01-01") -> pd.DataFrame:
    """Load 4H candle data from SQLite database."""
    conn = sqlite3.connect(db_path)

    query = f"""
        SELECT timestamp, open, high, low, close, volume
        FROM binance_minute240
        WHERE timestamp >= '{start_date}'
        ORDER BY timestamp
    """

    df = pd.read_sql(query, conn)
    conn.close()

    df['timestamp'] = pd.to_datetime(df['timestamp'])
    return df


def build_dataset(
    df: pd.DataFrame,
    bwin: int = 5,
    fwin: int = 2,
    alpha: float = 0.038,
    beta: float = 0.24,
    fee: float = 0.001,
    feature_set: str = FEATURE_SET_PAPER,
) -> tuple[np.ndarray, np.ndarray]:
    """Build features and labels from DataFrame."""

    print(f"Calculating features (bwin={bwin})...")
    features = calculate_mlp_features(
        df,
        bwin=bwin,
        include_temporal=True,
        feature_set=feature_set,
    )

    print(f"Computing labels (fwin={fwin}, alpha={alpha}, beta={beta})...")
    labels = compute_labels(df, bwin=bwin, fwin=fwin, alpha=alpha, beta=beta, fee=fee)

    # Remove warmup period and NaN
    warmup = max(100, bwin * 20)
    valid_mask = ~features.iloc[warmup:].isna().any(axis=1)

    X = features.iloc[warmup:][valid_mask].values.astype(np.float32)
    y = labels.iloc[warmup:][valid_mask].values.astype(np.int32)

    return X, y


def main():
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--db", default="data/binance_bitcoin.db")
    parser.add_argument("--output", default="data/mlp_datasets")
    parser.add_argument("--start-date", default="2019-01-01")
    parser.add_argument("--bwin", type=int, default=5)
    parser.add_argument("--fwin", type=int, default=2)
    parser.add_argument("--alpha", type=float, default=0.038)
    parser.add_argument("--beta", type=float, default=0.24)
    parser.add_argument(
        "--feature-set",
        type=str,
        default=FEATURE_SET_PAPER,
        choices=[FEATURE_SET_PAPER, FEATURE_SET_SHAP],
    )
    parser.add_argument(
        "--temporal",
        action="store_true",
        help="Use temporal splitting (time-ordered) instead of random stratified split",
    )
    args = parser.parse_args()

    output_dir = Path(args.output)
    output_dir.mkdir(parents=True, exist_ok=True)

    # Load data
    print(f"Loading 4H data from {args.db}...")
    df = load_4h_data(args.db, args.start_date)
    print(f"Loaded {len(df):,} candles")

    # Build dataset
    X, y = build_dataset(
        df,
        args.bwin,
        args.fwin,
        args.alpha,
        args.beta,
        feature_set=args.feature_set,
    )
    print(f"\nTotal samples: {len(X):,}")

    # Show label distribution
    dist = get_label_distribution(pd.Series(y))
    print("\nLabel distribution (before balancing):")
    for label_name, stats in dist.items():
        print(f"  {label_name}: {stats['count']:,} ({stats['percentage']:.1f}%)")

    # Split mode
    print(f"\nSplit mode: {'temporal (time-ordered)' if args.temporal else 'random (stratified)'}")

    if args.temporal:
        # Temporal split first (data already time-ordered from DB)
        print("\nSplitting data temporally...")
        X_train, X_val, X_test, y_train, y_val, y_test = split_train_val_test(
            X, y, val_ratio=0.15, test_ratio=0.15, temporal=True, gap=args.fwin,
        )

        print(f"Train: {len(X_train):,}")
        print(f"Val:   {len(X_val):,}")
        print(f"Test:  {len(X_test):,}")

        # Balance each split independently
        print("\nBalancing each split independently...")
        X_train, y_train = balance_dataset(X_train, y_train, random_state=42)
        X_val, y_val = balance_dataset(X_val, y_val, random_state=42)
        X_test, y_test = balance_dataset(X_test, y_test, random_state=42)

        print(f"Train (balanced): {len(X_train):,}")
        print(f"Val (balanced):   {len(X_val):,}")
        print(f"Test (balanced):  {len(X_test):,}")
    else:
        # Original flow: balance then random split
        print("\nBalancing classes...")
        X_bal, y_bal = balance_dataset(X, y, random_state=42)

        dist = get_label_distribution(pd.Series(y_bal))
        print("Label distribution (after balancing):")
        for label_name, stats in dist.items():
            print(f"  {label_name}: {stats['count']:,} ({stats['percentage']:.1f}%)")

        print("\nSplitting data...")
        X_train, X_val, X_test, y_train, y_val, y_test = split_train_val_test(
            X_bal, y_bal, val_ratio=0.15, test_ratio=0.15, random_state=42
        )

        print(f"Train: {len(X_train):,}")
        print(f"Val:   {len(X_val):,}")
        print(f"Test:  {len(X_test):,}")

    # Save
    output_path = output_dir / f"mlp_dataset_bwin{args.bwin}_fwin{args.fwin}.npz"
    feature_names = (
        FEATURE_NAMES_PAPER if args.feature_set == FEATURE_SET_PAPER else FEATURE_NAMES_SHAP
    )
    np.savez_compressed(
        output_path,
        X_train=X_train,
        X_val=X_val,
        X_test=X_test,
        y_train=y_train,
        y_val=y_val,
        y_test=y_test,
        feature_names=feature_names,
        feature_set=args.feature_set,
    )

    print(f"\nSaved to {output_path}")


if __name__ == "__main__":
    main()
