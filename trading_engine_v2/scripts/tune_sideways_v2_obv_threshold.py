#!/usr/bin/env python3
"""Tune SideWays_v2 OBV filter threshold (narrow range).

Goal: reduce MDD on 4H (minute240) by tuning only `obv_downtrend_threshold`.

- Uses core.DataLoader + core.Backtester (same as other runners)
- Scales day-semantics hold settings to bar counts for intraday timeframes

Example:
  .venv/bin/python trading_engine_v2/scripts/tune_sideways_v2_obv_threshold.py \
    --timeframe minute240 --train 2020-01-01 2024-12-31 --valid 2025-01-01 2025-12-11 \
    --center -0.05 --step 0.005 --steps 5 --min-trades 40
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Tuple

import sys

import numpy as np
import pandas as pd

# Path bootstrap (same pattern as backtest_v2_strategies.py)
PROJECT_ROOT = Path(__file__).parent.parent.parent

sys.path.insert(0, str(PROJECT_ROOT))

from core.data_loader import DataLoader
from core.backtester import Backtester
from trading_engine_v2.modules.strategies.sideways_v2 import SideWaysV2Strategy


def _bars_per_day(timeframe: str) -> int:
    if timeframe == "day":
        return 1
    if timeframe.startswith("minute"):
        minutes = int(timeframe.replace("minute", ""))
        return int(round(24 * 60 / minutes)) if minutes > 0 else 1
    return 1


def _compute_mdd(equity_curve: pd.DataFrame) -> float:
    if equity_curve is None or equity_curve.empty:
        return 0.0
    peak = equity_curve["total_equity"].cummax()
    drawdown = (equity_curve["total_equity"] - peak) / peak * 100
    return float(drawdown.min())


def _compute_sharpe(equity_curve: pd.DataFrame) -> float:
    if equity_curve is None or equity_curve.empty:
        return 0.0
    daily_returns = equity_curve["total_equity"].pct_change().dropna()
    if len(daily_returns) < 2 or daily_returns.std() == 0:
        return 0.0
    return float((daily_returns.mean() / daily_returns.std()) * np.sqrt(252))


class _SideWaysV2Adapter:
    def __init__(self, strategy_config: Dict, timeframe: str):
        self.strategy = SideWaysV2Strategy(strategy_config=strategy_config)
        self.timeframe = timeframe
        self._cached_df = None

    def __call__(self, df: pd.DataFrame, i: int, params: Dict) -> Dict:
        if i < 30:
            return {"action": "hold"}

        if self._cached_df is None or len(df) != len(self._cached_df):
            self._cached_df = self.strategy.add_indicators(df)

        signal = self.strategy.generate_signal(self._cached_df, i)
        return signal or {"action": "hold"}


@dataclass
class RunMetrics:
    threshold: float
    total_return: float
    total_trades: int
    win_rate: float
    mdd: float
    sharpe: float


def _run_backtest(
    loader: DataLoader,
    timeframe: str,
    start_date: str,
    end_date: str,
    strategy_config: Dict,
    initial_capital: float = 10_000_000,
) -> Dict:
    df = loader.load_timeframe(timeframe, start_date, end_date)

    backtester = Backtester(
        initial_capital=initial_capital,
        fee_rate=0.0005,
        slippage=0.0002,
    )

    adapter = _SideWaysV2Adapter(strategy_config=strategy_config, timeframe=timeframe)
    results = backtester.run(df, adapter, {})

    # add derived metrics
    eq = results.get("equity_curve")
    if isinstance(eq, pd.DataFrame):
        results["mdd"] = _compute_mdd(eq)
        results["sharpe"] = _compute_sharpe(eq)
    else:
        results["mdd"] = 0.0
        results["sharpe"] = 0.0

    return results


def _make_strategy_config_for_timeframe(timeframe: str, obv_threshold: float) -> Dict:
    # SideWaysV2Strategy.DEFAULT_CONFIG uses "bars" but was originally day semantics.
    # We preserve semantics when running intraday by scaling these hold values.
    bpd = _bars_per_day(timeframe)
    max_hold_days = 20
    min_hold_days_for_tp1 = 5

    cfg = {
        "obv_downtrend_threshold": float(obv_threshold),
        "max_hold_bars": int(round(max_hold_days * bpd)),
        "min_hold_bars_for_tp1": int(round(min_hold_days_for_tp1 * bpd)),
    }

    return cfg


def _score_for_selection(mdd: float, total_return: float) -> float:
    # Primary: reduce drawdown magnitude (mdd is negative). Secondary: prefer higher return.
    # Higher score is better.
    return (-abs(mdd)) + (0.02 * total_return)


def main() -> int:
    parser = argparse.ArgumentParser(description="Tune SideWays_v2 OBV filter threshold")
    parser.add_argument("--timeframe", default="minute240")
    parser.add_argument("--db-path", default=str(PROJECT_ROOT / "upbit_history_db" / "upbit_bitcoin.db"))

    parser.add_argument("--train", nargs=2, metavar=("START", "END"), default=["2020-01-01", "2024-12-31"])
    parser.add_argument("--valid", nargs=2, metavar=("START", "END"), default=["2025-01-01", "2025-12-11"])

    parser.add_argument("--center", type=float, default=-0.05)
    parser.add_argument("--step", type=float, default=0.005)
    parser.add_argument("--steps", type=int, default=5, help="Try center±step*steps")

    parser.add_argument("--min-trades", type=int, default=40)
    parser.add_argument("--min-return", type=float, default=0.0)

    args = parser.parse_args()

    timeframe = args.timeframe
    train_start, train_end = args.train
    valid_start, valid_end = args.valid

    thresholds: List[float] = []
    for k in range(-args.steps, args.steps + 1):
        thresholds.append(round(args.center + k * args.step, 6))

    print("=" * 80)
    print("SideWays_v2 OBV threshold tuning")
    print(f"timeframe={timeframe}")
    print(f"train={train_start}~{train_end}  valid={valid_start}~{valid_end}")
    print(f"grid center={args.center} step={args.step} steps={args.steps}")
    print(f"constraints: min_trades>={args.min_trades}, min_return>={args.min_return}%")
    print("=" * 80)

    loader = DataLoader(args.db_path)

    rows: List[RunMetrics] = []
    try:
        for t in thresholds:
            cfg = _make_strategy_config_for_timeframe(timeframe, t)
            res = _run_backtest(loader, timeframe, train_start, train_end, cfg)

            total_trades = int(res.get("total_trades", 0))
            total_return = float(res.get("total_return", 0.0))
            win_rate = float(res.get("win_rate", 0.0))
            mdd = float(res.get("mdd", 0.0))
            sharpe = float(res.get("sharpe", 0.0))

            rows.append(
                RunMetrics(
                    threshold=t,
                    total_return=total_return,
                    total_trades=total_trades,
                    win_rate=win_rate,
                    mdd=mdd,
                    sharpe=sharpe,
                )
            )

        df = pd.DataFrame([r.__dict__ for r in rows])
        df["score"] = df.apply(lambda r: _score_for_selection(r["mdd"], r["total_return"]), axis=1)

        # Apply constraints
        candidates = df[(df["total_trades"] >= args.min_trades) & (df["total_return"] >= args.min_return)]
        if candidates.empty:
            print("\nNo candidates met constraints; showing full grid sorted by (mdd desc, return desc).")
            print(df.sort_values(["mdd", "total_return"], ascending=[False, False]).to_string(index=False))
            return 2

        best = candidates.sort_values(["mdd", "total_return"], ascending=[False, False]).iloc[0]
        best_t = float(best["threshold"])

        print("\n[TRAIN grid results] (sorted by mdd desc, return desc)")
        print(candidates.sort_values(["mdd", "total_return"], ascending=[False, False]).to_string(index=False))

        print("\nBest on TRAIN:")
        print(best.to_string())

        # Validation
        cfg_best = _make_strategy_config_for_timeframe(timeframe, best_t)
        valid_res = _run_backtest(loader, timeframe, valid_start, valid_end, cfg_best)
        print("\n[VALID] best threshold run")
        print(
            f"threshold={best_t}  return={valid_res.get('total_return', 0):.2f}%  "
            f"trades={valid_res.get('total_trades', 0)}  "
            f"mdd={valid_res.get('mdd', 0):.2f}%  sharpe={valid_res.get('sharpe', 0):.2f}"
        )

        print("\nRecommended obv_downtrend_threshold:")
        print(best_t)

        return 0
    finally:
        try:
            loader.conn.close()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
