#!/usr/bin/env python3
"""
RMSE Evaluation for MLP Direction Models.

Evaluates models on BTC/ETH validation data using:
1. Classification metrics (accuracy, precision, recall)
2. RMSE (Root Mean Square Error) for predicted probabilities vs actual returns
3. Direction accuracy (predicted direction vs actual direction)

Usage:
    python evaluate_rmse.py --model-path models/mlp_direction/multiasset_v1/model_final.pt
"""

import argparse
import numpy as np
import torch
from pathlib import Path
from sklearn.metrics import classification_report, confusion_matrix
import sys

# Add project root to path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from mlp_trainer.src.mlp_model import MLPDirectionClassifier
from mlp_trainer.src.constants import (
    DIRECTION_THRESHOLD,
    INFERENCE_BATCH_SIZE,
    ALLOWED_MODEL_DIRS,
)


def validate_path(path: Path, allowed_dirs: list[str]) -> bool:
    """
    Validate that path is within allowed directories.

    Args:
        path: Path to validate
        allowed_dirs: List of allowed directory prefixes

    Returns:
        True if path is valid, raises ValueError otherwise
    """
    resolved = path.resolve()
    project_root_resolved = project_root.resolve()

    for allowed_dir in allowed_dirs:
        allowed_path = (project_root_resolved / allowed_dir).resolve()
        try:
            resolved.relative_to(allowed_path)
            return True
        except ValueError:
            continue

    raise ValueError(
        f"Path must be within allowed directories: {allowed_dirs}. "
        f"Got: {resolved}"
    )


def load_model(model_path: Path) -> tuple[MLPDirectionClassifier, dict]:
    """
    Load trained model and config securely.

    Args:
        model_path: Path to model checkpoint

    Returns:
        Tuple of (model, config dict)
    """
    # Use secure loading with path validation enabled (default)
    model = MLPDirectionClassifier.load(str(model_path), device="cpu", validate_path=True)

    # Extract config from model attributes instead of re-loading checkpoint
    config = {
        "input_dim": model.input_dim,
        "hidden_dims": model.hidden_dims,
        "num_classes": model.num_classes,
        "dropout": model.dropout_rate,
    }
    return model, config


def calculate_rmse(predictions: np.ndarray, actual_returns: np.ndarray) -> float:
    """
    Calculate RMSE between predicted probabilities and actual returns.

    For direction prediction:
    - Convert predictions to expected return: P(buy) - P(sell)
    - Compare to actual return direction

    Args:
        predictions: Probability array of shape (N, 3) with [Hold, Buy, Sell]
        actual_returns: Array of actual return directions

    Returns:
        RMSE value
    """
    # Predicted direction score: P(buy) - P(sell)
    predicted_direction = predictions[:, 1] - predictions[:, 2]

    # Actual direction: +1 for up, -1 for down, 0 for hold
    actual_direction = np.zeros_like(actual_returns)
    actual_direction[actual_returns > DIRECTION_THRESHOLD] = 1
    actual_direction[actual_returns < -DIRECTION_THRESHOLD] = -1

    # RMSE
    rmse = np.sqrt(np.mean((predicted_direction - actual_direction) ** 2))
    return rmse


def evaluate_model(
    model: MLPDirectionClassifier,
    X: np.ndarray,
    y: np.ndarray,
    batch_size: int = INFERENCE_BATCH_SIZE,
) -> dict:
    """
    Comprehensive model evaluation with batched inference.

    Args:
        model: Trained MLP model
        X: Feature array of shape (N, num_features)
        y: Label array of shape (N,)
        batch_size: Batch size for inference (memory efficiency)

    Returns:
        Dictionary with evaluation metrics
    """
    device = torch.device("cpu")
    model.to(device)
    model.eval()

    # Batched inference for memory efficiency
    all_probs = []
    for i in range(0, len(X), batch_size):
        batch_end = min(i + batch_size, len(X))
        X_batch = torch.FloatTensor(X[i:batch_end]).to(device)

        with torch.no_grad():
            logits = model(X_batch)
            probs = torch.softmax(logits, dim=1).cpu().numpy()
        all_probs.append(probs)

    probs = np.vstack(all_probs)
    preds = np.argmax(probs, axis=1)

    # Classification metrics
    accuracy = np.mean(preds == y)

    # Per-class metrics
    class_names = ["Hold", "Buy", "Sell"]
    report = classification_report(y, preds, target_names=class_names, output_dict=True)

    # Confusion matrix
    cm = confusion_matrix(y, preds)

    # Direction accuracy (ignoring Hold class)
    # "Direction Not Wrong" = correctly predicted OR predicted Hold
    direction_mask = y != 0  # Only Buy/Sell samples
    if direction_mask.sum() > 0:
        direction_correct = (preds[direction_mask] == y[direction_mask]).sum()
        direction_total = direction_mask.sum()
        direction_accuracy = direction_correct / direction_total

        # Direction Not Wrong = correct OR predicted Hold
        not_wrong = (preds == y) | (preds == 0)
        direction_not_wrong = not_wrong[direction_mask].mean()
    else:
        direction_accuracy = 0.0
        direction_not_wrong = 0.0

    # RMSE calculation
    # Convert labels to actual returns for RMSE
    # y=0 (Hold) -> 0, y=1 (Buy) -> +1, y=2 (Sell) -> -1
    actual_returns = np.zeros_like(y, dtype=np.float32)
    actual_returns[y == 1] = 1.0
    actual_returns[y == 2] = -1.0

    rmse = calculate_rmse(probs, actual_returns)

    # Precision for Buy signals (most important for trading)
    buy_precision = report["Buy"]["precision"]
    buy_recall = report["Buy"]["recall"]

    # Sell signal metrics
    sell_precision = report["Sell"]["precision"]
    sell_recall = report["Sell"]["recall"]

    return {
        "accuracy": accuracy,
        "rmse": rmse,
        "direction_accuracy": direction_accuracy,
        "direction_not_wrong": direction_not_wrong,
        "buy_precision": buy_precision,
        "buy_recall": buy_recall,
        "sell_precision": sell_precision,
        "sell_recall": sell_recall,
        "confusion_matrix": cm,
        "classification_report": report,
        "predictions": preds,
        "probabilities": probs,
    }


