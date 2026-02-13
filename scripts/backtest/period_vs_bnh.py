#!/usr/bin/env python3
"""Backtest enabled strategies and compare period returns vs buy-and-hold."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any
import re

import pandas as pd

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.backtest._common import load_data
from scripts.backtest.backtest_mlp import MLPDirectionBacktester, load_allocation_config
from trading.core.period_benchmark import (
    alpha_by_market_direction,
    build_period_comparison,
    build_portfolio_comparison,
    compound_return,
    compute_period_returns_from_equity,
    compute_period_returns_from_prices,
    normalize_period_freq,
)

DEFAULT_DB_BY_SYMBOL = {
    "BTC": PROJECT_ROOT / "data" / "binance_bitcoin.db",
    "ETH": PROJECT_ROOT / "data" / "binance_ethereum.db",
    "SOL": PROJECT_ROOT / "data" / "binance_solana.db",
    "BNB": PROJECT_ROOT / "data" / "binance_bnb.db",
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare monthly/quarterly strategy returns against buy-and-hold."
    )
    parser.add_argument(
        "--config",
        default="config/strategies/allocation.json",
        help="Path to allocation config.",
    )
    parser.add_argument("--start-date", default="2025-01-01")
    parser.add_argument("--end-date", default="2026-01-11")
    parser.add_argument("--timeframe", default="minute240")
    parser.add_argument("--capital", type=float, default=10_000.0)
    parser.add_argument(
        "--periods",
        default="M,Q",
        help="Comma-separated periods: M,Q",
    )
    parser.add_argument(
        "--symbols",
        default="",
        help="Comma-separated symbol filter, e.g. BTC,ETH. Empty = all enabled.",
    )
    parser.add_argument("--top-n", type=int, default=8)
    parser.add_argument(
        "--output-dir",
        default="logs/backtest_reports",
        help="Directory for CSV reports.",
    )
    return parser.parse_args()


def _infer_symbol(strategy_name: str, cfg: dict[str, Any]) -> str | None:
    symbols = cfg.get("symbols", [])
    if isinstance(symbols, list) and symbols:
        return str(symbols[0]).upper()
    tail = strategy_name.rsplit("_", 1)[-1]
    if tail and tail.isalpha():
        return tail.upper()
    return None


def _load_enabled_mlp_strategies(
    config_path: str,
    symbols_filter: set[str],
) -> list[tuple[str, str, dict[str, Any]]]:
    allocation = load_allocation_config(config_path)
    strategies = allocation.get("strategies", {})
    resolved: list[tuple[str, str, dict[str, Any]]] = []

    for strategy_name, cfg in strategies.items():
        if not isinstance(cfg, dict):
            continue
        if not cfg.get("enabled", True):
            continue
        symbol = _infer_symbol(strategy_name, cfg)
        if symbol is None:
            continue
        if symbols_filter and symbol not in symbols_filter:
            continue

        entry_class = str(cfg.get("entry", {}).get("class", ""))
        if "MLPDirectionEntryStrategy" not in entry_class:
            continue

        resolved.append((strategy_name, symbol, cfg))
    return resolved


def _to_percent(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    for col in ("strategy_return", "bnh_return", "alpha"):
        if col in out.columns:
            out[f"{col}_pct"] = out[col] * 100.0
    return out


def _print_worst(title: str, df: pd.DataFrame, top_n: int) -> None:
    print(f"\n{title}")
    if df.empty:
        print("  (no rows)")
        return
    rows = df.nsmallest(top_n, "alpha")
    for _, row in rows.iterrows():
        print(
            f"  {row['period']:<8} {row['symbol']:<10} "
            f"STR={row['strategy_return']*100:+7.2f}% "
            f"BnH={row['bnh_return']*100:+7.2f}% "
            f"Alpha={row['alpha']*100:+7.2f}%p"
        )


def _timeframe_to_minutes(timeframe: str) -> float:
    """Convert timeframe string into bar length minutes."""
    raw = (timeframe or "").strip().lower()
    if raw.startswith("minute"):
        suffix = raw[len("minute") :]
        if suffix.isdigit():
            return float(suffix)
    if raw.endswith("m") and raw[:-1].isdigit():
        return float(raw[:-1])
    if raw.endswith("h") and raw[:-1].isdigit():
        return float(raw[:-1]) * 60.0
    if raw in {"d", "1d", "day", "daily"}:
        return 1440.0
    match = re.search(r"(\d+)", raw)
    if match:
        return float(match.group(1))
    return 240.0


def _trade_timing_stats(trades: list[Any], bar_minutes: float) -> tuple[float, float]:
    """Compute avg hold bars and early-exit rate (<=2 bars)."""
    if not trades or bar_minutes <= 0:
        return 0.0, 0.0

    hold_bars: list[float] = []
    for trade in trades:
        entry_time = getattr(trade, "entry_time", None)
        exit_time = getattr(trade, "exit_time", None)
        if entry_time is None or exit_time is None:
            continue
        elapsed_seconds = (exit_time - entry_time).total_seconds()
        if elapsed_seconds < 0:
            continue
        hold_bars.append(elapsed_seconds / (bar_minutes * 60.0))

    if not hold_bars:
        return 0.0, 0.0

    avg_hold_bars = float(sum(hold_bars) / len(hold_bars))
    early_exit_count = sum(1 for bars in hold_bars if bars <= 2.0)
    early_exit_rate_pct = (early_exit_count / len(hold_bars)) * 100.0
    return avg_hold_bars, early_exit_rate_pct


def _compute_up_market_metrics(per_symbol_periods: pd.DataFrame) -> pd.DataFrame:
    """Compute up-market alpha and capture ratio per symbol."""
    if per_symbol_periods.empty:
        return pd.DataFrame(columns=["symbol", "up_market_alpha_pct", "up_market_capture_ratio"])

    monthly = per_symbol_periods[per_symbol_periods["freq"] == "M"].copy()
    if monthly.empty:
        monthly = per_symbol_periods.copy()

    rows: list[dict[str, Any]] = []
    for symbol, group in monthly.groupby("symbol"):
        up = group[group["bnh_return"] > 0]
        if up.empty:
            rows.append(
                {
                    "symbol": symbol,
                    "up_market_alpha_pct": 0.0,
                    "up_market_capture_ratio": 0.0,
                }
            )
            continue

        up_market_alpha_pct = float(up["alpha"].mean() * 100.0)
        denom = float(up["bnh_return"].sum())
        capture_ratio = float(up["strategy_return"].sum() / denom) if abs(denom) > 1e-12 else 0.0
        rows.append(
            {
                "symbol": symbol,
                "up_market_alpha_pct": up_market_alpha_pct,
                "up_market_capture_ratio": capture_ratio,
            }
        )

    return pd.DataFrame(rows)


def main() -> int:
    args = parse_args()
    periods = [normalize_period_freq(x) for x in args.periods.split(",") if x.strip()]
    symbols_filter = {
        token.strip().upper() for token in args.symbols.split(",") if token.strip()
    }

    selected = _load_enabled_mlp_strategies(args.config, symbols_filter)
    if not selected:
        print("No enabled MLP direction strategies found for the requested symbol filter.")
        return 1

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    period_rows: list[pd.DataFrame] = []
    symbol_summary_rows: list[dict[str, Any]] = []
    bar_minutes = _timeframe_to_minutes(args.timeframe)

    for strategy_name, symbol, strategy_cfg in selected:
        db_path = DEFAULT_DB_BY_SYMBOL.get(symbol)
        if db_path is None:
            print(f"Skipping {strategy_name}: unsupported symbol {symbol}")
            continue
        if not db_path.exists():
            print(f"Skipping {strategy_name}: DB not found ({db_path})")
            continue

        print(
            f"Running {strategy_name} ({symbol}) | "
            f"{args.start_date} -> {args.end_date} | {args.timeframe}"
        )
        raw_df = load_data(
            db_path=str(db_path),
            timeframe=args.timeframe,
            start_date=args.start_date,
            end_date=args.end_date,
            exchange="binance",
        )
        if raw_df.empty:
            print(f"  no data for {symbol} in requested period")
            continue

        backtester = MLPDirectionBacktester(symbol=symbol, config=strategy_cfg, strategy_label=strategy_name)
        prepared_df = backtester.prepare_data(raw_df.copy())
        results = backtester.run(prepared_df, initial_capital=args.capital)
        equity_curve = results.get("equity_curve")
        avg_hold_bars, early_exit_rate_pct = _trade_timing_stats(results.get("trades", []), bar_minutes)

        bnh_total = (float(raw_df["close"].iloc[-1]) / float(raw_df["close"].iloc[0])) - 1.0
        strategy_total = float(results.get("total_return", 0.0)) / 100.0

        symbol_summary_rows.append(
            {
                "strategy_name": strategy_name,
                "symbol": symbol,
                "strategy_return_pct": strategy_total * 100.0,
                "bnh_return_pct": bnh_total * 100.0,
                "alpha_pct": (strategy_total - bnh_total) * 100.0,
                "trades": int(results.get("total_trades", 0)),
                "win_rate_pct": float(results.get("win_rate", 0.0)) * 100.0,
                "avg_hold_bars": avg_hold_bars,
                "early_exit_rate_pct": early_exit_rate_pct,
            }
        )

        price_frame = raw_df[["timestamp", "close"]].copy()
        for freq in periods:
            strategy_period = compute_period_returns_from_equity(equity_curve, freq=freq)
            benchmark_period = compute_period_returns_from_prices(price_frame, freq=freq)
            comparison = build_period_comparison(
                strategy_returns=strategy_period,
                benchmark_returns=benchmark_period,
                symbol=symbol,
                freq=freq,
            )
            if not comparison.empty:
                comparison["strategy_name"] = strategy_name
                period_rows.append(comparison)

    if not period_rows:
        print("Backtests completed but no period rows were produced.")
        return 1

    per_symbol_periods = pd.concat(period_rows, ignore_index=True)
    portfolio_periods = build_portfolio_comparison(per_symbol_periods)
    summary_df = pd.DataFrame(symbol_summary_rows)
    up_metrics = _compute_up_market_metrics(per_symbol_periods)
    if not up_metrics.empty:
        summary_df = summary_df.merge(up_metrics, on="symbol", how="left")
    else:
        summary_df["up_market_alpha_pct"] = 0.0
        summary_df["up_market_capture_ratio"] = 0.0
    summary_df["up_market_alpha_pct"] = summary_df["up_market_alpha_pct"].fillna(0.0)
    summary_df["up_market_capture_ratio"] = summary_df["up_market_capture_ratio"].fillna(0.0)
    summary_df = summary_df.sort_values("alpha_pct")

    per_symbol_periods_out = _to_percent(per_symbol_periods)
    portfolio_periods_out = _to_percent(portfolio_periods)

    by_symbol_path = output_dir / "period_vs_bnh_by_symbol.csv"
    portfolio_path = output_dir / "period_vs_bnh_portfolio.csv"
    summary_path = output_dir / "period_vs_bnh_summary.csv"

    per_symbol_periods_out.to_csv(by_symbol_path, index=False)
    portfolio_periods_out.to_csv(portfolio_path, index=False)
    summary_df.to_csv(summary_path, index=False)

    print("\nOverall return (full window)")
    for _, row in summary_df.iterrows():
        print(
            f"  {row['symbol']:<4} STR={row['strategy_return_pct']:+7.2f}% "
            f"BnH={row['bnh_return_pct']:+7.2f}% Alpha={row['alpha_pct']:+7.2f}%p "
            f"UpAlpha={row['up_market_alpha_pct']:+7.2f}%p "
            f"Capture={row['up_market_capture_ratio']:+5.2f} "
            f"Trades={int(row['trades'])} "
            f"AvgHold={row['avg_hold_bars']:.2f}b "
            f"EarlyExit={row['early_exit_rate_pct']:.1f}%"
        )

    print("\nPortfolio compounded return by period")
    for freq in periods:
        subset = portfolio_periods[portfolio_periods["freq"] == freq]
        if subset.empty:
            continue
        strategy_total = compound_return(subset["strategy_return"])
        benchmark_total = compound_return(subset["bnh_return"])
        alpha_total = strategy_total - benchmark_total
        print(
            f"  {freq}: STR={strategy_total*100:+.2f}% "
            f"BnH={benchmark_total*100:+.2f}% Alpha={alpha_total*100:+.2f}%p"
        )
        split = alpha_by_market_direction(subset)
        print(
            f"      up-avg-alpha={split['up_mean_alpha']*100:+.2f}%p "
            f"down-avg-alpha={split['down_mean_alpha']*100:+.2f}%p"
        )

    monthly_portfolio = portfolio_periods[portfolio_periods["freq"] == "M"]
    quarterly_portfolio = portfolio_periods[portfolio_periods["freq"] == "Q"]
    monthly_symbols = per_symbol_periods[per_symbol_periods["freq"] == "M"]

    _print_worst("Worst portfolio months", monthly_portfolio.assign(symbol="PORTFOLIO"), args.top_n)
    _print_worst("Worst portfolio quarters", quarterly_portfolio.assign(symbol="PORTFOLIO"), args.top_n)
    _print_worst("Worst symbol-month alpha", monthly_symbols, args.top_n)

    print("\nSaved reports")
    print(f"  - {by_symbol_path}")
    print(f"  - {portfolio_path}")
    print(f"  - {summary_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
