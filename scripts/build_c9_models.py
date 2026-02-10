#!/usr/bin/env python3
"""Build and train C9 retrained-forward models, then patch allocation.c9.json."""

from __future__ import annotations

import argparse
import json
import random
import sqlite3
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import torch

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.mlp_labeling import balance_dataset, compute_labels
from mlp_trainer.src.mlp_train import MLPTrainer, TrainingConfig
from trading.indicators.mlp_features import (
    FEATURE_NAMES_PAPER,
    FEATURE_NAMES_SHAP,
    FEATURE_NAMES_V2,
    FEATURE_SET_PAPER,
    FEATURE_SET_SHAP,
    FEATURE_SET_V2,
    calculate_mlp_features,
)

ASSET_DB = {
    "BTC": PROJECT_ROOT / "data" / "binance_bitcoin.db",
    "ETH": PROJECT_ROOT / "data" / "binance_ethereum.db",
    "SOL": PROJECT_ROOT / "data" / "binance_solana.db",
    "BNB": PROJECT_ROOT / "data" / "binance_bnb.db",
}
FEATURE_NAME_MAP = {
    FEATURE_SET_PAPER: FEATURE_NAMES_PAPER,
    FEATURE_SET_SHAP: FEATURE_NAMES_SHAP,
    FEATURE_SET_V2: FEATURE_NAMES_V2,
}


@dataclass
class AssetPlan:
    symbol: str
    strategy_id: str
    bwin: int
    feature_set: str
    fwin: int = 2
    alpha: float = 0.038
    beta: float = 0.24
    fee: float = 0.001


def _detect_4h_table(conn: sqlite3.Connection) -> str:
    tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
    priority = [
        "binance_minute240",
        "minute240",
        "btc_minute240",
        "ethereum_minute240",
        "eth_minute240",
        "solana_minute240",
        "bnb_minute240",
    ]
    for table in priority:
        if table in tables:
            cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            if cnt > 0:
                return table
    for table in tables:
        if "minute240" not in table:
            continue
        cnt = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if cnt > 0:
            return table
    raise ValueError("No non-empty 4H table detected")


def load_4h_data(db_path: Path, start_date: str, end_date: str | None) -> pd.DataFrame:
    conn = sqlite3.connect(str(db_path))
    try:
        table = _detect_4h_table(conn)
        query = f"""
            SELECT timestamp, open, high, low, close, volume
            FROM {table}
            WHERE timestamp >= ?
            ORDER BY timestamp
        """
        params: list[Any] = [start_date]
        if end_date:
            query = f"""
                SELECT timestamp, open, high, low, close, volume
                FROM {table}
                WHERE timestamp >= ? AND timestamp <= ?
                ORDER BY timestamp
            """
            params.append(end_date)

        df = pd.read_sql(query, conn, params=params)
    finally:
        conn.close()

    if df.empty:
        raise ValueError(f"No 4H data in {db_path} for requested range")
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True, errors="coerce")
    df = df.dropna(subset=["timestamp"]).reset_index(drop=True)
    return df


def build_xy(df: pd.DataFrame, plan: AssetPlan) -> tuple[np.ndarray, np.ndarray]:
    feats = calculate_mlp_features(
        df,
        bwin=plan.bwin,
        include_temporal=True,
        feature_set=plan.feature_set,
    )
    labels = compute_labels(
        df,
        bwin=plan.bwin,
        fwin=plan.fwin,
        alpha=plan.alpha,
        beta=plan.beta,
        fee=plan.fee,
    )
    warmup = max(100, plan.bwin * 20)
    valid_mask = ~feats.iloc[warmup:].isna().any(axis=1)
    X = feats.iloc[warmup:][valid_mask].values.astype(np.float32)
    y = labels.iloc[warmup:][valid_mask].values.astype(np.int32)
    if len(X) < 200:
        raise ValueError(f"Not enough valid samples for {plan.symbol}: {len(X)}")
    return X, y


