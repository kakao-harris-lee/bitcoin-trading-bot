#!/usr/bin/env python3
"""Walk-Forward Validation Backtest for Tree Models.

Instead of a single temporal split, trains tree models on expanding windows
and evaluates on subsequent unseen periods. Stitches OOS predictions for
a realistic backtest.

Supports sliding window (--max-train-folds) and temporal decay weighting
(--temporal-decay) to prevent the model from becoming too conservative
when expanding windows accumulate too much HOLD-dominant data.

Usage:
    python scripts/backtest/walkforward_backtest.py --assets BTC ETH SOL
    python scripts/backtest/walkforward_backtest.py --n-splits 5 --by-year

    # Sliding window: only use 3 most recent folds for training
    python scripts/backtest/walkforward_backtest.py --max-train-folds 3

    # Temporal decay: exponentially downweight older samples
    python scripts/backtest/walkforward_backtest.py --temporal-decay 2.0

    # Both combined (recommended)
    python scripts/backtest/walkforward_backtest.py --max-train-folds 3 --temporal-decay 2.0 --by-year
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
import os
import time

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import (
    load_data,
    compute_metrics,
    print_yearly_table,
)
from core.backtester import Backtester

ASSET_DB = {
    "BTC": ("data/binance_bitcoin.db", "BTC"),
    "ETH": ("data/binance_ethereum.db", "ETH"),
    "SOL": ("data/binance_solana.db", "SOL"),
}


def compute_tree60_features(df: pd.DataFrame) -> pd.DataFrame:
    """Compute tree_60 features for entire DataFrame."""
    from trading.indicators.mlp_features import calculate_mlp_features
    return calculate_mlp_features(df, bwin=3, include_temporal=True, feature_set="tree_60")


def train_xgb_model(X_train, y_train, X_val, y_val, sample_weights=None, num_boost_round: int = 500):
    """Train XGBoost model on given data."""
    import xgboost as xgb

    n_classes = len(np.unique(y_train))
    dtrain = xgb.DMatrix(X_train, label=y_train)
    dval = xgb.DMatrix(X_val, label=y_val)

    if sample_weights is not None:
        dtrain.set_weight(sample_weights)

    params = {
        "objective": "multi:softprob",
        "num_class": n_classes,
        "max_depth": 6,
        "learning_rate": 0.05,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "eval_metric": "mlogloss",
        "tree_method": "hist",
        "nthread": int(os.getenv("WF_XGB_THREADS", "4")),
        "seed": 42,
        "verbosity": 0,
    }

    model = xgb.train(
        params, dtrain, num_boost_round=num_boost_round,
        evals=[(dval, "val")],
        early_stopping_rounds=50,
        verbose_eval=False,
    )
    return model


def train_lgb_model(X_train, y_train, X_val, y_val, sample_weights=None, num_boost_round: int = 500):
    """Train LightGBM model on given data."""
    import lightgbm as lgb

    n_classes = len(np.unique(y_train))
    dtrain = lgb.Dataset(X_train, label=y_train, weight=sample_weights)
    dval = lgb.Dataset(X_val, label=y_val, reference=dtrain)

    params = {
        "objective": "multiclass",
        "num_class": n_classes,
        "max_depth": 6,
        "learning_rate": 0.05,
        "num_leaves": 63,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_samples": 20,
        "reg_alpha": 0.1,
        "reg_lambda": 1.0,
        "metric": "multi_logloss",
        "num_threads": int(os.getenv("WF_LGB_THREADS", "4")),
        "seed": 42,
        "verbose": -1,
    }

    model = lgb.train(
        params, dtrain, num_boost_round=num_boost_round,
        valid_sets=[dval], valid_names=["val"],
        callbacks=[lgb.early_stopping(50), lgb.log_evaluation(0)],
    )
    return model


def compute_sample_weights(
    y: np.ndarray,
    temporal_decay: float = 0.0,
) -> np.ndarray:
    """Compute sample weights combining class imbalance and temporal decay.

    Args:
        y: Label array.
        temporal_decay: Exponential decay rate for older samples. 0 = no decay.
            Higher values = stronger recency bias (2.0 is a good default).
    """
    n = len(y)
    classes, counts = np.unique(y, return_counts=True)
    n_c = len(classes)
    cw = {c: n / (n_c * cnt) for c, cnt in zip(classes, counts)}
    weights = np.array([cw[label] for label in y], dtype=np.float32)

    # Temporal decay: exponentially downweight older samples
    if temporal_decay > 0:
        positions = np.arange(n, dtype=np.float32) / max(n - 1, 1)  # 0..1
        decay = np.exp(-temporal_decay * (1.0 - positions))  # newest=1, oldest=exp(-rate)
        weights *= decay

    return weights


def predict_xgb(model, X):
    """Predict probabilities with XGBoost."""
    import xgboost as xgb
    dmat = xgb.DMatrix(X)
    return model.predict(dmat)


def predict_lgb(model, X):
    """Predict probabilities with LightGBM."""
    probs = np.array(model.predict(X))
    if probs.ndim == 1:
        n_classes = 3
        probs = probs.reshape(-1, n_classes)
    return probs


class WalkForwardStrategy:
    """Hold-biased strategy with cooldown re-entry.

    Starts invested (like B&H). Exits on SELL signals. Re-enters either on
    BUY signal or automatically after a cooldown period (whichever comes first).
    Goal: dodge short-term dips while staying invested long-term.
    """

    def __init__(self, predictions, confidences, config):
        self._preds = predictions
        self._confs = confidences
        self._sell_conf_threshold = config.get("sell_confidence_threshold", 0.45)
        self._buy_conf_threshold = config.get("buy_confidence_threshold", 0.5)
        self._stop_loss_pct = config.get("stop_loss_pct", 15.0)
        self._position_pct = config.get("position_size", 0.8)
        self._cooldown_bars = config.get("cooldown_bars", 12)  # Auto re-enter after N bars
        self._in_position = False
        self._entry_price = 0.0
        self._entered_initial = False
        self._bars_since_exit = 0

    def __call__(self, df, i, params=None):
        row = df.iloc[i]
        close = row["close"]

        # Enter immediately on first bar (hold-biased)
        if not self._entered_initial:
            self._entered_initial = True
            self._in_position = True
            self._entry_price = close
            return {"action": "buy", "fraction": self._position_pct}

        # If in position: check for exit
        if self._in_position:
            pnl_pct = (close - self._entry_price) / self._entry_price * 100
            # Stop loss
            if pnl_pct <= -self._stop_loss_pct:
                self._in_position = False
                self._bars_since_exit = 0
                return {"action": "sell", "fraction": 1.0}
            # SELL signal from model
            if i in self._preds and self._preds[i] == 2:
                conf = self._confs.get(i, 0)
                if conf >= self._sell_conf_threshold:
                    self._in_position = False
                    self._bars_since_exit = 0
                    return {"action": "sell", "fraction": 1.0}

        # If out of position: re-enter on BUY signal or after cooldown
        if not self._in_position:
            self._bars_since_exit += 1

            # Re-enter on explicit BUY signal (immediate)
            if i in self._preds:
                pred = self._preds[i]
                conf = self._confs.get(i, 0)
                if pred == 1 and conf >= self._buy_conf_threshold:
                    self._in_position = True
                    self._entry_price = close
                    return {"action": "buy", "fraction": self._position_pct}

            # Auto re-enter after cooldown (don't miss prolonged rallies)
            if self._bars_since_exit >= self._cooldown_bars:
                # Don't re-enter if model is still screaming SELL
                if i in self._preds and self._preds[i] == 2:
                    conf = self._confs.get(i, 0)
                    if conf >= self._sell_conf_threshold:
                        return {"action": "hold"}
                self._in_position = True
                self._entry_price = close
                return {"action": "buy", "fraction": self._position_pct}

        return {"action": "hold"}


def run_walkforward_asset(
    asset: str,
    start_date: str,
    end_date: str,
    capital: float,
    n_splits: int = 5,
    max_train_folds: int = 0,
    temporal_decay: float = 0.0,
    xgb_rounds: int = 500,
    lgb_rounds: int = 500,
    progress_callback=None,
    should_cancel=None,
) -> dict:
    """Run walk-forward backtest for a single asset.

    Splits data into n_splits folds chronologically. For each fold k >= 1,
    trains on recent folds and tests on fold k.
    Stitches OOS predictions from all test periods.

    Args:
        max_train_folds: Max number of folds to include in training window.
            0 = expanding (use all prior folds). >0 = sliding window.
        temporal_decay: Exponential decay rate for older samples. 0 = disabled.
    """
    db_file, symbol = ASSET_DB[asset]
    db_path = str(PROJECT_ROOT / db_file)

    df = load_data(db_path, "minute240", start_date, end_date, exchange="binance")
    if df.empty:
        print(f"  WARNING: No data for {asset}", flush=True)
        return {}
    if should_cancel and should_cancel():
        raise RuntimeError(f"Walk-forward cancelled before feature prep ({asset})")

    # Compute tree_60 features
    features_df = compute_tree60_features(df)
    valid_mask = features_df.notna().all(axis=1)
    valid_indices = features_df[valid_mask].index

    X_all = features_df.loc[valid_indices].values
    # Compute labels using forward returns
    from core.mlp_labeling import compute_labels
    labels = compute_labels(df, bwin=3, fwin=1, alpha=0.038, beta=0.24)
    y_all = labels.loc[valid_indices].values

    n_total = len(X_all)
    fold_size = n_total // n_splits

    window_mode = f"sliding (max {max_train_folds} folds)" if max_train_folds > 0 else "expanding"
    print(f"\n  {asset}: {n_total} samples, {n_splits} folds ({fold_size} each), "
          f"window={window_mode}, decay={temporal_decay}", flush=True)
    if progress_callback:
        progress_callback(0.1)

    all_oos_preds = {}  # df_idx -> prediction
    all_oos_confs = {}  # df_idx -> confidence

    for fold in range(1, n_splits):
        if should_cancel and should_cancel():
            raise RuntimeError(f"Walk-forward cancelled at fold {fold}/{n_splits - 1} ({asset})")
        fold_start = time.monotonic()
        train_end = fold * fold_size
        test_end = min((fold + 1) * fold_size, n_total)

        # Sliding window: limit training start to most recent N folds
        if max_train_folds > 0 and fold > max_train_folds:
            train_start = (fold - max_train_folds) * fold_size
        else:
            train_start = 0

        # Validation set from end of training period
        gap = 1  # gap for label leakage prevention
        val_size = max(int(fold_size * 0.2), 50)
        val_start = train_end - gap - val_size
        train_actual_end = val_start - gap

        if train_actual_end <= train_start + fold_size // 2:
            continue

        X_train = X_all[train_start:train_actual_end]
        y_train = y_all[train_start:train_actual_end]
        X_val = X_all[val_start:train_end - gap]
        y_val = y_all[val_start:train_end - gap]
        X_test = X_all[train_end:test_end]
        y_test = y_all[train_end:test_end]

        if len(X_test) == 0 or len(X_val) == 0:
            continue

        # Class distribution diagnostic
        classes, counts = np.unique(y_train, return_counts=True)
        dist = {int(c): int(cnt) for c, cnt in zip(classes, counts)}
        buy_pct = dist.get(1, 0) / len(y_train) * 100
        hold_buy_ratio = dist.get(0, 0) / max(dist.get(1, 1), 1)

        sw = compute_sample_weights(y_train, temporal_decay=temporal_decay)

        # Train XGB + LGB ensemble
        xgb_model = train_xgb_model(X_train, y_train, X_val, y_val, sw, num_boost_round=xgb_rounds)
        lgb_model = train_lgb_model(X_train, y_train, X_val, y_val, sw, num_boost_round=lgb_rounds)

        # Predict on test fold
        xgb_probs = predict_xgb(xgb_model, X_test)
        lgb_probs = predict_lgb(lgb_model, X_test)

        # Equal-weight ensemble
        avg_probs = 0.5 * xgb_probs + 0.5 * lgb_probs
        preds = avg_probs.argmax(axis=1)
        confs = avg_probs[np.arange(len(preds)), preds]

        # Map back to DataFrame indices
        test_df_indices = valid_indices[train_end:test_end]
        for df_idx, pred, conf in zip(test_df_indices, preds, confs):
            iloc_pos = df.index.get_loc(df_idx)
            all_oos_preds[iloc_pos] = int(pred)
            all_oos_confs[iloc_pos] = float(conf)

        from sklearn.metrics import accuracy_score
        acc = accuracy_score(y_test, preds)
        buy_count = (preds == 1).sum()
        buy_mask = preds == 1
        buy_confs = confs[buy_mask] if buy_mask.any() else np.array([])
        conf_str = f", BUY conf=[{buy_confs.min():.3f}-{buy_confs.max():.3f}]" if len(buy_confs) > 0 else ""
        print(f"    Fold {fold}: train={len(X_train)} (BUY={buy_pct:.1f}%, ratio={hold_buy_ratio:.0f}:1), "
              f"test={len(X_test)}, acc={acc:.3f}, BUY={buy_count}{conf_str}, "
              f"elapsed={time.monotonic() - fold_start:.1f}s", flush=True)
        if progress_callback:
            progress_callback(0.1 + (fold / max(1, n_splits - 1)) * 0.7)

    if not all_oos_preds:
        print(f"  WARNING: No OOS predictions for {asset}", flush=True)
        return {}

    total_buy = sum(1 for v in all_oos_preds.values() if v == 1)
    total_sell = sum(1 for v in all_oos_preds.values() if v == 2)
    print(f"  Total OOS: {len(all_oos_preds)} preds, BUY={total_buy}, SELL={total_sell}", flush=True)
    if progress_callback:
        progress_callback(0.85)
    if should_cancel and should_cancel():
        raise RuntimeError(f"Walk-forward cancelled before backtest run ({asset})")

    # Run backtest with stitched predictions
    strategy = WalkForwardStrategy(all_oos_preds, all_oos_confs, {
        "buy_confidence_threshold": 0.5,
        "sell_confidence_threshold": 0.45,
        "stop_loss_pct": 15.0,
        "position_size": 0.8,
        "cooldown_bars": 12,  # Auto re-enter after 12 bars (2 days on 4H)
    })

    bt = Backtester(initial_capital=capital, fee_rate=0.001, slippage=0.0002)
    results = bt.run(df, strategy, {})
    metrics = compute_metrics(results.get("equity_curve"), timeframe="minute240")
    metrics["num_trades"] = len(bt.trades)
    if progress_callback:
        progress_callback(1.0)

    return {
        "results": results,
        "metrics": metrics,
        "equity_curve": results.get("equity_curve"),
    }


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Backtest")
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL"],
                        choices=list(ASSET_DB.keys()))
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2026-02-01")
    parser.add_argument("--n-splits", type=int, default=5)
    parser.add_argument("--by-year", action="store_true")
    parser.add_argument("--max-train-folds", type=int, default=0,
                        help="Max folds in training window (0=expanding, >0=sliding)")
    parser.add_argument("--temporal-decay", type=float, default=0.0,
                        help="Exponential decay rate for older samples (0=off, 2.0=recommended)")
    args = parser.parse_args()

    window_desc = f"sliding (max {args.max_train_folds})" if args.max_train_folds > 0 else "expanding"
    decay_desc = f", decay={args.temporal_decay}" if args.temporal_decay > 0 else ""

    print("=" * 85)
    print(f"  WALK-FORWARD VALIDATION BACKTEST (Tree tree_60, {window_desc}{decay_desc})")
    print(f"  Splits: {args.n_splits}, Period: {args.start_date} to {args.end_date}")
    print("=" * 85)

    all_results = {}
    for asset in args.assets:
        all_results[asset] = run_walkforward_asset(
            asset, args.start_date, args.end_date,
            args.capital, args.n_splits,
            max_train_folds=args.max_train_folds,
            temporal_decay=args.temporal_decay,
        )

    # Print results table
    print("\n")
    print("=" * 70)
    print("  WALK-FORWARD RESULTS (tree_60 XGB+LGB ensemble)")
    print("=" * 70)

    header = f"{'Asset':<8} {'Return':>10} {'MDD':>10} {'Sharpe':>10} {'Calmar':>10} {'Trades':>8}"
    print(header)
    print("-" * 70)

    total_return = 0.0
    n_valid = 0

    for asset in args.assets:
        m = all_results.get(asset, {}).get("metrics", {})
        if not m:
            print(f"{asset:<8} {'SKIPPED'}")
            continue

        ret = m.get("total_return", 0)
        mdd = m.get("mdd", 0)
        sharpe = m.get("sharpe", 0)
        calmar = abs(ret / mdd) if mdd != 0 else 0
        trades = m.get("num_trades", 0)

        print(f"{asset:<8} {ret:>+9.1f}% {mdd:>9.1f}% {sharpe:>10.2f} {calmar:>9.2f}x {trades:>8}")

        total_return += ret
        n_valid += 1

    if n_valid > 0:
        print("-" * 70)
        print(f"{'AVG':<8} {total_return/n_valid:>+9.1f}%")

    # Per-year breakdown
    if args.by_year:
        for asset in args.assets:
            eq = all_results.get(asset, {}).get("equity_curve")
            if eq is not None and not eq.empty:
                print(f"\n--- {asset} Walk-Forward Per-Year ---")
                print_yearly_table(eq)


if __name__ == "__main__":
    main()
