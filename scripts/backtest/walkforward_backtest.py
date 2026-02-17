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

# Default risk/re-entry settings aligned with dashboard walk-forward runs.
WF_TREE60_ASSET_DEFAULTS = {
    "BTC": {
        "cooldown_reentry_enabled": True,
        "cooldown_reentry_requires_buy": True,
        "min_bars_after_risk_exit": 24,
        "trailing_drawdown_exit_pct": 10.0,
        "reentry_trend_filter_enabled": True,
        "reentry_ema_span": 50,
        "reentry_require_ema_rising": True,
        "staged_reentry_enabled": True,
        "reentry_stage1_fraction": 0.55,
        "reentry_stage2_fraction": 0.8,
        "stage2_confirm_bars": 6,
        "stage2_trigger_pct": 0.8,
    },
    "ETH": {
        "cooldown_reentry_enabled": True,
        "cooldown_reentry_requires_buy": True,
        "min_bars_after_risk_exit": 24,
        "trailing_drawdown_exit_pct": 10.0,
        "reentry_trend_filter_enabled": True,
        "reentry_ema_span": 50,
        "reentry_require_ema_rising": True,
        "staged_reentry_enabled": True,
        "reentry_stage1_fraction": 0.55,
        "reentry_stage2_fraction": 0.8,
        "stage2_confirm_bars": 6,
        "stage2_trigger_pct": 0.8,
    },
    # Keep SOL conservative until dedicated tuning is completed.
    "SOL": {
        "cooldown_reentry_enabled": True,
        "cooldown_reentry_requires_buy": True,
        "min_bars_after_risk_exit": 24,
        "trailing_drawdown_exit_pct": 12.0,
        "reentry_trend_filter_enabled": False,
        "reentry_ema_span": 50,
        "reentry_require_ema_rising": True,
        "staged_reentry_enabled": False,
        "reentry_stage1_fraction": 0.45,
        "reentry_stage2_fraction": 0.8,
        "stage2_confirm_bars": 6,
        "stage2_trigger_pct": 1.5,
    },
}


