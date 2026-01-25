#!/usr/bin/env python3
"""Train price-forecasting LSTM on Binance minute60 data."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from tqdm import tqdm

# Ensure project root on path for DataLoader
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_loader import DataLoader as PriceDataLoader
from lstm_trainer.src.price_dataset import PriceDataset
from lstm_trainer.src.price_model import PriceLSTM


def train_epoch(model, loader, criterion, optimizer, device):
    model.train()
    total_loss = 0.0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        optimizer.zero_grad()
        pred = model(x)
        loss = criterion(pred, y)
        loss.backward()
        optimizer.step()
        total_loss += loss.item()
    return total_loss / len(loader)


def validate(model, loader, criterion, device):
    model.eval()
    total_loss = 0.0
    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)
            pred = model(x)
            loss = criterion(pred, y)
            total_loss += loss.item()
    return total_loss / len(loader)


def load_minute60(start: str, end: str) -> np.ndarray:
    with PriceDataLoader("data/binance_bitcoin.db", exchange="binance") as loader:
        df = loader.load_timeframe("minute60", start_date=start, end_date=end)
    # Drop NAs
    df = df.dropna(subset=["open", "high", "low", "close", "volume"])
    return df


def main():
    parser = argparse.ArgumentParser(description="Train price LSTM (minute60 -> next close).")
    parser.add_argument("--seq-len", type=int, default=120, help="Sequence length (default: 120 bars)")
    parser.add_argument("--batch-size", type=int, default=128, help="Batch size")
    parser.add_argument("--epochs", type=int, default=10, help="Training epochs")
    parser.add_argument("--hidden-size", type=int, default=64, help="LSTM hidden size")
    parser.add_argument("--num-layers", type=int, default=2, help="LSTM layers")
    parser.add_argument("--learning-rate", type=float, default=1e-3, help="Learning rate")
    parser.add_argument("--weight-decay", type=float, default=1e-4, help="Weight decay")
    parser.add_argument("--train-start", default="2020-01-01", help="Train start date")
    parser.add_argument("--train-end", default="2024-12-31", help="Train end date")
    parser.add_argument("--val-end", default="2025-12-31", help="Val end date (exclusive)")
    parser.add_argument("--model-path", default="models/trading_lstm_price.pth", help="Output model path")

    args = parser.parse_args()

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Load train/val data
    train_df = load_minute60(args.train_start, args.train_end)
    val_df = load_minute60(args.train_end, args.val_end)

    train_set = PriceDataset(train_df, seq_len=args.seq_len)
    val_set = PriceDataset(val_df, seq_len=args.seq_len)

    print(f"Train samples: {len(train_set):,} | Val samples: {len(val_set):,}")

    train_loader = DataLoader(train_set, batch_size=args.batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=args.batch_size, shuffle=False)

    model = PriceLSTM(
        input_size=5,
        hidden_size=args.hidden_size,
        num_layers=args.num_layers,
        dropout=0.2,
    ).to(device)

    criterion = nn.MSELoss()
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=args.learning_rate,
        weight_decay=args.weight_decay,
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer, mode="min", patience=3, factor=0.5
    )

    best_val = float("inf")
    model_path = Path(args.model_path)
    model_path.parent.mkdir(parents=True, exist_ok=True)

    for epoch in range(args.epochs):
        train_loss = train_epoch(model, train_loader, criterion, optimizer, device)
        val_loss = validate(model, val_loader, criterion, device)
        scheduler.step(val_loss)
        print(f"Epoch {epoch+1:02d} | Train {train_loss:.6f} | Val {val_loss:.6f}")

        if val_loss < best_val:
            best_val = val_loss
            torch.save(model.state_dict(), model_path)
            print(f"  -> Saved best model to {model_path}")

    print(f"Training complete. Best val loss: {best_val:.6f}")


if __name__ == "__main__":
    main()
