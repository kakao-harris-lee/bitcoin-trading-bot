#!/usr/bin/env python3
"""Diagnose why tuner validation metrics look flat.

This script loads the tuning results JSON and replays a handful of candidates on
validation period, printing:
- per-leg trade counts and returns (Upbit/Binance)
- combined return
- overlap length of merged daily equity curves
- regime distribution counts for the validation window

It avoids heredoc usage and is safe to run from terminal.
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pandas as pd

import sys

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from core.data_loader import DataLoader
from live_trading.regime_router import RegimeRouter as LiveRegimeRouter
from live_trading.regime_router import _calc_adx as _live_calc_adx
from live_trading.regime_router import _calc_mfi as _live_calc_mfi
from trading_engine_v2.scripts.backtest_operational_portfolio import (
    BearOnlyShortWrapper,
    PortfolioBacktestConfig,
    ShortMarginBacktester,
    _to_daily_last,
)
from trading_engine_v2.scripts.backtest_v2_strategies import RegimeRouterLiveAdapter
from core.backtester import Backtester


@dataclass
class Candidate:
    router_config: Dict[str, float]
    sideways_policy: str
    sideways_bear_policy: str
    binance_gate_mode: str
    sideways_v2_config: Dict[str, Any]
    v35_fraction_mult: float
    sideways_fraction_mult: float
    binance_fraction_mult: float


def _slice_by_date(df: pd.DataFrame, start_date: str, end_date: str) -> pd.DataFrame:
    ts = pd.to_datetime(df["timestamp"])
    mask = (ts >= pd.Timestamp(start_date)) & (ts <= pd.Timestamp(end_date))
    return df.loc[mask].reset_index(drop=True)


def _equity_return_pct(eq: pd.DataFrame) -> float:
    if eq is None or eq.empty:
        return 0.0
    start = float(eq["total_equity"].iloc[0])
    end = float(eq["total_equity"].iloc[-1])
    return ((end - start) / start) * 100 if start > 0 else 0.0


def _num_trades(result: Dict[str, Any]) -> int:
    trades = result.get("trades")
    if isinstance(trades, list):
        return int(len(trades))
    if "num_trades" in result:
        return int(result["num_trades"])
    return 0


def _regime_counts(df_day: pd.DataFrame, cand: Candidate) -> Tuple[Dict[str, int], Dict[str, int]]:
    router = LiveRegimeRouter(
        mfi_bull=float(cand.router_config["mfi_bull"]),
        mfi_bear=float(cand.router_config["mfi_bear"]),
        adx_strong=float(cand.router_config["adx_strong"]),
        adx_trend=float(cand.router_config["adx_trend"]),
        adx_weak=float(cand.router_config["adx_weak"]),
    )

    df = df_day.copy()
    df["mfi"] = _live_calc_mfi(df, period=router.mfi_period)
    df["adx"] = _live_calc_adx(df, period=router.adx_period)

    states: List[str] = [
        router.classify_from_values(float(m), float(a))
        for m, a in zip(df["mfi"].to_numpy(), df["adx"].to_numpy())
    ]

    state_counts: Dict[str, int] = {}
    regime_counts: Dict[str, int] = {"BULL": 0, "SIDEWAYS": 0, "BEAR": 0}

    for s in states:
        state_counts[s] = state_counts.get(s, 0) + 1
        if str(s).startswith("BULL"):
            regime_counts["BULL"] += 1
        elif str(s).startswith("SIDEWAYS"):
            regime_counts["SIDEWAYS"] += 1
        else:
            regime_counts["BEAR"] += 1

    return regime_counts, state_counts


def _run_candidate(cfg: PortfolioBacktestConfig, df_day: pd.DataFrame, df_h4: pd.DataFrame, cand: Candidate) -> Dict[str, Any]:
    upbit_strategy = RegimeRouterLiveAdapter(
        timeframe="day",
        router_config=cand.router_config,
        sideways_policy=cand.sideways_policy,
        sideways_bear_policy=cand.sideways_bear_policy,
        v35_fraction_mult=cand.v35_fraction_mult,
        sideways_fraction_mult=cand.sideways_fraction_mult,
        sideways_v2_config=cand.sideways_v2_config,
    )
    upbit_bt = Backtester(initial_capital=cfg.upbit_capital_krw, fee_rate=0.0005, slippage=0.0002)
    up = upbit_bt.run(df_day, upbit_strategy, {})

    router = LiveRegimeRouter(
        mfi_bull=float(cand.router_config["mfi_bull"]),
        mfi_bear=float(cand.router_config["mfi_bear"]),
        adx_strong=float(cand.router_config["adx_strong"]),
        adx_trend=float(cand.router_config["adx_trend"]),
        adx_weak=float(cand.router_config["adx_weak"]),
    )

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
        gate_mode=cand.binance_gate_mode,
        fraction_mult=cand.binance_fraction_mult,
    )
    short_bt = ShortMarginBacktester(initial_capital=cfg.binance_capital_usdt, fee_rate=0.0005, slippage=0.0002)
    bn = short_bt.run(df_h4, gated_short, {})

    up_daily = _to_daily_last(up["equity_curve"])
    bn_daily = _to_daily_last(bn["equity_curve"])

    combined = up_daily.merge(bn_daily, on="timestamp", how="inner", suffixes=("_upbit", "_binance"))
    combined["total_equity"] = combined["total_equity_upbit"] + (combined["total_equity_binance"] * cfg.fx_krw_per_usdt)

    return {
        "upbit_trades": _num_trades(up),
        "binance_trades": _num_trades(bn),
        "upbit_ret": _equity_return_pct(up["equity_curve"]),
        "binance_ret": _equity_return_pct(bn["equity_curve"]),
        "combined_days": int(len(combined)),
        "combined_ret": _equity_return_pct(combined[["timestamp", "total_equity"]]),
    }


def _pick_indices(n: int) -> List[int]:
    if n <= 0:
        return []
    if n == 1:
        return [0]
    if n == 2:
        return [0, n - 1]
    return [0, n // 2, n - 1]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--db-path", default=str(PROJECT_ROOT / "upbit_history_db" / "upbit_bitcoin.db"))
    p.add_argument("--tuning-json", default=str(PROJECT_ROOT / "analysis" / "tune_operational_router_results.json"))
    p.add_argument("--val-start", default="2025-01-01")
    p.add_argument("--val-end", default="2025-12-11")
    p.add_argument("--fx", type=float, default=1300.0)
    p.add_argument("--samples", type=int, default=3, help="How many candidates to replay: 3 -> top/mid/bottom")
    args = p.parse_args()

    tuning_path = Path(args.tuning_json)
    obj = json.loads(tuning_path.read_text(encoding="utf-8"))
    results = obj.get("results", [])
    if not results:
        raise SystemExit(f"No results in {tuning_path}")

    # sort as tuner does
    results = sorted(results, key=lambda r: (r["val"]["score"], r["train"]["score"]), reverse=True)

    cfg = PortfolioBacktestConfig(
        db_path=Path(args.db_path),
        start_date=None,
        end_date=None,
        upbit_capital_krw=10_000_000,
        binance_capital_usdt=10_000,
        fx_krw_per_usdt=float(args.fx),
    )

    with DataLoader(str(cfg.db_path)) as loader:
        df_day = loader.load_timeframe("day", args.val_start, args.val_end)
        h4_start, h4_end = loader.get_date_range("minute240")
        start_h4 = max(pd.Timestamp(args.val_start), pd.Timestamp(h4_start)).strftime("%Y-%m-%d")
        end_h4 = min(pd.Timestamp(args.val_end), pd.Timestamp(h4_end)).strftime("%Y-%m-%d")
        df_h4 = loader.load_timeframe("minute240", start_h4, end_h4)

    print(f"val df_day rows={len(df_day)} df_h4 rows={len(df_h4)}")

    # choose indices
    n = len(results)
    if args.samples <= 3:
        idxs = _pick_indices(n)
    else:
        step = max(1, n // args.samples)
        idxs = list(range(0, n, step))[: args.samples]

    for rank, idx in enumerate(idxs, start=1):
        r = results[idx]
        c = r["candidate"]
        cand = Candidate(
            router_config=c["router_config"],
            sideways_policy=c["sideways_policy"],
            sideways_bear_policy=c["sideways_bear_policy"],
            binance_gate_mode=c["binance_gate_mode"],
            sideways_v2_config=c.get("sideways_v2_config", {}),
            v35_fraction_mult=float(c.get("v35_fraction_mult", 1.0)),
            sideways_fraction_mult=float(c.get("sideways_fraction_mult", 1.0)),
            binance_fraction_mult=float(c.get("binance_fraction_mult", 1.0)),
        )

        reg_counts, state_counts = _regime_counts(df_day, cand)
        per_leg = _run_candidate(cfg, df_day, df_h4, cand)

        print("\n" + "-" * 100)
        print(f"sample#{rank} pick_index={idx} val.score={r['val']['score']:.4f} val.ret={r['val']['total_return']:+.3f}%")
        print(
            "cfg",
            {
                "sideways_policy": cand.sideways_policy,
                "sideways_bear_policy": cand.sideways_bear_policy,
                "binance_gate_mode": cand.binance_gate_mode,
                "router_config": cand.router_config,
                "mult": (cand.v35_fraction_mult, cand.sideways_fraction_mult, cand.binance_fraction_mult),
                "sw2": cand.sideways_v2_config,
            },
        )
        print("per_leg", per_leg)
        print("regime_counts", reg_counts)
        # compact state view
        top_states = sorted(state_counts.items(), key=lambda kv: kv[1], reverse=True)[:5]
        print("top_states", top_states)


if __name__ == "__main__":
    main()