def get_wf_tree60_asset_defaults(asset: str) -> dict:
    """Return per-asset walk-forward default params."""
    return dict(WF_TREE60_ASSET_DEFAULTS.get(asset, WF_TREE60_ASSET_DEFAULTS["BTC"]))


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
        self._trailing_drawdown_exit_pct = float(config.get("trailing_drawdown_exit_pct", 12.0))
        self._position_pct = config.get("position_size", 0.8)
        self._cooldown_bars = config.get("cooldown_bars", 12)  # Auto re-enter after N bars
        self._cooldown_reentry_enabled = bool(config.get("cooldown_reentry_enabled", True))
        self._cooldown_reentry_requires_buy = bool(config.get("cooldown_reentry_requires_buy", True))
        self._min_bars_after_risk_exit = int(config.get("min_bars_after_risk_exit", 24))
        self._reentry_trend_filter_enabled = bool(config.get("reentry_trend_filter_enabled", False))
        self._reentry_ema_span = int(config.get("reentry_ema_span", 50))
        self._reentry_require_ema_rising = bool(config.get("reentry_require_ema_rising", True))
        self._staged_reentry_enabled = bool(config.get("staged_reentry_enabled", False))
        self._reentry_stage1_fraction = float(config.get("reentry_stage1_fraction", 0.45))
        self._reentry_stage2_fraction = float(config.get("reentry_stage2_fraction", 0.8))
        self._stage2_confirm_bars = int(config.get("stage2_confirm_bars", 6))
        self._stage2_trigger_pct = float(config.get("stage2_trigger_pct", 1.5))
        self._in_position = False
        self._entry_price = 0.0
        self._high_water_mark = 0.0
        self._entered_initial = False
        self._bars_since_exit = 0
        self._last_exit_was_risk = False
        self._current_fraction = 0.0
        self._pending_scale_in = False
        self._scale_target_fraction = 0.0
        self._bars_since_reentry = 0
        self._ema_cache = None

    def __call__(self, df, i, params=None):
        row = df.iloc[i]
        close = row["close"]
        ema_value, ema_prev = self._get_reentry_ema(df, i)

        if not self._entered_initial:
            return self._initial_entry_signal(close)

        if self._in_position:
            signal = self._in_position_signal(i, close, ema_value, ema_prev)
            if signal is not None:
                return signal

        if not self._in_position:
            signal = self._out_of_position_signal(i, close, ema_value, ema_prev)
            if signal is not None:
                return signal

        return {"action": "hold"}

    def _initial_entry_signal(self, close):
        self._entered_initial = True
        self._in_position = True
        self._entry_price = close
        self._high_water_mark = close
        self._last_exit_was_risk = False
        self._current_fraction = self._position_pct
        self._pending_scale_in = False
        self._scale_target_fraction = self._position_pct
        self._bars_since_reentry = 0
        return {"action": "buy", "fraction": self._position_pct, "reason": "initial_entry"}

    def _in_position_signal(self, i, close, ema_value, ema_prev):
        self._bars_since_reentry += 1
        self._high_water_mark = max(self._high_water_mark, close)
        pnl_pct = (close - self._entry_price) / self._entry_price * 100
        dd_from_hwm_pct = ((close / self._high_water_mark) - 1.0) * 100 if self._high_water_mark > 0 else 0.0

        stage2_signal = self._stage2_scale_in_signal(close, ema_value, ema_prev)
        if stage2_signal is not None:
            return stage2_signal

        risk_signal = self._risk_exit_signal(pnl_pct, dd_from_hwm_pct)
        if risk_signal is not None:
            return risk_signal

        return self._model_sell_exit_signal(i)

    def _stage2_scale_in_signal(self, close, ema_value, ema_prev):
        if not self._pending_scale_in or self._current_fraction >= self._scale_target_fraction:
            return None
        if self._bars_since_reentry < self._stage2_confirm_bars:
            return None
        gain_from_reentry = ((close / self._entry_price) - 1.0) * 100 if self._entry_price > 0 else 0.0
        if gain_from_reentry < self._stage2_trigger_pct:
            return None
        if not self._passes_reentry_trend_filter(close, ema_value, ema_prev):
            return None
        add_fraction = self._compute_scale_in_fraction()
        if add_fraction <= 0:
            return None
        self._current_fraction = self._scale_target_fraction
        self._pending_scale_in = False
        return {
            "action": "buy",
            "fraction": add_fraction,
            "reason": (
                f"scale_in_stage2: gain={gain_from_reentry:.2f}% >= "
                f"{self._stage2_trigger_pct:.2f}%"
            ),
        }

    def _set_exited_state(self, risk_exit):
        self._in_position = False
        self._bars_since_exit = 0
        self._last_exit_was_risk = bool(risk_exit)
        self._pending_scale_in = False
        self._scale_target_fraction = 0.0
        self._current_fraction = 0.0

    def _risk_exit_signal(self, pnl_pct, dd_from_hwm_pct):
        if self._trailing_drawdown_exit_pct > 0 and dd_from_hwm_pct <= -self._trailing_drawdown_exit_pct:
            self._set_exited_state(risk_exit=True)
            return {
                "action": "sell",
                "fraction": 1.0,
                "reason": (
                    f"trailing_dd_exit: dd={dd_from_hwm_pct:.2f}% <= "
                    f"-{self._trailing_drawdown_exit_pct:.2f}%"
                ),
            }
        if pnl_pct <= -self._stop_loss_pct:
            self._set_exited_state(risk_exit=True)
            return {
                "action": "sell",
                "fraction": 1.0,
                "reason": f"stop_loss: pnl={pnl_pct:.2f}% <= -{self._stop_loss_pct:.2f}%",
            }
        return None

    def _model_sell_exit_signal(self, i):
        if i not in self._preds or self._preds[i] != 2:
            return None
        conf = self._confs.get(i, 0)
        if conf < self._sell_conf_threshold:
            return None
        self._set_exited_state(risk_exit=False)
        return {
            "action": "sell",
            "fraction": 1.0,
            "reason": f"model_sell: conf={conf:.3f} >= {self._sell_conf_threshold:.2f}",
        }

    def _out_of_position_signal(self, i, close, ema_value, ema_prev):
        self._bars_since_exit += 1
        model_buy = self._model_buy_reentry_signal(i, close, ema_value, ema_prev)
        if model_buy is not None:
            return model_buy
        return self._cooldown_reentry_signal(i, close, ema_value, ema_prev)

    def _model_buy_reentry_signal(self, i, close, ema_value, ema_prev):
        if i not in self._preds:
            return None
        pred = self._preds[i]
        conf = self._confs.get(i, 0)
        if pred != 1 or conf < self._buy_conf_threshold:
            return None
        if not self._passes_reentry_trend_filter(close, ema_value, ema_prev):
            return {"action": "hold", "reason": "model_buy_blocked_by_trend_filter"}
        return self._build_reentry_signal(
            close=close,
            reason=f"model_buy: conf={conf:.3f} >= {self._buy_conf_threshold:.2f}",
        )

    def _cooldown_reentry_signal(self, i, close, ema_value, ema_prev):
        if not self._cooldown_reentry_enabled or self._bars_since_exit < self._cooldown_bars:
            return None
        if self._last_exit_was_risk and self._bars_since_exit < self._min_bars_after_risk_exit:
            return {
                "action": "hold",
                "reason": (
                    f"risk_reentry_wait: bars={self._bars_since_exit} < "
                    f"{self._min_bars_after_risk_exit}"
                ),
            }
        if i in self._preds and self._preds[i] == 2:
            conf = self._confs.get(i, 0)
            if conf >= self._sell_conf_threshold:
                return {
                    "action": "hold",
                    "reason": f"cooldown_blocked_by_sell: conf={conf:.3f} >= {self._sell_conf_threshold:.2f}",
                }
        if self._cooldown_reentry_requires_buy:
            if i not in self._preds or self._preds[i] != 1:
                return {"action": "hold", "reason": "cooldown_wait_buy_signal"}
            conf = self._confs.get(i, 0)
            if conf < self._buy_conf_threshold:
                return {
                    "action": "hold",
                    "reason": (
                        f"cooldown_wait_buy_conf: conf={conf:.3f} < "
                        f"{self._buy_conf_threshold:.2f}"
                    ),
                }
        if not self._passes_reentry_trend_filter(close, ema_value, ema_prev):
            return {"action": "hold", "reason": "cooldown_blocked_by_trend_filter"}
        return self._build_reentry_signal(
            close=close,
            reason=f"cooldown_reentry: bars={self._cooldown_bars}",
        )

    def _get_reentry_ema(self, df, i):
        if self._ema_cache is None or len(self._ema_cache) != len(df):
            span = max(2, int(self._reentry_ema_span))
            self._ema_cache = df["close"].ewm(span=span, adjust=False).mean().values
        ema_value = float(self._ema_cache[i])
        ema_prev = float(self._ema_cache[i - 1]) if i > 0 else ema_value
        return ema_value, ema_prev

    def _passes_reentry_trend_filter(self, close: float, ema_value: float, ema_prev: float) -> bool:
        if not self._reentry_trend_filter_enabled:
            return True
        if close < ema_value:
            return False
        if self._reentry_require_ema_rising and ema_value <= ema_prev:
            return False
        return True

    def _build_reentry_signal(self, close: float, reason: str):
        self._in_position = True
        self._entry_price = close
        self._high_water_mark = close
        self._last_exit_was_risk = False
        self._bars_since_reentry = 0

        entry_fraction = self._position_pct
        self._pending_scale_in = False
        self._scale_target_fraction = self._position_pct

        if self._staged_reentry_enabled and self._position_pct > 0:
            stage1 = min(max(self._reentry_stage1_fraction, 0.0), self._position_pct)
            stage2 = min(max(self._reentry_stage2_fraction, stage1), self._position_pct)
            if stage2 > stage1 + 1e-9:
                entry_fraction = stage1
                self._pending_scale_in = True
                self._scale_target_fraction = stage2

        self._current_fraction = entry_fraction
        return {
            "action": "buy",
            "fraction": entry_fraction,
            "reason": reason,
        }

    def _compute_scale_in_fraction(self) -> float:
        if self._current_fraction >= 1.0:
            return 0.0
        target = min(max(self._scale_target_fraction, 0.0), 1.0)
        if target <= self._current_fraction + 1e-9:
            return 0.0
        # Backtester fraction applies to remaining cash.
        return (target - self._current_fraction) / max(1.0 - self._current_fraction, 1e-9)


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
    position_size: float = 0.8,
    cooldown_reentry_enabled: bool = True,
    cooldown_reentry_requires_buy: bool = True,
    trailing_drawdown_exit_pct: float = 12.0,
    min_bars_after_risk_exit: int = 24,
    reentry_trend_filter_enabled: bool = False,
    reentry_ema_span: int = 50,
    reentry_require_ema_rising: bool = True,
    staged_reentry_enabled: bool = False,
    reentry_stage1_fraction: float = 0.45,
    reentry_stage2_fraction: float = 0.8,
    stage2_confirm_bars: int = 6,
    stage2_trigger_pct: float = 1.5,
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
    _raise_if_cancelled(should_cancel, f"Walk-forward cancelled before feature prep ({asset})")

    valid_indices, X_all, y_all = _prepare_walkforward_arrays(df)

    n_total = len(X_all)
    fold_size = n_total // n_splits

    _print_walkforward_header(asset, n_total, n_splits, fold_size, max_train_folds, temporal_decay)
    if progress_callback:
        progress_callback(0.1)

    all_oos_preds, all_oos_confs = _collect_oos_predictions(
        asset=asset,
        n_splits=n_splits,
        X_all=X_all,
        y_all=y_all,
        df=df,
        valid_indices=valid_indices,
        fold_size=fold_size,
        n_total=n_total,
        max_train_folds=max_train_folds,
        temporal_decay=temporal_decay,
        xgb_rounds=xgb_rounds,
        lgb_rounds=lgb_rounds,
        progress_callback=progress_callback,
        should_cancel=should_cancel,
    )

    if not all_oos_preds:
        print(f"  WARNING: No OOS predictions for {asset}", flush=True)
        return {}

    total_buy = sum(1 for v in all_oos_preds.values() if v == 1)
    total_sell = sum(1 for v in all_oos_preds.values() if v == 2)
    print(f"  Total OOS: {len(all_oos_preds)} preds, BUY={total_buy}, SELL={total_sell}", flush=True)
    if progress_callback:
        progress_callback(0.85)
    _raise_if_cancelled(should_cancel, f"Walk-forward cancelled before backtest run ({asset})")

    results, metrics = _run_stitched_backtest(
        df=df,
        capital=capital,
        all_oos_preds=all_oos_preds,
        all_oos_confs=all_oos_confs,
        position_size=position_size,
        cooldown_reentry_enabled=cooldown_reentry_enabled,
        cooldown_reentry_requires_buy=cooldown_reentry_requires_buy,
        trailing_drawdown_exit_pct=trailing_drawdown_exit_pct,
        min_bars_after_risk_exit=min_bars_after_risk_exit,
        reentry_trend_filter_enabled=reentry_trend_filter_enabled,
        reentry_ema_span=reentry_ema_span,
        reentry_require_ema_rising=reentry_require_ema_rising,
        staged_reentry_enabled=staged_reentry_enabled,
        reentry_stage1_fraction=reentry_stage1_fraction,
        reentry_stage2_fraction=reentry_stage2_fraction,
        stage2_confirm_bars=stage2_confirm_bars,
        stage2_trigger_pct=stage2_trigger_pct,
    )
    if progress_callback:
        progress_callback(1.0)

    return {
        "results": results,
        "metrics": metrics,
        "equity_curve": results.get("equity_curve"),
    }


