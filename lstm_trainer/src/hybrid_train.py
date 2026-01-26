#!/usr/bin/env python3
"""Initial training script for Hybrid LSTM + RF model.

Trains both components on historical data:
1. LSTM: Learns price delta prediction from scaled time series
2. RF: Learns to predict LSTM errors for confidence scoring

Usage:
    python -m lstm_trainer.src.hybrid_train --data data/binance_bitcoin.db
    python -m lstm_trainer.src.hybrid_train --data data/binance_bitcoin.db --epochs 50
"""

from __future__ import annotations

import argparse
import logging
import sqlite3
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Dataset
from sklearn.model_selection import train_test_split

from .hybrid_model import HybridLSTM, HybridLoss
from .noise_filter import NoiseFilterRF

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TimeSeriesDataset(Dataset):
    """Dataset for time series sequences with price delta targets."""

    def __init__(
        self,
        features: np.ndarray,
        targets: np.ndarray,
        directions: np.ndarray,
        seq_len: int = 60,
    ):
        """Initialize dataset.

        Args:
            features: Feature array (n_samples, n_features).
            targets: Price delta targets (n_samples,).
            directions: Direction class labels (n_samples,).
            seq_len: Sequence length for LSTM.
        """
        self.features = features
        self.targets = targets
        self.directions = directions
        self.seq_len = seq_len

    def __len__(self) -> int:
        return len(self.features) - self.seq_len

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, torch.Tensor, torch.Tensor]:
        # Get sequence
        x = self.features[idx : idx + self.seq_len]
        # Target is at the end of sequence
        y_price = self.targets[idx + self.seq_len - 1]
        y_dir = self.directions[idx + self.seq_len - 1]

        return (
            torch.tensor(x, dtype=torch.float32),
            torch.tensor(y_price, dtype=torch.float32),
            torch.tensor(y_dir, dtype=torch.long),
        )


def load_data(db_path: str | Path, timeframe: str = "minute60") -> pd.DataFrame:
    """Load data from SQLite database.

    Args:
        db_path: Path to SQLite database.
        timeframe: Table name suffix (minute60, day, etc.).

    Returns:
        DataFrame with OHLCV and scaled columns.
    """
    db_path = Path(db_path)
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    conn = sqlite3.connect(str(db_path))
    df = pd.read_sql(f"SELECT * FROM binance_{timeframe} ORDER BY timestamp", conn)
    conn.close()

    logger.info(f"Loaded {len(df)} rows from {db_path}")
    return df


def prepare_features(
    df: pd.DataFrame,
    input_size: int = 22,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[str]]:
    """Prepare features and targets from DataFrame.

    Args:
        df: DataFrame with scaled columns.
        input_size: Number of input features.

    Returns:
        Tuple of (features, price_targets, direction_targets, column_names).
    """
    # Find scaled columns
    scaled_cols = [c for c in df.columns if c.endswith("_scaled") or c.endswith("_scaled_rolling")]
    scaled_cols = sorted(scaled_cols)[:input_size]

    if len(scaled_cols) < input_size:
        logger.warning(f"Only {len(scaled_cols)} scaled columns found, expected {input_size}")

    logger.info(f"Using {len(scaled_cols)} features: {scaled_cols[:5]}...")

    # Extract features
    features = df[scaled_cols].values

    # Calculate price delta (close change ratio)
    close_prices = df["close"].values
    price_delta = np.zeros(len(close_prices))
    price_delta[1:] = (close_prices[1:] - close_prices[:-1]) / close_prices[:-1]

    # Calculate direction classes (0=DOWN, 1=SIDEWAYS, 2=UP)
    threshold = 0.001  # 0.1% threshold for sideways
    directions = np.ones(len(price_delta), dtype=np.int64)  # Default sideways
    directions[price_delta > threshold] = 2  # UP
    directions[price_delta < -threshold] = 0  # DOWN

    # Handle NaN
    features = np.nan_to_num(features, nan=0.0)

    return features, price_delta, directions, scaled_cols


