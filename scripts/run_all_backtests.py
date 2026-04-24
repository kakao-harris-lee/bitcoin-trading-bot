#!/usr/bin/env python3
"""
Run all backtests comprehensively.

Usage:
    python scripts/run_all_backtests.py              # Full run
    python scripts/run_all_backtests.py --quick      # Quick sanity check
    python scripts/run_all_backtests.py --yearly     # Year-by-year breakdown
"""

import argparse
import subprocess
import sys
from pathlib import Path
from datetime import datetime

PROJECT_ROOT = Path(__file__).parent.parent
SCRIPTS_DIR = PROJECT_ROOT / "scripts"


def run_command(cmd: list, description: str) -> bool:
    """Run a command and return success status."""
    print(f"\n{'='*70}")
    print(f"  {description}")
    print(f"{'='*70}")
    print(f"  Command: {' '.join(cmd)}")
    print("-" * 70)

    try:
        result = subprocess.run(
            cmd,
            cwd=PROJECT_ROOT,
            env={"PYTHONPATH": str(PROJECT_ROOT), **dict(__import__('os').environ)},
            capture_output=False,
            check=False,
        )
        return result.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        print(f"ERROR: {e}")
        return False


def run_router_live_backtest(period: str = "all", by_year: bool = False):
    """Run Router Live (regime-based) backtest."""
    cmd = ["python", "scripts/backtest_strategies.py", "--strategy", "router_live", "--period", period]
    if by_year:
        cmd.append("--by-year")
    return run_command(cmd, f"Router Live (Regime-based) Backtest (period={period})")


def run_portfolio_backtest(by_year: bool = False):
    """Run combined portfolio backtest."""
    cmd = ["python", "scripts/backtest.py"]
    if by_year:
        cmd.append("--by-year")
    return run_command(cmd, "Combined Portfolio Backtest")


def run_unified_backtest(mode: str = "full", assets: list = None):
    """Run unified backtester."""
    cmd = ["python", "scripts/run_unified_backtest.py", "--mode", mode]
    if assets:
        cmd.extend(["--assets"] + assets)
    return run_command(cmd, f"Unified Backtest (mode={mode})")


def main():
    parser = argparse.ArgumentParser(description="Run all backtests")
    parser.add_argument("--quick", action="store_true", help="Quick sanity check (2024 only)")
    parser.add_argument("--yearly", action="store_true", help="Include year-by-year breakdown")
    parser.add_argument("--strategy", choices=["all", "router", "portfolio", "unified"],
                        default="all", help="Which strategy to backtest")
    parser.add_argument("--period", choices=["train", "test", "all"], default="all",
                        help="Backtest period")
    args = parser.parse_args()

    print("=" * 70)
    print("  ALL BACKTESTS RUNNER")
    print(f"  Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"  Mode: {'Quick' if args.quick else 'Full'}")
    print("=" * 70)

    results = {}

    period = "test" if args.quick else args.period
    by_year = args.yearly and not args.quick

    # 1. Router Live (Regime-based)
    if args.strategy in ["all", "router"]:
        results["Router Live"] = run_router_live_backtest(period, by_year)

    # 2. Combined Portfolio
    if args.strategy in ["all", "portfolio"]:
        results["Portfolio"] = run_portfolio_backtest(by_year)

    # 3. Unified Backtester
    if args.strategy in ["all", "unified"]:
        mode = "quick" if args.quick else "full"
        results["Unified"] = run_unified_backtest(mode)

    # Summary
    print("\n")
    print("=" * 70)
    print("  BACKTEST SUMMARY")
    print("=" * 70)

    for name, success in results.items():
        status = "PASS" if success else "FAIL"
        icon = "✓" if success else "✗"
        print(f"  {icon} {name}: {status}")

    total = len(results)
    passed = sum(1 for v in results.values() if v)
    print("-" * 70)
    print(f"  Total: {passed}/{total} passed")
    print(f"  Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    return 0 if all(results.values()) else 1


if __name__ == "__main__":
    sys.exit(main())
