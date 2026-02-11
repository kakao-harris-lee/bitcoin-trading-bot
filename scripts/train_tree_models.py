#!/usr/bin/env python3
"""Train XGBoost and LightGBM models on existing .npz MLP datasets.

Reuses the same feature data (paper_36) used for MLP training, but with
tree-based architectures for heterogeneous ensemble diversity.

Usage:
    # Train both XGBoost and LightGBM on default datasets
    python scripts/train_tree_models.py

    # Train specific model type on specific dataset
    python scripts/train_tree_models.py --dataset data/mlp_datasets/mlp_dataset_bwin3_fwin1.npz --model xgboost
    python scripts/train_tree_models.py --dataset data/mlp_datasets/mlp_dataset_bwin7_fwin3.npz --model lightgbm

    # Re-split with temporal ordering (recommended)
    python scripts/train_tree_models.py --temporal-split
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


# Default training configurations
DEFAULT_JOBS = [
    {
        "dataset": "data/mlp_datasets/mlp_dataset_bwin3_fwin1.npz",
        "model_type": "xgboost",
        "output_dir": "models/mlp_direction/xgb_bwin3_fwin1",
        "label": "XGBoost bwin3/fwin1",
    },
    {
        "dataset": "data/mlp_datasets/mlp_dataset_bwin7_fwin3.npz",
        "model_type": "lightgbm",
        "output_dir": "models/mlp_direction/lgb_bwin7_fwin3",
        "label": "LightGBM bwin7/fwin3",
    },
]

# tree_60 feature set jobs
TREE60_JOBS = [
    {
        "dataset": "data/mlp_datasets/tree60_dataset_bwin3_fwin1.npz",
        "model_type": "xgboost",
        "output_dir": "models/mlp_direction/xgb_tree60_bwin3_fwin1",
        "label": "XGBoost tree_60 bwin3/fwin1",
    },
    {
        "dataset": "data/mlp_datasets/tree60_dataset_bwin7_fwin3.npz",
        "model_type": "lightgbm",
        "output_dir": "models/mlp_direction/lgb_tree60_bwin7_fwin3",
        "label": "LightGBM tree_60 bwin7/fwin3",
    },
]


def load_dataset(path: str, temporal_split: bool = False) -> dict:
    """Load .npz dataset with optional temporal re-split."""
    data = np.load(path, allow_pickle=True)

    if temporal_split:
        # Concatenate all splits back, then re-split temporally
        X = np.concatenate([data["X_train"], data["X_val"], data["X_test"]])
        y = np.concatenate([data["y_train"], data["y_val"], data["y_test"]])

        from core.mlp_labeling import split_train_val_test

        # Extract fwin from config if available
        cfg = data.get("config", None)
        gap = int(cfg[1]) if cfg is not None and len(cfg) > 1 else 0
        X_train, X_val, X_test, y_train, y_val, y_test = split_train_val_test(
            X, y, temporal=True, gap=gap,
        )
        print(f"  Temporal re-split (gap={gap}): "
              f"train={len(y_train)}, val={len(y_val)}, test={len(y_test)}")
    else:
        X_train = data["X_train"]
        X_val = data["X_val"]
        X_test = data["X_test"]
        y_train = data["y_train"]
        y_val = data["y_val"]
        y_test = data["y_test"]

    feature_names = list(data.get("feature_names", []))

    return {
        "X_train": X_train, "X_val": X_val, "X_test": X_test,
        "y_train": y_train, "y_val": y_val, "y_test": y_test,
        "feature_names": feature_names,
    }


def compute_sample_weights(y: np.ndarray) -> np.ndarray:
    """Compute inverse-frequency sample weights for class imbalance."""
    classes, counts = np.unique(y, return_counts=True)
    n_samples = len(y)
    n_classes = len(classes)
    # sklearn-style balanced weights: n_samples / (n_classes * count_per_class)
    class_weights = {c: n_samples / (n_classes * cnt) for c, cnt in zip(classes, counts)}
    weights = np.array([class_weights[label] for label in y], dtype=np.float32)
    return weights


def train_xgboost(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    feature_names: list[str] | None = None,
    n_estimators: int = 500,
    max_depth: int = 6,
    learning_rate: float = 0.05,
    early_stopping_rounds: int = 50,
    use_sample_weights: bool = False,
) -> "xgb.Booster":
    """Train XGBoost multi-class classifier."""
    import xgboost as xgb

    n_classes = len(np.unique(y_train))

    dtrain = xgb.DMatrix(X_train, label=y_train)
    dval = xgb.DMatrix(X_val, label=y_val)

    if use_sample_weights:
        sw = compute_sample_weights(y_train)
        dtrain.set_weight(sw)
        print(f"  Sample weights applied (class balance correction)")

    params = {
        "objective": "multi:softprob",
        "num_class": n_classes,
        "max_depth": max_depth,
        "learning_rate": learning_rate,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "eval_metric": "mlogloss",
        "tree_method": "hist",
        "seed": 42,
        "verbosity": 1,
    }

    model = xgb.train(
        params,
        dtrain,
        num_boost_round=n_estimators,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=early_stopping_rounds,
        verbose_eval=50,
    )

    return model


def train_lightgbm(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_val: np.ndarray,
    y_val: np.ndarray,
    feature_names: list[str] | None = None,
    n_estimators: int = 500,
    max_depth: int = 6,
    learning_rate: float = 0.05,
    early_stopping_rounds: int = 50,
    use_sample_weights: bool = False,
) -> "lgb.Booster":
    """Train LightGBM multi-class classifier."""
    import lightgbm as lgb

    n_classes = len(np.unique(y_train))

    sw = compute_sample_weights(y_train) if use_sample_weights else None
    dtrain = lgb.Dataset(X_train, label=y_train, weight=sw)
    dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

    if use_sample_weights:
        print(f"  Sample weights applied (class balance correction)")

    params = {
        "objective": "multiclass",
        "num_class": n_classes,
        "max_depth": max_depth,
        "learning_rate": learning_rate,
        "num_leaves": 63,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_samples": 20,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "metric": "multi_logloss",
        "seed": 42,
        "verbose": -1,
    }

    callbacks = [
        lgb.log_evaluation(period=50),
        lgb.early_stopping(stopping_rounds=early_stopping_rounds),
    ]

    model = lgb.train(
        params,
        dtrain,
        num_boost_round=n_estimators,
        valid_sets=[dtrain, dval],
        valid_names=["train", "val"],
        callbacks=callbacks,
    )

    return model


def evaluate_model(model, X_test, y_test, model_type: str, feature_names: list[str] | None = None) -> dict:
    """Evaluate model accuracy on test set."""
    from sklearn.metrics import accuracy_score, classification_report

    if model_type == "xgboost":
        import xgboost as xgb
        dtest = xgb.DMatrix(X_test)
        probs = model.predict(dtest)
    else:
        probs = np.array(model.predict(X_test))

    if probs.ndim == 1:
        n_classes = len(np.unique(y_test))
        probs = probs.reshape(-1, n_classes)

    preds = probs.argmax(axis=1)
    acc = accuracy_score(y_test, preds)

    print(f"\n  Test Accuracy: {acc:.4f} ({acc*100:.1f}%)")
    print(f"\n  Classification Report:")
    labels = ["HOLD", "BUY", "SELL"]
    print(classification_report(y_test, preds, target_names=labels, digits=3))

    return {"accuracy": acc, "predictions": preds, "probabilities": probs}


def save_model(model, output_dir: str, model_type: str, metadata: dict) -> str:
    """Save model and metadata."""
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True)

    if model_type == "xgboost":
        model_path = out / "model.json"
        model.save_model(str(model_path))
    else:
        model_path = out / "model.txt"
        model.save_model(str(model_path))

    # Save training metadata
    meta_path = out / "metadata.json"
    meta_path.write_text(json.dumps(metadata, indent=2, default=str))

    print(f"  Model saved: {model_path}")
    print(f"  Metadata saved: {meta_path}")
    return str(model_path)


def run_training_job(
    job: dict, temporal_split: bool = False, use_sample_weights: bool = False,
) -> str | None:
    """Run a single training job. Returns model path on success."""
    print(f"\n{'='*60}")
    print(f"  Training: {job['label']}")
    print(f"  Dataset: {job['dataset']}")
    print(f"  Model: {job['model_type']}")
    print(f"  Sample weights: {use_sample_weights}")
    print(f"{'='*60}")

    dataset_path = str(PROJECT_ROOT / job["dataset"])
    if not Path(dataset_path).exists():
        print(f"  ERROR: Dataset not found: {dataset_path}")
        return None

    data = load_dataset(dataset_path, temporal_split=temporal_split)

    print(f"  Train: {data['X_train'].shape}, Val: {data['X_val'].shape}, "
          f"Test: {data['X_test'].shape}")

    # Class distribution
    vals, counts = np.unique(data["y_train"], return_counts=True)
    for v, c in zip(vals, counts):
        print(f"    class {v}: {c} ({c/len(data['y_train'])*100:.1f}%)")

    feature_names = data["feature_names"] if data["feature_names"] else None

    t0 = time.time()

    if job["model_type"] == "xgboost":
        model = train_xgboost(
            data["X_train"], data["y_train"],
            data["X_val"], data["y_val"],
            feature_names=feature_names,
            use_sample_weights=use_sample_weights,
        )
    else:
        model = train_lightgbm(
            data["X_train"], data["y_train"],
            data["X_val"], data["y_val"],
            feature_names=feature_names,
            use_sample_weights=use_sample_weights,
        )

    elapsed = time.time() - t0
    print(f"\n  Training time: {elapsed:.1f}s")

    # Evaluate
    eval_result = evaluate_model(model, data["X_test"], data["y_test"], job["model_type"], feature_names=feature_names)

    # Save
    metadata = {
        "model_type": job["model_type"],
        "dataset": job["dataset"],
        "temporal_split": temporal_split,
        "use_sample_weights": use_sample_weights,
        "train_samples": len(data["y_train"]),
        "val_samples": len(data["y_val"]),
        "test_samples": len(data["y_test"]),
        "test_accuracy": eval_result["accuracy"],
        "training_time_sec": elapsed,
        "n_features": data["X_train"].shape[1],
    }

    output_dir = str(PROJECT_ROOT / job["output_dir"])
    model_path = save_model(model, output_dir, job["model_type"], metadata)
    return model_path


def main():
    parser = argparse.ArgumentParser(description="Train tree models (XGBoost/LightGBM)")
    parser.add_argument(
        "--dataset", type=str, default=None,
        help="Path to single .npz dataset (overrides defaults)",
    )
    parser.add_argument(
        "--model", type=str, choices=["xgboost", "lightgbm"], default=None,
        help="Model type to train (requires --dataset)",
    )
    parser.add_argument(
        "--output", type=str, default=None,
        help="Output directory (requires --dataset)",
    )
    parser.add_argument(
        "--temporal-split", action="store_true",
        help="Re-split data temporally (recommended to avoid data leakage)",
    )
    parser.add_argument(
        "--tree60", action="store_true",
        help="Train on tree_60 feature set datasets",
    )
    parser.add_argument(
        "--sample-weights", action="store_true",
        help="Use inverse-frequency sample weights for class imbalance",
    )
    args = parser.parse_args()

    if args.dataset:
        if not args.model:
            parser.error("--model is required when --dataset is specified")
        output = args.output or f"models/mlp_direction/{args.model}_custom"
        jobs = [{
            "dataset": args.dataset,
            "model_type": args.model,
            "output_dir": output,
            "label": f"{args.model} (custom)",
        }]
    elif args.tree60:
        jobs = TREE60_JOBS
    else:
        jobs = DEFAULT_JOBS

    print(f"\n  Training {len(jobs)} model(s)")
    print(f"  Temporal split: {args.temporal_split}")
    print(f"  Sample weights: {args.sample_weights}")

    results = []
    for job in jobs:
        path = run_training_job(
            job,
            temporal_split=args.temporal_split,
            use_sample_weights=args.sample_weights,
        )
        if path:
            results.append(path)

    print(f"\n{'='*60}")
    print(f"  SUMMARY: {len(results)}/{len(jobs)} models trained successfully")
    for p in results:
        print(f"    {p}")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