def train_lstm(
    model: HybridLSTM,
    train_loader: DataLoader,
    val_loader: DataLoader,
    epochs: int = 100,
    lr: float = 0.001,
    patience: int = 10,
    device: torch.device = torch.device("cpu"),
) -> dict[str, list[float]]:
    """Train LSTM model.

    Args:
        model: HybridLSTM model.
        train_loader: Training data loader.
        val_loader: Validation data loader.
        epochs: Maximum training epochs.
        lr: Learning rate.
        patience: Early stopping patience.
        device: Training device.

    Returns:
        Training history dict.
    """
    model.to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=lr, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", factor=0.5, patience=5
    )
    criterion = HybridLoss(price_weight=1.0, direction_weight=0.3)

    history = {"train_loss": [], "val_loss": [], "val_price_loss": [], "val_dir_acc": []}
    best_val_loss = float("inf")
    best_state = None
    no_improve = 0

    for epoch in range(epochs):
        # Training
        model.train()
        train_losses = []

        for x, y_price, y_dir in train_loader:
            x = x.to(device)
            y_price = y_price.to(device)
            y_dir = y_dir.to(device)

            optimizer.zero_grad()
            output = model(x)
            losses = criterion(output, y_price, y_dir)
            losses["total"].backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), max_norm=1.0)
            optimizer.step()

            train_losses.append(losses["total"].item())

        # Validation
        model.eval()
        val_losses = []
        val_price_losses = []
        correct = 0
        total = 0

        with torch.no_grad():
            for x, y_price, y_dir in val_loader:
                x = x.to(device)
                y_price = y_price.to(device)
                y_dir = y_dir.to(device)

                output = model(x)
                losses = criterion(output, y_price, y_dir)
                val_losses.append(losses["total"].item())
                val_price_losses.append(losses["price"].item())

                # Direction accuracy
                pred_dir = output["direction_logits"].argmax(dim=1)
                correct += (pred_dir == y_dir).sum().item()
                total += len(y_dir)

        avg_train_loss = np.mean(train_losses)
        avg_val_loss = np.mean(val_losses)
        avg_val_price = np.mean(val_price_losses)
        dir_acc = correct / total if total > 0 else 0.0

        history["train_loss"].append(avg_train_loss)
        history["val_loss"].append(avg_val_loss)
        history["val_price_loss"].append(avg_val_price)
        history["val_dir_acc"].append(dir_acc)

        scheduler.step(avg_val_loss)

        logger.info(
            f"Epoch {epoch+1}/{epochs} - "
            f"Train: {avg_train_loss:.6f}, Val: {avg_val_loss:.6f}, "
            f"Price: {avg_val_price:.6f}, Dir Acc: {dir_acc:.3f}"
        )

        # Early stopping
        if avg_val_loss < best_val_loss:
            best_val_loss = avg_val_loss
            best_state = model.state_dict().copy()
            no_improve = 0
        else:
            no_improve += 1
            if no_improve >= patience:
                logger.info(f"Early stopping at epoch {epoch+1}")
                break

    # Restore best model
    if best_state is not None:
        model.load_state_dict(best_state)

    return history


def train_rf(
    rf: NoiseFilterRF,
    model: HybridLSTM,
    features: np.ndarray,
    targets: np.ndarray,
    seq_len: int = 60,
    device: torch.device = torch.device("cpu"),
) -> None:
    """Train RandomForest on LSTM prediction errors.

    Args:
        rf: NoiseFilterRF instance.
        model: Trained HybridLSTM model.
        features: Input features array.
        targets: Price delta targets.
        seq_len: Sequence length.
        device: Inference device.
    """
    model.eval()
    model.to(device)

    rf_features = []
    rf_errors = []

    logger.info("Generating RF training data from LSTM predictions...")

    # Generate predictions for all sequences
    batch_size = 256
    n_samples = len(features) - seq_len

    for i in range(0, n_samples, batch_size):
        end_idx = min(i + batch_size, n_samples)
        batch_x = []

        for j in range(i, end_idx):
            batch_x.append(features[j : j + seq_len])

        batch_x = torch.tensor(np.array(batch_x), dtype=torch.float32).to(device)

        with torch.no_grad():
            output = model(batch_x)
            predictions = output["price_delta"].cpu().numpy()
            hidden_states = output["hidden_state"].cpu().numpy()

        # Calculate errors and build RF features
        for k, (pred, hidden) in enumerate(zip(predictions, hidden_states)):
            actual = targets[i + k + seq_len - 1]
            error = abs(pred - actual)

            # Build market context (simplified for training)
            market_context = {
                "mfi": 50.0,
                "adx": 20.0,
                "volatility": 0.02,
                "regime": "SIDEWAYS_FLAT",
                "breakout_signal": 0,
            }

            rf_feat = rf.build_features(pred, hidden, market_context)
            rf_features.append(rf_feat)
            rf_errors.append(error)

    rf_features = np.array(rf_features)
    rf_errors = np.array(rf_errors)

    logger.info(f"Training RF on {len(rf_features)} samples...")
    rf.fit(rf_features, rf_errors)