def _prepare_walkforward_arrays(df: pd.DataFrame):
    features_df = compute_tree60_features(df)
    valid_mask = features_df.notna().all(axis=1)
    valid_indices = features_df[valid_mask].index
    X_all = features_df.loc[valid_indices].values

    from core.mlp_labeling import compute_labels
    labels = compute_labels(df, bwin=3, fwin=1, alpha=0.038, beta=0.24)
    y_all = labels.loc[valid_indices].values
    return valid_indices, X_all, y_all


def _raise_if_cancelled(should_cancel, message: str) -> None:
    if should_cancel and should_cancel():
        raise RuntimeError(message)


def _print_walkforward_header(
    asset: str,
    n_total: int,
    n_splits: int,
    fold_size: int,
    max_train_folds: int,
    temporal_decay: float,
) -> None:
    window_mode = f"sliding (max {max_train_folds} folds)" if max_train_folds > 0 else "expanding"
    print(
        f"\n  {asset}: {n_total} samples, {n_splits} folds ({fold_size} each), "
        f"window={window_mode}, decay={temporal_decay}",
        flush=True,
    )


def _collect_oos_predictions(
    *,
    asset: str,
    n_splits: int,
    X_all: np.ndarray,
    y_all: np.ndarray,
    df: pd.DataFrame,
    valid_indices,
    fold_size: int,
    n_total: int,
    max_train_folds: int,
    temporal_decay: float,
    xgb_rounds: int,
    lgb_rounds: int,
    progress_callback=None,
    should_cancel=None,
):
    all_oos_preds = {}
    all_oos_confs = {}

    for fold in range(1, n_splits):
        _raise_if_cancelled(
            should_cancel,
            f"Walk-forward cancelled at fold {fold}/{n_splits - 1} ({asset})",
        )
        fold_start = time.monotonic()
        fold_data = _build_fold_data(
            X_all=X_all,
            y_all=y_all,
            fold=fold,
            fold_size=fold_size,
            n_total=n_total,
            max_train_folds=max_train_folds,
        )
        if fold_data is None:
            continue

        fold_out = _run_fold_models(
            fold_data=fold_data,
            temporal_decay=temporal_decay,
            xgb_rounds=xgb_rounds,
            lgb_rounds=lgb_rounds,
        )
        _store_fold_predictions(
            df=df,
            valid_indices=valid_indices,
            train_end=fold_data["train_end"],
            test_end=fold_data["test_end"],
            preds=fold_out["preds"],
            confs=fold_out["confs"],
            all_oos_preds=all_oos_preds,
            all_oos_confs=all_oos_confs,
        )
        _print_fold_summary(
            fold=fold,
            fold_data=fold_data,
            buy_pct=fold_out["buy_pct"],
            hold_buy_ratio=fold_out["hold_buy_ratio"],
            acc=fold_out["acc"],
            buy_count=fold_out["buy_count"],
            buy_conf_range=fold_out["buy_conf_range"],
            elapsed=time.monotonic() - fold_start,
        )
        if progress_callback:
            progress_callback(0.1 + (fold / max(1, n_splits - 1)) * 0.7)

    return all_oos_preds, all_oos_confs


