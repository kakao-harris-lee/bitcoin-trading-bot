#!/usr/bin/env python3
"""Train a RandomForest regime classifier from a feature table CSV/Parquet."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import joblib
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, classification_report, f1_score

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from trading.regime.training import (
    CLASS_TO_REGIME,
    DEFAULT_FEATURE_COLUMNS,
    add_regime_target,
    build_supervised_dataset,
    chronological_split,
    compute_class_weight_map,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train RandomForest regime model.")
    parser.add_argument("--dataset", required=True, help="Input feature table (.csv/.parquet)")
    parser.add_argument("--output-dir", required=True, help="Output directory for model artifacts")
    parser.add_argument("--target-column", default="", help="Optional existing target column")
    parser.add_argument("--features", default="", help="Comma-separated feature columns")
    parser.add_argument("--forward-horizon", type=int, default=24)
    parser.add_argument("--bull-threshold", type=float, default=0.02)
    parser.add_argument("--bear-threshold", type=float, default=-0.02)
    parser.add_argument("--n-estimators", type=int, default=500)
    parser.add_argument("--max-depth", type=int, default=10)
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--train-ratio", type=float, default=0.7)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    return parser.parse_args()


def _read_frame(path: Path) -> pd.DataFrame:
    if path.suffix.lower() == ".parquet":
        return pd.read_parquet(path)
    return pd.read_csv(path)


def main() -> int:
    args = parse_args()

    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise FileNotFoundError(f"dataset not found: {dataset_path}")

    df = _read_frame(dataset_path)

    if args.target_column:
        target_column = args.target_column
    else:
        df = add_regime_target(
            df,
            forward_horizon=args.forward_horizon,
            bull_threshold=args.bull_threshold,
            bear_threshold=args.bear_threshold,
        )
        target_column = "regime_target_class"

    feature_columns = [f.strip() for f in args.features.split(",") if f.strip()] or list(DEFAULT_FEATURE_COLUMNS)
    data = build_supervised_dataset(df, feature_columns=feature_columns, target_column=target_column)

    X_train, X_val, X_test, y_train, y_val, y_test = chronological_split(
        data.X,
        data.y,
        train_ratio=args.train_ratio,
        val_ratio=args.val_ratio,
    )

    class_weight = compute_class_weight_map(y_train)
    model = RandomForestClassifier(
        n_estimators=args.n_estimators,
        max_depth=args.max_depth,
        class_weight=class_weight or None,
        random_state=args.random_state,
        n_jobs=-1,
    )
    model.fit(X_train, y_train)

    pred_val = model.predict(X_val)
    pred_test = model.predict(X_test)

    val_f1 = f1_score(y_val, pred_val, average="macro")
    test_f1 = f1_score(y_test, pred_test, average="macro")
    test_acc = accuracy_score(y_test, pred_test)

    print(f"Validation macro F1: {val_f1:.4f}")
    print(f"Test macro F1: {test_f1:.4f}")
    print(f"Test accuracy: {test_acc:.4f}")

    labels = sorted(CLASS_TO_REGIME.keys())
    target_names = [CLASS_TO_REGIME[i] for i in labels]
    print("\nClassification report (test):")
    print(
        classification_report(
            y_test,
            pred_test,
            labels=labels,
            target_names=target_names,
            digits=4,
            zero_division=0,
        )
    )

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    model_path = output_dir / "regime_rf.joblib"
    meta_path = output_dir / "metadata.json"

    joblib.dump(model, model_path)

    metadata = {
        "model_type": "RandomForestClassifier",
        "dataset": str(dataset_path),
        "feature_columns": feature_columns,
        "target_column": target_column,
        "rows": int(len(data.X)),
        "train_rows": int(len(X_train)),
        "val_rows": int(len(X_val)),
        "test_rows": int(len(X_test)),
        "class_weight": {str(k): v for k, v in class_weight.items()},
        "metrics": {
            "val_macro_f1": float(val_f1),
            "test_macro_f1": float(test_f1),
            "test_accuracy": float(test_acc),
        },
        "params": {
            "n_estimators": args.n_estimators,
            "max_depth": args.max_depth,
            "random_state": args.random_state,
            "train_ratio": args.train_ratio,
            "val_ratio": args.val_ratio,
            "forward_horizon": args.forward_horizon,
            "bull_threshold": args.bull_threshold,
            "bear_threshold": args.bear_threshold,
        },
    }
    meta_path.write_text(json.dumps(metadata, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Saved model: {model_path}")
    print(f"Saved metadata: {meta_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
