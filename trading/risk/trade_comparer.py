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
    exchange: str = "upbit"


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

        # Track which trades have been matched
        matched_actual = set()
        matched_backtest = set()

        # Sort trades by timestamp
        sorted_actual = sorted(actual_trades, key=lambda t: t.timestamp)
        sorted_backtest = sorted(backtest_trades, key=lambda t: t.timestamp)

        # Match actual trades to backtest trades
        for i, actual in enumerate(sorted_actual):
            best_match: Optional[Tuple[int, BacktestTrade]] = None
            best_time_diff = timedelta.max

            for j, backtest in enumerate(sorted_backtest):
                if j in matched_backtest:
                    continue

                time_diff = abs(actual.timestamp - backtest.timestamp)

                if time_diff <= self.tolerance_delta and time_diff < best_time_diff:
                    best_match = (j, backtest)
                    best_time_diff = time_diff

            if best_match:
                j, backtest = best_match
                matched_actual.add(i)
                matched_backtest.add(j)

                # Check if actions match (normalize case)
                actual_action_norm = actual.action.upper()
                backtest_action_norm = backtest.action.upper()
                actions_match = actual_action_norm == backtest_action_norm

                # Calculate price difference
                price_diff = abs(actual.price - backtest.price)
                price_diff_pct = (price_diff / backtest.price * 100) if backtest.price > 0 else 0.0

                if actions_match:
                    match_status = MatchStatus.MATCH
                else:
                    match_status = MatchStatus.MISMATCH
                    # Add discrepancy for wrong direction
                    pnl_impact = actual.profit if actual.profit else 0.0
                    pnl_impact_pct = actual.profit_pct if actual.profit_pct else 0.0

                    discrepancy = DiscrepancyRecord(
                        timestamp=actual.timestamp,
                        discrepancy_type=DiscrepancyType.WRONG_DIRECTION,
                        severity=self.calculate_severity(DiscrepancyType.WRONG_DIRECTION, pnl_impact_pct),
                        actual_value=actual_action_norm,
                        expected_value=backtest_action_norm,
                        pnl_impact=pnl_impact,
                        pnl_impact_pct=pnl_impact_pct,
                        explanation=f"Trade direction mismatch: actual {actual_action_norm}, expected {backtest_action_norm}"
                    )
                    discrepancies.append(discrepancy)

                comparison = TradeComparison(
                    actual_timestamp=actual.timestamp,
                    backtest_timestamp=backtest.timestamp,
                    actual_action=actual_action_norm,
                    backtest_action=backtest_action_norm,
                    actual_price=actual.price,
                    backtest_price=backtest.price,
                    price_difference=price_diff,
                    price_difference_pct=price_diff_pct,
                    match_status=match_status
                )
                trade_comparisons.append(comparison)
            else:
                # Extra trade - actual trade with no matching backtest trade
                comparison = TradeComparison(
                    actual_timestamp=actual.timestamp,
                    backtest_timestamp=None,
                    actual_action=actual.action.upper(),
                    backtest_action=None,
                    actual_price=actual.price,
                    backtest_price=None,
                    price_difference=0.0,
                    price_difference_pct=0.0,
                    match_status=MatchStatus.EXTRA
                )
                trade_comparisons.append(comparison)

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
                    explanation=f"Extra trade executed not in backtest: {actual.action.upper()} at {actual.timestamp}"
                )
                discrepancies.append(discrepancy)

        # Handle missed trades - backtest trades with no matching actual trade
        for j, backtest in enumerate(sorted_backtest):
            if j not in matched_backtest:
                comparison = TradeComparison(
                    actual_timestamp=None,
                    backtest_timestamp=backtest.timestamp,
                    actual_action=None,
                    backtest_action=backtest.action.upper(),
                    actual_price=None,
                    backtest_price=backtest.price,
                    price_difference=0.0,
                    price_difference_pct=0.0,
                    match_status=MatchStatus.MISSING
                )
                trade_comparisons.append(comparison)

                # Estimate P/L impact from missed trade
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
                    explanation=f"Missed trade from backtest: {backtest.action.upper()} at {backtest.timestamp}"
                )
                discrepancies.append(discrepancy)

        # Calculate match rate
        total_trades = max(len(actual_trades), len(backtest_trades))
        matched_count = len([tc for tc in trade_comparisons if tc.match_status == MatchStatus.MATCH])
        match_rate = matched_count / total_trades if total_trades > 0 else 1.0

        return ComparisonResult(
            trade_comparisons=trade_comparisons,
            discrepancies=discrepancies,
            match_rate=match_rate
        )

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
