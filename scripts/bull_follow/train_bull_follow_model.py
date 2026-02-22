#!/usr/bin/env python3
"""Train and backtest cross-asset bull-follow model.

Pipeline:
1) Load per-symbol spot OHLCV CSV files.
2) Build technical + cross-sectional features.
3) Train a pooled cross-asset model for forward return ranking.
4) Run top-K long-only portfolio backtest with risk-on gate.
5) Compare against equal-weight buy-and-hold benchmark.
"""

from __future__ import annotations

import argparse
import json
import math
import pickle
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, r2_score

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from trading.indicators.bull_follow_features import (  # noqa: E402
    BULL_FOLLOW_FEATURE_COLUMNS,
    LIQUIDITY_FEATURE_COLUMNS,
    BullFollowTargetConfig,
    prepare_universe_features,
)


DEFAULT_DATA_DIR = PROJECT_ROOT / "data" / "universe_backtest_4h"
DEFAULT_MODEL_DIR = PROJECT_ROOT / "models" / "bull_follow" / "v1"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports"
DEFAULT_EXCLUDED_SYMBOLS = ("BTC", "ETH", "BNB")


@dataclass(frozen=True)
class TrainConfig:
    start_date: str
    end_date: str
    train_end_date: str | None
    timeframe: str
    top_k: int
    min_score: float
    min_adx: float
    breakout_floor: float
    risk_on_breadth: float
    fee_rate: float
    slippage: float
    horizon_bars: int
    min_history: int
    random_state: int
    weighting_mode: str
    max_symbol_weight: float
    atr_vol_floor: float
    atr_vol_cap: float
    crash_guard_enabled: bool
    crash_ret3_threshold: float
    crash_breadth_threshold: float
    score_power: float
    trend_weight: float
    vol_penalty_power: float
    full_deploy_on_signal: bool
    score_quantile: float
    breadth_adaptive_enabled: bool
    min_score_breadth_coef: float
    min_score_floor: float
    top_k_breadth_boost: float
    top_k_max: int
    symbol_quality_filter_enabled: bool
    symbol_quality_ema_alpha: float
    symbol_quality_min_ema: float
    symbol_quality_min_obs: int
    regime_weak_guard_enabled: bool
    regime_breadth_drop_threshold: float
    regime_cs_ret1_threshold: float


