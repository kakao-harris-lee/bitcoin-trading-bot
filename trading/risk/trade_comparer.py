"""
Trade comparison logic for matching actual trades against backtest trades.
"""

from datetime import datetime, timedelta
from typing import List, Tuple, Optional
from dataclasses import dataclass

from .comparison_models import (
    TradeComparison,
    DiscrepancyRecord,
    ComparisonResult,
    MatchStatus,
    DiscrepancyType,
    Severity
)


@dataclass
class ActualTrade:
    """Represents an actual executed trade from live trading."""
    timestamp: datetime
    action: str  # "BUY" or "SELL"
    price: float
    volume: float
    profit: Optional[float] = None
    profit_pct: Optional[float] = None
    exchange: str = "binance"


@dataclass
class BacktestTrade:
    """Represents a trade from backtesting."""
    timestamp: datetime
    action: str  # "buy" or "sell"
    price: float
    quantity: float
    profit_loss: Optional[float] = None
    profit_loss_pct: Optional[float] = None


class TradeComparer:
    """Compares actual trades against backtest trades with timestamp tolerance."""

    TIMESTAMP_TOLERANCE_MINUTES: int = 5

    def __init__(self, tolerance_minutes: int = 5):
        """
        Initialize the comparer.

        Args:
            tolerance_minutes: Timestamp matching tolerance window (default: 5 minutes)
        """
        self.tolerance_minutes = tolerance_minutes
        self.tolerance_delta = timedelta(minutes=tolerance_minutes)

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
            ComparisonResult with trade comparisons, discrepancies, and match rate
        """
        trade_comparisons: List[TradeComparison] = []
        discrepancies: List[DiscrepancyRecord] = []
        matched_backtest = set()
        sorted_actual, sorted_backtest = self._sort_trade_inputs(actual_trades, backtest_trades)

        for actual in sorted_actual:
            match = self._find_best_backtest_match(actual, sorted_backtest, matched_backtest)
            if match is None:
                comparison, discrepancy = self._build_extra_trade_records(actual)
                trade_comparisons.append(comparison)
                discrepancies.append(discrepancy)
                continue

            backtest_index, backtest = match
            matched_backtest.add(backtest_index)
            comparison, mismatch_discrepancy = self._build_matched_trade_records(actual, backtest)
            trade_comparisons.append(comparison)
            if mismatch_discrepancy is not None:
                discrepancies.append(mismatch_discrepancy)

        for backtest_index, backtest in enumerate(sorted_backtest):
            if backtest_index in matched_backtest:
                continue
            comparison, discrepancy = self._build_missing_trade_records(backtest)
            trade_comparisons.append(comparison)
            discrepancies.append(discrepancy)

        match_rate = self._calculate_match_rate(trade_comparisons, actual_trades, backtest_trades)
        return ComparisonResult(trade_comparisons=trade_comparisons, discrepancies=discrepancies, match_rate=match_rate)

    def _sort_trade_inputs(
        self, actual_trades: List[ActualTrade], backtest_trades: List[BacktestTrade]
    ) -> Tuple[List[ActualTrade], List[BacktestTrade]]:
        return (
            sorted(actual_trades, key=lambda trade: trade.timestamp),
            sorted(backtest_trades, key=lambda trade: trade.timestamp),
        )

    def _find_best_backtest_match(
        self,
        actual: ActualTrade,
        sorted_backtest: List[BacktestTrade],
        matched_backtest: set,
    ) -> Optional[Tuple[int, BacktestTrade]]:
        best_match: Optional[Tuple[int, BacktestTrade]] = None
        best_time_diff = timedelta.max
        for index, backtest in enumerate(sorted_backtest):
            if index in matched_backtest:
                continue
            time_diff = abs(actual.timestamp - backtest.timestamp)
            if time_diff <= self.tolerance_delta and time_diff < best_time_diff:
                best_match = (index, backtest)
                best_time_diff = time_diff
        return best_match

    def _build_matched_trade_records(
        self, actual: ActualTrade, backtest: BacktestTrade
    ) -> Tuple[TradeComparison, Optional[DiscrepancyRecord]]:
        actual_action = actual.action.upper()
        backtest_action = backtest.action.upper()
        price_diff = abs(actual.price - backtest.price)
        price_diff_pct = (price_diff / backtest.price * 100) if backtest.price > 0 else 0.0
        is_match = actual_action == backtest_action

        comparison = TradeComparison(
            actual_timestamp=actual.timestamp,
            backtest_timestamp=backtest.timestamp,
            actual_action=actual_action,
            backtest_action=backtest_action,
            actual_price=actual.price,
            backtest_price=backtest.price,
            price_difference=price_diff,
            price_difference_pct=price_diff_pct,
            match_status=MatchStatus.MATCH if is_match else MatchStatus.MISMATCH,
        )
        if is_match:
            return comparison, None
        return comparison, self._build_wrong_direction_discrepancy(actual, actual_action, backtest_action)

    def _build_wrong_direction_discrepancy(
        self, actual: ActualTrade, actual_action: str, backtest_action: str
    ) -> DiscrepancyRecord:
        pnl_impact = actual.profit if actual.profit else 0.0
        pnl_impact_pct = actual.profit_pct if actual.profit_pct else 0.0
        return DiscrepancyRecord(
            timestamp=actual.timestamp,
            discrepancy_type=DiscrepancyType.WRONG_DIRECTION,
            severity=self.calculate_severity(DiscrepancyType.WRONG_DIRECTION, pnl_impact_pct),
            actual_value=actual_action,
            expected_value=backtest_action,
            pnl_impact=pnl_impact,
            pnl_impact_pct=pnl_impact_pct,
            explanation=f"Trade direction mismatch: actual {actual_action}, expected {backtest_action}",
        )

    def _build_extra_trade_records(
        self, actual: ActualTrade
    ) -> Tuple[TradeComparison, DiscrepancyRecord]:
        comparison = TradeComparison(
            actual_timestamp=actual.timestamp,
            backtest_timestamp=None,
            actual_action=actual.action.upper(),
            backtest_action=None,
            actual_price=actual.price,
            backtest_price=None,
            price_difference=0.0,
            price_difference_pct=0.0,
            match_status=MatchStatus.EXTRA,
        )
        pnl_impact = actual.profit if actual.profit else 0.0
        pnl_impact_pct = actual.profit_pct if actual.profit_pct else 0.0
        discrepancy = DiscrepancyRecord(
            timestamp=actual.timestamp,
            discrepancy_type=DiscrepancyType.EXTRA_TRADE,
            severity=self.calculate_severity(DiscrepancyType.EXTRA_TRADE, pnl_impact_pct),
            actual_value=f"{actual.action.upper()} @ {actual.price:,.0f}",
            expected_value=None,
            pnl_impact=pnl_impact,
            pnl_impact_pct=pnl_impact_pct,
            explanation=f"Extra trade executed not in backtest: {actual.action.upper()} at {actual.timestamp}",
        )
        return comparison, discrepancy

    def _build_missing_trade_records(
        self, backtest: BacktestTrade
    ) -> Tuple[TradeComparison, DiscrepancyRecord]:
        comparison = TradeComparison(
            actual_timestamp=None,
            backtest_timestamp=backtest.timestamp,
            actual_action=None,
            backtest_action=backtest.action.upper(),
            actual_price=None,
            backtest_price=backtest.price,
            price_difference=0.0,
            price_difference_pct=0.0,
            match_status=MatchStatus.MISSING,
        )
        pnl_impact = backtest.profit_loss if backtest.profit_loss else 0.0
        pnl_impact_pct = backtest.profit_loss_pct if backtest.profit_loss_pct else 0.0
        discrepancy = DiscrepancyRecord(
            timestamp=backtest.timestamp,
            discrepancy_type=DiscrepancyType.MISSED_TRADE,
            severity=self.calculate_severity(DiscrepancyType.MISSED_TRADE, pnl_impact_pct),
            actual_value=None,
            expected_value=f"{backtest.action.upper()} @ {backtest.price:,.0f}",
            pnl_impact=pnl_impact,
            pnl_impact_pct=pnl_impact_pct,
            explanation=f"Missed trade from backtest: {backtest.action.upper()} at {backtest.timestamp}",
        )
        return comparison, discrepancy

    def _calculate_match_rate(
        self,
        trade_comparisons: List[TradeComparison],
        actual_trades: List[ActualTrade],
        backtest_trades: List[BacktestTrade],
    ) -> float:
        total_trades = max(len(actual_trades), len(backtest_trades))
        if total_trades <= 0:
            return 1.0
        matched_count = len(
            [comparison for comparison in trade_comparisons if comparison.match_status == MatchStatus.MATCH]
        )
        return matched_count / total_trades

    def calculate_severity(
        self,
        discrepancy_type: DiscrepancyType,
        pnl_impact_pct: float
    ) -> Severity:
        """
        Determine severity level for a discrepancy.

        Severity rules:
        - Low: P/L impact < 1%
        - Medium: P/L impact 1-5%
        - High: P/L impact > 5% OR wrong direction trade

        Args:
            discrepancy_type: Type of mismatch
            pnl_impact_pct: Estimated P/L impact as percentage

        Returns:
            Severity enum (Low, Medium, High)
        """
        # Wrong direction is always high severity
        if discrepancy_type == DiscrepancyType.WRONG_DIRECTION:
            return Severity.HIGH

        abs_impact = abs(pnl_impact_pct)

        if abs_impact >= 5.0:
            return Severity.HIGH
        elif abs_impact >= 1.0:
            return Severity.MEDIUM
        else:
            return Severity.LOW
