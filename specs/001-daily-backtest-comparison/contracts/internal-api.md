# Internal API Contracts: Daily Backtest Comparison Report

**Date**: 2025-01-09
**Feature**: 001-daily-backtest-comparison

This document defines the internal Python API contracts for the comparison report feature. These are module interfaces, not HTTP APIs.

---

## Module: `trading.risk.comparison_report`

### Class: `ComparisonReportGenerator`

Main orchestrator for generating daily comparison reports.

```python
class ComparisonReportGenerator:
    """Generates daily comparison reports between actual and backtested trades."""

    def __init__(
        self,
        db_path: str = "trading/trading_results.db",
        data_loader: Optional[DataLoader] = None
    ) -> None:
        """
        Initialize the report generator.

        Args:
            db_path: Path to trading results database
            data_loader: DataLoader instance for market data (uses default if None)
        """

    def generate_report(
        self,
        report_date: date,
        strategy_name: str
    ) -> DailyComparisonReport:
        """
        Generate comparison report for a specific date and strategy.

        Args:
            report_date: Date to generate report for (YYYY-MM-DD)
            strategy_name: Strategy identifier (e.g., "v35_classic_wide", "short_v1")

        Returns:
            DailyComparisonReport with all metrics and discrepancies

        Raises:
            ValueError: If report_date is in the future
            DataNotFoundError: If market data unavailable for date
        """

    def generate_all_reports(
        self,
        report_date: date
    ) -> List[DailyComparisonReport]:
        """
        Generate reports for all active strategies for a given date.

        Args:
            report_date: Date to generate reports for

        Returns:
            List of DailyComparisonReport, one per active strategy
        """

    def save_report(
        self,
        report: DailyComparisonReport
    ) -> int:
        """
        Persist report to database.

        Args:
            report: Report to save

        Returns:
            Database ID of saved report

        Raises:
            DatabaseError: If save fails after retries
        """

    def get_report(
        self,
        report_date: date,
        strategy_name: str
    ) -> Optional[DailyComparisonReport]:
        """
        Retrieve a previously generated report.

        Args:
            report_date: Date of report
            strategy_name: Strategy identifier

        Returns:
            DailyComparisonReport if found, None otherwise
        """

    def get_reports_in_range(
        self,
        start_date: date,
        end_date: date,
        strategy_name: Optional[str] = None
    ) -> List[DailyComparisonReport]:
        """
        Retrieve reports within a date range.

        Args:
            start_date: Start of range (inclusive)
            end_date: End of range (inclusive)
            strategy_name: Filter by strategy (all strategies if None)

        Returns:
            List of matching reports, sorted by date descending
        """
```

---

### Class: `TradeComparer`

Handles the trade-by-trade comparison logic.

```python
class TradeComparer:
    """Compares actual trades against backtest trades."""

    TIMESTAMP_TOLERANCE_MINUTES: int = 5

    def __init__(self, tolerance_minutes: int = 5) -> None:
        """
        Initialize the comparer.

        Args:
            tolerance_minutes: Timestamp matching tolerance window
        """

    def compare_trades(
        self,
        actual_trades: List[ActualTrade],
        backtest_trades: List[BacktestTrade]
    ) -> ComparisonResult:
        """
        Compare two lists of trades and identify matches/discrepancies.

        Args:
            actual_trades: Trades from live trading, sorted by timestamp
            backtest_trades: Trades from backtest, sorted by timestamp

        Returns:
            ComparisonResult containing:
            - trade_comparisons: List[TradeComparison]
            - discrepancies: List[DiscrepancyRecord]
            - match_rate: float (0.0 to 1.0)
        """

    def calculate_severity(
        self,
        discrepancy_type: DiscrepancyType,
        pnl_impact_pct: float
    ) -> Severity:
        """
        Determine severity level for a discrepancy.

        Args:
            discrepancy_type: Type of mismatch
            pnl_impact_pct: Estimated P/L impact as percentage

        Returns:
            Severity enum (Low, Medium, High)
        """
```

---

### Class: `ReportNotifier`

Handles Telegram delivery of reports.