@dataclass
class PortfolioMetrics:
    total_return_pct: float
    mdd_pct: float
    cagr_pct: float
    sharpe: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train and backtest bull-follow model")
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--timeframe", default="minute240")
    parser.add_argument(
        "--symbols", nargs="+", default=None, help="Optional symbol whitelist"
    )
    parser.add_argument(
        "--exclude-symbols",
        nargs="+",
        default=list(DEFAULT_EXCLUDED_SYMBOLS),
        help="Symbols excluded from universe (default keeps base MLP majors unchanged)",
    )
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument(
        "--end-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--train-end-date", default="2024-12-31")
    parser.add_argument("--top-k", type=int, default=8)
    parser.add_argument("--min-score", type=float, default=0.004)
    parser.add_argument("--min-adx", type=float, default=10.0)
    parser.add_argument("--breakout-floor", type=float, default=-0.01)
    parser.add_argument("--risk-on-breadth", type=float, default=0.45)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0002)
    parser.add_argument("--horizon-bars", type=int, default=1)
    parser.add_argument("--min-history", type=int, default=240)
    parser.add_argument(
        "--weighting-mode",
        choices=("equal", "inv_vol", "trend_score", "trend_score_inv_vol"),
        default="trend_score_inv_vol",
        help="Portfolio weighting mode",
    )
    parser.add_argument(
        "--max-symbol-weight",
        type=float,
        default=0.75,
        help="Per-symbol max exposure weight cap.",
    )
    parser.add_argument(
        "--atr-vol-floor",
        type=float,
        default=0.01,
        help="Lower ATR%% clip for inverse-vol weighting.",
    )
    parser.add_argument(
        "--atr-vol-cap",
        type=float,
        default=0.12,
        help="Upper ATR%% clip for inverse-vol weighting.",
    )
    parser.add_argument(
        "--crash-ret3-threshold",
        type=float,
        default=-0.06,
        help="Crash guard trigger on cross-sectional 3-bar median return.",
    )
    parser.add_argument(
        "--crash-breadth-threshold",
        type=float,
        default=0.35,
        help="Crash guard trigger on breadth (above EMA50 ratio).",
    )
    parser.add_argument(
        "--no-crash-guard",
        action="store_true",
        help="Disable crash guard liquidation gate.",
    )
    parser.add_argument(
        "--score-power",
        type=float,
        default=2.5,
        help="Concentration power applied to trend score weights.",
    )
    parser.add_argument(
        "--trend-weight",
        type=float,
        default=1.5,
        help="Weight multiplier for technical trend-strength term.",
    )
    parser.add_argument(
        "--vol-penalty-power",
        type=float,
        default=0.5,
        help="Volatility penalty power used in *_inv_vol weighting modes.",
    )
    parser.add_argument(
        "--no-full-deploy-on-signal",
        action="store_true",
        help="When set, keep residual cash instead of fully normalizing weights.",
    )
    parser.add_argument(
        "--score-quantile",
        type=float,
        default=0.0,
        help="Cross-sectional quantile gate on pred_score (0 disables).",
    )
    parser.add_argument(
        "--enable-breadth-adaptive",
        action="store_true",
        help="Enable breadth-adaptive min_score/top_k expansion in strong trend breadth.",
    )
    parser.add_argument(
        "--no-breadth-adaptive",
        action="store_true",
        help=argparse.SUPPRESS,
    )
    parser.add_argument(
        "--min-score-breadth-coef",
        type=float,
        default=0.004,
        help="Min-score relaxation coefficient when breadth exceeds risk_on_breadth.",
    )
    parser.add_argument(
        "--min-score-floor",
        type=float,
        default=0.003,
        help="Lower bound for adaptive min_score.",
    )
    parser.add_argument(
        "--top-k-breadth-boost",
        type=float,
        default=0.5,
        help="Additional top_k scaling factor by breadth delta.",
    )
    parser.add_argument(
        "--top-k-max",
        type=int,
        default=10,
        help="Upper bound of adaptive top_k.",
    )
    parser.add_argument(
        "--enable-symbol-quality-filter",
        action="store_true",
        help="Block symbols with persistently weak realized return EMA.",
    )
    parser.add_argument(
        "--symbol-quality-ema-alpha",
        type=float,
        default=0.35,
        help="EMA alpha for per-symbol realized return quality score.",
    )
    parser.add_argument(
        "--symbol-quality-min-ema",
        type=float,
        default=-0.006,
        help="Minimum symbol quality EMA required once enough observations exist.",
    )
    parser.add_argument(
        "--symbol-quality-min-obs",
        type=int,
        default=4,
        help="Minimum realized observations before applying symbol-quality filter.",
    )
    parser.add_argument(
        "--enable-regime-weak-guard",
        action="store_true",
        help="Block new entries when breadth drops sharply and cs_ret_1 is weak.",
    )
    parser.add_argument(
        "--regime-breadth-drop-threshold",
        type=float,
        default=0.08,
        help="Breadth drop threshold (absolute) to trigger regime weak guard.",
    )
    parser.add_argument(
        "--regime-cs-ret1-threshold",
        type=float,
        default=-0.01,
        help="cs_ret_1_median threshold to trigger regime weak guard.",
    )
    parser.add_argument(
        "--target-mode",
        choices=("forward", "excess", "pnl"),
        default="forward",
        help="Training target: forward return / excess return / pnl utility",
    )
    parser.add_argument(
        "--feature-profile",
        choices=("base", "liquidity"),
        default="base",
        help="Feature set profile to train on",
    )
    parser.add_argument(
        "--pnl-downside-penalty",
        type=float,
        default=1.0,
        help="Penalty multiplier on forward-window downside drawdown for pnl target",
    )
    parser.add_argument(
        "--pnl-fee-buffer",
        type=float,
        default=0.0012,
        help="Cost buffer subtracted from forward return for pnl target",
    )
    parser.add_argument("--random-state", type=int, default=42)
    parser.add_argument("--model-dir", default=str(DEFAULT_MODEL_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument(
        "--max-symbols", type=int, default=0, help="Limit symbols for quick iteration"
    )
    return parser.parse_args()


def resolve_feature_columns(feature_profile: str) -> list[str]:
    if feature_profile == "base":
        return list(BULL_FOLLOW_FEATURE_COLUMNS)
    if feature_profile == "liquidity":
        return list(BULL_FOLLOW_FEATURE_COLUMNS) + list(LIQUIDITY_FEATURE_COLUMNS)
    raise ValueError(f"Unknown feature profile: {feature_profile}")


def resolve_target_column(target_mode: str) -> str:
    if target_mode == "forward":
        return "target_forward_return"
    if target_mode == "excess":
        return "target_forward_excess_return"
    if target_mode == "pnl":
        return "target_forward_pnl_utility"
    raise ValueError(f"Unknown target mode: {target_mode}")


def discover_symbols(data_dir: Path, timeframe: str) -> list[str]:
    suffix = f"_{timeframe}.csv"
    symbols: list[str] = []
    for path in sorted(data_dir.glob(f"*{suffix}")):
        name = path.name
        if not name.endswith(suffix):
            continue
        symbol = name[: -len(suffix)].upper()
        symbols.append(symbol)
    return symbols


def load_symbol_frames(
    data_dir: Path,
    timeframe: str,
    symbols: list[str] | None,
    exclude_symbols: list[str] | None,
    start_date: str,
    end_date: str,
    max_symbols: int,
) -> dict[str, pd.DataFrame]:
    resolved_symbols = symbols or discover_symbols(data_dir, timeframe)
    resolved_symbols = [s.upper() for s in resolved_symbols]
    excluded = {s.upper() for s in (exclude_symbols or [])}
    if excluded:
        resolved_symbols = [s for s in resolved_symbols if s not in excluded]
    if max_symbols > 0:
        resolved_symbols = resolved_symbols[:max_symbols]

    out: dict[str, pd.DataFrame] = {}
    start_ts = pd.Timestamp(start_date)
    end_ts = pd.Timestamp(end_date)

    for symbol in resolved_symbols:
        path = data_dir / f"{symbol.lower()}_{timeframe}.csv"
        if not path.exists():
            continue

        frame = pd.read_csv(path)
        if frame.empty:
            continue

        frame["timestamp"] = pd.to_datetime(frame["timestamp"], errors="coerce")
        frame = frame.dropna(subset=["timestamp"])
        frame = frame[(frame["timestamp"] >= start_ts) & (frame["timestamp"] <= end_ts)]
        if frame.empty:
            continue

        for col in ["open", "high", "low", "close", "volume"]:
            frame[col] = pd.to_numeric(frame[col], errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close", "volume"])
        frame = frame.sort_values("timestamp").reset_index(drop=True)
        if len(frame) < 300:
            continue

        out[symbol] = frame[
            ["timestamp", "open", "high", "low", "close", "volume"]
        ].copy()

    return out


def resolve_train_end_date(
    frame: pd.DataFrame, train_end_date: str | None
) -> pd.Timestamp:
    if train_end_date:
        return pd.Timestamp(train_end_date)

    unique_ts = frame["timestamp"].drop_duplicates().sort_values().to_numpy()
    idx = int(len(unique_ts) * 0.7)
    idx = min(max(idx, 0), len(unique_ts) - 1)
    return pd.Timestamp(unique_ts[idx])


def build_train_test(
    frame: pd.DataFrame,
    feature_cols: list[str],
    train_end_date: pd.Timestamp,
    target_column: str = "target_forward_return",
) -> tuple[pd.DataFrame, pd.DataFrame]:
    core_cols = feature_cols + [target_column, "target_worst_drawdown", "fwd_ret_1"]
    clean = frame.dropna(subset=core_cols).copy()

    train = clean[clean["timestamp"] <= train_end_date].copy()
    test = clean[clean["timestamp"] > train_end_date].copy()

    # Keep only symbols that have samples in both train and test windows.
    # This avoids unstable comparisons when a symbol exists only in one split.
    train_syms = set(train["symbol"].unique().tolist())
    test_syms = set(test["symbol"].unique().tolist())
    common_syms = sorted(train_syms & test_syms)
    train = train[train["symbol"].isin(common_syms)].copy()
    test = test[test["symbol"].isin(common_syms)].copy()

    if train.empty or test.empty:
        raise ValueError(
            f"Train/test split empty. train_rows={len(train)} test_rows={len(test)} train_end={train_end_date}"
        )

    return train, test


def fit_model(
    train_df: pd.DataFrame,
    feature_cols: list[str],
    random_state: int,
    target_column: str = "target_forward_return",
) -> RandomForestRegressor:
    X_train = train_df[feature_cols].to_numpy(dtype=np.float32)
    y_train = train_df[target_column].to_numpy(dtype=np.float32)
    y_train = np.clip(y_train, -0.35, 0.45)

    model = RandomForestRegressor(
        n_estimators=260,
        max_depth=10,
        min_samples_leaf=40,
        max_features="sqrt",
        n_jobs=-1,
        random_state=random_state,
    )
    model.fit(X_train, y_train)
    return model


def evaluate_model(
    model: RandomForestRegressor,
    test_df: pd.DataFrame,
    feature_cols: list[str],
    target_column: str = "target_forward_return",
) -> dict[str, float]:
    X_test = test_df[feature_cols].to_numpy(dtype=np.float32)
    y_test = test_df[target_column].to_numpy(dtype=np.float32)

    pred = model.predict(X_test)

    mae = float(mean_absolute_error(y_test, pred))
    r2 = float(r2_score(y_test, pred))

    pred_s = pd.Series(pred)
    y_s = pd.Series(y_test)
    ic = float(pred_s.corr(y_s, method="spearman")) if len(pred_s) > 2 else float("nan")

    top_q = float(np.nanquantile(pred, 0.8))
    bot_q = float(np.nanquantile(pred, 0.2))
    top_realized = (
        float(y_s[pred_s >= top_q].mean()) if np.any(pred_s >= top_q) else 0.0
    )
    bot_realized = (
        float(y_s[pred_s <= bot_q].mean()) if np.any(pred_s <= bot_q) else 0.0
    )

    return {
        "mae": mae,
        "r2": r2,
        "spearman_ic": ic,
        "top20_realized_mean": top_realized,
        "bottom20_realized_mean": bot_realized,
        "top_minus_bottom": top_realized - bot_realized,
    }


def _compute_metrics(equity: pd.Series, timestamps: pd.Series) -> PortfolioMetrics:
    if equity.empty or len(equity) < 3:
        return PortfolioMetrics(0.0, 0.0, 0.0, 0.0)

    eq = equity.astype(float)
    ts = pd.to_datetime(timestamps)

    total_return = (eq.iloc[-1] / eq.iloc[0] - 1.0) * 100.0

    peak = eq.cummax()
    drawdown = (eq / peak) - 1.0
    mdd = float(drawdown.min() * 100.0)

    span_years = max(
        (ts.iloc[-1] - ts.iloc[0]).total_seconds() / (365.25 * 24 * 3600), 1e-9
    )
    cagr = (
        ((eq.iloc[-1] / eq.iloc[0]) ** (1.0 / span_years) - 1.0) * 100.0
        if eq.iloc[0] > 0
        else 0.0
    )

    rets = eq.pct_change().dropna()
    if len(rets) > 2 and rets.std() > 0:
        sharpe = float((rets.mean() / rets.std()) * math.sqrt(365 * 6))
    else:
        sharpe = 0.0

    return PortfolioMetrics(
        total_return_pct=float(total_return),
        mdd_pct=float(mdd),
        cagr_pct=float(cagr),
        sharpe=float(sharpe),
    )


def _build_target_weights(
    selected: pd.DataFrame,
    cfg: TrainConfig,
) -> tuple[dict[str, float], float]:
    if selected.empty:
        return {}, 0.0

    symbols = selected["symbol"].astype(str).tolist()
    n = len(symbols)
    if n == 0:
        return {}, 0.0

    max_w = float(np.clip(cfg.max_symbol_weight, 0.0, 1.0))
    score_power = max(0.1, float(cfg.score_power))
    trend_weight = max(0.0, float(cfg.trend_weight))
    vol_penalty_power = max(0.0, float(cfg.vol_penalty_power))

    pred_score = (
        selected.get("pred_score", pd.Series(np.zeros(n))).astype(float).to_numpy()
    )
    threshold_ref = (
        float(selected["_effective_min_score"].iloc[0])
        if "_effective_min_score" in selected.columns and not selected.empty
        else float(cfg.min_score)
    )
    score_edge = np.maximum(pred_score - threshold_ref, 0.0)
    ema_edge = np.maximum(
        selected.get("ema_ratio_1_50", pd.Series(np.ones(n))).astype(float).to_numpy()
        - 1.0,
        0.0,
    )
    breakout_edge = np.maximum(
        selected.get("breakout_20", pd.Series(np.zeros(n))).astype(float).to_numpy(),
        0.0,
    )
    trend_term = ema_edge + breakout_edge
    trend_score = np.maximum(score_edge + trend_weight * trend_term, 1e-9)

    if cfg.weighting_mode == "equal":
        raw = np.full(n, 1.0 / n, dtype=float)
    elif cfg.weighting_mode == "inv_vol":
        raw = np.full(n, 1.0 / n, dtype=float)
    elif cfg.weighting_mode in {"trend_score", "trend_score_inv_vol"}:
        raw = np.power(trend_score, score_power)
        raw_sum = float(np.nansum(raw))
        if raw_sum <= 0.0:
            raw = np.full(n, 1.0 / n, dtype=float)
        else:
            raw = raw / raw_sum
    else:
        raw = np.full(n, 1.0 / n, dtype=float)

    if cfg.weighting_mode in {"inv_vol", "trend_score_inv_vol"}:
        vols = (
            selected["atr_pct_14"]
            .astype(float)
            .clip(
                lower=max(1e-6, cfg.atr_vol_floor),
                upper=max(cfg.atr_vol_floor, cfg.atr_vol_cap),
            )
            .to_numpy(dtype=float)
        )
        vol_penalty = np.power(vols, vol_penalty_power)
        raw = raw / np.maximum(vol_penalty, 1e-9)
        raw_sum = float(np.nansum(raw))
        if raw_sum <= 0.0:
            raw = np.full(n, 1.0 / n, dtype=float)
        else:
            raw = raw / raw_sum

    if max_w <= 0.0:
        clipped = np.zeros_like(raw)
    else:
        clipped = np.minimum(raw, max_w)

    if cfg.full_deploy_on_signal and float(clipped.sum()) > 0.0:
        cap = max_w
        if cap < (1.0 / n):
            cap = 1.0 / n
        w = raw.copy()
        w_sum = float(w.sum())
        if w_sum > 0.0:
            w = w / w_sum
        for _ in range(4 * n + 8):
            over = w > (cap + 1e-12)
            if not np.any(over):
                break
            excess = float(np.sum(w[over] - cap))
            w[over] = cap
            under = ~over
            if not np.any(under) or excess <= 1e-12:
                break
            under_mass = float(np.sum(w[under]))
            if under_mass <= 1e-12:
                w[under] += excess / float(np.sum(under))
            else:
                w[under] += excess * (w[under] / under_mass)
        w = np.maximum(w, 0.0)
        w_sum = float(np.sum(w))
        clipped = (w / w_sum) if w_sum > 0.0 else np.zeros_like(w)

    target_weights = {
        sym: float(w) for sym, w in zip(symbols, clipped.tolist()) if w > 0.0
    }
    gross_exposure = float(sum(target_weights.values()))
    return target_weights, gross_exposure


def run_portfolio_backtest(
    test_df: pd.DataFrame,
    model: RandomForestRegressor,
    feature_cols: list[str],
    cfg: TrainConfig,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, Any]]:
    grouped = test_df.sort_values(["timestamp", "symbol"]).groupby(
        "timestamp", sort=True
    )

    equity = 1.0
    benchmark_eq = 1.0
    prev_weights: dict[str, float] = {}

    rows: list[dict[str, Any]] = []

    symbol_stats: dict[str, dict[str, float]] = {}
    symbol_quality_ema: dict[str, float] = {}
    symbol_quality_obs: dict[str, int] = {}
    quality_alpha = float(np.clip(cfg.symbol_quality_ema_alpha, 0.01, 1.0))
    prev_breadth: float | None = None

    for ts, grp in grouped:
        g = grp.dropna(subset=feature_cols + ["fwd_ret_1"]).copy()
        if g.empty:
            continue

        breadth = float(g["cs_above_ema50_ratio"].iloc[0])
        cs_ret1 = float(g["cs_ret_1_median"].iloc[0])
        cs_ret3 = float(g["cs_ret_3_median"].iloc[0])
        breadth_delta = (
            0.0 if prev_breadth is None else float(breadth - float(prev_breadth))
        )
        risk_on = bool(breadth >= cfg.risk_on_breadth)
        crash_block = bool(
            cfg.crash_guard_enabled
            and cs_ret3 <= cfg.crash_ret3_threshold
            and breadth <= cfg.crash_breadth_threshold
        )
        regime_weak_block = bool(
            cfg.regime_weak_guard_enabled
            and breadth_delta <= -abs(float(cfg.regime_breadth_drop_threshold))
            and cs_ret1 <= float(cfg.regime_cs_ret1_threshold)
        )
        selected = pd.DataFrame(columns=g.columns)

        if risk_on and not crash_block and not regime_weak_block:
            effective_min_score = float(cfg.min_score)
            effective_top_k = int(cfg.top_k)
            if cfg.breadth_adaptive_enabled and breadth > cfg.risk_on_breadth:
                breadth_delta = float(breadth - cfg.risk_on_breadth)
                effective_min_score = max(
                    float(cfg.min_score_floor),
                    float(cfg.min_score)
                    - float(cfg.min_score_breadth_coef) * breadth_delta,
                )
                effective_top_k = min(
                    int(cfg.top_k_max),
                    int(
                        round(
                            float(cfg.top_k)
                            + float(cfg.top_k_breadth_boost) * breadth_delta
                        )
                    ),
                )
            elig = g[
                (g["ema_ratio_1_50"] > 1.0)
                & (g["adx_14"] >= cfg.min_adx)
                & (g["breakout_20"] >= cfg.breakout_floor)
            ].copy()
            if not elig.empty:
                if cfg.symbol_quality_filter_enabled:
                    min_obs = max(1, int(cfg.symbol_quality_min_obs))
                    min_ema = float(cfg.symbol_quality_min_ema)
                    qual_obs = (
                        elig["symbol"]
                        .astype(str)
                        .map(symbol_quality_obs)
                        .fillna(0)
                        .astype(int)
                    )
                    qual_ema = (
                        elig["symbol"]
                        .astype(str)
                        .map(symbol_quality_ema)
                        .fillna(0.0)
                        .astype(float)
                    )
                    keep_mask = (qual_obs < min_obs) | (qual_ema >= min_ema)
                    elig = elig[keep_mask.to_numpy(dtype=bool)]
                if elig.empty:
                    selected = pd.DataFrame(columns=g.columns)
                else:
                    if "pred_score" not in elig.columns:
                        elig["pred_score"] = model.predict(
                            elig[feature_cols].to_numpy(dtype=np.float32)
                        )
                    elig = elig[elig["pred_score"] >= effective_min_score]
                    if cfg.score_quantile > 0.0 and not elig.empty:
                        q = float(
                            elig["pred_score"].quantile(
                                min(1.0, max(0.0, cfg.score_quantile))
                            )
                        )
                        elig = elig[elig["pred_score"] >= q]
                    selected = elig.sort_values("pred_score", ascending=False).head(
                        effective_top_k
                    )
                    if not selected.empty:
                        selected = selected.copy()
                        selected["_effective_min_score"] = effective_min_score

        target_weights, gross_exposure = _build_target_weights(selected, cfg)
        if selected.empty or not target_weights:
            selected = pd.DataFrame(columns=g.columns)
            gross_ret = 0.0
        else:
            selected = selected.copy()
            selected["weight"] = selected["symbol"].map(target_weights).fillna(0.0)
            selected = selected[selected["weight"] > 0.0]
            gross_ret = float((selected["fwd_ret_1"] * selected["weight"]).sum())
            gross_exposure = float(selected["weight"].sum())

        union_symbols = set(prev_weights) | set(target_weights)
        turnover = float(
            sum(
                abs(target_weights.get(sym, 0.0) - prev_weights.get(sym, 0.0))
                for sym in union_symbols
            )
        )
        tx_cost = turnover * (cfg.fee_rate + cfg.slippage)
        net_ret = gross_ret - tx_cost

        bench_ret = float(g["fwd_ret_1"].mean())

        equity *= 1.0 + net_ret
        benchmark_eq *= 1.0 + bench_ret

        selected_symbols = selected["symbol"].tolist() if not selected.empty else []
        selected_scores = [
            float(x)
            for x in selected.get("pred_score", pd.Series(dtype=float)).tolist()
        ]

        for _, row in selected.iterrows():
            sym = str(row["symbol"])
            sym_stat = symbol_stats.setdefault(
                sym, {"bars": 0.0, "weighted_ret_sum": 0.0}
            )
            sym_stat["bars"] += 1.0
            sym_stat["weighted_ret_sum"] += float(row["fwd_ret_1"]) * float(
                row["weight"]
            )
            realized = float(row["fwd_ret_1"])
            prev_q = float(symbol_quality_ema.get(sym, realized))
            symbol_quality_ema[sym] = quality_alpha * realized + (
                (1.0 - quality_alpha) * prev_q
            )
            symbol_quality_obs[sym] = int(symbol_quality_obs.get(sym, 0) + 1)

        rows.append(
            {
                "timestamp": ts,
                "risk_on": risk_on,
                "crash_block": crash_block,
                "regime_weak_block": regime_weak_block,
                "selected_count": len(selected_symbols),
                "selected_symbols": ",".join(selected_symbols),
                "selected_scores": ",".join(f"{s:.6f}" for s in selected_scores),
                "weighting_mode": cfg.weighting_mode,
                "gross_exposure": gross_exposure,
                "gross_return": gross_ret,
                "turnover": turnover,
                "tx_cost": tx_cost,
                "net_return": net_ret,
                "benchmark_return": bench_ret,
                "equity": equity,
                "benchmark_equity": benchmark_eq,
                "cs_ret_1_median": cs_ret1,
                "cs_above_ema50_ratio": breadth,
                "cs_breadth_delta": breadth_delta,
                "cs_breakout_ratio": float(g["cs_breakout_ratio"].iloc[0]),
                "cs_ret_3_median": cs_ret3,
            }
        )

        prev_weights = target_weights
        prev_breadth = breadth

    equity_df = pd.DataFrame(rows)
    if equity_df.empty:
        raise ValueError(
            "Backtest produced no rows. Check feature availability and filters."
        )

    symbol_rows = []
    for symbol, stat in sorted(symbol_stats.items()):
        bars = stat["bars"]
        wr = stat["weighted_ret_sum"]
        symbol_rows.append(
            {
                "symbol": symbol,
                "selected_bars": int(bars),
                "weighted_return_sum": wr,
                "weighted_return_avg": (wr / bars) if bars > 0 else 0.0,
            }
        )

    symbol_df = pd.DataFrame(symbol_rows)
    extra = {
        "bars": int(len(equity_df)),
        "risk_on_bars": int(equity_df["risk_on"].sum()),
        "crash_block_bars": int(equity_df["crash_block"].sum()),
        "regime_weak_block_bars": int(equity_df["regime_weak_block"].sum()),
        "avg_selected_count": float(equity_df["selected_count"].mean()),
        "avg_turnover": float(equity_df["turnover"].mean()),
        "avg_gross_exposure": float(equity_df["gross_exposure"].mean()),
        "symbol_quality_tracked": int(len(symbol_quality_obs)),
    }

    return equity_df, symbol_df, extra


def write_report(
    run_tag: str,
    experiment_tag: str,
    feature_profile: str,
    target_mode: str,
    target_column: str,
    target_config: BullFollowTargetConfig,
    cfg: TrainConfig,
    model: RandomForestRegressor,
    model_eval: dict[str, float],
    train_df: pd.DataFrame,
    test_df: pd.DataFrame,
    feature_cols: list[str],
    equity_df: pd.DataFrame,
    symbol_df: pd.DataFrame,
    extra: dict[str, Any],
    model_dir: Path,
    report_dir: Path,
) -> dict[str, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    model_dir.mkdir(parents=True, exist_ok=True)

    metrics_strategy = _compute_metrics(equity_df["equity"], equity_df["timestamp"])
    metrics_bnh = _compute_metrics(
        equity_df["benchmark_equity"], equity_df["timestamp"]
    )
    alpha_return = metrics_strategy.total_return_pct - metrics_bnh.total_return_pct

    model_path = model_dir / f"bull_follow_v1_{experiment_tag}_{run_tag}.pkl"
    with model_path.open("wb") as f:
        pickle.dump(
            {
                "model": model,
                "feature_columns": feature_cols,
                "config": asdict(cfg),
                "trained_at": datetime.now(timezone.utc).isoformat(),
            },
            f,
        )

    feature_importance_df = pd.DataFrame(
        {
            "feature": feature_cols,
            "importance": model.feature_importances_,
        }
    ).sort_values("importance", ascending=False)

    equity_csv = report_dir / f"bull_follow_v1_{experiment_tag}_{run_tag}_equity.csv"
    symbol_csv = (
        report_dir / f"bull_follow_v1_{experiment_tag}_{run_tag}_symbol_contrib.csv"
    )
    feat_csv = (
        report_dir / f"bull_follow_v1_{experiment_tag}_{run_tag}_feature_importance.csv"
    )
    summary_json = (
        report_dir / f"bull_follow_v1_{experiment_tag}_{run_tag}_summary.json"
    )
    summary_md = report_dir / f"bull_follow_v1_{experiment_tag}_{run_tag}_summary.md"

    equity_df.to_csv(equity_csv, index=False)
    symbol_df.to_csv(symbol_csv, index=False)
    feature_importance_df.to_csv(feat_csv, index=False)

    payload = {
        "run_tag": run_tag,
        "model_path": str(model_path.relative_to(PROJECT_ROOT)),
        "train_rows": int(len(train_df)),
        "test_rows": int(len(test_df)),
        "symbols_train": sorted(train_df["symbol"].unique().tolist()),
        "symbols_test": sorted(test_df["symbol"].unique().tolist()),
        "model_eval": model_eval,
        "strategy_metrics": asdict(metrics_strategy),
        "benchmark_metrics": asdict(metrics_bnh),
        "alpha_return_pct": alpha_return,
        "backtest_extra": extra,
        "feature_profile": feature_profile,
        "target_mode": target_mode,
        "target_column": target_column,
        "target_config": asdict(target_config),
        "config": asdict(cfg),
        "artifacts": {
            "equity_csv": str(equity_csv.relative_to(PROJECT_ROOT)),
            "symbol_csv": str(symbol_csv.relative_to(PROJECT_ROOT)),
            "feature_importance_csv": str(feat_csv.relative_to(PROJECT_ROOT)),
        },
    }
    summary_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    top_feat_lines = "\n".join(
        f"- `{row.feature}`: {row.importance:.5f}"
        for row in feature_importance_df.head(12).itertuples()
    )

    lines = [
        "# Bull-Follow v1 Training/Backtest Summary",
        "",
        f"- run_tag: `{run_tag}`",
        f"- model: `{model_path.relative_to(PROJECT_ROOT)}`",
        f"- train_rows: `{len(train_df)}`",
        f"- test_rows: `{len(test_df)}`",
        f"- symbols(train): `{len(payload['symbols_train'])}`",
        f"- symbols(test): `{len(payload['symbols_test'])}`",
        f"- feature_profile: `{feature_profile}` ({len(feature_cols)} features)",
        f"- target_mode: `{target_mode}` (`{target_column}`)",
        f"- target_config: `pnl_downside_penalty={target_config.pnl_downside_penalty}, pnl_fee_buffer={target_config.pnl_fee_buffer}`",
        f"- weighting_mode: `{cfg.weighting_mode}` (max_symbol_weight={cfg.max_symbol_weight:.2f})",
        f"- weighting_params: `score_power={cfg.score_power:.2f}, trend_weight={cfg.trend_weight:.2f}, vol_penalty_power={cfg.vol_penalty_power:.2f}, full_deploy_on_signal={cfg.full_deploy_on_signal}, score_quantile={cfg.score_quantile:.2f}, breadth_adaptive_enabled={cfg.breadth_adaptive_enabled}, min_score_breadth_coef={cfg.min_score_breadth_coef:.4f}, min_score_floor={cfg.min_score_floor:.4f}, top_k_breadth_boost={cfg.top_k_breadth_boost:.2f}, top_k_max={cfg.top_k_max}`",
        f"- symbol_quality_filter: `enabled={cfg.symbol_quality_filter_enabled}, ema_alpha={cfg.symbol_quality_ema_alpha:.2f}, min_ema={cfg.symbol_quality_min_ema:.4f}, min_obs={cfg.symbol_quality_min_obs}`",
        f"- regime_weak_guard: `enabled={cfg.regime_weak_guard_enabled}, breadth_drop_threshold={cfg.regime_breadth_drop_threshold:.3f}, cs_ret1_threshold={cfg.regime_cs_ret1_threshold:.4f}`",
        f"- crash_guard: `enabled={cfg.crash_guard_enabled}, ret3<={cfg.crash_ret3_threshold:.3f}, breadth<={cfg.crash_breadth_threshold:.2f}`",
        "",
        "## Model Quality",
        "",
        f"- MAE: `{model_eval['mae']:.6f}`",
        f"- R2: `{model_eval['r2']:.6f}`",
        f"- Spearman IC: `{model_eval['spearman_ic']:.6f}`",
        f"- Top20%-Bottom20% realized spread: `{model_eval['top_minus_bottom'] * 100:.4f}%p`",
        "",
        "## Portfolio Comparison",
        "",
        f"- Bull-Follow return: `{metrics_strategy.total_return_pct:.2f}%`",
        f"- Bull-Follow MDD: `{metrics_strategy.mdd_pct:.2f}%`",
        f"- Bull-Follow Sharpe: `{metrics_strategy.sharpe:.3f}`",
        f"- Equal-weight B&H return: `{metrics_bnh.total_return_pct:.2f}%`",
        f"- Equal-weight B&H MDD: `{metrics_bnh.mdd_pct:.2f}%`",
        f"- Alpha (return diff): `{alpha_return:.2f}%p`",
        "",
        "## Backtest Runtime Stats",
        "",
        f"- bars: `{extra['bars']}`",
        f"- risk_on_bars: `{extra['risk_on_bars']}`",
        f"- crash_block_bars: `{extra['crash_block_bars']}`",
        f"- regime_weak_block_bars: `{extra['regime_weak_block_bars']}`",
        f"- avg_selected_count: `{extra['avg_selected_count']:.2f}`",
        f"- avg_turnover: `{extra['avg_turnover']:.4f}`",
        f"- avg_gross_exposure: `{extra['avg_gross_exposure']:.3f}`",
        f"- symbol_quality_tracked: `{extra['symbol_quality_tracked']}`",
        "",
        "## Top Feature Importance",
        "",
        top_feat_lines,
        "",
        "## Artifacts",
        "",
        f"- equity: `{equity_csv.relative_to(PROJECT_ROOT)}`",
        f"- symbol contribution: `{symbol_csv.relative_to(PROJECT_ROOT)}`",
        f"- feature importance: `{feat_csv.relative_to(PROJECT_ROOT)}`",
        f"- summary json: `{summary_json.relative_to(PROJECT_ROOT)}`",
    ]
    summary_md.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return {
        "model_path": model_path,
        "equity_csv": equity_csv,
        "symbol_csv": symbol_csv,
        "feature_importance_csv": feat_csv,
        "summary_json": summary_json,
        "summary_md": summary_md,
    }


def main() -> int:
    args = parse_args()
    feature_cols = resolve_feature_columns(args.feature_profile)
    target_column = resolve_target_column(args.target_mode)
    experiment_tag = f"{args.feature_profile}_{args.target_mode}_{args.weighting_mode}"
    target_cfg = BullFollowTargetConfig(
        horizon_bars=int(args.horizon_bars),
        pnl_downside_penalty=float(args.pnl_downside_penalty),
        pnl_fee_buffer=float(args.pnl_fee_buffer),
    )
    excluded_symbols = [s.upper() for s in args.exclude_symbols]

    cfg = TrainConfig(
        start_date=args.start_date,
        end_date=args.end_date,
        train_end_date=args.train_end_date,
        timeframe=args.timeframe,
        top_k=int(args.top_k),
        min_score=float(args.min_score),
        min_adx=float(args.min_adx),
        breakout_floor=float(args.breakout_floor),
        risk_on_breadth=float(args.risk_on_breadth),
        fee_rate=float(args.fee_rate),
        slippage=float(args.slippage),
        horizon_bars=int(args.horizon_bars),
        min_history=int(args.min_history),
        random_state=int(args.random_state),
        weighting_mode=str(args.weighting_mode),
        max_symbol_weight=float(args.max_symbol_weight),
        atr_vol_floor=float(args.atr_vol_floor),
        atr_vol_cap=float(args.atr_vol_cap),
        crash_guard_enabled=not bool(args.no_crash_guard),
        crash_ret3_threshold=float(args.crash_ret3_threshold),
        crash_breadth_threshold=float(args.crash_breadth_threshold),
        score_power=float(args.score_power),
        trend_weight=float(args.trend_weight),
        vol_penalty_power=float(args.vol_penalty_power),
        full_deploy_on_signal=not bool(args.no_full_deploy_on_signal),
        score_quantile=float(args.score_quantile),
        breadth_adaptive_enabled=bool(args.enable_breadth_adaptive)
        and not bool(args.no_breadth_adaptive),
        min_score_breadth_coef=float(args.min_score_breadth_coef),
        min_score_floor=float(args.min_score_floor),
        top_k_breadth_boost=float(args.top_k_breadth_boost),
        top_k_max=int(args.top_k_max),
        symbol_quality_filter_enabled=bool(args.enable_symbol_quality_filter),
        symbol_quality_ema_alpha=float(args.symbol_quality_ema_alpha),
        symbol_quality_min_ema=float(args.symbol_quality_min_ema),
        symbol_quality_min_obs=int(args.symbol_quality_min_obs),
        regime_weak_guard_enabled=bool(args.enable_regime_weak_guard),
        regime_breadth_drop_threshold=float(args.regime_breadth_drop_threshold),
        regime_cs_ret1_threshold=float(args.regime_cs_ret1_threshold),
    )

    data_dir = Path(args.data_dir)
    model_dir = Path(args.model_dir)
    report_dir = Path(args.report_dir)

    frames = load_symbol_frames(
        data_dir=data_dir,
        timeframe=cfg.timeframe,
        symbols=[s.upper() for s in args.symbols] if args.symbols else None,
        exclude_symbols=excluded_symbols,
        start_date=cfg.start_date,
        end_date=cfg.end_date,
        max_symbols=int(args.max_symbols),
    )
    if not frames:
        print("No symbol frames loaded. Check data-dir/timeframe/symbols.")
        return 1

    print(f"Loaded {len(frames)} symbols from {data_dir}")
    print(
        "Experiment:",
        f"feature_profile={args.feature_profile}",
        f"target_mode={args.target_mode}",
        f"feature_count={len(feature_cols)}",
        f"weighting_mode={cfg.weighting_mode}",
        f"score_power={cfg.score_power}",
        f"trend_weight={cfg.trend_weight}",
        f"vol_penalty_power={cfg.vol_penalty_power}",
        f"full_deploy_on_signal={cfg.full_deploy_on_signal}",
        f"score_quantile={cfg.score_quantile}",
        f"breadth_adaptive_enabled={cfg.breadth_adaptive_enabled}",
        f"min_score_breadth_coef={cfg.min_score_breadth_coef}",
        f"min_score_floor={cfg.min_score_floor}",
        f"top_k_breadth_boost={cfg.top_k_breadth_boost}",
        f"top_k_max={cfg.top_k_max}",
        f"symbol_quality_filter_enabled={cfg.symbol_quality_filter_enabled}",
        f"symbol_quality_ema_alpha={cfg.symbol_quality_ema_alpha}",
        f"symbol_quality_min_ema={cfg.symbol_quality_min_ema}",
        f"symbol_quality_min_obs={cfg.symbol_quality_min_obs}",
        f"regime_weak_guard_enabled={cfg.regime_weak_guard_enabled}",
        f"regime_breadth_drop_threshold={cfg.regime_breadth_drop_threshold}",
        f"regime_cs_ret1_threshold={cfg.regime_cs_ret1_threshold}",
        f"excluded={excluded_symbols}",
        f"pnl_downside_penalty={target_cfg.pnl_downside_penalty}",
        f"pnl_fee_buffer={target_cfg.pnl_fee_buffer}",
    )

    feature_frame = prepare_universe_features(
        symbol_frames=frames,
        target_config=target_cfg,
        min_history=cfg.min_history,
    )

    train_end_ts = resolve_train_end_date(feature_frame, cfg.train_end_date)
    train_df, test_df = build_train_test(
        frame=feature_frame,
        feature_cols=feature_cols,
        train_end_date=train_end_ts,
        target_column=target_column,
    )

    print(
        "Train/Test split:",
        f"train={len(train_df):,}",
        f"test={len(test_df):,}",
        f"train_end={train_end_ts.date()}",
    )

    model = fit_model(
        train_df,
        feature_cols,
        random_state=cfg.random_state,
        target_column=target_column,
    )
    eval_stats = evaluate_model(
        model,
        test_df,
        feature_cols,
        target_column=target_column,
    )
    print(
        "Model eval:",
        f"MAE={eval_stats['mae']:.6f}",
        f"R2={eval_stats['r2']:.6f}",
        f"IC={eval_stats['spearman_ic']:.6f}",
        f"spread={eval_stats['top_minus_bottom'] * 100:.4f}%p",
    )

    equity_df, symbol_df, extra = run_portfolio_backtest(
        test_df=test_df,
        model=model,
        feature_cols=feature_cols,
        cfg=cfg,
    )

    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifacts = write_report(
        run_tag=run_tag,
        experiment_tag=experiment_tag,
        feature_profile=args.feature_profile,
        target_mode=args.target_mode,
        target_column=target_column,
        target_config=target_cfg,
        cfg=cfg,
        model=model,
        model_eval=eval_stats,
        train_df=train_df,
        test_df=test_df,
        feature_cols=feature_cols,
        equity_df=equity_df,
        symbol_df=symbol_df,
        extra=extra,
        model_dir=model_dir,
        report_dir=report_dir,
    )

    print(f"Summary: {artifacts['summary_md'].relative_to(PROJECT_ROOT)}")
    print(f"Model: {artifacts['model_path'].relative_to(PROJECT_ROOT)}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
