"""
MLP Dataset Builder Module.

Builds ML-ready datasets from multi-asset OHLCV data:
1. Feature extraction using mlp_features module
2. Label computation using mlp_labeling module
3. Class balancing via random undersampling
4. Train/validation/test splitting

Reference: Parente & Rizzuti (2025)
"""

import logging
from pathlib import Path
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from trading.indicators.mlp_features import (
    calculate_mlp_features,
    FEATURE_SET_PAPER,
    FEATURE_SET_SHAP,
    FEATURE_SET_V2,
    FEATURE_SET_PAPER_MTF,
    FEATURE_NAMES_PAPER,
    FEATURE_NAMES_SHAP,
    FEATURE_NAMES_V2,
    FEATURE_NAMES_PAPER_MTF,
)
from core.mlp_labeling import (
    compute_labels,
    balance_dataset,
    split_train_val_test,
    get_label_distribution,
    LABEL_NAMES,
)

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent.parent
DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "multi_asset_4h"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "mlp_datasets"


@dataclass
class DatasetConfig:
    """Configuration for dataset building."""

    backward_window: int = 5
    forward_window: int = 2
    alpha: float = 0.038  # Minimum return threshold (3.8%)
    beta: float = 0.24  # Maximum return threshold (24%)
    fee: float = 0.001  # Trading fee (0.1%)
    val_ratio: float = 0.15
    test_ratio: float = 0.15
    balance_classes: bool = True
    random_state: int = 42
    min_samples_per_symbol: int = 500
    feature_set: str = FEATURE_SET_PAPER
    temporal_split: bool = False  # Use temporal split instead of random split
    # Paper-aligned date filters (training on non-BTC/ETH up to 2022-12-22)
    train_start: str | None = None
    train_end: str | None = "2022-12-22"
    # Paper-aligned validation windows (BTC/ETH)
    validation_backtest_end: str | None = "2022-12-22"
    validation_forward_start: str | None = "2022-12-23"
    validation_forward_end: str | None = "2024-11-11"
    exclude_symbols: tuple[str, ...] = ("BTCUSDT", "ETHUSDT")