def _build_fold_data(
    *,
    X_all: np.ndarray,
    y_all: np.ndarray,
    fold: int,
    fold_size: int,
    n_total: int,
    max_train_folds: int,
):
    train_end = fold * fold_size
    test_end = min((fold + 1) * fold_size, n_total)
    if max_train_folds > 0 and fold > max_train_folds:
        train_start = (fold - max_train_folds) * fold_size
    else:
        train_start = 0

    gap = 1
    val_size = max(int(fold_size * 0.2), 50)
    val_start = train_end - gap - val_size
    train_actual_end = val_start - gap
    if train_actual_end <= train_start + fold_size // 2:
        return None

    X_train = X_all[train_start:train_actual_end]
    y_train = y_all[train_start:train_actual_end]
    X_val = X_all[val_start:train_end - gap]
    y_val = y_all[val_start:train_end - gap]
    X_test = X_all[train_end:test_end]
    y_test = y_all[train_end:test_end]
    if len(X_test) == 0 or len(X_val) == 0:
        return None

    return {
        "train_end": train_end,
        "test_end": test_end,
        "X_train": X_train,
        "y_train": y_train,
        "X_val": X_val,
        "y_val": y_val,
        "X_test": X_test,
        "y_test": y_test,
    }


def _run_fold_models(
    *,
    fold_data: dict,
    temporal_decay: float,
    xgb_rounds: int,
    lgb_rounds: int,
):
    X_train = fold_data["X_train"]
    y_train = fold_data["y_train"]
    X_val = fold_data["X_val"]
    y_val = fold_data["y_val"]
    X_test = fold_data["X_test"]
    y_test = fold_data["y_test"]

    classes, counts = np.unique(y_train, return_counts=True)
    dist = {int(c): int(cnt) for c, cnt in zip(classes, counts)}
    buy_pct = dist.get(1, 0) / len(y_train) * 100
    hold_buy_ratio = dist.get(0, 0) / max(dist.get(1, 1), 1)

    sw = compute_sample_weights(y_train, temporal_decay=temporal_decay)
    xgb_model = train_xgb_model(X_train, y_train, X_val, y_val, sw, num_boost_round=xgb_rounds)
    lgb_model = train_lgb_model(X_train, y_train, X_val, y_val, sw, num_boost_round=lgb_rounds)

    xgb_probs = predict_xgb(xgb_model, X_test)
    lgb_probs = predict_lgb(lgb_model, X_test)
    avg_probs = 0.5 * xgb_probs + 0.5 * lgb_probs
    preds = avg_probs.argmax(axis=1)
    confs = avg_probs[np.arange(len(preds)), preds]

    from sklearn.metrics import accuracy_score
    acc = accuracy_score(y_test, preds)
    buy_count = int((preds == 1).sum())
    buy_mask = preds == 1
    buy_confs = confs[buy_mask] if buy_mask.any() else np.array([])
    buy_conf_range = None
    if len(buy_confs) > 0:
        buy_conf_range = (float(buy_confs.min()), float(buy_confs.max()))

    return {
        "preds": preds,
        "confs": confs,
        "buy_pct": buy_pct,
        "hold_buy_ratio": hold_buy_ratio,
        "acc": acc,
        "buy_count": buy_count,
        "buy_conf_range": buy_conf_range,
    }


