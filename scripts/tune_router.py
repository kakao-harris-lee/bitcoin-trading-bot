#!/usr/bin/env python3
"""Tune operational regime routing to improve portfolio performance.

Searches over:
- RegimeRouter thresholds (mfi_bull/mfi_bear/adx_*), using the same logic as live_trading/regime_router.py
- Upbit SIDEWAYS policy: {sideways_v2, v35, hold}

Evaluates a combined portfolio:
- Upbit: router_live on DAY
- Binance: short_v1 on 4H gated to daily BEAR regime
- Combined equity in KRW using fixed FX

By default:
- Train: 2020-01-01..2024-12-31
- Validate: 2025-01-01..2025-12-11

Outputs top configs with train + val metrics, and writes a JSON report.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.backtester import Backtester
from core.data_loader import DataLoader

from trading.strategy.regime_router import RegimeRouter as LiveRegimeRouter
from trading.strategy.regime_router import _calc_adx as _live_calc_adx
from trading.strategy.regime_router import _calc_mfi as _live_calc_mfi
from scripts.backtest import (
    BearOnlyShortWrapper,
    PortfolioBacktestConfig,
    ShortMarginBacktester,
    _compute_metrics,
    _daily_regime_series,
    _daily_market_state_series,
    _to_daily_last,
)
from scripts.backtest_strategies import RegimeRouterLiveAdapter


@dataclass
class EvalResult:
    score: float
    total_return: float
    cagr: float
    mdd: float
    sharpe: float
    year_worst_return: float
    year_worst_mdd: float


@dataclass
class Candidate:
    router_config: Dict[str, float]
    bull_policy: str
    bull_hold_fraction: float
    sideways_policy: str
    sideways_bear_policy: str
    bear_moderate_policy: str
    bear_strong_policy: str
    binance_gate_mode: str
    sideways_v2_config: Dict
    v35_fraction_mult: float
    sideways_fraction_mult: float
    binance_fraction_mult: float


def _yearly_stats(equity_daily: pd.DataFrame) -> Tuple[float, float]:
    if equity_daily.empty:
        return 0.0, 0.0
    df = equity_daily.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    df["year"] = df["timestamp"].dt.year

    worst_ret = 0.0
    worst_mdd = 0.0

    for _, grp in df.groupby("year"):
        start = float(grp["total_equity"].iloc[0])
        end = float(grp["total_equity"].iloc[-1])
        ret = ((end - start) / start) * 100 if start > 0 else 0.0
        peak = grp["total_equity"].cummax()
        dd = (grp["total_equity"] - peak) / peak
        mdd = float(dd.min() * 100)

        worst_ret = min(worst_ret, float(ret))
        worst_mdd = min(worst_mdd, float(mdd))

    return float(worst_ret), float(worst_mdd)


def _combined_portfolio_backtest(
    cfg: PortfolioBacktestConfig,
    df_day: pd.DataFrame,
    df_h4: pd.DataFrame,
    candidate: Candidate,
) -> Tuple[pd.DataFrame, Dict]:
    # Upbit backtest on preloaded daily df
    upbit_strategy = RegimeRouterLiveAdapter(
        timeframe="day",
        router_config=candidate.router_config,
        bull_policy=candidate.bull_policy,
        bull_hold_fraction=candidate.bull_hold_fraction,
        sideways_policy=candidate.sideways_policy,
        sideways_bear_policy=candidate.sideways_bear_policy,
        bear_moderate_policy=candidate.bear_moderate_policy,
        bear_strong_policy=candidate.bear_strong_policy,
        v35_fraction_mult=candidate.v35_fraction_mult,
        sideways_fraction_mult=candidate.sideways_fraction_mult,
        sideways_v2_config=candidate.sideways_v2_config,
    )

    upbit_bt = Backtester(initial_capital=cfg.upbit_capital_krw, fee_rate=0.0005, slippage=0.0002)
    upbit_res = upbit_bt.run(df_day, upbit_strategy, {})

    router = LiveRegimeRouter(
        mfi_bull=float(candidate.router_config["mfi_bull"]),
        mfi_bear=float(candidate.router_config["mfi_bear"]),
        adx_strong=float(candidate.router_config["adx_strong"]),
        adx_trend=float(candidate.router_config["adx_trend"]),
        adx_weak=float(candidate.router_config["adx_weak"]),
    )

    # Precompute MFI/ADX once per df_day, then apply thresholds cheaply.
    df_ind = df_day.copy()
    df_ind["mfi"] = _live_calc_mfi(df_ind, period=router.mfi_period)
    df_ind["adx"] = _live_calc_adx(df_ind, period=router.adx_period)
    idx = pd.to_datetime(df_ind["timestamp"]).dt.normalize()
    market_state_by_day = pd.Series(
        [router.classify_from_values(float(m), float(a)) for m, a in zip(df_ind["mfi"].to_numpy(), df_ind["adx"].to_numpy())],
        index=idx,
        name="market_state",
    )
    regime_by_day = market_state_by_day.apply(lambda s: "BULL" if str(s).startswith("BULL") else ("SIDEWAYS" if str(s).startswith("SIDEWAYS") else "BEAR"))

    gated_short = BearOnlyShortWrapper(
        regime_by_day=regime_by_day,
        market_state_by_day=market_state_by_day,
        gate_mode=candidate.binance_gate_mode,
        fraction_mult=candidate.binance_fraction_mult,
    )
    short_bt = ShortMarginBacktester(initial_capital=cfg.binance_capital_usdt, fee_rate=0.0005, slippage=0.0002)
    binance_res = short_bt.run(df_h4, gated_short, {})

    # Aggregate daily
    upbit_daily = _to_daily_last(upbit_res["equity_curve"])
    binance_daily = _to_daily_last(binance_res["equity_curve"])

    combined = upbit_daily.merge(binance_daily, on="timestamp", how="inner", suffixes=("_upbit", "_binance"))
    combined["total_equity"] = combined["total_equity_upbit"] + (combined["total_equity_binance"] * cfg.fx_krw_per_usdt)
    combined = combined[["timestamp", "total_equity"]]

    res = {
        "upbit": upbit_res,
        "binance": binance_res,
    }
    return combined, res


def _slice_by_date(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    ts = pd.to_datetime(df["timestamp"])
    mask = (ts >= pd.Timestamp(start_date)) & (ts <= pd.Timestamp(end_date))
    return df.loc[mask].reset_index(drop=True)


def _score(equity_daily: pd.DataFrame) -> EvalResult:
    metrics = _compute_metrics(equity_daily)

    initial = float(equity_daily["total_equity"].iloc[0])
    final = float(equity_daily["total_equity"].iloc[-1])
    total_return = ((final - initial) / initial) * 100 if initial > 0 else 0.0

    worst_ret, worst_mdd = _yearly_stats(equity_daily)

    # Detect no-trade / flat equity curves (degenerate solutions) and penalize heavily
    is_flat = False
    if not equity_daily.empty and "total_equity" in equity_daily.columns:
        is_flat = int(equity_daily["total_equity"].nunique()) <= 1

    # Score: favor return and Sharpe, penalize drawdowns and unstable years.
    # We keep it simple and interpretable.
    score = (
        total_return
        + 2.0 * float(metrics.get("sharpe", 0.0))
        - 1.0 * abs(float(metrics.get("mdd", 0.0)))
        - 0.5 * abs(float(worst_mdd))
        + 0.3 * float(worst_ret)  # worst_ret is negative when bad -> penalizes
    )

    if is_flat:
        score -= 50.0

    return EvalResult(
        score=float(score),
        total_return=float(total_return),
        cagr=float(metrics.get("cagr", 0.0)),
        mdd=float(metrics.get("mdd", 0.0)),
        sharpe=float(metrics.get("sharpe", 0.0)),
        year_worst_return=float(worst_ret),
        year_worst_mdd=float(worst_mdd),
    )


def _candidate_grid() -> List[Candidate]:
    raise RuntimeError("_candidate_grid is intentionally disabled; use _sample_candidates() to avoid OOM")


def _sample_candidates(max_trials: int, seed: int) -> List[Candidate]:
    rng = random.Random(int(seed))

    mfi_bull_list = [50.0, 51.0, 52.0, 53.0, 54.0]
    mfi_bear_list = [46.0, 47.0, 48.0, 49.0]
    adx_strong_list = [22.0, 25.0, 28.0]
    adx_trend_list = [18.0, 20.0, 22.0]
    adx_weak_list = [12.0, 15.0, 18.0]

    bull_policies = ["v35", "hold_long"]
    bull_hold_fracs = [0.25, 0.4, 0.6, 0.8, 1.0]

    sideways_policies = ["sideways_v2", "v35", "hold"]
    sideways_bear_policies = ["hold", "sideways_v2"]

    bear_moderate_policies = ["hold", "sideways_v2", "v35"]
    bear_strong_policies = ["hold", "sideways_v2"]

    binance_gate_modes = [
        "bear_only",
        "bear_or_sideways_bear",
        "bear_strong_only",
        "bear_strong_or_sideways_bear",
    ]

    v35_mults = [0.8, 1.0, 1.2]
    sideways_mults = [0.8, 1.0, 1.2]
    binance_mults = [0.0, 0.4, 0.8, 1.0]

    obv_thresholds = [-0.02, -0.03, -0.04, -0.05]
    pos_sizes = [0.25, 0.35, 0.45]

    candidates: List[Candidate] = []
    seen: set = set()
    attempts = 0
    target = max(1, int(max_trials))

    while len(candidates) < target and attempts < target * 200:
        attempts += 1

        mfi_bull = float(rng.choice(mfi_bull_list))
        mfi_bear = float(rng.choice(mfi_bear_list))
        if mfi_bull <= mfi_bear:
            continue

        adx_strong = float(rng.choice(adx_strong_list))
        adx_trend = float(rng.choice(adx_trend_list))
        adx_weak = float(rng.choice(adx_weak_list))
        if not (adx_strong >= adx_trend >= adx_weak):
            continue

        bull_policy = str(rng.choice(bull_policies))
        bull_hold_fraction = float(rng.choice(bull_hold_fracs))
        sideways_policy = str(rng.choice(sideways_policies))
        sideways_bear_policy = str(rng.choice(sideways_bear_policies))
        bear_moderate_policy = str(rng.choice(bear_moderate_policies))
        bear_strong_policy = str(rng.choice(bear_strong_policies))
        binance_gate_mode = str(rng.choice(binance_gate_modes))

        v35_fraction_mult = float(rng.choice(v35_mults))
        sideways_fraction_mult = float(rng.choice(sideways_mults))
        binance_fraction_mult = float(rng.choice(binance_mults))

        obv_th = float(rng.choice(obv_thresholds))
        pos_size = float(rng.choice(pos_sizes))

        key = (
            mfi_bull,
            mfi_bear,
            adx_strong,
            adx_trend,
            adx_weak,
            bull_policy,
            bull_hold_fraction,
            sideways_policy,
            sideways_bear_policy,
            bear_moderate_policy,
            bear_strong_policy,
            binance_gate_mode,
            v35_fraction_mult,
            sideways_fraction_mult,
            binance_fraction_mult,
            obv_th,
            pos_size,
        )
        if key in seen:
            continue
        seen.add(key)

        candidates.append(
            Candidate(
                router_config={
                    "mfi_bull": mfi_bull,
                    "mfi_bear": mfi_bear,
                    "adx_strong": adx_strong,
                    "adx_trend": adx_trend,
                    "adx_weak": adx_weak,
                },
                bull_policy=bull_policy,
                bull_hold_fraction=bull_hold_fraction,
                sideways_policy=sideways_policy,
                sideways_bear_policy=sideways_bear_policy,
                bear_moderate_policy=bear_moderate_policy,
                bear_strong_policy=bear_strong_policy,
                binance_gate_mode=binance_gate_mode,
                sideways_v2_config={
                    "obv_downtrend_threshold": obv_th,
                    "position_size": pos_size,
                },
                v35_fraction_mult=v35_fraction_mult,
                sideways_fraction_mult=sideways_fraction_mult,
                binance_fraction_mult=binance_fraction_mult,
            )
        )

    return candidates


def main():
    p = argparse.ArgumentParser(description="Tune operational router thresholds/policy")
    p.add_argument("--db-path", default=str(PROJECT_ROOT / "upbit_history_db" / "upbit_bitcoin.db"))
    p.add_argument("--train-start", default="2020-01-01")
    p.add_argument("--train-end", default="2024-12-31")
    p.add_argument("--val-start", default="2025-01-01")
    p.add_argument("--val-end", default="2025-12-11")
    p.add_argument("--max-trials", type=int, default=180)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--fx", type=float, default=1300.0)
    p.add_argument("--out", default=str(PROJECT_ROOT / "analysis" / "tune_operational_router_results.json"))

    args = p.parse_args()

    cfg = PortfolioBacktestConfig(
        db_path=Path(args.db_path),
        start_date=None,
        end_date=None,
        upbit_capital_krw=10_000_000,
        binance_capital_usdt=10_000,
        fx_krw_per_usdt=float(args.fx),
    )

    candidates = _sample_candidates(max_trials=int(args.max_trials), seed=int(args.seed))

    results = []

    # Preload data once (avoid per-candidate SQLite reads)
    with DataLoader(str(cfg.db_path)) as loader:
        df_day_all = loader.load_timeframe(
            "day",
            start_date=min(args.train_start, args.val_start),
            end_date=max(args.train_end, args.val_end),
        )
        h4_start, h4_end = loader.get_date_range("minute240")
        h4_start = pd.Timestamp(h4_start).strftime("%Y-%m-%d")
        h4_end = pd.Timestamp(h4_end).strftime("%Y-%m-%d")
        start_h4_all = max(pd.Timestamp(min(args.train_start, args.val_start)), pd.Timestamp(h4_start)).strftime("%Y-%m-%d")
        end_h4_all = min(pd.Timestamp(max(args.train_end, args.val_end)), pd.Timestamp(h4_end)).strftime("%Y-%m-%d")
        df_h4_all = loader.load_timeframe("minute240", start_h4_all, end_h4_all)

    df_day_train = _slice_by_date(df_day_all, args.train_start, args.train_end)
    df_day_val = _slice_by_date(df_day_all, args.val_start, args.val_end)
    df_h4_train = _slice_by_date(df_h4_all, args.train_start, args.train_end)
    df_h4_val = _slice_by_date(df_h4_all, args.val_start, args.val_end)

    for idx, cand in enumerate(candidates, start=1):
        combined_train, _ = _combined_portfolio_backtest(cfg, df_day_train, df_h4_train, cand)
        train_eval = _score(combined_train)

        # Hard risk constraints for stability
        if train_eval.mdd < -8.0:
            continue
        if train_eval.year_worst_mdd < -6.0:
            continue

        combined_val, _ = _combined_portfolio_backtest(cfg, df_day_val, df_h4_val, cand)
        val_eval = _score(combined_val)

        results.append(
            {
                "candidate": {
                    "router_config": cand.router_config,
                    "bull_policy": cand.bull_policy,
                    "bull_hold_fraction": cand.bull_hold_fraction,
                    "sideways_policy": cand.sideways_policy,
                    "sideways_bear_policy": cand.sideways_bear_policy,
                    "bear_moderate_policy": cand.bear_moderate_policy,
                    "bear_strong_policy": cand.bear_strong_policy,
                    "binance_gate_mode": cand.binance_gate_mode,
                    "sideways_v2_config": cand.sideways_v2_config,
                    "v35_fraction_mult": cand.v35_fraction_mult,
                    "sideways_fraction_mult": cand.sideways_fraction_mult,
                    "binance_fraction_mult": cand.binance_fraction_mult,
                },
                "train": asdict(train_eval),
                "val": asdict(val_eval),
            }
        )

        if idx % 20 == 0:
            print(f"progress: {idx}/{len(candidates)} | kept={len(results)}")

    # Sort primarily by validation score, then train score
    results.sort(key=lambda r: (r["val"]["score"], r["train"]["score"]), reverse=True)

    top = results[:10]
    print("\nTOP 10 (sorted by val.score)")
    print("=" * 120)
    for i, r in enumerate(top, start=1):
        cfg_str = r["candidate"]
        tr = r["train"]
        va = r["val"]
        print(
            f"#{i:02d} bull={cfg_str['bull_policy']:<9} bullFrac={cfg_str['bull_hold_fraction']:.2f} upbit_sideways={cfg_str['sideways_policy']:<11} sideways_bear={cfg_str['sideways_bear_policy']:<11} "
            f"bear_mod={cfg_str['bear_moderate_policy']:<11} bear_str={cfg_str['bear_strong_policy']:<11} "
            f"binance_gate={cfg_str['binance_gate_mode']:<24} "
            f"mfi(bull/bear)={cfg_str['router_config']['mfi_bull']:.0f}/{cfg_str['router_config']['mfi_bear']:.0f} "
            f"adx(s/t/w)={cfg_str['router_config']['adx_strong']:.0f}/{cfg_str['router_config']['adx_trend']:.0f}/{cfg_str['router_config']['adx_weak']:.0f} | "
            f"mult(v35/sw/bn)={cfg_str['v35_fraction_mult']:.1f}/{cfg_str['sideways_fraction_mult']:.1f}/{cfg_str['binance_fraction_mult']:.1f} "
            f"sw2(obv,pos)={cfg_str['sideways_v2_config']['obv_downtrend_threshold']:.2f}/{cfg_str['sideways_v2_config']['position_size']:.2f} | "
            f"TRAIN: ret={tr['total_return']:+.2f}% mdd={tr['mdd']:.2f}% sharpe={tr['sharpe']:+.2f} wyRet={tr['year_worst_return']:+.2f}% wyMdd={tr['year_worst_mdd']:.2f}% score={tr['score']:+.2f} | "
            f"VAL: ret={va['total_return']:+.2f}% mdd={va['mdd']:.2f}% sharpe={va['sharpe']:+.2f} wyRet={va['year_worst_return']:+.2f}% wyMdd={va['year_worst_mdd']:.2f}% score={va['score']:+.2f}"
        )

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(UTC).isoformat(),
        "train": {"start": args.train_start, "end": args.train_end},
        "val": {"start": args.val_start, "end": args.val_end},
        "fx": float(args.fx),
        "max_trials": int(args.max_trials),
        "kept": len(results),
        "results": results,
    }
    out_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nWrote: {out_path}")


if __name__ == "__main__":
    main()
