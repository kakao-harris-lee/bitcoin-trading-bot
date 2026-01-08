"""
Comparison Report Generator for daily backtest comparison.

Generates reports comparing actual trades against backtested trades
to identify strategy drift and execution issues.
"""

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional, Dict, Any

import pandas as pd

from core.backtester import Backtester, Trade
from core.data_loader import DataLoader

from .comparison_models import (
    DailyComparisonReport,
    TradeComparison,
    DiscrepancyRecord,
    ComparisonResult,
    Severity,
)
from .comparison_exceptions import (
    DataNotFoundError,
    DatabaseError,
    BacktestError,
)
from .trade_comparer import TradeComparer, ActualTrade, BacktestTrade
from .trade_logger import TradeLogger

logger = logging.getLogger(__name__)

# Project root for default paths
_PROJECT_ROOT = Path(__file__).parent.parent.parent


class ComparisonReportGenerator:
    """Generates daily comparison reports between actual and backtested trades."""

    # Active strategies for comparison
    ACTIVE_STRATEGIES = ["v35_long", "short_v1"]

    # Strategy to exchange mapping
    STRATEGY_EXCHANGE_MAP = {
        "v35_long": "upbit",
        "short_v1": "binance",
    }

    # Strategy function registry - maps strategy names to their backtest functions
    # These are simplified versions of the real-time strategies for backtesting
    STRATEGY_FUNCS = {}

    def __init__(
        self,
        db_path: str = None,
        data_loader: Optional[DataLoader] = None,
    ) -> None:
        """
        Initialize the report generator.

        Args:
            db_path: Path to trading results database
            data_loader: DataLoader instance for market data (uses default if None)
        """
        if db_path is None:
            db_path = str(_PROJECT_ROOT / "trading_results.db")

        self.db_path = db_path
        self._data_loader = data_loader

        # Initialize components
        self.trade_logger = TradeLogger(db_path)
        self.trade_comparer = TradeComparer(tolerance_minutes=5)

        # Register strategy functions
        self._register_strategies()

        logger.info(f"ComparisonReportGenerator initialized with db: {db_path}")

    def _register_strategies(self):
        """Register backtest strategy functions."""
        # Import strategy configs and create backtest functions
        self.STRATEGY_FUNCS["v35_long"] = self._create_v35_strategy_func()
        self.STRATEGY_FUNCS["short_v1"] = self._create_short_v1_strategy_func()

    def _create_v35_strategy_func(self):
        """Create V35 long strategy function for backtesting."""
        def v35_strategy(df: pd.DataFrame, i: int, params: Dict) -> Dict:
            """V35 Long Strategy (simplified for backtest comparison)."""
            if i < 30:
                return {"action": "hold"}

            # Add indicators if not present
            if "rsi" not in df.columns:
                df = _add_indicators(df)

            row = df.iloc[i]

            # Get indicators
            rsi = row.get("rsi", 50)
            macd = row.get("macd", 0)
            macd_signal = row.get("macd_signal", 0)
            mfi = row.get("mfi", 50)
            adx = row.get("adx", 20)

            # Simple market state classification
            is_bull = mfi >= 54 and adx >= 18

            # Entry conditions
            if is_bull and macd > macd_signal and rsi > 52:
                return {"action": "buy", "fraction": 0.5}

            # Exit conditions (if in position - tracked by backtester)
            if macd < macd_signal and rsi < 50:
                return {"action": "sell", "fraction": 1.0}

            return {"action": "hold"}

        return v35_strategy

    def _create_short_v1_strategy_func(self):
        """Create Short V1 strategy function for backtesting."""
        def short_v1_strategy(df: pd.DataFrame, i: int, params: Dict) -> Dict:
            """Short V1 Strategy (simplified for backtest comparison)."""
            if i < 30:
                return {"action": "hold"}

            # Add indicators if not present
            if "rsi" not in df.columns:
                df = _add_indicators(df)

            row = df.iloc[i]

            # Get indicators
            rsi = row.get("rsi", 50)
            mfi = row.get("mfi", 50)
            adx = row.get("adx", 20)

            # Bear detection for short entry
            is_bear = mfi < 49 and adx >= 25

            # Short entry (represented as 'buy' in backtest - opening short)
            if is_bear and rsi < 45:
                return {"action": "buy", "fraction": 0.5}

            # Short exit (represented as 'sell' in backtest - closing short)
            if mfi > 52 or rsi > 55:
                return {"action": "sell", "fraction": 1.0}

            return {"action": "hold"}

        return short_v1_strategy

    def _get_data_loader(self) -> DataLoader:
        """Get or create DataLoader instance."""
        if self._data_loader is None:
            self._data_loader = DataLoader()
        return self._data_loader

    def generate_report(
        self,
        report_date: date,
        strategy_name: str,
    ) -> DailyComparisonReport:
        """
        Generate comparison report for a specific date and strategy.

        Args:
            report_date: Date to generate report for (YYYY-MM-DD)
            strategy_name: Strategy identifier (e.g., "v35_long", "short_v1")

        Returns:
            DailyComparisonReport with all metrics and discrepancies

        Raises:
            ValueError: If report_date is in the future
            DataNotFoundError: If market data unavailable for date
        """
        logger.info(f"Generating report for {report_date} - {strategy_name}")

        # Validate date
        if report_date > date.today():
            raise ValueError(f"Cannot generate report for future date: {report_date}")

        # Get actual trades for the date
        actual_trades_raw = self.trade_logger.get_trades_for_date(
            target_date=report_date,
            strategy_name=strategy_name,
            exchange=self.STRATEGY_EXCHANGE_MAP.get(strategy_name),
        )

        actual_trades = [
            ActualTrade(
                timestamp=t["timestamp"],
                action=t["action"],
                price=t["price"],
                volume=t["volume"],
                profit=t.get("profit"),
                profit_pct=t.get("profit_pct"),
                exchange=t.get("exchange", "upbit"),
            )
            for t in actual_trades_raw
        ]

        # Run backtest for the date
        backtest_trades = self._run_single_day_backtest(report_date, strategy_name)

        # Compare trades
        comparison_result = self.trade_comparer.compare_trades(
            actual_trades, backtest_trades
        )

        # Calculate metrics
        actual_metrics = self._calculate_metrics(actual_trades_raw)
        backtest_metrics = self._calculate_backtest_metrics(backtest_trades)

        # Determine max severity
        max_severity = self._get_max_severity(comparison_result.discrepancies)

        # Create report
        report = DailyComparisonReport(
            report_date=report_date,
            strategy_name=strategy_name,
            actual_trades_count=len(actual_trades),
            backtest_trades_count=len(backtest_trades),
            actual_pnl=actual_metrics["pnl"],
            backtest_pnl=backtest_metrics["pnl"],
            actual_pnl_pct=actual_metrics["pnl_pct"],
            backtest_pnl_pct=backtest_metrics["pnl_pct"],
            actual_win_rate=actual_metrics["win_rate"],
            backtest_win_rate=backtest_metrics["win_rate"],
            actual_max_drawdown=actual_metrics["max_drawdown"],
            backtest_max_drawdown=backtest_metrics["max_drawdown"],
            discrepancy_count=len(comparison_result.discrepancies),
            max_severity=max_severity,
            trade_comparisons=comparison_result.trade_comparisons,
            discrepancies=comparison_result.discrepancies,
            created_at=datetime.now(),
        )

        logger.info(
            f"Report generated: {len(actual_trades)} actual trades, "
            f"{len(backtest_trades)} backtest trades, "
            f"{len(comparison_result.discrepancies)} discrepancies"
        )

        return report

    def generate_all_reports(self, report_date: date) -> List[DailyComparisonReport]:
        """
        Generate reports for all active strategies for a given date.

        Args:
            report_date: Date to generate reports for

        Returns:
            List of DailyComparisonReport, one per active strategy
        """
        reports = []

        for strategy_name in self.ACTIVE_STRATEGIES:
            try:
                report = self.generate_report(report_date, strategy_name)
                reports.append(report)
            except Exception as e:
                logger.error(f"Failed to generate report for {strategy_name}: {e}")
                # Continue with other strategies

        return reports

    def _run_single_day_backtest(
        self, report_date: date, strategy_name: str
    ) -> List[BacktestTrade]:
        """
        Run backtest for a single day.

        Args:
            report_date: Date to run backtest for
            strategy_name: Strategy identifier

        Returns:
            List of BacktestTrade from the backtest
        """
        logger.info(f"Running backtest for {report_date} - {strategy_name}")

        # Get strategy function
        strategy_func = self.STRATEGY_FUNCS.get(strategy_name)
        if not strategy_func:
            raise BacktestError(f"Unknown strategy: {strategy_name}")

        # Determine exchange for data loading
        exchange = self.STRATEGY_EXCHANGE_MAP.get(strategy_name, "upbit")

        # Load market data for the date (include some days before for indicator warmup)
        warmup_days = 3
        start_date = report_date - timedelta(days=warmup_days)
        end_date = report_date + timedelta(days=1)  # Include full day

        try:
            loader = self._get_data_loader()
            df = loader.load_timeframe(
                "minute60",  # Use hourly data for comparison
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
                exchange=exchange,
            )

            if df.empty:
                raise DataNotFoundError(
                    f"No market data for {report_date} on {exchange}"
                )

        except FileNotFoundError:
            raise DataNotFoundError(f"Market database not found for {exchange}")

        # Add indicators
        df = _add_indicators(df)

        # Run backtester
        backtester = Backtester(
            initial_capital=10_000_000,
            fee_rate=0.0005,
            slippage=0.0002,
        )

        results = backtester.run(df, strategy_func, {})

        # Convert Trade objects to BacktestTrade
        backtest_trades = []
        raw_trades: List[Trade] = results.get("trades", [])

        for trade in raw_trades:
            # Filter to only trades on the report date
            trade_date = trade.entry_time.date() if isinstance(trade.entry_time, datetime) else trade.entry_time

            if trade_date == report_date:
                bt_trade = BacktestTrade(
                    timestamp=trade.entry_time,
                    action=trade.side,  # "buy" or "sell"
                    price=trade.entry_price,
                    quantity=trade.quantity,
                    profit_loss=trade.profit_loss,
                    profit_loss_pct=trade.profit_loss_pct,
                )
                backtest_trades.append(bt_trade)

                # Also add exit as a trade if present
                if trade.exit_time:
                    exit_trade = BacktestTrade(
                        timestamp=trade.exit_time,
                        action="sell" if trade.side == "buy" else "buy",
                        price=trade.exit_price,
                        quantity=trade.quantity,
                        profit_loss=trade.profit_loss,
                        profit_loss_pct=trade.profit_loss_pct,
                    )
                    if exit_trade.timestamp.date() == report_date:
                        backtest_trades.append(exit_trade)

        logger.info(f"Backtest complete: {len(backtest_trades)} trades on {report_date}")
        return backtest_trades

    def _calculate_metrics(self, trades: List[Dict]) -> Dict[str, float]:
        """Calculate metrics from actual trades."""
        if not trades:
            return {
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
            }

        # Sum P/L from sell trades
        total_pnl = sum(
            t.get("profit", 0) or 0
            for t in trades
            if t.get("action", "").upper() == "SELL"
        )

        total_pnl_pct = sum(
            t.get("profit_pct", 0) or 0
            for t in trades
            if t.get("action", "").upper() == "SELL"
        )

        # Win rate
        sell_trades = [t for t in trades if t.get("action", "").upper() == "SELL"]
        winning = sum(1 for t in sell_trades if (t.get("profit", 0) or 0) > 0)
        win_rate = winning / len(sell_trades) if sell_trades else 0.0

        # Simple max drawdown (from sequential P/L)
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            if t.get("action", "").upper() == "SELL":
                cumulative += t.get("profit_pct", 0) or 0
                peak = max(peak, cumulative)
                dd = peak - cumulative
                max_dd = max(max_dd, dd)

        return {
            "pnl": total_pnl,
            "pnl_pct": total_pnl_pct,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
        }

    def _calculate_backtest_metrics(
        self, trades: List[BacktestTrade]
    ) -> Dict[str, float]:
        """Calculate metrics from backtest trades."""
        if not trades:
            return {
                "pnl": 0.0,
                "pnl_pct": 0.0,
                "max_drawdown": 0.0,
                "win_rate": 0.0,
            }

        # Sum P/L from trades with profit info
        total_pnl = sum(t.profit_loss or 0 for t in trades if t.profit_loss is not None)
        total_pnl_pct = sum(
            t.profit_loss_pct or 0 for t in trades if t.profit_loss_pct is not None
        )

        # Win rate
        trades_with_pnl = [t for t in trades if t.profit_loss is not None]
        winning = sum(1 for t in trades_with_pnl if t.profit_loss > 0)
        win_rate = winning / len(trades_with_pnl) if trades_with_pnl else 0.0

        # Simple max drawdown
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for t in trades:
            if t.profit_loss_pct is not None:
                cumulative += t.profit_loss_pct
                peak = max(peak, cumulative)
                dd = peak - cumulative
                max_dd = max(max_dd, dd)

        return {
            "pnl": total_pnl,
            "pnl_pct": total_pnl_pct,
            "max_drawdown": max_dd,
            "win_rate": win_rate,
        }

    def _get_max_severity(self, discrepancies: List[DiscrepancyRecord]) -> Severity:
        """Get the maximum severity from discrepancies."""
        if not discrepancies:
            return Severity.LOW

        severity_order = {Severity.LOW: 0, Severity.MEDIUM: 1, Severity.HIGH: 2}
        max_sev = Severity.LOW

        for d in discrepancies:
            if severity_order[d.severity] > severity_order[max_sev]:
                max_sev = d.severity

        return max_sev

    def save_report(self, report: DailyComparisonReport) -> int:
        """
        Persist report to database.

        Args:
            report: Report to save

        Returns:
            Database ID of saved report

        Raises:
            DatabaseError: If save fails
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            # Serialize report to JSON
            report_json = self._serialize_report(report)

            cursor.execute(
                """
                INSERT OR REPLACE INTO comparison_reports (
                    report_date, strategy_name,
                    actual_trades_count, backtest_trades_count,
                    actual_pnl, backtest_pnl,
                    actual_pnl_pct, backtest_pnl_pct,
                    actual_max_drawdown, backtest_max_drawdown,
                    discrepancy_count, max_severity,
                    report_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    report.report_date.isoformat(),
                    report.strategy_name,
                    report.actual_trades_count,
                    report.backtest_trades_count,
                    report.actual_pnl,
                    report.backtest_pnl,
                    report.actual_pnl_pct,
                    report.backtest_pnl_pct,
                    report.actual_max_drawdown,
                    report.backtest_max_drawdown,
                    report.discrepancy_count,
                    report.max_severity.value,
                    report_json,
                    report.created_at.isoformat(),
                ),
            )

            conn.commit()
            report_id = cursor.lastrowid
            conn.close()

            logger.info(f"Report saved with ID: {report_id}")
            return report_id

        except sqlite3.Error as e:
            raise DatabaseError(f"Failed to save report: {e}")

    def _serialize_report(self, report: DailyComparisonReport) -> str:
        """Serialize report to JSON string."""
        data = {
            "report_date": report.report_date.isoformat(),
            "strategy_name": report.strategy_name,
            "actual_trades_count": report.actual_trades_count,
            "backtest_trades_count": report.backtest_trades_count,
            "actual_pnl": report.actual_pnl,
            "backtest_pnl": report.backtest_pnl,
            "actual_pnl_pct": report.actual_pnl_pct,
            "backtest_pnl_pct": report.backtest_pnl_pct,
            "actual_win_rate": report.actual_win_rate,
            "backtest_win_rate": report.backtest_win_rate,
            "actual_max_drawdown": report.actual_max_drawdown,
            "backtest_max_drawdown": report.backtest_max_drawdown,
            "discrepancy_count": report.discrepancy_count,
            "max_severity": report.max_severity.value,
            "trade_comparisons": [
                {
                    "actual_timestamp": tc.actual_timestamp.isoformat()
                    if tc.actual_timestamp
                    else None,
                    "backtest_timestamp": tc.backtest_timestamp.isoformat()
                    if tc.backtest_timestamp
                    else None,
                    "actual_action": tc.actual_action,
                    "backtest_action": tc.backtest_action,
                    "actual_price": tc.actual_price,
                    "backtest_price": tc.backtest_price,
                    "price_difference": tc.price_difference,
                    "price_difference_pct": tc.price_difference_pct,
                    "match_status": tc.match_status.value,
                }
                for tc in report.trade_comparisons
            ],
            "discrepancies": [
                {
                    "timestamp": d.timestamp.isoformat(),
                    "discrepancy_type": d.discrepancy_type.value,
                    "severity": d.severity.value,
                    "actual_value": d.actual_value,
                    "expected_value": d.expected_value,
                    "pnl_impact": d.pnl_impact,
                    "pnl_impact_pct": d.pnl_impact_pct,
                    "explanation": d.explanation,
                }
                for d in report.discrepancies
            ],
            "created_at": report.created_at.isoformat(),
        }
        return json.dumps(data, ensure_ascii=False)

    def get_report(
        self, report_date: date, strategy_name: str
    ) -> Optional[DailyComparisonReport]:
        """
        Retrieve a previously generated report.

        Args:
            report_date: Date of report
            strategy_name: Strategy identifier

        Returns:
            DailyComparisonReport if found, None otherwise
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute(
                """
                SELECT report_json FROM comparison_reports
                WHERE report_date = ? AND strategy_name = ?
            """,
                (report_date.isoformat(), strategy_name),
            )

            row = cursor.fetchone()
            conn.close()

            if row:
                return self._deserialize_report(row[0])
            return None

        except sqlite3.Error as e:
            logger.error(f"Failed to get report: {e}")
            return None

    def get_reports_in_range(
        self,
        start_date: date,
        end_date: date,
        strategy_name: Optional[str] = None,
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
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            if strategy_name:
                cursor.execute(
                    """
                    SELECT report_json FROM comparison_reports
                    WHERE report_date >= ? AND report_date <= ?
                    AND strategy_name = ?
                    ORDER BY report_date DESC
                """,
                    (start_date.isoformat(), end_date.isoformat(), strategy_name),
                )
            else:
                cursor.execute(
                    """
                    SELECT report_json FROM comparison_reports
                    WHERE report_date >= ? AND report_date <= ?
                    ORDER BY report_date DESC
                """,
                    (start_date.isoformat(), end_date.isoformat()),
                )

            rows = cursor.fetchall()
            conn.close()

            reports = []
            for row in rows:
                report = self._deserialize_report(row[0])
                if report:
                    reports.append(report)

            return reports

        except sqlite3.Error as e:
            logger.error(f"Failed to get reports in range: {e}")
            return []

    def _deserialize_report(self, json_str: str) -> Optional[DailyComparisonReport]:
        """Deserialize report from JSON string."""
        try:
            from .comparison_models import MatchStatus, DiscrepancyType

            data = json.loads(json_str)

            trade_comparisons = [
                TradeComparison(
                    actual_timestamp=datetime.fromisoformat(tc["actual_timestamp"])
                    if tc["actual_timestamp"]
                    else None,
                    backtest_timestamp=datetime.fromisoformat(tc["backtest_timestamp"])
                    if tc["backtest_timestamp"]
                    else None,
                    actual_action=tc["actual_action"],
                    backtest_action=tc["backtest_action"],
                    actual_price=tc["actual_price"],
                    backtest_price=tc["backtest_price"],
                    price_difference=tc["price_difference"],
                    price_difference_pct=tc["price_difference_pct"],
                    match_status=MatchStatus(tc["match_status"]),
                )
                for tc in data["trade_comparisons"]
            ]

            discrepancies = [
                DiscrepancyRecord(
                    timestamp=datetime.fromisoformat(d["timestamp"]),
                    discrepancy_type=DiscrepancyType(d["discrepancy_type"]),
                    severity=Severity(d["severity"]),
                    actual_value=d["actual_value"],
                    expected_value=d["expected_value"],
                    pnl_impact=d["pnl_impact"],
                    pnl_impact_pct=d["pnl_impact_pct"],
                    explanation=d["explanation"],
                )
                for d in data["discrepancies"]
            ]

            return DailyComparisonReport(
                report_date=date.fromisoformat(data["report_date"]),
                strategy_name=data["strategy_name"],
                actual_trades_count=data["actual_trades_count"],
                backtest_trades_count=data["backtest_trades_count"],
                actual_pnl=data["actual_pnl"],
                backtest_pnl=data["backtest_pnl"],
                actual_pnl_pct=data["actual_pnl_pct"],
                backtest_pnl_pct=data["backtest_pnl_pct"],
                actual_win_rate=data.get("actual_win_rate", 0.0),
                backtest_win_rate=data.get("backtest_win_rate", 0.0),
                actual_max_drawdown=data["actual_max_drawdown"],
                backtest_max_drawdown=data["backtest_max_drawdown"],
                discrepancy_count=data["discrepancy_count"],
                max_severity=Severity(data["max_severity"]),
                trade_comparisons=trade_comparisons,
                discrepancies=discrepancies,
                created_at=datetime.fromisoformat(data["created_at"]),
            )

        except (json.JSONDecodeError, KeyError, ValueError) as e:
            logger.error(f"Failed to deserialize report: {e}")
            return None


def _add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add technical indicators to dataframe."""
    import numpy as np

    # RSI
    delta = df["close"].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    df["rsi"] = 100 - (100 / (1 + rs))

    # MACD
    ema12 = df["close"].ewm(span=12, adjust=False).mean()
    ema26 = df["close"].ewm(span=26, adjust=False).mean()
    df["macd"] = ema12 - ema26
    df["macd_signal"] = df["macd"].ewm(span=9, adjust=False).mean()

    # MFI
    typical_price = (df["high"] + df["low"] + df["close"]) / 3
    raw_money_flow = typical_price * df["volume"]
    positive_flow = raw_money_flow.where(typical_price > typical_price.shift(1), 0)
    negative_flow = raw_money_flow.where(typical_price < typical_price.shift(1), 0)
    positive_mf = positive_flow.rolling(window=14).sum()
    negative_mf = negative_flow.rolling(window=14).sum()
    mfi_ratio = positive_mf / negative_mf.replace(0, np.nan)
    df["mfi"] = 100 - (100 / (1 + mfi_ratio))

    # ADX (simplified)
    high = df["high"]
    low = df["low"]
    close = df["close"]

    tr1 = high - low
    tr2 = abs(high - close.shift(1))
    tr3 = abs(low - close.shift(1))
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0)

    plus_dm = pd.Series(plus_dm, index=df.index)
    minus_dm = pd.Series(minus_dm, index=df.index)

    period = 14
    atr = tr.ewm(alpha=1 / period, adjust=False).mean()
    smooth_plus = plus_dm.ewm(alpha=1 / period, adjust=False).mean()
    smooth_minus = minus_dm.ewm(alpha=1 / period, adjust=False).mean()

    plus_di = 100 * smooth_plus / atr.replace(0, np.nan)
    minus_di = 100 * smooth_minus / atr.replace(0, np.nan)

    dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di).replace(0, np.nan)
    df["adx"] = dx.ewm(alpha=1 / period, adjust=False).mean()

    return df
