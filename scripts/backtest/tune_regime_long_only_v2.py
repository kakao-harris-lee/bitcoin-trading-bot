#!/usr/bin/env python3
"""Grid-search tuning for Regime Long-Only Swing strategy.

Objective:
- maximize mean alpha vs B&H across selected symbols.
- no hard MDD constraint in this stage (user requested return-first exploration).
"""

from __future__ import annotations

import argparse
import itertools
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import compute_metrics, load_data
from scripts.backtest.compare_regime_long_only_v1 import (
    ASSET_DB,
    RegimeParams,
    _build_bnh_equity,
    _to_daily,
    run_regime_long_only,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Tune Regime Long-Only Swing parameters")
    parser.add_argument("--start-date", default="2021-01-01")
    parser.add_argument("--end-date", default="2026-02-13")
    parser.add_argument("--symbols", nargs="+", default=["BTC", "ETH", "SOL", "BNB"])
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument("--output-dir", default="reports")
    parser.add_argument("--top-k", type=int, default=20)
    parser.add_argument("--fee-rate", type=float, default=0.001)
    return parser.parse_args()


def _load_daily_frames(symbols: list[str], start_date: str, end_date: str) -> dict[str, pd.DataFrame]:
    daily_by_symbol: dict[str, pd.DataFrame] = {}
    for symbol in symbols:
        db_path = ASSET_DB.get(symbol)
        if db_path is None or not db_path.exists():
            continue
        df_4h = load_data(
            db_path=str(db_path),
            timeframe="minute240",
            start_date=start_date,
            end_date=end_date,
            exchange="binance",
        )
        if df_4h.empty:
            continue
        daily = _to_daily(df_4h)
        if len(daily) < 200:
            continue
        daily_by_symbol[symbol] = daily
    return daily_by_symbol


def _build_bnh_returns(
    daily_by_symbol: dict[str, pd.DataFrame],
    capital: float,
) -> dict[str, float]:
    out: dict[str, float] = {}
    for symbol, daily in daily_by_symbol.items():
        bnh_eq = _build_bnh_equity(daily, capital)
        bnh_metrics = compute_metrics(bnh_eq, timeframe="day")
        out[symbol] = float(bnh_metrics["total_return"])
    return out


def _grid() -> list[dict[str, Any]]:
    entry_quorum = [2, 3, 4]
    drop_1d = [-0.05, -0.06, -0.07]
    drop_3d = [-0.08, -0.10, -0.12]
    peak_dd = [0.10, 0.12, 0.15]
    cooldown = [1, 3, 5]

    combos: list[dict[str, Any]] = []
    for q, d1, d3, pdd, cd in itertools.product(
        entry_quorum, drop_1d, drop_3d, peak_dd, cooldown
    ):
        combos.append(
            {
                "entry_quorum": q,
                "drop_1d_pct": d1,
                "drop_3d_pct": d3,
                "peak_dd_exit_pct": pdd,
                "cooldown_days": cd,
            }
        )
    return combos


def main() -> int:
    args = parse_args()
    symbols = [s.upper() for s in args.symbols]
    daily_by_symbol = _load_daily_frames(symbols, args.start_date, args.end_date)
    if not daily_by_symbol:
        print("No valid symbol data loaded.")
        return 1

    bnh_returns = _build_bnh_returns(daily_by_symbol, args.capital)
    combos = _grid()
    rows: list[dict[str, Any]] = []

    for i, combo in enumerate(combos, 1):
        symbol_rows: list[dict[str, Any]] = []
        for symbol, daily in daily_by_symbol.items():
            p = RegimeParams(
                entry_lookback_days=4,
                entry_quorum=int(combo["entry_quorum"]),
                drop_1d_pct=float(combo["drop_1d_pct"]),
                drop_3d_pct=float(combo["drop_3d_pct"]),
                peak_dd_exit_pct=float(combo["peak_dd_exit_pct"]),
                cooldown_days=int(combo["cooldown_days"]),
                fee_rate=float(args.fee_rate),
            )
            result = run_regime_long_only(daily=daily, capital=args.capital, p=p)
            alpha = float(result["total_return_pct"] - bnh_returns[symbol])
            symbol_rows.append(
                {
                    "symbol": symbol,
                    "return_pct": float(result["total_return_pct"]),
                    "alpha_vs_bnh_pctp": alpha,
                    "mdd_pct": float(result["mdd_pct"]),
                    "trades": int(result["trades"]),
                    "win_rate_pct": float(result["win_rate_pct"]),
                }
            )

        df_sym = pd.DataFrame(symbol_rows)
        rows.append(
            {
                "trial": i,
                **combo,
                "mean_return_pct": float(df_sym["return_pct"].mean()),
                "mean_alpha_vs_bnh_pctp": float(df_sym["alpha_vs_bnh_pctp"].mean()),
                "mean_mdd_pct": float(df_sym["mdd_pct"].mean()),
                "max_symbol_mdd_pct": float(df_sym["mdd_pct"].max()),
                "total_trades": int(df_sym["trades"].sum()),
                "mean_win_rate_pct": float(df_sym["win_rate_pct"].mean()),
                "beating_symbols": int((df_sym["alpha_vs_bnh_pctp"] > 0).sum()),
                "per_symbol": symbol_rows,
            }
        )

    ranking = pd.DataFrame(rows).sort_values(
        by=["mean_alpha_vs_bnh_pctp", "mean_return_pct", "beating_symbols"],
        ascending=[False, False, False],
    )
    top = ranking.head(args.top_k).copy()

    best = rows[int(top.iloc[0]["trial"]) - 1]
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_dir = PROJECT_ROOT / args.output_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / f"regime_long_only_v2_tuning_{ts}.csv"
    json_path = out_dir / f"regime_long_only_v2_tuning_{ts}.json"
    md_path = out_dir / f"regime_long_only_v2_tuning_{ts}.md"
    tuned_path = PROJECT_ROOT / "config" / "tuned" / f"regime_long_only_v2_best_{ts}.json"
    tuned_path.parent.mkdir(parents=True, exist_ok=True)

    top.drop(columns=["per_symbol"]).to_csv(csv_path, index=False)
    payload = {
        "generated_at": datetime.now().isoformat(),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "symbols": list(daily_by_symbol.keys()),
        "objective": "maximize mean_alpha_vs_bnh_pctp",
        "search_space_size": len(combos),
        "top_k": int(args.top_k),
        "top_trials": rows[:0] + [rows[int(t) - 1] for t in top["trial"].tolist()],
        "best_trial": best,
    }
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    tuned_path.write_text(
        json.dumps(
            {
                "meta": {
                    "generated_at": datetime.now().isoformat(),
                    "source_report": str(json_path.relative_to(PROJECT_ROOT)),
                    "objective": "maximize mean alpha vs B&H",
                },
                "params": {
                    "entry_lookback_days": 4,
                    "entry_quorum": best["entry_quorum"],
                    "drop_1d_pct": best["drop_1d_pct"],
                    "drop_3d_pct": best["drop_3d_pct"],
                    "peak_dd_exit_pct": best["peak_dd_exit_pct"],
                    "cooldown_days": best["cooldown_days"],
                    "fee_rate": args.fee_rate,
                },
                "summary": {
                    "mean_return_pct": best["mean_return_pct"],
                    "mean_alpha_vs_bnh_pctp": best["mean_alpha_vs_bnh_pctp"],
                    "mean_mdd_pct": best["mean_mdd_pct"],
                    "max_symbol_mdd_pct": best["max_symbol_mdd_pct"],
                    "beating_symbols": best["beating_symbols"],
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    lines: list[str] = []
    lines.append("# Regime Long-Only v2 Tuning")
    lines.append("")
    lines.append(f"- Generated: {payload['generated_at']}")
    lines.append(f"- Period: {args.start_date} to {args.end_date}")
    lines.append(f"- Symbols: {', '.join(payload['symbols'])}")
    lines.append(f"- Search space: {len(combos)}")
    lines.append("")
    lines.append("## Best Trial")
    lines.append("")
    lines.append(f"- entry_quorum: {best['entry_quorum']}")
    lines.append(f"- drop_1d_pct: {best['drop_1d_pct']}")
    lines.append(f"- drop_3d_pct: {best['drop_3d_pct']}")
    lines.append(f"- peak_dd_exit_pct: {best['peak_dd_exit_pct']}")
    lines.append(f"- cooldown_days: {best['cooldown_days']}")
    lines.append("")
    lines.append(
        f"- mean_return_pct: {best['mean_return_pct']:.2f}, "
        f"mean_alpha_vs_bnh_pctp: {best['mean_alpha_vs_bnh_pctp']:.2f}, "
        f"mean_mdd_pct: {best['mean_mdd_pct']:.2f}, beating_symbols: {best['beating_symbols']}"
    )
    lines.append("")
    lines.append("## Top Trials")
    lines.append("")
    lines.append("| Trial | entry_quorum | drop_1d_pct | drop_3d_pct | peak_dd_exit_pct | cooldown_days | Mean Return % | Mean Alpha vs B&H %p | Mean MDD % | Beating Symbols |")
    lines.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for _, r in top.iterrows():
        lines.append(
            f"| {int(r['trial'])} | {int(r['entry_quorum'])} | {r['drop_1d_pct']:.3f} | "
            f"{r['drop_3d_pct']:.3f} | {r['peak_dd_exit_pct']:.3f} | {int(r['cooldown_days'])} | "
            f"{r['mean_return_pct']:.2f} | {r['mean_alpha_vs_bnh_pctp']:.2f} | {r['mean_mdd_pct']:.2f} | "
            f"{int(r['beating_symbols'])} |"
        )
    md_path.write_text("\n".join(lines), encoding="utf-8")

    print(f"Saved: {csv_path}")
    print(f"Saved: {json_path}")
    print(f"Saved: {md_path}")
    print(f"Saved: {tuned_path}")
    print("\nBest trial:")
    best_params = {
        "entry_quorum": int(best["entry_quorum"]),
        "drop_1d_pct": float(best["drop_1d_pct"]),
        "drop_3d_pct": float(best["drop_3d_pct"]),
        "peak_dd_exit_pct": float(best["peak_dd_exit_pct"]),
        "cooldown_days": int(best["cooldown_days"]),
    }
    print(
        f"trial={best['trial']} alpha={best['mean_alpha_vs_bnh_pctp']:.2f} "
        f"ret={best['mean_return_pct']:.2f} mdd={best['mean_mdd_pct']:.2f} "
        f"params={best_params}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