def _store_fold_predictions(
    *,
    df: pd.DataFrame,
    valid_indices,
    train_end: int,
    test_end: int,
    preds,
    confs,
    all_oos_preds: dict,
    all_oos_confs: dict,
):
    test_df_indices = valid_indices[train_end:test_end]
    for df_idx, pred, conf in zip(test_df_indices, preds, confs):
        iloc_pos = df.index.get_loc(df_idx)
        all_oos_preds[iloc_pos] = int(pred)
        all_oos_confs[iloc_pos] = float(conf)


def _print_fold_summary(
    *,
    fold: int,
    fold_data: dict,
    buy_pct: float,
    hold_buy_ratio: float,
    acc: float,
    buy_count: int,
    buy_conf_range,
    elapsed: float,
):
    conf_str = ""
    if buy_conf_range is not None:
        low, high = buy_conf_range
        conf_str = f", BUY conf=[{low:.3f}-{high:.3f}]"
    print(
        f"    Fold {fold}: train={len(fold_data['X_train'])} (BUY={buy_pct:.1f}%, ratio={hold_buy_ratio:.0f}:1), "
        f"test={len(fold_data['X_test'])}, acc={acc:.3f}, BUY={buy_count}{conf_str}, "
        f"elapsed={elapsed:.1f}s",
        flush=True,
    )


