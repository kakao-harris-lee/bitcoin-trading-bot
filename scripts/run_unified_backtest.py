#!/usr/bin/env python3
"""
Run comprehensive backtests using the unified backtester.

Usage:
    python scripts/run_unified_backtest.py --mode full
    python scripts/run_unified_backtest.py --mode quick --assets BTC
    python scripts/run_unified_backtest.py --start 2023-01-01 --end 2024-12-31
"""

import argparse
import sys
from pathlib import Path
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.unified_backtester import UnifiedBacktester, BacktestConfig
import pandas as pd


def run_training_test(assets: list, enable_arb: bool = True):
    """Run backtest on training period (2020-2024)."""
    print("\n" + "=" * 70)
    print("TRAINING PERIOD: 2020-01-01 to 2024-12-31")
    print("=" * 70)

    config = BacktestConfig(
        start_date="2020-01-01",
        end_date="2024-12-31",
        upbit_capital_krw=10_000_000,
        binance_capital_usdt=10_000,
        assets=assets,
        enable_premium_arb=enable_arb,
    )

    backtester = UnifiedBacktester(config)
    result = backtester.run()

    print_results(result, "Training")
    return result


def run_validation_test(assets: list, enable_arb: bool = True):
    """Run backtest on validation period (2025)."""
    print("\n" + "=" * 70)
    print("VALIDATION PERIOD (OOS): 2025-01-01 to 2025-12-31")
    print("=" * 70)

    config = BacktestConfig(
        start_date="2025-01-01",
        end_date="2025-12-31",
        upbit_capital_krw=10_000_000,
        binance_capital_usdt=10_000,
        assets=assets,
        enable_premium_arb=enable_arb,
    )

    backtester = UnifiedBacktester(config)
    result = backtester.run()

    print_results(result, "Validation (OOS)")
    return result


def run_yearly_breakdown(assets: list, enable_arb: bool = True):
    """Run year-by-year backtest."""
    print("\n" + "=" * 70)
    print("YEARLY BREAKDOWN")
    print("=" * 70)

    years = range(2020, 2026)
    yearly_results = []

    for year in years:
        config = BacktestConfig(
            start_date=f"{year}-01-01",
            end_date=f"{year}-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=assets,
            enable_premium_arb=enable_arb,
        )

        try:
            backtester = UnifiedBacktester(config)
            result = backtester.run()

            yearly_results.append({
                'year': year,
                'return_pct': result['total_return_pct'],
                'trades': result['total_trades'],
                'win_rate': result['win_rate'],
                'sharpe': result['sharpe_ratio'],
                'max_dd': result['max_drawdown_pct'],
            })
        except Exception as e:
            print(f"  {year}: Error - {e}")

    # Print table
    print("\n{:^6} {:>12} {:>8} {:>10} {:>8} {:>10}".format(
        "Year", "Return %", "Trades", "Win Rate", "Sharpe", "Max DD"
    ))
    print("-" * 60)

    for r in yearly_results:
        print("{:^6} {:>12.2f} {:>8} {:>10.1f}% {:>8.2f} {:>10.2f}%".format(
            r['year'], r['return_pct'], r['trades'], r['win_rate'],
            r['sharpe'], r['max_dd']
        ))


def run_component_comparison():
    """Compare different strategy components."""
    print("\n" + "=" * 70)
    print("COMPONENT COMPARISON (2024)")
    print("=" * 70)

    components = [
        ("Long Only", True, False, False),
        ("Short Only", False, True, False),
        ("Long + Short", True, True, False),
        ("Long + Premium Arb", True, False, True),
        ("Full System", True, True, True),
    ]

    results = []
    for name, enable_long, enable_short, enable_arb in components:
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
            enable_long=enable_long,
            enable_short=enable_short,
            enable_premium_arb=enable_arb,
        )

        try:
            backtester = UnifiedBacktester(config)
            result = backtester.run()

            results.append({
                'component': name,
                'return_pct': result['total_return_pct'],
                'trades': result['total_trades'],
                'sharpe': result['sharpe_ratio'],
            })
        except Exception as e:
            print(f"  {name}: Error - {e}")

    print("\n{:<20} {:>12} {:>8} {:>8}".format(
        "Component", "Return %", "Trades", "Sharpe"
    ))
    print("-" * 50)

    for r in results:
        print("{:<20} {:>12.2f} {:>8} {:>8.2f}".format(
            r['component'], r['return_pct'], r['trades'], r['sharpe']
        ))


def print_results(result: dict, period_name: str):
    """Print formatted results."""
    print(f"\n{period_name} Results:")
    print("-" * 40)
    print(f"  Total Return:    {result['total_return_pct']:>10.2f}%")
    print(f"  Total Trades:    {result['total_trades']:>10}")
    print(f"  Win Rate:        {result['win_rate']:>10.1f}%")
    print(f"  Sharpe Ratio:    {result['sharpe_ratio']:>10.2f}")
    print(f"  Max Drawdown:    {result['max_drawdown_pct']:>10.2f}%")
    print(f"  Avg Win:         {result['avg_win_pct']:>10.2f}%")
    print(f"  Avg Loss:        {result['avg_loss_pct']:>10.2f}%")

    # Success criteria check
    print("\n  Success Criteria Check:")
    oos_pass = result['total_return_pct'] >= 15
    sharpe_pass = result['sharpe_ratio'] >= 1.5
    mdd_pass = result['max_drawdown_pct'] >= -20

    print(f"    OOS Return >= 15%:  {'PASS' if oos_pass else 'FAIL'} ({result['total_return_pct']:.1f}%)")
    print(f"    Sharpe >= 1.5:      {'PASS' if sharpe_pass else 'FAIL'} ({result['sharpe_ratio']:.2f})")
    print(f"    Max DD >= -20%:     {'PASS' if mdd_pass else 'FAIL'} ({result['max_drawdown_pct']:.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="Run unified backtests")
    parser.add_argument("--mode", choices=["quick", "full", "yearly", "compare"],
                        default="quick", help="Backtest mode")
    parser.add_argument("--assets", nargs="+", default=["BTC"],
                        help="Assets to backtest")
    parser.add_argument("--start", type=str, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", type=str, help="End date (YYYY-MM-DD)")
    parser.add_argument("--no-arb", action="store_true",
                        help="Disable premium arbitrage")

    args = parser.parse_args()

    print("=" * 70)
    print("UNIFIED BACKTESTING FRAMEWORK")
    print(f"Mode: {args.mode} | Assets: {', '.join(args.assets)}")
    print(f"Premium Arbitrage: {'Disabled' if args.no_arb else 'Enabled'}")
    print("=" * 70)

    enable_arb = not args.no_arb

    if args.mode == "quick":
        # Quick test on 2024 only
        config = BacktestConfig(
            start_date=args.start or "2024-01-01",
            end_date=args.end or "2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=args.assets,
            enable_premium_arb=enable_arb,
        )
        backtester = UnifiedBacktester(config)
        result = backtester.run()
        print_results(result, "Quick Test")

    elif args.mode == "full":
        run_training_test(args.assets, enable_arb)
        run_validation_test(args.assets, enable_arb)

    elif args.mode == "yearly":
        run_yearly_breakdown(args.assets, enable_arb)

    elif args.mode == "compare":
        run_component_comparison()


if __name__ == "__main__":
    main()