def chrono_split(
    X: np.ndarray,
    y: np.ndarray,
    val_ratio: float,
    test_ratio: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    n = len(X)
    test_n = max(1, int(n * test_ratio))
    val_n = max(1, int(n * val_ratio)) if val_ratio > 0 else 0
    train_n = n - val_n - test_n
    if train_n <= 0:
        raise ValueError(f"Invalid split sizes for n={n}, val={val_ratio}, test={test_ratio}")

    X_train = X[:train_n]
    y_train = y[:train_n]
    X_val = X[train_n : train_n + val_n]
    y_val = y[train_n : train_n + val_n]
    X_test = X[train_n + val_n :]
    y_test = y[train_n + val_n :]
    return X_train, X_val, X_test, y_train, y_val, y_test


def _safe_name(feature_set: str) -> str:
    return feature_set.replace("_", "")


def compute_auto_focal_alpha(y_train: np.ndarray) -> list[float]:
    counts = np.bincount(y_train.astype(np.int64), minlength=3).astype(np.float64)
    counts = np.maximum(counts, 1.0)
    freqs = counts / counts.sum()
    inv = 1.0 / freqs
    alpha = inv / (inv.mean() + 1e-12)
    alpha = np.clip(alpha, 0.2, 5.0)
    return [float(alpha[i]) for i in range(3)]


def parse_alpha(alpha_str: str, y_train: np.ndarray) -> list[float]:
    if alpha_str.strip().lower() == "auto":
        return compute_auto_focal_alpha(y_train)
    vals = [float(x.strip()) for x in alpha_str.split(",") if x.strip()]
    if len(vals) != 3:
        raise ValueError("--focal-alpha must be 'auto' or 3 comma-separated floats")
    return vals


def _load_plans_from_config(config: dict[str, Any]) -> list[AssetPlan]:
    plans: list[AssetPlan] = []
    for symbol in ["BTC", "ETH", "SOL", "BNB"]:
        sid = f"mlp_direction_{symbol.lower()}"
        strategy = config["strategies"].get(sid, {})
        feature_set = strategy.get("mlp_feature_set", FEATURE_SET_PAPER)
        bwin = int(strategy.get("bwin", 5 if symbol == "BTC" else 4))
        plans.append(
            AssetPlan(
                symbol=symbol,
                strategy_id=sid,
                bwin=bwin,
                feature_set=feature_set,
            )
        )
    return plans


def patch_config_model_paths(
    config: dict[str, Any],
    model_paths: dict[str, str],
) -> dict[str, Any]:
    for symbol in ["BTC", "ETH", "SOL", "BNB"]:
        sid = f"mlp_direction_{symbol.lower()}"
        strategy = config["strategies"].get(sid)
        if not strategy or sid not in model_paths:
            continue
        model_path = model_paths[sid]

        strategy["model_path"] = model_path
        strategy.pop("ensemble_models", None)

        entry = strategy.get("entry", {}).get("params", {})
        exit_params = strategy.get("exit", {}).get("params", {})
        entry["model_path"] = model_path
        entry.pop("ensemble_models", None)
        exit_params["model_path"] = model_path

    return config


def main() -> None:
    parser = argparse.ArgumentParser(description="Retrain forward-focused C9 MLP models")
    parser.add_argument("--config-in", default="config/strategies/allocation.c8.json")
    parser.add_argument("--config-out", default="config/strategies/allocation.c9.json")
    parser.add_argument("--dataset-dir", default="data/mlp_datasets/c9")
    parser.add_argument("--models-root", default="models/mlp_direction/c9")
    parser.add_argument("--start-date", default="2022-01-01")
    parser.add_argument("--end-date", default=None)
    parser.add_argument("--val-ratio", type=float, default=0.15)
    parser.add_argument("--test-ratio", type=float, default=0.15)
    parser.add_argument("--epochs", type=int, default=120)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--lr", type=float, default=1e-3)
    parser.add_argument("--dropout", type=float, default=0.2)
    parser.add_argument("--patience", type=int, default=12)
    parser.add_argument("--hidden-dims", default="128,64,32")
    parser.add_argument("--loss", choices=["cross_entropy", "focal"], default="cross_entropy")
    parser.add_argument("--focal-gamma", type=float, default=2.0)
    parser.add_argument(
        "--focal-alpha",
        default="auto",
        help="Focal alpha weights as 'a,b,c' or 'auto' (hold,buy,sell)",
    )
    parser.add_argument("--no-balance-train", action="store_true")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)

    config_in = PROJECT_ROOT / args.config_in
    config_out = PROJECT_ROOT / args.config_out
    dataset_dir = PROJECT_ROOT / args.dataset_dir
    models_root = PROJECT_ROOT / args.models_root
    dataset_dir.mkdir(parents=True, exist_ok=True)
    models_root.mkdir(parents=True, exist_ok=True)

    if not config_out.exists():
        config_out.write_text(config_in.read_text(), encoding="utf-8")

    cfg = json.loads(config_out.read_text(encoding="utf-8"))
    plans = _load_plans_from_config(cfg)
    hidden_dims = tuple(int(x.strip()) for x in args.hidden_dims.split(",") if x.strip())
    if not hidden_dims:
        raise ValueError("hidden-dims must contain at least one dimension")

    summary: list[dict[str, Any]] = []
    model_paths: dict[str, str] = {}

    for plan in plans:
        if plan.feature_set not in FEATURE_NAME_MAP:
            raise ValueError(f"Unsupported feature set for C9: {plan.feature_set}")
        db_path = ASSET_DB[plan.symbol]
        print(f"\n[{plan.symbol}] loading {db_path.name} ({args.start_date}..{args.end_date or 'latest'})")
        df = load_4h_data(db_path, args.start_date, args.end_date)
        X, y = build_xy(df, plan)

        X_train, X_val, X_test, y_train, y_val, y_test = chrono_split(
            X=X,
            y=y,
            val_ratio=args.val_ratio,
            test_ratio=args.test_ratio,
        )
        if not args.no_balance_train:
            X_train, y_train = balance_dataset(X_train, y_train, random_state=args.seed)
        focal_alpha = parse_alpha(args.focal_alpha, y_train) if args.loss == "focal" else [0.25, 0.5, 0.5]

        ds_path = dataset_dir / (
            f"{plan.symbol.lower()}_{_safe_name(plan.feature_set)}_b{plan.bwin}_f{plan.fwin}.npz"
        )
        np.savez_compressed(
            ds_path,
            X_train=X_train,
            X_val=X_val,
            X_test=X_test,
            y_train=y_train,
            y_val=y_val,
            y_test=y_test,
            feature_names=FEATURE_NAME_MAP[plan.feature_set],
            feature_set=plan.feature_set,
        )

        model_dir = models_root / (
            f"{plan.symbol.lower()}_{_safe_name(plan.feature_set)}_b{plan.bwin}_f{plan.fwin}"
        )
        trainer = MLPTrainer(
            TrainingConfig(
                input_dim=int(X_train.shape[1]),
                hidden_dims=hidden_dims,
                dropout=args.dropout,
                epochs=args.epochs,
                batch_size=args.batch_size,
                learning_rate=args.lr,
                patience=args.patience,
                output_dir=model_dir,
                loss_type=args.loss,
                focal_gamma=args.focal_gamma,
                focal_alpha=tuple(focal_alpha),
            )
        )
        train_out = trainer.train(X_train, y_train, X_val, y_val, run_name=f"c9_{plan.symbol.lower()}")
        test_metrics = trainer.evaluate(X_test, y_test)

        best_path = model_dir / "model_best.pt"
        final_path = model_dir / "model_final.pt"
        selected_path = best_path if best_path.exists() else final_path
        model_paths[plan.strategy_id] = str(selected_path.relative_to(PROJECT_ROOT))

        summary.append(
            {
                "symbol": plan.symbol,
                "strategy_id": plan.strategy_id,
                "feature_set": plan.feature_set,
                "bwin": plan.bwin,
                "samples_total": int(len(X)),
                "samples_train": int(len(X_train)),
                "samples_val": int(len(X_val)),
                "samples_test": int(len(X_test)),
                "best_val_acc": float(train_out["best_val_acc"]),
                "test_acc": float(test_metrics["test_acc"]),
                "test_buy_acc": float(test_metrics["buy_acc"]),
                "test_sell_acc": float(test_metrics["sell_acc"]),
                "loss": args.loss,
                "focal_alpha": focal_alpha,
                "model_path": model_paths[plan.strategy_id],
            }
        )
        print(
            f"[{plan.symbol}] done: test_acc={test_metrics['test_acc']:.4f}, "
            f"buy={test_metrics['buy_acc']:.4f}, sell={test_metrics['sell_acc']:.4f}"
        )

    patched = patch_config_model_paths(cfg, model_paths)
    config_out.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")

    summary_path = PROJECT_ROOT / "logs" / "c9_training_summary.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(f"\nUpdated config: {config_out}")
    print(f"Training summary: {summary_path}")


if __name__ == "__main__":
    main()