def _build_walkforward_strategy_config(
    *,
    position_size: float,
    cooldown_reentry_enabled: bool,
    cooldown_reentry_requires_buy: bool,
    trailing_drawdown_exit_pct: float,
    min_bars_after_risk_exit: int,
    reentry_trend_filter_enabled: bool,
    reentry_ema_span: int,
    reentry_require_ema_rising: bool,
    staged_reentry_enabled: bool,
    reentry_stage1_fraction: float,
    reentry_stage2_fraction: float,
    stage2_confirm_bars: int,
    stage2_trigger_pct: float,
) -> dict:
    return {
        "buy_confidence_threshold": 0.5,
        "sell_confidence_threshold": 0.45,
        "stop_loss_pct": 15.0,
        "trailing_drawdown_exit_pct": trailing_drawdown_exit_pct,
        "position_size": position_size,
        "cooldown_bars": 12,  # Auto re-enter after 12 bars (2 days on 4H)
        "cooldown_reentry_enabled": cooldown_reentry_enabled,
        "cooldown_reentry_requires_buy": cooldown_reentry_requires_buy,
        "min_bars_after_risk_exit": min_bars_after_risk_exit,
        "reentry_trend_filter_enabled": reentry_trend_filter_enabled,
        "reentry_ema_span": reentry_ema_span,
        "reentry_require_ema_rising": reentry_require_ema_rising,
        "staged_reentry_enabled": staged_reentry_enabled,
        "reentry_stage1_fraction": reentry_stage1_fraction,
        "reentry_stage2_fraction": reentry_stage2_fraction,
        "stage2_confirm_bars": stage2_confirm_bars,
        "stage2_trigger_pct": stage2_trigger_pct,
    }


