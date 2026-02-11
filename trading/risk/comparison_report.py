"""
Comparison Report Generator for daily backtest comparison.

Generates reports comparing actual trades against backtested trades
to identify strategy drift and execution issues.
Uses StrategyFactory to ensure backtest logic matches live execution logic.
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
# NOTE: ComponentStrategyAdapter import is deferred to avoid circular import
# (component_adapter -> trading.strategies.components -> trading -> trading.risk -> here)
from trading.strategies.components.strategy_factory import StrategyFactory, STRATEGY_REGISTRY
from trading.indicators import add_all_indicators

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

        # Strategy Factory
        self.factory = StrategyFactory(redis=None)

        logger.info(f"ComparisonReportGenerator initialized with db: {db_path}")

    @property
    def active_strategies(self) -> List[str]:
        """Dynamic list of active strategies from Registry."""
        return list(STRATEGY_REGISTRY.keys())

    def _get_strategy_exchange(self, strategy_name: str) -> str:
        """Get exchange for strategy. System is Binance-only since PR #21."""
        return "binance"

    def _get_data_loader(self, exchange: str = "binance") -> DataLoader:
        """Get or create DataLoader instance."""
        if self._data_loader is None:
            self._data_loader = DataLoader(exchange=exchange)
        elif self._data_loader.exchange != exchange:
            self._data_loader = DataLoader(exchange=exchange)
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
            strategy_name: Strategy identifier (e.g., "short_v1", "short_v1")

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

        exchange = self._get_strategy_exchange(strategy_name)

        # Get actual trades for the date
        actual_trades_raw = self.trade_logger.get_trades_for_date(
            target_date=report_date,
            strategy_name=strategy_name,
            exchange=exchange,
        )

        actual_trades = [
            ActualTrade(
                timestamp=t["timestamp"],
                action=t["action"],
                price=t["price"],
                volume=t["volume"],
                profit=t.get("profit"),
                profit_pct=t.get("profit_pct"),
                exchange=t.get("exchange", exchange),
            )
            for t in actual_trades_raw
        ]

        # Run backtest for the date
        backtest_trades = self._run_single_day_backtest(report_date, strategy_name, exchange)

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

        for strategy_name in self.active_strategies:
            try:
                report = self.generate_report(report_date, strategy_name)
                reports.append(report)
            except Exception as e:
                logger.error(f"Failed to generate report for {strategy_name}: {e}")
                # Continue with other strategies

        return reports

    def _run_single_day_backtest(
        self, report_date: date, strategy_name: str, exchange: str
    ) -> List[BacktestTrade]:
        """
        Run backtest for a single day.

        Args:
            report_date: Date to run backtest for
            strategy_name: Strategy identifier
            exchange: Exchange to load data from (binance/upbit)

        Returns:
            List of BacktestTrade from the backtest
        """
        logger.info(f"Running backtest for {report_date} - {strategy_name}")

        if strategy_name not in STRATEGY_REGISTRY:
            raise BacktestError(f"Unknown strategy: {strategy_name}")

        adapter = self._build_component_adapter(strategy_name)
        df = self._load_backtest_dataframe(report_date, strategy_name, exchange)
        add_all_indicators(df)
        trades = self._replay_backtest_day(df, report_date, adapter)

        logger.info(f"Backtest complete: {len(trades)} trades on {report_date}")
        return trades

    def _build_component_adapter(self, strategy_name: str):
        config = self._load_strategy_config(strategy_name)
        # Lazy import to avoid circular dependency
        from core.component_adapter import ComponentStrategyAdapter
        return ComponentStrategyAdapter(self.factory, strategy_name, config)

    def _load_strategy_config(self, strategy_name: str) -> Dict[str, Any]:
        config_path = _PROJECT_ROOT / f"config/strategies/{strategy_name}.json"
        if not config_path.exists():
            return {}
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def _load_backtest_dataframe(
        self,
        report_date: date,
        strategy_name: str,
        exchange: str,
    ) -> pd.DataFrame:
        warmup_days = 20
        start_date = report_date - timedelta(days=warmup_days)
        end_date = report_date + timedelta(days=1)
        timeframe = STRATEGY_REGISTRY[strategy_name].timeframe

        try:
            loader = self._get_data_loader(exchange)
            df = loader.load_timeframe(
                timeframe=timeframe,
                start_date=start_date.strftime("%Y-%m-%d"),
                end_date=end_date.strftime("%Y-%m-%d"),
            )
            if df.empty:
                raise DataNotFoundError(
                    f"No market data for {report_date} on {exchange}"
                )
            return df
        except FileNotFoundError:
            raise DataNotFoundError(f"Market database not found for {exchange}")

    def _replay_backtest_day(self, df: pd.DataFrame, report_date: date, adapter) -> List[BacktestTrade]:
        adapter.symbol = "BTC"
        date_str = report_date.strftime("%Y-%m-%d")
        trades: List[BacktestTrade] = []
        position_size = 0.0

        for i in range(len(df)):
            signal = adapter(df, i)
            row = df.iloc[i]
            ts_str = str(row.get("timestamp", row.name))
            is_target_day = ts_str.startswith(date_str)
            action = signal.get("action", "hold")

            if not is_target_day:
                position_size = self._apply_warmup_action(action, position_size)
                continue

            position_size = self._apply_target_day_action(
                action=action,
                position_size=position_size,
                ts_str=ts_str,
                close_price=row["close"],
                trades=trades,
            )

        return trades

    def _apply_warmup_action(self, action: str, position_size: float) -> float:
        if action in ("buy", "open_short") and position_size == 0:
            return 1.0 if action == "buy" else -1.0
        if action in ("sell", "close_short") and position_size != 0:
            return 0.0
        return position_size

    def _apply_target_day_action(
        self,
        action: str,
        position_size: float,
        ts_str: str,
        close_price: float,
        trades: List[BacktestTrade],
    ) -> float:
        if action == "buy" and position_size == 0:
            trades.append(
                BacktestTrade(
                    timestamp=datetime.fromisoformat(ts_str),
                    action="buy",
                    price=close_price,
                    volume=1.0,
                    profit=None,
                    profit_pct=None,
                )
            )
            return 1.0

        if action == "open_short" and position_size == 0:
            trades.append(
                BacktestTrade(
                    timestamp=datetime.fromisoformat(ts_str),
                    action="sell",
                    price=close_price,
                    volume=1.0,
                    profit=None,
                    profit_pct=None,
                )
            )
            return -1.0

        if action == "sell" and position_size > 0:
            trades.append(
                BacktestTrade(
                    timestamp=datetime.fromisoformat(ts_str),
                    action="sell",
                    price=close_price,
                    volume=1.0,
                    profit=0,
                    profit_pct=0,
                )
            )
            return 0.0

        if action == "close_short" and position_size < 0:
            trades.append(
                BacktestTrade(
                    timestamp=datetime.fromisoformat(ts_str),
                    action="buy",
                    price=close_price,
                    volume=1.0,
                    profit=0,
                    profit_pct=0,
                )
            )
            return 0.0

        return position_size

    def _calculate_metrics(self, trades: List[Dict]) -> Dict[str, float]:
        """Calculate metrics from actual trades."""
        if not trades:
            return self._empty_metrics()

        sell_trades = [trade for trade in trades if trade.get("action", "").upper() == "SELL"]
        profits = [(trade.get("profit", 0) or 0) for trade in sell_trades]
        profit_pcts = [(trade.get("profit_pct", 0) or 0) for trade in sell_trades]
        return self._calculate_metrics_from_values(profits, profit_pcts)

    def _calculate_backtest_metrics(
        self, trades: List[BacktestTrade]
    ) -> Dict[str, float]:
        """Calculate metrics from backtest trades."""
        if not trades:
            return self._empty_metrics()

        trades_with_pnl = [trade for trade in trades if trade.profit_loss is not None]
        profits = [trade.profit_loss or 0 for trade in trades_with_pnl]
        profit_pcts = [trade.profit_loss_pct or 0 for trade in trades if trade.profit_loss_pct is not None]
        return self._calculate_metrics_from_values(profits, profit_pcts)

    def _empty_metrics(self) -> Dict[str, float]:
        return {"pnl": 0.0, "pnl_pct": 0.0, "max_drawdown": 0.0, "win_rate": 0.0}

    def _calculate_metrics_from_values(
        self, profits: List[float], profit_pcts: List[float]
    ) -> Dict[str, float]:
        total_pnl = sum(profits)
        total_pnl_pct = sum(profit_pcts)
        winning = sum(1 for profit in profits if profit > 0)
        win_rate = winning / len(profits) if profits else 0.0
        return {
            "pnl": total_pnl,
            "pnl_pct": total_pnl_pct,
            "max_drawdown": self._max_drawdown_from_pcts(profit_pcts),
            "win_rate": win_rate,
        }

    def _max_drawdown_from_pcts(self, profit_pcts: List[float]) -> float:
        cumulative = 0.0
        peak = 0.0
        max_dd = 0.0
        for value in profit_pcts:
            cumulative += value
            peak = max(peak, cumulative)
            max_dd = max(max_dd, peak - cumulative)
        return max_dd

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
