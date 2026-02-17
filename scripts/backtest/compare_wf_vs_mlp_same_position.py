#!/usr/bin/env python3
"""Compare WF Tree60 and MLP Direction with the same position sizing.

Example:
    python scripts/backtest/compare_wf_vs_mlp_same_position.py --assets BTC ETH
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import compute_metrics, load_data
from scripts.backtest.backtest_mlp import load_strategy_config, run_backtest
from scripts.backtest.walkforward_backtest import (
    ASSET_DB,
    get_wf_tree60_asset_defaults,
    run_walkforward_asset,
)


def _bh_return_pct(asset: str, start_date: str, end_date: str) -> float:
    db_file, _ = ASSET_DB[asset]
    df = load_data(
        str(PROJECT_ROOT / db_file),
        "minute240",
        start_date,
        end_date,
        exchange="binance",
    )
    if df.empty:
        return 0.0
    first = float(df["close"].iloc[0])
    last = float(df["close"].iloc[-1])
    if first <= 0:
        return 0.0
    return ((last / first) - 1.0) * 100.0


def _apply_same_position(config: dict[str, Any], position_pct: float) -> dict[str, Any]:
    cfg = copy.deepcopy(config)
    cfg["position_pct"] = position_pct
    cfg["position_size"] = position_pct

    vol_cfg = cfg.get("volatility_sizing")
    if isinstance(vol_cfg, dict):
        vol_cfg["enabled"] = False

    entry = cfg.get("entry")
    if isinstance(entry, dict):
        entry_params = entry.setdefault("params", {})
        entry_params["position_size"] = position_pct
        entry_params["risk_on_position_size"] = position_pct
        entry_params["risk_off_position_size"] = position_pct

    return cfg


def _row(
    asset: str,
    strategy: str,
    position_pct: float,
    ret: float,
    mdd: float,
    sharpe: float,
    trades: int,
    bh: float,
) -> dict[str, Any]:
    return {
        "asset": asset,
        "strategy": strategy,
        "position_pct": position_pct * 100.0,
        "return_pct": ret,
        "mdd_pct": mdd,
        "sharpe": sharpe,
        "trades": trades,
        "bh_return_pct": bh,
        "alpha_vs_bh_pct": ret - bh,
    }


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Compare wf_tree60 vs mlp_direction with same position sizing"
    )
    parser.add_argument("--assets", nargs="+", default=["BTC", "ETH"], choices=list(ASSET_DB.keys()))
    parser.add_argument("--start-date", default="2024-01-01")
    parser.add_argument("--end-date", default="2024-12-31")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument(
        "--position-pct",
        type=float,
        default=0.8,
        help="Same position fraction for both strategies (default: 0.8)",
    )
    parser.add_argument("--n-splits", type=int, default=7)
    parser.add_argument("--max-train-folds", type=int, default=3)
    parser.add_argument("--temporal-decay", type=float, default=2.0)
    parser.add_argument("--xgb-rounds", type=int, default=500)
    parser.add_argument("--lgb-rounds", type=int, default=500)
    args = parser.parse_args()

    rows: list[dict[str, Any]] = []
    for asset in args.assets:
        print(f"\n[{asset}] running wf_tree60...", flush=True)
        wf_defaults = get_wf_tree60_asset_defaults(asset)
        wf_result = run_walkforward_asset(
            asset=asset,
            start_date=args.start_date,
            end_date=args.end_date,
            capital=args.capital,
            n_splits=args.n_splits,
            max_train_folds=args.max_train_folds,
            temporal_decay=args.temporal_decay,
            xgb_rounds=args.xgb_rounds,
            lgb_rounds=args.lgb_rounds,
            position_size=args.position_pct,
            cooldown_reentry_enabled=wf_defaults["cooldown_reentry_enabled"],
            cooldown_reentry_requires_buy=wf_defaults["cooldown_reentry_requires_buy"],
            trailing_drawdown_exit_pct=wf_defaults["trailing_drawdown_exit_pct"],
            min_bars_after_risk_exit=wf_defaults["min_bars_after_risk_exit"],
            reentry_trend_filter_enabled=wf_defaults["reentry_trend_filter_enabled"],
            reentry_ema_span=wf_defaults["reentry_ema_span"],
            reentry_require_ema_rising=wf_defaults["reentry_require_ema_rising"],
            staged_reentry_enabled=wf_defaults["staged_reentry_enabled"],
            reentry_stage1_fraction=wf_defaults["reentry_stage1_fraction"],
            reentry_stage2_fraction=wf_defaults["reentry_stage2_fraction"],
            stage2_confirm_bars=wf_defaults["stage2_confirm_bars"],
            stage2_trigger_pct=wf_defaults["stage2_trigger_pct"],
        )
        wf_metrics = wf_result.get("metrics", {}) if wf_result else {}
        wf_ret = float(wf_metrics.get("total_return", 0.0))
        wf_mdd = float(wf_metrics.get("mdd", 0.0))
        wf_sharpe = float(wf_metrics.get("sharpe", 0.0))
        wf_trades = int(wf_metrics.get("num_trades", 0))

        bh_ret = _bh_return_pct(asset, args.start_date, args.end_date)
        rows.append(
            _row(
                asset=asset,
                strategy=f"wf_tree60_{asset.lower()}",
                position_pct=args.position_pct,
                ret=wf_ret,
                mdd=wf_mdd,
                sharpe=wf_sharpe,
                trades=wf_trades,
                bh=bh_ret,
            )
        )

        print(f"[{asset}] running mlp_direction...", flush=True)
        _, strategy_id, strategy_config = load_strategy_config(
            config_path=str(PROJECT_ROOT / "config" / "strategies" / "allocation.json"),
            symbol=asset,
            mode="paper",
            strategy_id=f"mlp_direction_{asset.lower()}",
        )
        strategy_config = _apply_same_position(strategy_config, args.position_pct)
        mlp_results = run_backtest(
            symbol=asset,
            db_path="",
            start_date=args.start_date,
            end_date=args.end_date,
            timeframe="minute240",
            initial_capital=args.capital,
            strategy_config=strategy_config,
            entry_overrides={
                "position_size": args.position_pct,
                "risk_on_position_size": args.position_pct,
                "risk_off_position_size": args.position_pct,
            },
            exit_overrides={},
            strategy_label=f"{strategy_id}_same_position",
        )
        mlp_metrics = compute_metrics(mlp_results.get("equity_curve"), timeframe="minute240")
        rows.append(
            _row(
                asset=asset,
                strategy=f"mlp_direction_{asset.lower()}",
                position_pct=args.position_pct,
                ret=float(mlp_metrics.get("total_return", 0.0)),
                mdd=float(mlp_metrics.get("mdd", 0.0)),
                sharpe=float(mlp_metrics.get("sharpe", 0.0)),
                trades=int(mlp_results.get("total_trades", 0)),
                bh=bh_ret,
            )
        )

    df = pd.DataFrame(rows)
    df = df.sort_values(["asset", "strategy"]).reset_index(drop=True)

    reports_dir = PROJECT_ROOT / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    period = f"{args.start_date}_{args.end_date}".replace("-", "")
    base = reports_dir / f"wf_vs_mlp_same_position_{int(args.position_pct*100)}pct_{period}_{stamp}"

    csv_path = base.with_suffix(".csv")
    json_path = base.with_suffix(".json")
    md_path = base.with_suffix(".md")

    df.to_csv(csv_path, index=False)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "capital": args.capital,
        "same_position_pct": args.position_pct * 100.0,
        "rows": rows,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    lines = [
        "# WF Tree60 vs MLP Direction (Same Position)",
        "",
        f"- Period: {args.start_date} ~ {args.end_date}",
        f"- Capital: {args.capital:.0f}",
        f"- Same position: {args.position_pct * 100.0:.1f}%",
        "",
        "| Asset | Strategy | Position % | Return % | MDD % | Sharpe | Trades | B&H % | Alpha vs B&H % |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for _, row_data in df.iterrows():
        lines.append(
            "| "
            f"{row_data['asset']} | {row_data['strategy']} | {row_data['position_pct']:.1f} | "
            f"{row_data['return_pct']:.2f} | {row_data['mdd_pct']:.2f} | {row_data['sharpe']:.2f} | "
            f"{int(row_data['trades'])} | {row_data['bh_return_pct']:.2f} | {row_data['alpha_vs_bh_pct']:.2f} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print("\nWROTE", csv_path.relative_to(PROJECT_ROOT))
    print("WROTE", json_path.relative_to(PROJECT_ROOT))
    print("WROTE", md_path.relative_to(PROJECT_ROOT))
    print("\nSUMMARY")
    print(df.to_string(index=False))


if __name__ == "__main__":
    main()