def main():
    parser = argparse.ArgumentParser(description="Train Hybrid LSTM + RF model")
    parser.add_argument(
        "--data",
        type=str,
        default="data/binance_bitcoin.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        default="minute60",
        help="Data timeframe (minute60, day)",
    )
    parser.add_argument("--epochs", type=int, default=100, help="Training epochs")
    parser.add_argument("--batch-size", type=int, default=64, help="Batch size")
    parser.add_argument("--lr", type=float, default=0.001, help="Learning rate")
    parser.add_argument("--seq-len", type=int, default=60, help="Sequence length")
    parser.add_argument("--input-size", type=int, default=22, help="Input features")
    parser.add_argument("--hidden-size", type=int, default=64, help="Hidden size")
    parser.add_argument(
        "--output-dir",
        type=str,
        default="lstm_trainer/models",
        help="Output directory",
    )
    parser.add_argument(
        "--device",
        type=str,
        default="cuda" if torch.cuda.is_available() else "cpu",
        help="Training device",
    )
    args = parser.parse_args()

    device = torch.device(args.device)
    logger.info(f"Using device: {device}")

    # Load data
    df = load_data(args.data, args.timeframe)

    # Prepare features
    features, targets, directions, col_names = prepare_features(df, args.input_size)

    # Split data
    train_idx = int(len(features) * 0.8)
    val_idx = int(len(features) * 0.9)

    train_features = features[:train_idx]
    train_targets = targets[:train_idx]
    train_dirs = directions[:train_idx]

    val_features = features[train_idx:val_idx]
    val_targets = targets[train_idx:val_idx]
    val_dirs = directions[train_idx:val_idx]

    logger.info(f"Train: {len(train_features)}, Val: {len(val_features)}")

    # Create datasets
    train_dataset = TimeSeriesDataset(
        train_features, train_targets, train_dirs, args.seq_len
    )
    val_dataset = TimeSeriesDataset(
        val_features, val_targets, val_dirs, args.seq_len
    )

    train_loader = DataLoader(
        train_dataset, batch_size=args.batch_size, shuffle=True, num_workers=0
    )
    val_loader = DataLoader(
        val_dataset, batch_size=args.batch_size, shuffle=False, num_workers=0
    )

    # Initialize model
    model = HybridLSTM(
        input_size=args.input_size,
        hidden_size=args.hidden_size,
        num_layers=2,
        dropout=0.2,
    )

    # Train LSTM
    logger.info("Training HybridLSTM...")
    history = train_lstm(
        model,
        train_loader,
        val_loader,
        epochs=args.epochs,
        lr=args.lr,
        patience=10,
        device=device,
    )

    # Save LSTM
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    lstm_path = output_dir / "hybrid_lstm.pth"
    torch.save(
        {
            "model_state_dict": model.state_dict(),
            "input_size": args.input_size,
            "hidden_size": args.hidden_size,
            "seq_len": args.seq_len,
            "feature_columns": col_names,
            "history": history,
        },
        lstm_path,
    )
    logger.info(f"Saved LSTM to {lstm_path}")

    # Train RF on LSTM errors
    rf = NoiseFilterRF()
    train_rf(rf, model, features[:val_idx], targets[:val_idx], args.seq_len, device)

    # Save RF
    rf_path = output_dir / "noise_filter_rf.pkl"
    rf.save(rf_path)

    logger.info("Training complete!")
    logger.info(f"Final val loss: {history['val_loss'][-1]:.6f}")
    logger.info(f"Final dir accuracy: {history['val_dir_acc'][-1]:.3f}")


if __name__ == "__main__":
    main()
