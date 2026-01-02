#!/usr/bin/env python3
# lstm_trainer/src/train.py
"""Training script for LSTM model."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from tqdm import tqdm

from config import load_config
from dataset import TrendDataset
from model import TrendLSTM


def train_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> float:
    """Train for one epoch."""
    model.train()
    total_loss = 0.0

    for x, y in loader:
        x, y = x.to(device), y.to(device)

        optimizer.zero_grad()
        logits = model(x)
        loss = criterion(logits, y)
        loss.backward()
        optimizer.step()

        total_loss += loss.item()

    return total_loss / len(loader)


def validate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> tuple[float, float]:
    """Validate model."""
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0

    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)

            logits = model(x)
            loss = criterion(logits, y)

            total_loss += loss.item()
            preds = logits.argmax(dim=1)
            correct += (preds == y).sum().item()
            total += y.size(0)

    return total_loss / len(loader), correct / total


def train(config_path: str = "config/default.yaml"):
    """Main training function."""
    config = load_config(config_path)

    # Device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Load data
    data_path = Path(config["paths"]["data_processed"]) / "h4_candles.parquet"
    df = pd.read_parquet(data_path)
    print(f"Loaded {len(df):,} candles")

    # Split data chronologically
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    train_end = pd.Timestamp(config["data"]["train_end"])
    val_end = pd.Timestamp(config["data"]["val_end"])

    train_df = df[df["timestamp"] <= train_end]
    val_df = df[(df["timestamp"] > train_end) & (df["timestamp"] <= val_end)]
    test_df = df[df["timestamp"] > val_end]

    print(f"Train: {len(train_df):,} | Val: {len(val_df):,} | Test: {len(test_df):,}")

    # Create datasets
    seq_len = config["data"]["seq_len"]
    threshold = config["data"]["threshold"]

    train_set = TrendDataset(train_df, seq_len=seq_len, threshold=threshold)
    val_set = TrendDataset(val_df, seq_len=seq_len, threshold=threshold)

    # Class weights
    class_weights = train_set.get_class_weights().to(device)
    print(f"Class weights: {class_weights.tolist()}")

    # DataLoaders
    batch_size = config["training"]["batch_size"]
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)

    # Model
    model = TrendLSTM(
        input_size=config["model"]["input_size"],
        hidden_size=config["model"]["hidden_size"],
        num_layers=config["model"]["num_layers"],
        dropout=config["model"]["dropout"],
        num_classes=config["model"]["num_classes"],
    ).to(device)

    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    # Training setup
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config["training"]["learning_rate"],
        weight_decay=config["training"]["weight_decay"],
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="min",
        patience=config["training"]["scheduler_patience"],
        factor=0.5,
    )

    # Training loop
    best_val_loss = float("inf")
    patience_counter = 0
    max_patience = config["training"]["early_stopping_patience"]

    model_dir = Path(config["paths"]["models"])
    model_dir.mkdir(parents=True, exist_ok=True)

    for epoch in range(config["training"]["max_epochs"]):
        train_loss = train_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = validate(model, val_loader, criterion, device)
        scheduler.step(val_loss)

        print(
            f"Epoch {epoch+1:3d} | "
            f"Train Loss: {train_loss:.4f} | "
            f"Val Loss: {val_loss:.4f} | "
            f"Val Acc: {val_acc:.2%}"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), model_dir / "trading_lstm.pth")
            print(f"  -> Saved best model (val_loss: {val_loss:.4f})")
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= max_patience:
                print(f"Early stopping at epoch {epoch+1}")
                break

    print(f"\nTraining complete. Best model saved to {model_dir / 'trading_lstm.pth'}")


def main():
    parser = argparse.ArgumentParser(description="Train LSTM model")
    parser.add_argument(
        "--config",
        default="config/default.yaml",
        help="Path to config file",
    )

    args = parser.parse_args()
    train(args.config)


if __name__ == "__main__":
    main()
