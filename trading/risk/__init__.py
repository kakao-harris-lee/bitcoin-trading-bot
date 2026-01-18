"""
Risk management module for the trading bot.

Includes daily backtest comparison reporting functionality.
"""

from .comparison_models import (
    MatchStatus,
    DiscrepancyType,
    Severity,
    TradeComparison,
    DiscrepancyRecord,
    DailyComparisonReport,
    ComparisonResult,
)
from .comparison_exceptions import (
    ComparisonError,
    DataNotFoundError,
    DatabaseError,
    BacktestError,
    ConfigurationError,
)
from .comparison_report import ComparisonReportGenerator
from .report_notifier import ReportNotifier
from .trade_comparer import TradeComparer, ActualTrade, BacktestTrade
from .trade_logger import TradeLogger
from .liquidation_guard import LiquidationGuard, LiquidationInfo
from .funding_tracker import FundingTracker, FundingRate

__all__ = [
    # Models
    "MatchStatus",
    "DiscrepancyType",
    "Severity",
    "TradeComparison",
    "DiscrepancyRecord",
    "DailyComparisonReport",
    "ComparisonResult",
    # Exceptions
    "ComparisonError",
    "DataNotFoundError",
    "DatabaseError",
    "BacktestError",
    "ConfigurationError",
    # Classes
    "ComparisonReportGenerator",
    "ReportNotifier",
    "TradeComparer",
    "ActualTrade",
    "BacktestTrade",
    "TradeLogger",
    # Futures risk management
    "LiquidationGuard",
    "LiquidationInfo",
    "FundingTracker",
    "FundingRate",
]
