#!/usr/bin/env python3
"""Run decision matrix backtests and auto-select a winner.

Usage:
    python scripts/run_decision_matrix.py --start-date 2025-01-01 --end-date 2026-01-23
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest.backtest_mlp import load_strategy_config, MLPDirectionBacktester
from scripts.backtest._common import compute_metrics, load_data
from core.backtester import Backtester
from core.component_adapter import ComponentStrategyAdapter
from trading.strategies.components.strategy_factory import StrategyFactory

ASSET_DB = {
    "BTC": "data/binance_bitcoin.db",
    "ETH": "data/binance_ethereum.db",
    "SOL": "data/binance_solana.db",
    "BNB": "data/binance_bnb.db",
}


ASSETS = ["BTC", "ETH", "SOL", "BNB"]
STRATEGY_IDS = {
    "BTC": "mlp_direction_btc",
    "ETH": "mlp_direction_eth",
    "SOL": "mlp_direction_sol",
    "BNB": "mlp_direction_bnb",
}


@dataclass
class GateConfig:
    min_return_pct: float = 0.0
    max_mdd_pct: float = -20.0
    min_sharpe: float = 0.6
    min_worst_day_pct: float = -5.0
    max_consecutive_down_days: int = 2


def _daily_stats(equity_curve: pd.DataFrame) -> tuple[float, int]:
    """Return (worst_day_pct, max_consecutive_down_days)."""
    df = equity_curve.copy()
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    daily = (
        df.set_index("timestamp")["total_equity"]
        .resample("D")
        .last()
        .dropna()
        .pct_change()
        .dropna()
        * 100.0
    )
    if daily.empty:
        return 0.0, 0

    worst_day = float(daily.min())
    down = daily < 0
    max_streak = 0
    streak = 0
    for flag in down:
        if flag:
            streak += 1
            max_streak = max(max_streak, streak)
        else:
            streak = 0
    return worst_day, max_streak


def _run_portfolio(
    config_path: str,
    start_date: str,
    end_date: str,
    fee_rate: float,
    slippage: float,
) -> dict[str, Any]:
    per_asset: dict[str, dict[str, Any]] = {}
    asset_equity_curves: dict[str, pd.DataFrame] = {}
    asset_regime_masks: dict[str, pd.DataFrame] = {}
    merged_eq: pd.DataFrame | None = None

    for asset in ASSETS:
        _, strategy_id, strategy_cfg = load_strategy_config(
            config_path=config_path,
            symbol=asset,
            mode="paper",
            strategy_id=STRATEGY_IDS[asset],
        )
        db_path = str((Path(__file__).resolve().parent.parent / ASSET_DB[asset]).resolve())
        mlp_bt = MLPDirectionBacktester(
            symbol=asset,
            config=strategy_cfg,
            strategy_label=strategy_id,
        )
        df = load_data(db_path, "minute240", start_date, end_date, exchange="binance")
        df = mlp_bt.prepare_data(df)
        regime_on = (
            (df["mfi"] >= 50.0)
            & (df["adx"] >= 18.0)
            & ((df["ema_200"] <= 0.0) | (df["close"] >= df["ema_200"]))
        )
        regime_df = df[["timestamp"]].copy()
        regime_df["timestamp"] = pd.to_datetime(regime_df["timestamp"])
        regime_df["risk_on"] = regime_on.astype(bool)

        factory = StrategyFactory(redis=None)
        adapter = ComponentStrategyAdapter(
            factory=factory,
            strategy_name="mlp_direction",
            config=strategy_cfg,
        )
        adapter.symbol = asset
        adapter.precompute_mlp_predictions(df)

        bt = Backtester(
            initial_capital=10_000,
            fee_rate=fee_rate,
            slippage=slippage,
        )
        results = bt.run(df, adapter, {})
        metrics = compute_metrics(results.get("equity_curve"), timeframe="minute240")
        metrics["trades"] = int(len(bt.trades))
        per_asset[asset] = metrics

        eq = results["equity_curve"][["timestamp", "total_equity"]].copy()
        eq = eq.rename(columns={"total_equity": f"eq_{asset}"})
        eq["timestamp"] = pd.to_datetime(eq["timestamp"])
        asset_equity_curves[asset] = eq.rename(columns={f"eq_{asset}": "total_equity"})
        asset_regime_masks[asset] = regime_df
        merged_eq = eq if merged_eq is None else merged_eq.merge(eq, on="timestamp", how="inner")

    assert merged_eq is not None
    merged_eq["total_equity"] = merged_eq[[f"eq_{a}" for a in ASSETS]].sum(axis=1)

    portfolio_metrics = compute_metrics(merged_eq[["timestamp", "total_equity"]], timeframe="minute240")
    worst_day, down_streak = _daily_stats(merged_eq[["timestamp", "total_equity"]])
    portfolio_metrics["worst_day_pct"] = worst_day
    portfolio_metrics["max_consecutive_down_days"] = down_streak
    portfolio_metrics["calmar"] = (
        abs(portfolio_metrics["total_return"] / portfolio_metrics["mdd"])
        if portfolio_metrics["mdd"] != 0
        else 0.0
    )
    portfolio_metrics["fee_rate"] = fee_rate
    portfolio_metrics["slippage"] = slippage

    return {
        "portfolio": portfolio_metrics,
        "assets": per_asset,
        "asset_equity_curves": asset_equity_curves,
        "asset_regime_masks": asset_regime_masks,
    }


def _run_switch_portfolio(
    c1_run: dict[str, Any],
    c10_run: dict[str, Any],
) -> dict[str, Any]:
    per_asset: dict[str, dict[str, Any]] = {}
    merged_eq: pd.DataFrame | None = None

    for asset in ASSETS:
        eq1 = c1_run["asset_equity_curves"][asset].copy()
        eq10 = c10_run["asset_equity_curves"][asset].copy()
        regime = c1_run["asset_regime_masks"][asset].copy()

        eq1 = eq1.rename(columns={"total_equity": "eq_c1"})
        eq10 = eq10.rename(columns={"total_equity": "eq_c10"})
        combined = eq1.merge(eq10, on="timestamp", how="inner").merge(regime, on="timestamp", how="inner")
        if combined.empty:
            raise ValueError(f"No overlapping equity/regime data for {asset}")

        combined["ret_c1"] = combined["eq_c1"].pct_change().fillna(0.0)
        combined["ret_c10"] = combined["eq_c10"].pct_change().fillna(0.0)
        active_c1 = combined["risk_on"].shift(1).fillna(False).astype(bool)
        combined["ret_switch"] = np.where(active_c1, combined["ret_c1"], combined["ret_c10"])

        initial_equity = float(combined["eq_c1"].iloc[0])
        combined["eq_switch"] = initial_equity * (1.0 + combined["ret_switch"]).cumprod()

        asset_eq = combined[["timestamp", "eq_switch"]].rename(columns={"eq_switch": "total_equity"})
        per_asset[asset] = compute_metrics(asset_eq, timeframe="minute240")
        merged = asset_eq.rename(columns={"total_equity": f"eq_{asset}"})
        merged_eq = merged if merged_eq is None else merged_eq.merge(merged, on="timestamp", how="inner")

    assert merged_eq is not None
    merged_eq["total_equity"] = merged_eq[[f"eq_{a}" for a in ASSETS]].sum(axis=1)
    portfolio_metrics = compute_metrics(merged_eq[["timestamp", "total_equity"]], timeframe="minute240")
    worst_day, down_streak = _daily_stats(merged_eq[["timestamp", "total_equity"]])
    portfolio_metrics["worst_day_pct"] = worst_day
    portfolio_metrics["max_consecutive_down_days"] = down_streak
    portfolio_metrics["calmar"] = (
        abs(portfolio_metrics["total_return"] / portfolio_metrics["mdd"])
        if portfolio_metrics["mdd"] != 0
        else 0.0
    )
    return {"portfolio": portfolio_metrics, "assets": per_asset}


def _passes_gates(metrics: dict[str, float], gates: GateConfig) -> tuple[bool, list[str]]:
    reasons: list[str] = []
    if metrics["total_return"] <= gates.min_return_pct:
        reasons.append(f"return<= {gates.min_return_pct:.2f}%")
    if metrics["mdd"] < gates.max_mdd_pct:
        reasons.append(f"mdd< {gates.max_mdd_pct:.2f}%")
    if metrics["sharpe"] < gates.min_sharpe:
        reasons.append(f"sharpe< {gates.min_sharpe:.2f}")
    if metrics["worst_day_pct"] < gates.min_worst_day_pct:
        reasons.append(f"worst_day< {gates.min_worst_day_pct:.2f}%")
    if metrics["max_consecutive_down_days"] > gates.max_consecutive_down_days:
        reasons.append(f"down_streak> {gates.max_consecutive_down_days}")
    return len(reasons) == 0, reasons


def main() -> None:
    parser = argparse.ArgumentParser(description="Decision matrix runner for MLP configs")
    parser.add_argument("--start-date", default=None)
    parser.add_argument("--end-date", default=None)
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=120,
        help="Used when start/end are omitted (default: 120)",
    )
    parser.add_argument("--fee-rate", type=float, default=0.001)
    parser.add_argument("--slippage", type=float, default=0.0004)
    parser.add_argument("--c1", default="config/strategies/allocation.c1.json")
    parser.add_argument("--c2", default="config/strategies/allocation.c2.json")
    parser.add_argument("--c3", default="config/strategies/allocation.c3.json")
    parser.add_argument("--c4", default="config/strategies/allocation.c4.json")
    parser.add_argument("--c5", default="config/strategies/allocation.c5.json")
    parser.add_argument("--c6", default="config/strategies/allocation.c6.json")
    parser.add_argument("--c7", default="config/strategies/allocation.c7.json")
    parser.add_argument("--c8", default="config/strategies/allocation.c8.json")
    parser.add_argument("--c9", default="config/strategies/allocation.c9.json")
    parser.add_argument("--c10", default="config/strategies/allocation.c10.json")
    parser.add_argument("--c11", default="config/strategies/allocation.c11.json")
    parser.add_argument(
        "--include-legacy",
        action="store_true",
        help="Include legacy candidate configs (C2..C9) in matrix output",
    )
    parser.add_argument(
        "--include-synthetic-switch",
        action="store_true",
        help="Include synthetic switch curve (C1/C10 blend) for analysis",
    )
    parser.add_argument("--min-return", type=float, default=0.0)
    parser.add_argument("--max-mdd", type=float, default=-20.0)
    parser.add_argument("--min-sharpe", type=float, default=0.6)
    parser.add_argument("--min-worst-day", type=float, default=-5.0)
    parser.add_argument("--max-down-streak", type=int, default=2)
    args = parser.parse_args()

    if args.start_date and args.end_date:
        start_date = args.start_date
        end_date = args.end_date
    else:
        end_dt = datetime.now(timezone.utc).date()
        start_dt = end_dt - timedelta(days=max(args.lookback_days, 1))
        start_date = start_dt.isoformat()
        end_date = end_dt.isoformat()

    gates = GateConfig(
        min_return_pct=args.min_return,
        max_mdd_pct=args.max_mdd,
        min_sharpe=args.min_sharpe,
        min_worst_day_pct=args.min_worst_day,
        max_consecutive_down_days=args.max_down_streak,
    )

    configs: dict[str, str] = {"C1_current_v2_mtf_on_sol6": args.c1}
    optional = {
        "C10_hybrid_alpha_guarded": args.c10,
        "C11_runtime_switch_mode": args.c11,
    }
    for name, path in optional.items():
        if Path(path).exists():
            configs[name] = path

    if args.include_legacy:
        legacy = {
            "C2_v1_mtf_on_sol6": args.c2,
            "C3_v2_mtf_off_sol6": args.c3,
            "C4_conservative_moderate": args.c4,
            "C5_conservative_strict": args.c5,
            "C6_recovery_targeted": args.c6,
            "C7_alpha_first": args.c7,
            "C8_model_refresh_mixed": args.c8,
            "C9_retrained_forward": args.c9,
        }
        for name, path in legacy.items():
            if Path(path).exists():
                configs[name] = path

    runs: dict[str, dict[str, Any]] = {}
    for name, cfg in configs.items():
        if not Path(cfg).exists():
            raise FileNotFoundError(cfg)
        runs[name] = _run_portfolio(
            config_path=cfg,
            start_date=start_date,
            end_date=end_date,
            fee_rate=args.fee_rate,
            slippage=args.slippage,
        )

    if (
        args.include_synthetic_switch
        and "C1_current_v2_mtf_on_sol6" in runs
        and "C10_hybrid_alpha_guarded" in runs
    ):
        runs["C11_switch_c1_c10_regime"] = _run_switch_portfolio(
            c1_run=runs["C1_current_v2_mtf_on_sol6"],
            c10_run=runs["C10_hybrid_alpha_guarded"],
        )

    summary_rows: list[dict[str, Any]] = []
    for name, data in runs.items():
        p = data["portfolio"]
        passed, reasons = _passes_gates(p, gates)
        summary_rows.append(
            {
                "config": name,
                "return_pct": p["total_return"],
                "mdd_pct": p["mdd"],
                "sharpe": p["sharpe"],
                "calmar": p["calmar"],
                "worst_day_pct": p["worst_day_pct"],
                "down_streak_days": p["max_consecutive_down_days"],
                "pass": passed,
                "fail_reasons": "; ".join(reasons) if reasons else "",
            }
        )

    summary = pd.DataFrame(summary_rows).sort_values(
        by=["pass", "calmar", "sharpe"],
        ascending=[False, False, False],
    )

    print(f"\n=== Decision Matrix Summary ({start_date} .. {end_date}) ===")
    print(
        summary[
            [
                "config",
                "return_pct",
                "mdd_pct",
                "sharpe",
                "calmar",
                "worst_day_pct",
                "down_streak_days",
                "pass",
                "fail_reasons",
            ]
        ].to_string(
            index=False,
            formatters={
                "return_pct": "{:+.2f}%".format,
                "mdd_pct": "{:.2f}%".format,
                "sharpe": "{:.2f}".format,
                "calmar": "{:.2f}".format,
                "worst_day_pct": "{:.2f}%".format,
            },
        )
    )

    passing = summary[summary["pass"]]
    if passing.empty:
        print("\nWinner: NONE (no config passed all gates)")
        return

    winner = passing.iloc[0]
    print(f"\nWinner: {winner['config']}")

    c1 = summary[summary["config"] == "C1_current_v2_mtf_on_sol6"].iloc[0]
    if winner["config"] != "C1_current_v2_mtf_on_sol6":
        calmar_gain = (winner["calmar"] - c1["calmar"]) / max(abs(c1["calmar"]), 1e-9)
        mdd_not_worse = winner["mdd_pct"] >= c1["mdd_pct"]
        promote = calmar_gain >= 0.15 and mdd_not_worse
        print(
            "Promotion check vs C1: "
            f"calmar_gain={calmar_gain*100:.1f}%, mdd_not_worse={mdd_not_worse}, promote={promote}"
        )


if __name__ == "__main__":
    main()
