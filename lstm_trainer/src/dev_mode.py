#!/usr/bin/env python3
# lstm_trainer/src/dev_mode.py
"""Quick validation on CPU with recent data."""

import argparse
from pathlib import Path

import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, Subset
from tqdm import tqdm

from dataset import TrendDataset
from model import TrendLSTM


def dev_train(data_path: str, days: int = 30):
    """
    Fast training on recent month for logic validation.

    Args:
        data_path: Path to h4_candles.parquet
        days: Number of days of data to use
    """
    print(f"Loading data from {data_path}...")
    df = pd.read_parquet(data_path)

    # Use only recent data
    samples = days * 6  # 6 H4 candles per day
    recent = df.tail(samples + 70).copy()  # Extra for seq_len + buffer
    print(f"Using {len(recent)} candles ({days} days)")

    # Create dataset with smaller seq_len for speed
    dataset = TrendDataset(recent, seq_len=30, threshold=0.015)
    print(f"Dataset size: {len(dataset)}")

    # Chronological split 80/20 (no data leakage)
    train_size = int(0.8 * len(dataset))
    train_indices = list(range(train_size))
    val_indices = list(range(train_size, len(dataset)))
    train_set = Subset(dataset, train_indices)
    val_set = Subset(dataset, val_indices)

    train_loader = DataLoader(train_set, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=32, shuffle=False)

    # Smaller model for CPU speed
    model = TrendLSTM(
        input_size=5,
        hidden_size=32,
        num_layers=1,
        dropout=0.1,
        num_classes=3,
    )

    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    # Quick training
    print("\nTraining (10 epochs)...")
    for epoch in range(10):
        model.train()
        train_loss = 0.0
        for x, y in train_loader:
            optimizer.zero_grad()
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        # Validate
        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for x, y in val_loader:
                preds = model(x).argmax(dim=1)
                correct += (preds == y).sum().item()
                total += y.size(0)

        val_acc = correct / total if total > 0 else 0
        print(f"Epoch {epoch+1:2d} | Train Loss: {train_loss/len(train_loader):.4f} | Val Acc: {val_acc:.2%}")

    print("\n" + "=" * 50)
    print("Pipeline validated - ready for full GPU training!")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Quick CPU validation")
    parser.add_argument(
        "--data",
        default="data/processed/h4_candles.parquet",
        help="Path to data file",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days of recent data to use",
    )

    args = parser.parse_args()
    dev_train(args.data, args.days)


if __name__ == "__main__":
    main()