def _run_stitched_backtest(
    *,
    df: pd.DataFrame,
    capital: float,
    all_oos_preds: dict,
    all_oos_confs: dict,
    position_size: float,
    cooldown_reentry_enabled: bool,
    cooldown_reentry_requires_buy: bool,
    trailing_drawdown_exit_pct: float,
    min_bars_after_risk_exit: int,
    reentry_trend_filter_enabled: bool,
    reentry_ema_span: int,
    reentry_require_ema_rising: bool,
    staged_reentry_enabled: bool,
    reentry_stage1_fraction: float,
    reentry_stage2_fraction: float,
    stage2_confirm_bars: int,
    stage2_trigger_pct: float,
):
    strategy = WalkForwardStrategy(
        all_oos_preds,
        all_oos_confs,
        _build_walkforward_strategy_config(
            position_size=position_size,
            cooldown_reentry_enabled=cooldown_reentry_enabled,
            cooldown_reentry_requires_buy=cooldown_reentry_requires_buy,
            trailing_drawdown_exit_pct=trailing_drawdown_exit_pct,
            min_bars_after_risk_exit=min_bars_after_risk_exit,
            reentry_trend_filter_enabled=reentry_trend_filter_enabled,
            reentry_ema_span=reentry_ema_span,
            reentry_require_ema_rising=reentry_require_ema_rising,
            staged_reentry_enabled=staged_reentry_enabled,
            reentry_stage1_fraction=reentry_stage1_fraction,
            reentry_stage2_fraction=reentry_stage2_fraction,
            stage2_confirm_bars=stage2_confirm_bars,
            stage2_trigger_pct=stage2_trigger_pct,
        ),
    )
    bt = Backtester(initial_capital=capital, fee_rate=0.001, slippage=0.0002)
    results = bt.run(df, strategy, {})
    metrics = compute_metrics(results.get("equity_curve"), timeframe="minute240")
    metrics["num_trades"] = len(bt.trades)
    return results, metrics


def main():
    parser = argparse.ArgumentParser(description="Walk-Forward Backtest")
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH", "SOL"],
                        choices=list(ASSET_DB.keys()))
    parser.add_argument("--capital", type=float, default=10_000)
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument("--end-date", default="2026-02-01")
    parser.add_argument("--n-splits", type=int, default=7)
    parser.add_argument("--by-year", action="store_true")
    parser.add_argument("--max-train-folds", type=int, default=3,
                        help="Max folds in training window (0=expanding, >0=sliding, default=3)")
    parser.add_argument("--temporal-decay", type=float, default=2.0,
                        help="Exponential decay rate for older samples (0=off, default=2.0)")
    args = parser.parse_args()

    window_desc = f"sliding (max {args.max_train_folds})" if args.max_train_folds > 0 else "expanding"
    decay_desc = f", decay={args.temporal_decay}" if args.temporal_decay > 0 else ""

    print("=" * 85)
    print(f"  WALK-FORWARD VALIDATION BACKTEST (Tree tree_60, {window_desc}{decay_desc})")
    print(f"  Splits: {args.n_splits}, Period: {args.start_date} to {args.end_date}")
    print("=" * 85)

    all_results = {}
    for asset in args.assets:
        asset_defaults = get_wf_tree60_asset_defaults(asset)
        all_results[asset] = run_walkforward_asset(
            asset, args.start_date, args.end_date,
            args.capital, args.n_splits,
            max_train_folds=args.max_train_folds,
            temporal_decay=args.temporal_decay,
            cooldown_reentry_enabled=asset_defaults["cooldown_reentry_enabled"],
            cooldown_reentry_requires_buy=asset_defaults["cooldown_reentry_requires_buy"],
            trailing_drawdown_exit_pct=asset_defaults["trailing_drawdown_exit_pct"],
            min_bars_after_risk_exit=asset_defaults["min_bars_after_risk_exit"],
            reentry_trend_filter_enabled=asset_defaults["reentry_trend_filter_enabled"],
            reentry_ema_span=asset_defaults["reentry_ema_span"],
            reentry_require_ema_rising=asset_defaults["reentry_require_ema_rising"],
            staged_reentry_enabled=asset_defaults["staged_reentry_enabled"],
            reentry_stage1_fraction=asset_defaults["reentry_stage1_fraction"],
            reentry_stage2_fraction=asset_defaults["reentry_stage2_fraction"],
            stage2_confirm_bars=asset_defaults["stage2_confirm_bars"],
            stage2_trigger_pct=asset_defaults["stage2_trigger_pct"],
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