class MLPDatasetBuilder:
    """
    Builds ML-ready datasets for MLP direction classification.

    Pipeline:
    1. Load multi-asset OHLCV data
    2. Calculate features for each symbol
    3. Compute labels using parametric labeling
    4. Combine all symbols
    5. Balance classes (optional)
    6. Split into train/val/test
    7. Save to numpy format
    """

    def __init__(self, config: Optional[DatasetConfig] = None):
        self.config = config or DatasetConfig()

    def process_single_symbol(
        self,
        df: pd.DataFrame,
        symbol: str,
    ) -> tuple[np.ndarray, np.ndarray, int, pd.Index | None]:
        """
        Process a single symbol's data.

        Args:
            df: DataFrame with OHLCV data
            symbol: Symbol name for logging

        Returns:
            Tuple of (features, labels, num_valid_samples)
        """
        try:
            # Calculate features
            features = calculate_mlp_features(
                df,
                bwin=self.config.backward_window,
                include_temporal=True,
                feature_set=self.config.feature_set,
            )

            # Compute labels
            labels = compute_labels(
                df,
                bwin=self.config.backward_window,
                fwin=self.config.forward_window,
                alpha=self.config.alpha,
                beta=self.config.beta,
                fee=self.config.fee,
            )

            # Find valid indices (no NaN in features)
            # Need sufficient warmup period for indicators
            warmup = max(100, self.config.backward_window * 20)
            valid_mask = ~features.iloc[warmup:].isna().any(axis=1)

            # Get valid data
            valid_features = features.iloc[warmup:][valid_mask]
            valid_labels = labels.iloc[warmup:][valid_mask]

            if len(valid_features) < self.config.min_samples_per_symbol:
                logger.warning(
                    f"{symbol}: insufficient valid samples ({len(valid_features)})"
                )
                return None, None, 0, None

            return (
                valid_features.values.astype(np.float32),
                valid_labels.values.astype(np.int32),
                len(valid_features),
                valid_features.index,
            )

        except Exception as e:
            logger.error(f"{symbol}: processing failed - {e}")
            return None, None, 0, None

    def build_from_parquet(
        self,
        parquet_path: Path,
        output_dir: Optional[Path] = None,
    ) -> dict:
        """
        Build dataset from combined parquet file.

        Args:
            parquet_path: Path to parquet file with all symbols
            output_dir: Output directory for saving

        Returns:
            Dict with dataset statistics
        """
        output_dir = output_dir or DEFAULT_OUTPUT_DIR
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Loading data from {parquet_path}")
        df = pd.read_parquet(parquet_path)

        # Optional date filtering (paper-aligned)
        if "timestamp" in df.columns:
            if self.config.train_start:
                df = df[df["timestamp"] >= pd.to_datetime(self.config.train_start)]
            if self.config.train_end:
                df = df[df["timestamp"] <= pd.to_datetime(self.config.train_end)]

        # Optional symbol exclusion (paper trains without BTC/ETH)
        if "symbol" in df.columns and self.config.exclude_symbols:
            df = df[~df["symbol"].isin(self.config.exclude_symbols)]

        symbols = df["symbol"].unique()
        logger.info(f"Found {len(symbols)} symbols")

        all_features = []
        all_labels = []
        all_timestamps = []
        symbol_stats = {}

        for i, symbol in enumerate(symbols):
            symbol_df = df[df["symbol"] == symbol].copy()
            symbol_df = symbol_df.sort_values("timestamp").reset_index(drop=True)

            features, labels, n_samples, timestamps = self.process_single_symbol(
                symbol_df, symbol
            )

            if features is not None:
                all_features.append(features)
                all_labels.append(labels)
                if timestamps is not None:
                    # Convert pandas timestamps to numpy int64 (Unix timestamps)
                    ts_array = symbol_df.loc[timestamps, "timestamp"].values.astype(np.int64)
                    all_timestamps.append(ts_array)
                symbol_stats[symbol] = n_samples

                if (i + 1) % 50 == 0:
                    logger.info(f"Processed {i+1}/{len(symbols)} symbols")

        if not all_features:
            raise ValueError("No valid data processed")

        # Combine all data
        X = np.vstack(all_features)
        y = np.concatenate(all_labels)

        logger.info(f"\nTotal samples: {len(X):,}")
        logger.info(f"Successful symbols: {len(symbol_stats)}")

        # Log label distribution before balancing
        dist = get_label_distribution(pd.Series(y))
        logger.info("\nLabel distribution (before balancing):")
        for label_name, stats in dist.items():
            logger.info(f"  {label_name}: {stats['count']:,} ({stats['percentage']:.1f}%)")

        # Handle temporal vs random split
        if self.config.temporal_split:
            logger.info("\nUsing temporal split (time-ordered)...")

            # Concatenate timestamps
            timestamps = np.concatenate(all_timestamps)

            # Sort by timestamp globally (multi-asset time-ordered)
            sort_idx = np.argsort(timestamps)
            X = X[sort_idx]
            y = y[sort_idx]

            # Temporal split FIRST (without data leakage)
            X_train, X_val, X_test, y_train, y_val, y_test = split_train_val_test(
                X,
                y,
                val_ratio=self.config.val_ratio,
                test_ratio=self.config.test_ratio,
                random_state=self.config.random_state,
                temporal=True,
                gap=self.config.forward_window,
            )

            # Balance each split independently
            if self.config.balance_classes:
                logger.info("Balancing classes (per split)...")
                X_train, y_train = balance_dataset(X_train, y_train, random_state=self.config.random_state)
                X_val, y_val = balance_dataset(X_val, y_val, random_state=self.config.random_state)
                X_test, y_test = balance_dataset(X_test, y_test, random_state=self.config.random_state)

                logger.info("Label distribution (after balancing):")
                for split_name, y_split in [("Train", y_train), ("Val", y_val), ("Test", y_test)]:
                    dist = get_label_distribution(pd.Series(y_split))
                    logger.info(f"  {split_name}:")
                    for label_name, stats in dist.items():
                        logger.info(f"    {label_name}: {stats['count']:,} ({stats['percentage']:.1f}%)")
        else:
            logger.info("\nUsing random split...")

            # Original flow: balance then random split
            if self.config.balance_classes:
                logger.info("Balancing classes...")
                X, y = balance_dataset(X, y, random_state=self.config.random_state)

                dist = get_label_distribution(pd.Series(y))
                logger.info("Label distribution (after balancing):")
                for label_name, stats in dist.items():
                    logger.info(f"  {label_name}: {stats['count']:,} ({stats['percentage']:.1f}%)")

            # Split data
            logger.info("Splitting data...")
            X_train, X_val, X_test, y_train, y_val, y_test = split_train_val_test(
                X,
                y,
                val_ratio=self.config.val_ratio,
                test_ratio=self.config.test_ratio,
                random_state=self.config.random_state,
            )

        logger.info(f"Train: {len(X_train):,}")
        logger.info(f"Validation: {len(X_val):,}")
        logger.info(f"Test: {len(X_test):,}")

        # Save datasets
        config_str = f"bwin{self.config.backward_window}_fwin{self.config.forward_window}"
        output_path = output_dir / f"mlp_dataset_{config_str}.npz"

        feature_names_map = {
            FEATURE_SET_PAPER: FEATURE_NAMES_PAPER,
            FEATURE_SET_SHAP: FEATURE_NAMES_SHAP,
            FEATURE_SET_V2: FEATURE_NAMES_V2,
            FEATURE_SET_PAPER_MTF: FEATURE_NAMES_PAPER + FEATURE_NAMES_PAPER_MTF,
        }
        feature_names = feature_names_map.get(
            self.config.feature_set, FEATURE_NAMES_PAPER
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
            feature_set=self.config.feature_set,
            config=np.array(
                [
                    self.config.backward_window,
                    self.config.forward_window,
                    self.config.alpha,
                    self.config.beta,
                    self.config.fee,
                ]
            ),
        )

        logger.info(f"\nSaved dataset to {output_path}")

        return {
            "output_path": str(output_path),
            "total_samples": len(X),
            "train_samples": len(X_train),
            "val_samples": len(X_val),
            "test_samples": len(X_test),
            "num_symbols": len(symbol_stats),
            "num_features": X.shape[1],
            "symbol_stats": symbol_stats,
        }

    def build_validation_dataset(
        self,
        parquet_path: Path,
        output_dir: Optional[Path] = None,
    ) -> dict:
        """
        Build validation dataset (BTC/ETH) without splitting.

        This is used for final model evaluation on unseen assets.

        Args:
            parquet_path: Path to validation parquet file
            output_dir: Output directory for saving

        Returns:
            Dict with dataset statistics
        """
        output_dir = output_dir or DEFAULT_OUTPUT_DIR
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"Loading validation data from {parquet_path}")
        df = pd.read_parquet(parquet_path)

        feature_names_map = {
            FEATURE_SET_PAPER: FEATURE_NAMES_PAPER,
            FEATURE_SET_SHAP: FEATURE_NAMES_SHAP,
            FEATURE_SET_V2: FEATURE_NAMES_V2,
            FEATURE_SET_PAPER_MTF: FEATURE_NAMES_PAPER + FEATURE_NAMES_PAPER_MTF,
        }
        feature_names = feature_names_map.get(
            self.config.feature_set, FEATURE_NAMES_PAPER
        )

        symbols = df["symbol"].unique()
        logger.info(f"Found symbols: {list(symbols)}")

        validation_data = {}

        backtest_end = (
            pd.to_datetime(self.config.validation_backtest_end)
            if self.config.validation_backtest_end
            else None
        )
        forward_start = (
            pd.to_datetime(self.config.validation_forward_start)
            if self.config.validation_forward_start
            else None
        )

        # Optional date filtering for forward/backtest windows
        if "timestamp" in df.columns:
            if self.config.validation_forward_end:
                df = df[df["timestamp"] <= pd.to_datetime(self.config.validation_forward_end)]

        for symbol in symbols:
            symbol_df = df[df["symbol"] == symbol].copy()
            symbol_df = symbol_df.sort_values("timestamp").reset_index(drop=True)

            features, labels, n_samples, valid_index = self.process_single_symbol(
                symbol_df, symbol
            )

            if features is not None:
                if valid_index is None:
                    continue
                timestamps = symbol_df.loc[valid_index, "timestamp"].values
                symbol_payload = {
                    "X": features,
                    "y": labels,
                    "timestamps": timestamps,
                }
                if backtest_end is not None:
                    back_mask = timestamps <= backtest_end
                    symbol_payload["backtest"] = {
                        "X": features[back_mask],
                        "y": labels[back_mask],
                        "timestamps": timestamps[back_mask],
                    }
                if forward_start is not None:
                    fwd_mask = timestamps >= forward_start
                    symbol_payload["forward"] = {
                        "X": features[fwd_mask],
                        "y": labels[fwd_mask],
                        "timestamps": timestamps[fwd_mask],
                    }

                validation_data[symbol] = symbol_payload

                dist = get_label_distribution(pd.Series(labels))
                logger.info(f"\n{symbol}: {n_samples:,} samples")
                for label_name, stats in dist.items():
                    logger.info(f"  {label_name}: {stats['count']:,} ({stats['percentage']:.1f}%)")

        # Save each symbol separately (for per-asset backtesting)
        config_str = f"bwin{self.config.backward_window}_fwin{self.config.forward_window}"

        for symbol, data in validation_data.items():
            output_path = output_dir / f"validation_{symbol}_{config_str}.npz"
            np.savez_compressed(
                output_path,
                X=data["X"],
                y=data["y"],
                timestamps=data["timestamps"],
                feature_names=feature_names,
                feature_set=self.config.feature_set,
            )
            logger.info(f"Saved {symbol} to {output_path}")

            if "backtest" in data:
                back_path = output_dir / f"validation_{symbol}_{config_str}_backtest.npz"
                np.savez_compressed(
                    back_path,
                    X=data["backtest"]["X"],
                    y=data["backtest"]["y"],
                    timestamps=data["backtest"]["timestamps"],
                    feature_names=feature_names,
                    feature_set=self.config.feature_set,
                )
                logger.info(f"Saved {symbol} backtest to {back_path}")

            if "forward" in data:
                fwd_path = output_dir / f"validation_{symbol}_{config_str}_forward.npz"
                np.savez_compressed(
                    fwd_path,
                    X=data["forward"]["X"],
                    y=data["forward"]["y"],
                    timestamps=data["forward"]["timestamps"],
                    feature_names=feature_names,
                    feature_set=self.config.feature_set,
                )
                logger.info(f"Saved {symbol} forward to {fwd_path}")

        return validation_data


