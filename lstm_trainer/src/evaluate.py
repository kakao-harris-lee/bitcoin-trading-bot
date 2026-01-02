#!/usr/bin/env python3
# lstm_trainer/src/evaluate.py
"""Evaluate trained LSTM model."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import classification_report, confusion_matrix
from torch.utils.data import DataLoader

from config import load_config
from dataset import TrendDataset
from model import TrendLSTM


def evaluate(config_path: str = "config/default.yaml", model_path: str = None):
    """Evaluate model on test set."""
    config = load_config(config_path)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Load data
    data_path = Path(config["paths"]["data_processed"]) / "h4_candles.parquet"
    df = pd.read_parquet(data_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Get test set
    val_end = pd.Timestamp(config["data"]["val_end"])
    test_df = df[df["timestamp"] > val_end]
    print(f"Test set: {len(test_df):,} candles")

    # Create dataset
    test_set = TrendDataset(
        test_df,
        seq_len=config["data"]["seq_len"],
        threshold=config["data"]["threshold"],
    )
    test_loader = DataLoader(test_set, batch_size=64, shuffle=False)

    # Load model
    model = TrendLSTM(
        input_size=config["model"]["input_size"],
        hidden_size=config["model"]["hidden_size"],
        num_layers=config["model"]["num_layers"],
        dropout=config["model"]["dropout"],
        num_classes=config["model"]["num_classes"],
    ).to(device)

    if model_path is None:
        model_path = Path(config["paths"]["models"]) / "trading_lstm.pth"

    model.load_state_dict(torch.load(model_path, map_location=device, weights_only=True))
    model.eval()
    print(f"Loaded model from {model_path}")

    # Collect predictions
    all_preds = []
    all_labels = []
    all_probs = []

    with torch.no_grad():
        for x, y in test_loader:
            x = x.to(device)
            logits = model(x)
            probs = torch.softmax(logits, dim=1)
            preds = logits.argmax(dim=1)

            all_preds.extend(preds.cpu().tolist())
            all_labels.extend(y.tolist())
            all_probs.extend(probs.cpu().tolist())

    # Metrics
    labels = ["UP", "DOWN", "SIDEWAYS"]

    print("\n" + "=" * 60)
    print("Classification Report")
    print("=" * 60)
    print(classification_report(all_labels, all_preds, target_names=labels))

    print("\n" + "=" * 60)
    print("Confusion Matrix")
    print("=" * 60)
    cm = confusion_matrix(all_labels, all_preds)
    print(f"{'':>12} {'UP':>8} {'DOWN':>8} {'SIDE':>8}")
    for i, label in enumerate(labels):
        print(f"{label:>12} {cm[i, 0]:>8} {cm[i, 1]:>8} {cm[i, 2]:>8}")

    # Directional accuracy (UP/DOWN only)
    directional_mask = [l != 2 for l in all_labels]
    dir_labels = [l for l, m in zip(all_labels, directional_mask) if m]
    dir_preds = [p for p, m in zip(all_preds, directional_mask) if m]
    dir_acc = sum(l == p for l, p in zip(dir_labels, dir_preds)) / len(dir_labels)

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    overall_acc = sum(l == p for l, p in zip(all_labels, all_preds)) / len(all_labels)
    print(f"Overall Accuracy:     {overall_acc:.2%}")
    print(f"Directional Accuracy: {dir_acc:.2%}")

    return {
        "overall_accuracy": overall_acc,
        "directional_accuracy": dir_acc,
        "predictions": all_preds,
        "labels": all_labels,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate LSTM model")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--model", default=None, help="Path to model file")

    args = parser.parse_args()
    evaluate(args.config, args.model)


if __name__ == "__main__":
    main()