```python
class ReportNotifier:
    """Sends comparison reports via Telegram."""

    def __init__(
        self,
        telegram_notifier: Optional[TelegramNotifier] = None
    ) -> None:
        """
        Initialize the notifier.

        Args:
            telegram_notifier: Existing TelegramNotifier instance (creates new if None)
        """

    def send_report(
        self,
        report: DailyComparisonReport
    ) -> bool:
        """
        Send report summary via Telegram.

        Args:
            report: Report to send

        Returns:
            True if sent successfully, False otherwise
        """

    def send_failure_notification(
        self,
        report_date: date,
        error: Exception
    ) -> bool:
        """
        Notify about report generation failure.

        Args:
            report_date: Date that failed
            error: Exception that caused failure

        Returns:
            True if notification sent, False otherwise
        """

    def format_report_message(
        self,
        report: DailyComparisonReport
    ) -> str:
        """
        Format report as Telegram-compatible message.

        Args:
            report: Report to format

        Returns:
            Markdown-formatted message string
        """
```

---

## Module: `scripts.daily_comparison`

### Function: `main`

Entry point for cron-scheduled execution.

```python
def main(
    report_date: Optional[date] = None,
    strategies: Optional[List[str]] = None,
    dry_run: bool = False
) -> int:
    """
    Generate and send daily comparison reports.

    Args:
        report_date: Date to report (defaults to yesterday)
        strategies: List of strategy names (defaults to all active)
        dry_run: If True, generate but don't save or notify

    Returns:
        Exit code: 0 for success, 1 for partial failure, 2 for total failure

    CLI Usage:
        python scripts/daily_comparison.py
        python scripts/daily_comparison.py --date 2025-01-08
        python scripts/daily_comparison.py --strategies v35_classic_wide,short_v1
        python scripts/daily_comparison.py --dry-run
    """


def run_with_retry(
    func: Callable[[], T],
    max_attempts: int = 3,
    base_delay_seconds: int = 300
) -> T:
    """
    Execute function with retry logic.

    Args:
        func: Function to execute
        max_attempts: Maximum retry attempts
        base_delay_seconds: Base delay between retries (multiplied by attempt number)

    Returns:
        Function result if successful

    Raises:
        Exception: Final exception if all retries fail
    """
```

---

## Data Classes

```python
from dataclasses import dataclass
from datetime import date, datetime
from enum import Enum
from typing import List, Optional


class MatchStatus(Enum):
    MATCH = "match"
    MISMATCH = "mismatch"
    EXTRA = "extra"
    MISSING = "missing"


class DiscrepancyType(Enum):
    MISSED_TRADE = "missed_trade"
    EXTRA_TRADE = "extra_trade"
    WRONG_DIRECTION = "wrong_direction"
    TIMING_DIFFERENCE = "timing_difference"
    PRICE_DEVIATION = "price_deviation"


class Severity(Enum):
    LOW = "Low"
    MEDIUM = "Medium"
    HIGH = "High"


@dataclass
class TradeComparison:
    actual_timestamp: Optional[datetime]
    backtest_timestamp: Optional[datetime]
    actual_action: Optional[str]  # "BUY" / "SELL" / None
    backtest_action: Optional[str]
    actual_price: Optional[float]
    backtest_price: Optional[float]
    price_difference: float
    price_difference_pct: float
    match_status: MatchStatus


@dataclass
class DiscrepancyRecord:
    timestamp: datetime
    discrepancy_type: DiscrepancyType
    severity: Severity
    actual_value: Optional[str]
    expected_value: Optional[str]
    pnl_impact: float
    pnl_impact_pct: float
    explanation: str


@dataclass
class DailyComparisonReport:
    report_date: date
    strategy_name: str
    actual_trades_count: int
    backtest_trades_count: int
    actual_pnl: float
    backtest_pnl: float
    actual_pnl_pct: float
    backtest_pnl_pct: float
    actual_max_drawdown: float
    backtest_max_drawdown: float
    discrepancy_count: int
    max_severity: Severity
    trade_comparisons: List[TradeComparison]
    discrepancies: List[DiscrepancyRecord]
    created_at: datetime


@dataclass
class ComparisonResult:
    trade_comparisons: List[TradeComparison]
    discrepancies: List[DiscrepancyRecord]
    match_rate: float
```

---

## Error Handling

```python
class ComparisonError(Exception):
    """Base exception for comparison report errors."""
    pass


class DataNotFoundError(ComparisonError):
    """Raised when required data is not available."""
    pass


class DatabaseError(ComparisonError):
    """Raised when database operations fail."""
    pass
```