def load_dataset(path: Path) -> dict:
    """
    Load dataset from npz file.

    Args:
        path: Path to npz file

    Returns:
        Dict with X_train, X_val, X_test, y_train, y_val, y_test
    """
    data = np.load(path)
    return {
        "X_train": data["X_train"],
        "X_val": data["X_val"],
        "X_test": data["X_test"],
        "y_train": data["y_train"],
        "y_val": data["y_val"],
        "y_test": data["y_test"],
        "feature_names": list(data["feature_names"]),
        "feature_set": str(data["feature_set"]) if "feature_set" in data else None,
    }


def main():
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(description="Build MLP training dataset")
    parser.add_argument(
        "--input",
        type=str,
        default=str(DEFAULT_DATA_DIR / "train_4h.parquet"),
        help="Input parquet file path",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="Output directory",
    )
    parser.add_argument(
        "--bwin",
        type=int,
        default=5,
        help="Backward window size",
    )
    parser.add_argument(
        "--fwin",
        type=int,
        default=2,
        help="Forward window size",
    )
    parser.add_argument(
        "--alpha",
        type=float,
        default=0.038,
        help="Minimum return threshold",
    )
    parser.add_argument(
        "--beta",
        type=float,
        default=0.24,
        help="Maximum return threshold",
    )
    parser.add_argument(
        "--feature-set",
        type=str,
        default=FEATURE_SET_PAPER,
        choices=[FEATURE_SET_PAPER, FEATURE_SET_SHAP, FEATURE_SET_V2, FEATURE_SET_PAPER_MTF],
        help="Feature set to use",
    )
    parser.add_argument(
        "--train-start",
        type=str,
        default=None,
        help="Training data start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--train-end",
        type=str,
        default="2022-12-22",
        help="Training data end date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--validation-backtest-end",
        type=str,
        default="2022-12-22",
        help="Validation backtest end date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--validation-forward-start",
        type=str,
        default="2022-12-23",
        help="Validation forward start date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--validation-forward-end",
        type=str,
        default="2024-11-11",
        help="Validation forward end date (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--no-balance",
        action="store_true",
        help="Disable class balancing",
    )
    parser.add_argument(
        "--val-ratio",
        type=float,
        default=0.15,
        help="Validation ratio (set 0.0 to disable validation split)",
    )
    parser.add_argument(
        "--test-ratio",
        type=float,
        default=0.15,
        help="Test ratio",
    )
    parser.add_argument(
        "--validation",
        type=str,
        default=None,
        help="Path to validation parquet (BTC/ETH)",
    )
    parser.add_argument(
        "--temporal-split",
        action="store_true",
        help="Use temporal split instead of random split",
    )

    args = parser.parse_args()

    config = DatasetConfig(
        backward_window=args.bwin,
        forward_window=args.fwin,
        alpha=args.alpha,
        beta=args.beta,
        balance_classes=not args.no_balance,
        val_ratio=args.val_ratio,
        test_ratio=args.test_ratio,
        feature_set=args.feature_set,
        temporal_split=args.temporal_split,
        train_start=args.train_start,
        train_end=args.train_end,
        validation_backtest_end=args.validation_backtest_end,
        validation_forward_start=args.validation_forward_start,
        validation_forward_end=args.validation_forward_end,
    )

    builder = MLPDatasetBuilder(config)

    # Build training dataset
    logger.info("=" * 60)
    logger.info("Building training dataset")
    logger.info("=" * 60)
    stats = builder.build_from_parquet(
        Path(args.input),
        Path(args.output),
    )

    # Build validation dataset if provided
    if args.validation:
        logger.info("")
        logger.info("=" * 60)
        logger.info("Building validation dataset")
        logger.info("=" * 60)
        builder.build_validation_dataset(
            Path(args.validation),
            Path(args.output),
        )

    print(f"\nDataset saved to: {stats['output_path']}")
    print(f"Total samples: {stats['total_samples']:,}")
    print(f"Train/Val/Test: {stats['train_samples']:,}/{stats['val_samples']:,}/{stats['test_samples']:,}")


if __name__ == "__main__":
    main()