def print_results(results: dict, model_name: str) -> None:
    """Print evaluation results."""
    print()
    print("=" * 60)
    print(f"Model Evaluation: {model_name}")
    print("=" * 60)

    print("\n[Overall Metrics]")
    print(f"  Classification Accuracy: {results['accuracy']*100:.2f}%")
    print(f"  Direction Accuracy: {results['direction_accuracy']*100:.2f}%")
    print(f"  Direction Not Wrong: {results['direction_not_wrong']*100:.2f}%")
    print(f"  RMSE: {results['rmse']:.4f}")

    print("\n[Buy Signal Quality]")
    print(f"  Precision: {results['buy_precision']*100:.2f}%")
    print(f"  Recall: {results['buy_recall']*100:.2f}%")
    random_precision = 1/3 * 100
    lift = results['buy_precision'] / (1/3)
    print(f"  Lift vs Random: {lift:.2f}x (random={random_precision:.1f}%)")

    print("\n[Sell Signal Quality]")
    print(f"  Precision: {results['sell_precision']*100:.2f}%")
    print(f"  Recall: {results['sell_recall']*100:.2f}%")

    print("\n[Confusion Matrix]")
    cm = results['confusion_matrix']
    print("            Predicted")
    print("            Hold   Buy   Sell")
    for i, label in enumerate(["Hold", "Buy ", "Sell"]):
        print(f"  Actual {label}  {cm[i,0]:5d}  {cm[i,1]:5d}  {cm[i,2]:5d}")


def main() -> int:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Evaluate MLP model with RMSE")
    parser.add_argument("--model-path", type=str, required=True,
                        help="Path to model checkpoint")
    parser.add_argument("--dataset", type=str, default="data/mlp_datasets/mlp_dataset_bwin5_fwin2.npz",
                        help="Path to dataset")
    parser.add_argument("--split", type=str, default="val", choices=["val", "test"],
                        help="Which split to evaluate on")
    parser.add_argument("--batch-size", type=int, default=INFERENCE_BATCH_SIZE,
                        help="Batch size for inference")
    args = parser.parse_args()

    model_path = Path(args.model_path).resolve()
    dataset_path = Path(args.dataset).resolve()

    # Validate paths
    try:
        validate_path(model_path, ALLOWED_MODEL_DIRS)
    except ValueError as e:
        print(f"Error: {e}")
        return 1

    if not model_path.exists():
        print(f"Error: Model not found at {model_path}")
        return 1

    if not dataset_path.exists():
        print(f"Error: Dataset not found at {dataset_path}")
        return 1

    # Load model
    print(f"Loading model from {model_path}...")
    try:
        model, config = load_model(model_path)
    except Exception as e:
        print(f"Error loading model: {e}")
        return 1

    print(f"Model input dim: {config.get('input_dim', 36)}")
    print(f"Model hidden dims: {config.get('hidden_dims', (128, 64, 32))}")

    # Load data
    print(f"\nLoading {args.split} data from {dataset_path}...")
    try:
        data = np.load(dataset_path)
    except Exception as e:
        print(f"Error loading dataset: {e}")
        return 1

    if args.split == "val":
        X = data["X_val"]
        y = data["y_val"]
    else:
        X = data["X_test"]
        y = data["y_test"]

    print(f"Data shape: {X.shape}")
    print(f"Label distribution: Hold={np.sum(y==0):,}, Buy={np.sum(y==1):,}, Sell={np.sum(y==2):,}")

    # Evaluate
    results = evaluate_model(model, X, y, batch_size=args.batch_size)

    # Print results
    model_name = model_path.parent.name
    print_results(results, model_name)

    # Summary for comparison
    print("\n" + "=" * 60)
    print("Summary (for comparison)")
    print("=" * 60)
    print(f"Model: {model_name}")
    print(f"Accuracy: {results['accuracy']*100:.2f}%")
    print(f"RMSE: {results['rmse']:.4f}")
    print(f"Buy Precision: {results['buy_precision']*100:.2f}%")
    print(f"Direction Accuracy: {results['direction_accuracy']*100:.2f}%")

    return 0


if __name__ == "__main__":
    sys.exit(main())
