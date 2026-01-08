#!/usr/bin/env python3
"""
Daily Backtest Comparison Report CLI.

Generates and sends comparison reports between actual and backtested trades.

Usage:
    python scripts/daily_comparison.py                     # Yesterday's report
    python scripts/daily_comparison.py --date 2025-01-08   # Specific date
    python scripts/daily_comparison.py --strategies v35_long  # Specific strategy
    python scripts/daily_comparison.py --dry-run           # Don't save or notify
    python scripts/daily_comparison.py --history 7         # Last 7 days of reports
"""

import argparse
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Callable, List, Optional, TypeVar

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from trading.risk.comparison_report import ComparisonReportGenerator
from trading.risk.comparison_models import DailyComparisonReport, Severity
from trading.risk.report_notifier import ReportNotifier

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

T = TypeVar("T")


def run_with_retry(
    func: Callable[[], T],
    max_attempts: int = 3,
    delay_seconds: int = 300,
) -> T:
    """
    Execute function with retry logic.

    Args:
        func: Function to execute
        max_attempts: Maximum retry attempts
        delay_seconds: Fixed delay between retries (default: 300s = 5 minutes per spec FR-010)

    Returns:
        Function result if successful

    Raises:
        Exception: Final exception if all retries fail
    """
    last_exception = None

    for attempt in range(1, max_attempts + 1):
        try:
            return func()
        except Exception as e:
            last_exception = e
            logger.warning(f"Attempt {attempt}/{max_attempts} failed: {e}")

            if attempt < max_attempts:
                logger.info(f"Retrying in {delay_seconds} seconds...")
                time.sleep(delay_seconds)

    raise last_exception


def format_report_summary(report: DailyComparisonReport) -> str:
    """Format a report as a summary string."""
    severity_emoji = {
        Severity.LOW: "🟢",
        Severity.MEDIUM: "🟡",
        Severity.HIGH: "🔴",
    }

    lines = [
        f"\n{'='*60}",
        f"📊 Comparison Report: {report.report_date} - {report.strategy_name}",
        f"{'='*60}",
        "",
        "📈 Trade Counts:",
        f"   Actual:   {report.actual_trades_count}",
        f"   Backtest: {report.backtest_trades_count}",
        "",
        "💰 P/L:",
        f"   Actual:   {report.actual_pnl:,.0f} ({report.actual_pnl_pct:+.2f}%)",
        f"   Backtest: {report.backtest_pnl:,.0f} ({report.backtest_pnl_pct:+.2f}%)",
        "",
        "🏆 Win Rate:",
        f"   Actual:   {report.actual_win_rate:.1f}%",
        f"   Backtest: {report.backtest_win_rate:.1f}%",
        "",
        "📉 Max Drawdown:",
        f"   Actual:   {report.actual_max_drawdown:.2f}%",
        f"   Backtest: {report.backtest_max_drawdown:.2f}%",
        "",
        f"⚠️  Discrepancies: {report.discrepancy_count}",
        f"   Max Severity: {severity_emoji.get(report.max_severity, '⚪')} {report.max_severity.value}",
    ]

    # Add discrepancy details if any
    if report.discrepancies:
        lines.append("")
        lines.append("📋 Discrepancy Details:")
        for i, d in enumerate(report.discrepancies[:5], 1):  # Show first 5
            lines.append(
                f"   {i}. [{d.severity.value}] {d.discrepancy_type.value}: {d.explanation[:50]}..."
            )
        if len(report.discrepancies) > 5:
            lines.append(f"   ... and {len(report.discrepancies) - 5} more")

    lines.append(f"\n{'='*60}")

    return "\n".join(lines)


