#!/usr/bin/env python3
"""Summarize weak periods from period-vs-BnH backtest outputs.

Reads:
  - period_vs_bnh_by_symbol.csv
  - period_vs_bnh_portfolio.csv
  - period_vs_bnh_summary.csv

Writes:
  - period_vs_bnh_problem_areas_*.md
  - period_vs_bnh_symbol_weakness.csv
  - period_vs_bnh_up_market_weakness.csv
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize problem areas from period_vs_bnh outputs.",
    )
    parser.add_argument(
        "--input-dir",
        default="logs/backtest_reports",
        help="Directory containing period_vs_bnh CSV outputs.",
    )
    parser.add_argument(
        "--label",
        default="latest",
        help="Suffix label for markdown report filename.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=10,
        help="Top-N worst symbol-month cases to include.",
    )
    return parser.parse_args()


def _ensure_pct_columns(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "alpha_pct" not in out.columns and "alpha" in out.columns:
        out["alpha_pct"] = out["alpha"] * 100.0
    if "strategy_return_pct" not in out.columns and "strategy_return" in out.columns:
        out["strategy_return_pct"] = out["strategy_return"] * 100.0
    if "bnh_return_pct" not in out.columns and "bnh_return" in out.columns:
        out["bnh_return_pct"] = out["bnh_return"] * 100.0
    return out


def main() -> int:
    args = parse_args()
    input_dir = Path(args.input_dir)

    by_symbol_path = input_dir / "period_vs_bnh_by_symbol.csv"
    portfolio_path = input_dir / "period_vs_bnh_portfolio.csv"
    summary_path = input_dir / "period_vs_bnh_summary.csv"

    if not by_symbol_path.exists() or not portfolio_path.exists() or not summary_path.exists():
        raise FileNotFoundError(
            "Required files not found. Run scripts/backtest/period_vs_bnh.py first."
        )

    by_symbol = _ensure_pct_columns(pd.read_csv(by_symbol_path))
    portfolio = _ensure_pct_columns(pd.read_csv(portfolio_path))
    summary = pd.read_csv(summary_path)

    monthly = by_symbol[by_symbol["freq"] == "M"].copy()
    portfolio_m = portfolio[portfolio["freq"] == "M"].copy()
    portfolio_q = portfolio[portfolio["freq"] == "Q"].copy()

    symbol_weakness = (
        monthly.groupby("symbol")
        .agg(
            mean_alpha_pct=("alpha_pct", "mean"),
            worst_alpha_pct=("alpha_pct", "min"),
            neg_alpha_months=("alpha_pct", lambda s: int((s < 0).sum())),
            total_months=("alpha_pct", "count"),
        )
        .reset_index()
    )
    symbol_weakness["neg_alpha_ratio_pct"] = (
        symbol_weakness["neg_alpha_months"] / symbol_weakness["total_months"] * 100.0
    ).round(1)
    symbol_weakness = symbol_weakness.sort_values("mean_alpha_pct")

    up_weak = monthly[(monthly["bnh_return_pct"] > 0) & (monthly["alpha_pct"] < 0)].copy()
    up_market_weakness = (
        up_weak.groupby("symbol")
        .agg(
            up_weak_months=("alpha_pct", "count"),
            up_weak_mean_alpha_pct=("alpha_pct", "mean"),
            up_weak_worst_alpha_pct=("alpha_pct", "min"),
        )
        .reset_index()
        .sort_values("up_weak_mean_alpha_pct")
    )

    worst_portfolio_months = portfolio_m.nsmallest(5, "alpha_pct")[
        ["period", "alpha_pct", "strategy_return_pct", "bnh_return_pct"]
    ]
    worst_portfolio_quarters = portfolio_q.nsmallest(3, "alpha_pct")[
        ["period", "alpha_pct", "strategy_return_pct", "bnh_return_pct"]
    ]
    worst_symbol_months = monthly.nsmallest(args.top_n, "alpha_pct")[
        ["period", "symbol", "alpha_pct", "strategy_return_pct", "bnh_return_pct", "strategy_name"]
    ]

    md_path = input_dir / f"period_vs_bnh_problem_areas_{args.label}.md"
    symbol_weakness_path = input_dir / "period_vs_bnh_symbol_weakness.csv"
    up_market_weakness_path = input_dir / "period_vs_bnh_up_market_weakness.csv"

    lines: list[str] = []
    lines.append(f"# Period vs BnH Problem Areas ({args.label})")
    lines.append("")
    lines.append("## Overall Alpha by Symbol")
    for _, r in symbol_weakness.iterrows():
        lines.append(
            f"- {r['symbol']}: mean_alpha={r['mean_alpha_pct']:+.2f}%p, "
            f"worst_month={r['worst_alpha_pct']:+.2f}%p, "
            f"negative_alpha_months={int(r['neg_alpha_months'])}/{int(r['total_months'])} "
            f"({r['neg_alpha_ratio_pct']:.1f}%)"
        )

    lines.append("")
    lines.append("## Weakness in Up Markets (BnH>0 and Alpha<0)")
    if up_market_weakness.empty:
        lines.append("- none")
    else:
        for _, r in up_market_weakness.iterrows():
            lines.append(
                f"- {r['symbol']}: months={int(r['up_weak_months'])}, "
                f"mean_alpha={r['up_weak_mean_alpha_pct']:+.2f}%p, "
                f"worst={r['up_weak_worst_alpha_pct']:+.2f}%p"
            )

    lines.append("")
    lines.append("## Worst Portfolio Months")
    for _, r in worst_portfolio_months.iterrows():
        lines.append(
            f"- {r['period']}: alpha={r['alpha_pct']:+.2f}%p "
            f"(STR={r['strategy_return_pct']:+.2f}%, BnH={r['bnh_return_pct']:+.2f}%)"
        )

    lines.append("")
    lines.append("## Worst Portfolio Quarters")
    for _, r in worst_portfolio_quarters.iterrows():
        lines.append(
            f"- {r['period']}: alpha={r['alpha_pct']:+.2f}%p "
            f"(STR={r['strategy_return_pct']:+.2f}%, BnH={r['bnh_return_pct']:+.2f}%)"
        )

    lines.append("")
    lines.append("## Worst Symbol-Month Cases")
    for _, r in worst_symbol_months.iterrows():
        lines.append(
            f"- {r['period']} {r['symbol']}: alpha={r['alpha_pct']:+.2f}%p "
            f"(STR={r['strategy_return_pct']:+.2f}%, BnH={r['bnh_return_pct']:+.2f}%, "
            f"strategy={r['strategy_name']})"
        )

    lines.append("")
    lines.append("## Total Return Snapshot")
    for _, r in summary.sort_values("alpha_pct").iterrows():
        lines.append(
            f"- {r['symbol']}: alpha={r['alpha_pct']:+.2f}%p "
            f"(STR={r['strategy_return_pct']:+.2f}%, BnH={r['bnh_return_pct']:+.2f}%, "
            f"trades={int(r['trades'])})"
        )

    md_path.write_text("\n".join(lines), encoding="utf-8")
    symbol_weakness.to_csv(symbol_weakness_path, index=False)
    up_market_weakness.to_csv(up_market_weakness_path, index=False)

    print(f"Saved: {md_path}")
    print(f"Saved: {symbol_weakness_path}")
    print(f"Saved: {up_market_weakness_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
