#!/usr/bin/env python3
"""
Forward Test for MLP Direction Strategy.

Tests the MLP Direction strategy on out-of-sample data (2025+) to validate
real-world performance potential.

Usage:
    python scripts/backtest/forward_test_mlp.py --symbol BTC
    python scripts/backtest/forward_test_mlp.py --symbol ETH --start-date 2025-01-01
"""

from __future__ import annotations

import sys
from pathlib import Path
from datetime import datetime
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import argparse

from scripts.backtest._common import (
    compute_metrics,
    print_summary,
    print_yearly_table,
)
from scripts.backtest.backtest_mlp import load_strategy_config, run_backtest


def generate_forward_test_report(
    results: dict,
    symbol: str,
    start_date: str,
    end_date: str,
    mode: str,
    strategy_id: str,
    output_dir: Path,
) -> str:
    """Generate forward test report.

    Args:
        results: Backtest results.
        symbol: Trading symbol.
        start_date: Test start date.
        end_date: Test end date.
        output_dir: Report output directory.

    Returns:
        Path to generated report.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Compute metrics
    metrics = compute_metrics(results.get("equity_curve"), "minute240")

    # Generate report content
    report = []
    report.append("# MLP Direction Forward Test Report")
    report.append(f"\n**Generated**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    report.append(f"**Symbol**: {symbol}")
    report.append(f"**Mode**: {mode}")
    report.append(f"**Strategy Config**: {strategy_id}")
    report.append(f"**Period**: {start_date} to {end_date}")
    report.append("")

    report.append("## Performance Summary")
    report.append("")
    report.append("| Metric | Value |")
    report.append("|--------|-------|")
    report.append(f"| Initial Capital | ${results.get('initial_capital', 0):,.2f} |")
    report.append(f"| Final Capital | ${results.get('final_capital', 0):,.2f} |")
    report.append(f"| Total Return | {results.get('total_return', 0):+.2f}% |")
    report.append(f"| CAGR | {metrics.get('cagr', 0):+.2f}% |")
    report.append(f"| Max Drawdown | {metrics.get('mdd', 0):.2f}% |")
    report.append(f"| Sharpe Ratio | {metrics.get('sharpe', 0):.2f} |")
    report.append("")

    report.append("## Trade Statistics")
    report.append("")
    report.append("| Metric | Value |")
    report.append("|--------|-------|")
    report.append(f"| Total Trades | {results.get('total_trades', 0)} |")
    report.append(f"| Win Rate | {results.get('win_rate', 0) * 100:.1f}% |")
    report.append(f"| Profit Factor | {results.get('profit_factor', 0):.2f} |")
    report.append(f"| Avg Profit | ${results.get('avg_profit', 0):,.2f} |")
    report.append(f"| Avg Loss | ${results.get('avg_loss', 0):,.2f} |")
    report.append("")

    # Equity curve analysis
    eq = results.get("equity_curve")
    if eq is not None and not eq.empty:
        report.append("## Monthly Performance")
        report.append("")

        df = eq.copy()
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df["month"] = df["timestamp"].dt.to_period("M")

        report.append("| Month | Start | End | Return % |")
        report.append("|-------|-------|-----|----------|")

        for month, grp in df.groupby("month"):
            if len(grp) < 2:
                continue
            start_eq = float(grp["total_equity"].iloc[0])
            end_eq = float(grp["total_equity"].iloc[-1])
            ret = ((end_eq - start_eq) / start_eq * 100) if start_eq > 0 else 0.0
            report.append(f"| {month} | ${start_eq:,.0f} | ${end_eq:,.0f} | {ret:+.2f}% |")

    # Write report
    report_path = output_dir / f"forward_test_{symbol.lower()}_{start_date.replace('-', '')}_{end_date.replace('-', '')}.md"
    with open(report_path, "w", encoding="utf-8") as f:
        f.write("\n".join(report))

    return str(report_path)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Forward test MLP Direction strategy on out-of-sample data"
    )

    parser.add_argument(
        "--symbol",
        default="BTC",
        choices=["BTC", "ETH", "SOL"],
        help="Trading symbol (default: BTC)",
    )
    parser.add_argument(
        "--mode",
        choices=["paper", "live"],
        default="paper",
        help="Config mode to load from allocation.json (default: paper)",
    )
    parser.add_argument(
        "--config",
        default="config/strategies/allocation.json",
        help="Path to allocation config (default: config/strategies/allocation.json)",
    )
    parser.add_argument(
        "--strategy-id",
        default=None,
        help="Strategy config id in allocation.json (default: auto by mode/symbol)",
    )
    parser.add_argument(
        "--start-date",
        default="2025-01-01",
        help="Forward test start date (default: 2025-01-01)",
    )
    parser.add_argument(
        "--end-date",
        default=datetime.now().strftime("%Y-%m-%d"),
        help="Forward test end date (default: today)",
    )
    parser.add_argument(
        "--capital",
        type=float,
        default=10_000,
        help="Initial capital (default: 10,000)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override model path (defaults to allocation.json)",
    )
    parser.add_argument(
        "--confidence",
        type=float,
        default=None,
        help="Override buy_confidence_threshold (default: use config)",
    )
    parser.add_argument(
        "--stop-loss",
        type=float,
        default=None,
        help="Override stop_loss_pct (default: use config)",
    )
    parser.add_argument(
        "--fwin-exit",
        action="store_true",
        default=None,
        help="Force enable FWin exit (override config)",
    )
    parser.add_argument(
        "--no-fwin-exit",
        action="store_true",
        default=None,
        help="Force disable FWin exit (override config)",
    )
    parser.add_argument(
        "--fwin-periods",
        type=int,
        default=None,
        help="Override fwin_periods (default: use config)",
    )
    parser.add_argument(
        "--output",
        default="reports/mlp_forward_test",
        help="Output directory for report",
    )
    parser.add_argument(
        "--by-year",
        action="store_true",
        help="Show year-by-year breakdown",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Verbose output",
    )

    args = parser.parse_args()

    print("=" * 60)
    print("MLP DIRECTION FORWARD TEST")
    print("=" * 60)
    print(f"Symbol: {args.symbol}")
    print(f"Period: {args.start_date} to {args.end_date}")
    print(f"Mode: {args.mode}")

    try:
        _, strategy_id, strategy_config = load_strategy_config(
            config_path=args.config,
            symbol=args.symbol,
            mode=args.mode,
            strategy_id=args.strategy_id,
        )
    except ValueError as exc:
        print(f"ERROR: {exc}")
        sys.exit(1)

    entry_overrides: dict[str, Any] = {}
    exit_overrides: dict[str, Any] = {}

    if args.model:
        strategy_config["model_path"] = args.model
        entry_overrides["model_path"] = args.model
        exit_overrides["model_path"] = args.model

    if args.confidence is not None:
        entry_overrides["buy_confidence_threshold"] = args.confidence

    if args.stop_loss is not None:
        exit_overrides["stop_loss_pct"] = args.stop_loss

    if args.fwin_exit is not None or args.no_fwin_exit is not None:
        if args.fwin_exit and args.no_fwin_exit:
            print("WARNING: Both --fwin-exit and --no-fwin-exit set; using --no-fwin-exit.")
        fwin_enabled = bool(args.fwin_exit) and not bool(args.no_fwin_exit)
        exit_overrides["fwin_exit_enabled"] = fwin_enabled

    if args.fwin_periods is not None:
        exit_overrides["fwin_periods"] = args.fwin_periods

    model_path = strategy_config.get("model_path")
    if model_path:
        model_path = Path(model_path)
        if not model_path.exists():
            print(f"WARNING: Model not found at {model_path}")
            print("Run training first: python mlp_trainer/train.py")
            print("Proceeding (will fail at prediction step)...")

    print(f"Strategy Config: {strategy_id}")
    if strategy_config.get("model_path"):
        print(f"Model: {strategy_config.get('model_path')}")
    print("")

    # Run forward test
    results = run_backtest(
        symbol=args.symbol,
        db_path=None,  # Auto-detect from symbol
        start_date=args.start_date,
        end_date=args.end_date,
        timeframe="minute240",
        initial_capital=args.capital,
        strategy_config=strategy_config,
        entry_overrides=entry_overrides,
        exit_overrides=exit_overrides,
        strategy_label=strategy_id,
    )

    if not results:
        print("Forward test failed - no results returned.")
        sys.exit(1)

    # Compute metrics
    metrics = compute_metrics(results.get("equity_curve"), "minute240")

    # Print results
    print_summary(
        f"MLP Direction Forward Test ({args.symbol}) [{strategy_id}]",
        results,
        metrics,
        verbose=args.verbose,
    )

    if args.by_year:
        print_yearly_table(results.get("equity_curve"))

    # Generate report
    output_dir = Path(args.output)
    report_path = generate_forward_test_report(
        results,
        args.symbol,
        args.start_date,
        args.end_date,
        args.mode,
        strategy_id,
        output_dir,
    )
    print(f"\nReport saved to: {report_path}")

    # Summary assessment
    print("\n" + "=" * 60)
    print("FORWARD TEST ASSESSMENT")
    print("=" * 60)

    total_return = results.get("total_return", 0.0)
    mdd = metrics.get("mdd", 0.0)
    win_rate = results.get("win_rate", 0.0) * 100

    if total_return > 0:
        print(f"✓ Positive return: {total_return:+.2f}%")
    else:
        print(f"✗ Negative return: {total_return:+.2f}%")

    if abs(mdd) < 25:
        print(f"✓ MDD within target: {mdd:.2f}% (target: <25%)")
    else:
        print(f"✗ MDD exceeds target: {mdd:.2f}% (target: <25%)")

    if win_rate >= 45:
        print(f"✓ Win rate acceptable: {win_rate:.1f}% (target: >=45%)")
    else:
        print(f"✗ Win rate below target: {win_rate:.1f}% (target: >=45%)")


if __name__ == "__main__":
    main()