def main(
    report_date: Optional[date] = None,
    strategies: Optional[List[str]] = None,
    dry_run: bool = False,
    history_days: Optional[int] = None,
    no_notify: bool = False,
) -> int:
    """
    Generate and send daily comparison reports.

    Args:
        report_date: Date to report (defaults to yesterday)
        strategies: List of strategy names (defaults to all active)
        dry_run: If True, generate but don't save or notify
        history_days: If set, retrieve this many days of past reports
        no_notify: If True, skip Telegram notifications

    Returns:
        Exit code: 0 for success, 1 for partial failure, 2 for total failure
    """
    logger.info("Starting daily comparison report generation")

    try:
        generator = ComparisonReportGenerator()
    except Exception as e:
        logger.error(f"Failed to initialize report generator: {e}")
        return 2

    # Initialize notifier (may fail silently if Telegram not configured)
    notifier = None
    if not dry_run and not no_notify:
        try:
            notifier = ReportNotifier()
        except Exception as e:
            logger.warning(f"Could not initialize ReportNotifier: {e}")

    # Handle history mode
    if history_days is not None:
        return _show_history(generator, history_days, strategies)

    # Default to yesterday
    if report_date is None:
        report_date = date.today() - timedelta(days=1)

    # Default to all active strategies
    if strategies is None:
        strategies = generator.ACTIVE_STRATEGIES.copy()

    logger.info(f"Report date: {report_date}")
    logger.info(f"Strategies: {strategies}")
    logger.info(f"Dry run: {dry_run}")

    # Generate reports
    success_count = 0
    failure_count = 0
    reports: List[DailyComparisonReport] = []

    for strategy_name in strategies:
        try:
            logger.info(f"Generating report for {strategy_name}...")

            def generate():
                return generator.generate_report(report_date, strategy_name)

            report = run_with_retry(generate, max_attempts=3, delay_seconds=300)
            reports.append(report)

            # Print summary
            print(format_report_summary(report))

            # Save report (unless dry run)
            if not dry_run:
                report_id = generator.save_report(report)
                logger.info(f"Report saved with ID: {report_id}")

            # Send Telegram notification
            if notifier and not dry_run:
                notifier.send_report(report)

            success_count += 1

        except Exception as e:
            logger.error(f"Failed to generate report for {strategy_name}: {e}")
            failure_count += 1

            # Send failure notification
            if notifier and not dry_run:
                notifier.send_failure_notification(report_date, e)

    # Summary
    print(f"\n{'='*60}")
    print(f"📊 Summary: {success_count} succeeded, {failure_count} failed")
    print(f"{'='*60}")

    # Determine exit code
    if failure_count == 0:
        return 0
    elif success_count > 0:
        return 1
    else:
        return 2


def _show_history(
    generator: ComparisonReportGenerator,
    days: int,
    strategies: Optional[List[str]] = None,
) -> int:
    """Show historical reports."""
    end_date = date.today() - timedelta(days=1)
    start_date = end_date - timedelta(days=days - 1)

    logger.info(f"Fetching reports from {start_date} to {end_date}")

    strategy_filter = strategies[0] if strategies and len(strategies) == 1 else None
    reports = generator.get_reports_in_range(start_date, end_date, strategy_filter)

    if not reports:
        print(f"\nNo reports found for {start_date} to {end_date}")
        return 0

    print(f"\n{'='*60}")
    print(f"📊 Historical Reports: {start_date} to {end_date}")
    print(f"{'='*60}")

    for report in reports:
        print(format_report_summary(report))

    return 0


def parse_args():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description="Generate daily backtest comparison reports",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    %(prog)s                          # Generate report for yesterday
    %(prog)s --date 2025-01-08        # Generate report for specific date
    %(prog)s --strategies v35_long    # Generate for specific strategy
    %(prog)s --dry-run                # Generate without saving
    %(prog)s --history 7              # Show last 7 days of reports
        """,
    )

    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Report date (YYYY-MM-DD), defaults to yesterday",
    )

    parser.add_argument(
        "--strategies",
        type=str,
        default=None,
        help="Comma-separated list of strategies (default: all active)",
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Generate report without saving or notifying",
    )

    parser.add_argument(
        "--history",
        type=int,
        default=None,
        metavar="DAYS",
        help="Show reports for the last N days",
    )

    parser.add_argument(
        "--no-notify",
        action="store_true",
        help="Skip Telegram notifications",
    )

    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()

    # Parse date
    report_date = None
    if args.date:
        try:
            report_date = date.fromisoformat(args.date)
        except ValueError:
            print(f"Error: Invalid date format: {args.date}")
            print("Expected format: YYYY-MM-DD")
            sys.exit(2)

    # Parse strategies
    strategies = None
    if args.strategies:
        strategies = [s.strip() for s in args.strategies.split(",")]

    # Run
    exit_code = main(
        report_date=report_date,
        strategies=strategies,
        dry_run=args.dry_run,
        history_days=args.history,
        no_notify=args.no_notify,
    )

    sys.exit(exit_code)
