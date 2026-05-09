"""
Comparison Report Generator for daily backtest comparison.

Generates reports comparing actual trades against backtested trades
to identify strategy drift and execution issues.
Uses StrategyFactory to ensure backtest logic matches live execution logic.
"""

# pylint: disable=logging-fstring-interpolation,broad-exception-caught

import json
import logging
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional, Dict, Any

import pandas as pd

from core.data_loader import DataLoader
# NOTE: ComponentStrategyAdapter import is deferred to avoid circular import
# (component_adapter -> trading.strategies.components -> trading -> trading.risk -> here)
from trading.strategies.components.strategy_factory import StrategyFactory, STRATEGY_REGISTRY
from trading.indicators import add_all_indicators

from .comparison_models import (
    DailyComparisonReport,
    TradeComparison,
    DiscrepancyRecord,
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
_ALLOCATION_PATH = _PROJECT_ROOT / "config" / "strategies" / "allocation.json"
_DEFAULT_PAPER_DB_PATH = _PROJECT_ROOT / "data" / "paper_trading_results.db"
_SYMBOL_DB_MAPPING = {
    "BTC": _PROJECT_ROOT / "data" / "binance_bitcoin.db",
    "ETH": _PROJECT_ROOT / "data" / "binance_ethereum.db",
    "SOL": _PROJECT_ROOT / "data" / "binance_solana.db",
    "BNB": _PROJECT_ROOT / "data" / "binance_bnb.db",
}


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
            db_path = str(_DEFAULT_PAPER_DB_PATH)

        self.db_path = db_path
        self._data_loader = data_loader

        # Initialize components
        self.trade_logger = TradeLogger(db_path, strategy_name="paper_trading")
        self.trade_comparer = TradeComparer(tolerance_minutes=5)
        self._init_comparison_schema()

        # Strategy Factory
        self.factory = StrategyFactory(redis=None)

        logger.info(f"ComparisonReportGenerator initialized with db: {db_path}")

    @property
    def active_strategies(self) -> List[str]:
        """Dynamic list of active strategies from allocation.json and registry."""
        allocation_strategies = self._load_allocation_strategies()
        enabled = [
            name
            for name, cfg in allocation_strategies.items()
            if isinstance(cfg, dict)
            and cfg.get("enabled", True)
            and cfg.get("market", "spot") == "spot"
        ]
        if enabled:
            return enabled
        return list(STRATEGY_REGISTRY.keys())

    def _get_strategy_exchange(self, _strategy_name: str) -> str:
        """Get exchange for strategy. System is Binance-only since PR #21."""
        return "binance"

    def _get_data_loader(self, exchange: str = "binance") -> DataLoader:
        """Get or create DataLoader instance."""
        if self._data_loader is None:
            self._data_loader = DataLoader(exchange=exchange)
        elif self._data_loader.exchange != exchange:
            self._data_loader = DataLoader(exchange=exchange)
        return self._data_loader

    def get_strategy_data_coverage(self, strategy_name: str) -> Dict[str, Any]:
        """Return available OHLCV coverage for a configured strategy."""
        strategy_config = self._load_strategy_config(strategy_name)
        symbol = self._resolve_strategy_symbol(strategy_config)
        timeframe = self._resolve_db_timeframe(
            self._resolve_strategy_timeframe(strategy_name, strategy_config)
        )
        db_path = _SYMBOL_DB_MAPPING.get(symbol, _SYMBOL_DB_MAPPING["BTC"])
        if not db_path.exists():
            return {
                "strategy": strategy_name,
                "symbol": symbol,
                "timeframe": timeframe,
                "db_path": str(db_path),
                "exists": False,
                "rows": 0,
                "min_timestamp": None,
                "max_timestamp": None,
            }

        loader = DataLoader(db_path=str(db_path))
        table_name = loader._get_table_name(timeframe)
        try:
            cursor = loader.conn.execute(
                f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table_name}"
            )
            rows, min_ts, max_ts = cursor.fetchone()
        finally:
            loader.close()
        return {
            "strategy": strategy_name,
            "symbol": symbol,
            "timeframe": timeframe,
            "db_path": str(db_path),
            "table": table_name,
            "exists": True,
            "rows": rows,
            "min_timestamp": min_ts,
            "max_timestamp": max_ts,
        }


    def generate_report(
        self,
        report_date: date,
        strategy_name: str,
    ) -> DailyComparisonReport:
        """
        Generate comparison report for a specific date and strategy.

        Args:
            report_date: Date to generate report for (YYYY-MM-DD)
            strategy_name: Strategy identifier (e.g., "llm_direction_btc")

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

        strategy_config = self._load_strategy_config(strategy_name)

        actual_trades_raw = self._load_actual_trades(
            target_date=report_date,
            strategy_name=strategy_name,
            strategy_config=strategy_config,
            exchange=exchange,
        )
        actual_trades = self._to_actual_trades(actual_trades_raw, exchange)

        # Run backtest for the date
        backtest_trades = self._run_single_day_backtest(
            report_date,
            strategy_name,
            exchange,
            strategy_config,
            actual_trades_raw=actual_trades_raw,
        )

        # Compare trades
        trade_comparer = TradeComparer(
            tolerance_minutes=self._resolve_comparison_tolerance_minutes(
                strategy_name, strategy_config
            )
        )
        comparison_result = trade_comparer.compare_trades(
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

    def _init_comparison_schema(self) -> None:
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            cursor.executescript(
                """
                CREATE TABLE IF NOT EXISTS comparison_reports (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    report_date DATE NOT NULL,
                    strategy_name TEXT NOT NULL,
                    actual_trades_count INTEGER DEFAULT 0,
                    backtest_trades_count INTEGER DEFAULT 0,
                    actual_pnl REAL DEFAULT 0.0,
                    backtest_pnl REAL DEFAULT 0.0,
                    actual_pnl_pct REAL DEFAULT 0.0,
                    backtest_pnl_pct REAL DEFAULT 0.0,
                    actual_max_drawdown REAL DEFAULT 0.0,
                    backtest_max_drawdown REAL DEFAULT 0.0,
                    discrepancy_count INTEGER DEFAULT 0,
                    max_severity TEXT DEFAULT 'Low',
                    report_json TEXT NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(report_date, strategy_name)
                );
                CREATE INDEX IF NOT EXISTS idx_comparison_reports_date
                ON comparison_reports(report_date);
                CREATE INDEX IF NOT EXISTS idx_comparison_reports_strategy
                ON comparison_reports(strategy_name);
                CREATE INDEX IF NOT EXISTS idx_comparison_reports_date_strategy
                ON comparison_reports(report_date, strategy_name);
                """
            )
            conn.commit()
            conn.close()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to initialize comparison schema: {exc}") from exc

    def _load_actual_trades(
        self,
        target_date: date,
        strategy_name: str,
        strategy_config: Dict[str, Any],
        exchange: str,
    ) -> List[Dict[str, Any]]:
        symbol = self._resolve_strategy_symbol(strategy_config)
        strategy_rows = self.trade_logger.get_trades_for_date(
            target_date=target_date,
            strategy_name=strategy_name,
            exchange=exchange,
        )
        if strategy_rows:
            return [
                row
                for row in strategy_rows
                if str(row.get("symbol", symbol)).upper() == symbol
            ]
        return self._load_symbol_trades_for_date(
            target_date=target_date,
            symbol=symbol,
            exchange=exchange,
        )

    def _load_symbol_trades_for_date(
        self,
        target_date: date,
        symbol: str,
        exchange: str,
    ) -> List[Dict[str, Any]]:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT action, price, volume, profit, profit_pct, exchange, symbol, timestamp
                FROM trades
                WHERE date(timestamp) = ?
                AND upper(symbol) = ?
                AND exchange = ?
                AND COALESCE(paper, 1) = 1
                ORDER BY timestamp ASC
                """,
                (target_date.strftime("%Y-%m-%d"), symbol.upper(), exchange),
            )
            rows = cursor.fetchall()
            conn.close()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to load symbol trades: {exc}") from exc

        return [
            {
                "action": row["action"],
                "price": row["price"],
                "volume": row["volume"],
                "profit": row["profit"],
                "profit_pct": row["profit_pct"],
                "exchange": row["exchange"],
                "symbol": row["symbol"],
                "timestamp": self._parse_trade_timestamp(row["timestamp"]),
            }
            for row in rows
        ]

    def _to_actual_trades(
        self, rows: List[Dict[str, Any]], exchange: str
    ) -> List[ActualTrade]:
        return [
            ActualTrade(
                timestamp=t["timestamp"],
                action=t["action"],
                price=t["price"],
                volume=t["volume"],
                profit=t.get("profit"),
                profit_pct=t.get("profit_pct"),
                exchange=t.get("exchange", exchange),
            )
            for t in rows
        ]

    def _parse_trade_timestamp(self, raw: str) -> datetime:
        value = str(raw)
        try:
            return datetime.strptime(value, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            return datetime.fromisoformat(value)

    def _run_single_day_backtest(
        self,
        report_date: date,
        strategy_name: str,
        exchange: str,
        strategy_config: Dict[str, Any] | None = None,
        actual_trades_raw: Optional[List[Dict[str, Any]]] = None,
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

        strategy_config = strategy_config or self._load_strategy_config(strategy_name)
        base_strategy = self._resolve_base_strategy_name(strategy_name, strategy_config)
        if base_strategy not in STRATEGY_REGISTRY:
            raise BacktestError(f"Unknown strategy: {strategy_name}")

        adapter = self._build_component_adapter(strategy_name, strategy_config)
        df = self._load_backtest_dataframe(
            report_date, strategy_name, exchange, strategy_config
        )
        add_all_indicators(df)
        carry_position = self._reconstruct_open_position_before_date(
            target_date=report_date,
            strategy_config=strategy_config,
            exchange=exchange,
            target_day_trades=actual_trades_raw or [],
        )
        trades = self._replay_backtest_day(
            df, report_date, adapter, strategy_config, carry_position=carry_position
        )

        logger.info(f"Backtest complete: {len(trades)} trades on {report_date}")
        return trades

    def _build_component_adapter(self, strategy_name: str, config: Dict[str, Any]):
        # Lazy import to avoid circular dependency
        from core.component_adapter import ComponentStrategyAdapter

        config = dict(config)
        config.setdefault("backtest_force_entry_fallback", True)
        base_strategy = self._resolve_base_strategy_name(strategy_name, config)
        adapter = ComponentStrategyAdapter(self.factory, base_strategy, config)
        adapter.symbol = self._resolve_strategy_symbol(config)
        return adapter

    def _load_strategy_config(self, strategy_name: str) -> Dict[str, Any]:
        allocation_config = self._load_allocation_strategies().get(strategy_name)
        if isinstance(allocation_config, dict):
            return dict(allocation_config)

        config_path = _PROJECT_ROOT / f"config/strategies/{strategy_name}.json"
        if not config_path.exists():
            return {}
        try:
            with open(config_path, encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    def _load_allocation_strategies(self) -> Dict[str, Any]:
        if not _ALLOCATION_PATH.exists():
            return {}
        try:
            with _ALLOCATION_PATH.open(encoding="utf-8") as f:
                allocation = json.load(f)
            strategies = allocation.get("strategies", {})
            return strategies if isinstance(strategies, dict) else {}
        except Exception as exc:
            logger.warning("Failed to load allocation strategies: %s", exc)
            return {}

    def _resolve_base_strategy_name(
        self, strategy_name: str, strategy_config: Dict[str, Any]
    ) -> str:
        if strategy_name in STRATEGY_REGISTRY:
            return strategy_name
        base_strategy = strategy_config.get("base_strategy")
        if base_strategy:
            return str(base_strategy)
        if "entry" in strategy_config and "exit" in strategy_config:
            if strategy_name.startswith("llm_direction"):
                return "llm_direction"
            if strategy_name.startswith("regime_long_v2"):
                return "regime_long_v2"
        for registered in STRATEGY_REGISTRY:
            if strategy_name.startswith(registered):
                return registered
        return strategy_name

    def _resolve_strategy_symbol(self, strategy_config: Dict[str, Any]) -> str:
        symbols = strategy_config.get("symbols", [])
        if isinstance(symbols, list) and symbols:
            return str(symbols[0]).upper()
        return "BTC"

    def _resolve_strategy_timeframe(
        self, strategy_name: str, strategy_config: Dict[str, Any]
    ) -> str:
        timeframe = strategy_config.get("timeframe")
        if timeframe:
            return str(timeframe)
        base_strategy = self._resolve_base_strategy_name(strategy_name, strategy_config)
        return STRATEGY_REGISTRY[base_strategy].timeframe

    def _resolve_db_timeframe(self, timeframe: str) -> str:
        timeframe_map = {
            "hour1": "minute60",
            "hour4": "minute240",
            "1h": "minute60",
            "4h": "minute240",
            "1d": "day",
        }
        return timeframe_map.get(timeframe, timeframe)

    def _resolve_comparison_tolerance_minutes(
        self, strategy_name: str, strategy_config: Dict[str, Any]
    ) -> int:
        timeframe = self._resolve_db_timeframe(
            self._resolve_strategy_timeframe(strategy_name, strategy_config)
        )
        if timeframe.startswith("minute"):
            try:
                minutes = int(timeframe.replace("minute", ""))
            except ValueError:
                return 5
            return max(5, min(minutes // 4, 120))
        return 5

    def _load_backtest_dataframe(
        self,
        report_date: date,
        strategy_name: str,
        exchange: str,
        strategy_config: Dict[str, Any],
    ) -> pd.DataFrame:
        warmup_days = int(strategy_config.get("backtest_warmup_days", 90) or 90)
        start_date = report_date - timedelta(days=warmup_days)
        end_date = report_date + timedelta(days=1)
        timeframe = self._resolve_db_timeframe(
            self._resolve_strategy_timeframe(strategy_name, strategy_config)
        )
        symbol = self._resolve_strategy_symbol(strategy_config)
        db_path = _SYMBOL_DB_MAPPING.get(symbol, _SYMBOL_DB_MAPPING["BTC"])

        try:
            loader = DataLoader(db_path=str(db_path), exchange=exchange)
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
        except FileNotFoundError as exc:
            raise DataNotFoundError(f"Market database not found for {exchange}") from exc

    def _replay_backtest_day(
        self,
        df: pd.DataFrame,
        report_date: date,
        adapter,
        strategy_config: Dict[str, Any],
        carry_position: Optional[Dict[str, Any]] = None,
    ) -> List[BacktestTrade]:
        date_str = report_date.strftime("%Y-%m-%d")
        trades: List[BacktestTrade] = []
        state = {
            "quantity": float((carry_position or {}).get("quantity", 0.0) or 0.0),
            "avg_price": float((carry_position or {}).get("entry_price", 0.0) or 0.0),
        }
        allow_scale_in = bool(strategy_config.get("allow_scale_in_entries", False))
        seeded_carry_position = False

        for i in range(len(df)):
            row = df.iloc[i]
            ts_str = str(row.get("timestamp", row.name))
            report_ts = self._market_timestamp_to_report_timestamp(
                row.get("timestamp", row.name)
            )
            is_target_day = ts_str.startswith(date_str)

            if not is_target_day:
                self._warm_adapter_context(adapter, df, i)
                continue

            if carry_position and not seeded_carry_position:
                self._seed_adapter_position(adapter, carry_position)
                seeded_carry_position = True

            signal = adapter(df, i)
            action = signal.get("action", "hold")
            self._apply_replay_action(
                action=action,
                price=float(row["close"]),
                timestamp=report_ts,
                state=state,
                trades=trades,
                allow_scale_in=allow_scale_in,
                quantity=float(signal.get("fraction", 1.0) or 1.0),
            )

        return trades

    def _warm_adapter_context(self, adapter, df: pd.DataFrame, index: int) -> None:
        """Warm stateful regime filters without creating synthetic trades."""
        required = (
            "_decrement_timers",
            "_update_period_risk_state",
            "_extract_row_values",
            "_build_context",
        )
        if not all(hasattr(adapter, name) for name in required):
            return
        row = df.iloc[index]
        adapter._decrement_timers()
        adapter._update_period_risk_state(row)
        values = adapter._extract_row_values(row)
        adapter._build_context(row, values)

    def _market_timestamp_to_report_timestamp(self, raw_timestamp: Any) -> datetime:
        """Convert UTC market-data timestamps into local report timestamps."""
        value = pd.to_datetime(raw_timestamp).to_pydatetime()
        if value.tzinfo is not None:
            return value.astimezone().replace(tzinfo=None)
        local_offset = datetime.now().astimezone().utcoffset() or timedelta()
        return (value.replace(tzinfo=timezone.utc) + local_offset).replace(tzinfo=None)

    def _reconstruct_open_position_before_date(
        self,
        target_date: date,
        strategy_config: Dict[str, Any],
        exchange: str,
        target_day_trades: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        """Rebuild the actual carried position at the start of the report day."""
        symbol = self._resolve_strategy_symbol(strategy_config)
        target_sell = self._infer_position_from_target_day_sell(
            target_date, symbol, target_day_trades
        )
        prior_position = self._load_prior_open_position(target_date, symbol, exchange)

        if target_sell:
            prior_qty = float((prior_position or {}).get("quantity", 0.0) or 0.0)
            target_qty = float(target_sell["quantity"])
            if prior_qty <= 1e-12 or prior_qty + 1e-10 < target_qty:
                return target_sell

        return prior_position or target_sell

    def _infer_position_from_target_day_sell(
        self,
        target_date: date,
        symbol: str,
        target_day_trades: List[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        midnight = datetime.combine(target_date, datetime.min.time())
        for trade in target_day_trades:
            if str(trade.get("action", "")).upper() != "SELL":
                continue
            quantity = float(trade.get("volume", 0.0) or 0.0)
            price = float(trade.get("price", 0.0) or 0.0)
            profit = trade.get("profit")
            if quantity <= 0 or price <= 0 or profit is None:
                continue
            entry_price = price - (float(profit) / quantity)
            if entry_price <= 0:
                continue
            return {
                "symbol": symbol,
                "quantity": quantity,
                "entry_price": entry_price,
                "entry_time": midnight - timedelta(days=1),
                "source": "target_day_sell_profit",
            }
        return None

    def _load_prior_open_position(
        self,
        target_date: date,
        symbol: str,
        exchange: str,
    ) -> Optional[Dict[str, Any]]:
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT action, price, volume, exchange, symbol, timestamp
                FROM trades
                WHERE timestamp < ?
                AND upper(symbol) = ?
                AND exchange = ?
                AND COALESCE(paper, 1) = 1
                ORDER BY timestamp ASC
                """,
                (target_date.strftime("%Y-%m-%d 00:00:00"), symbol.upper(), exchange),
            )
            rows = cursor.fetchall()
            conn.close()
        except sqlite3.Error as exc:
            raise DatabaseError(f"Failed to reconstruct prior position: {exc}") from exc

        quantity = 0.0
        avg_price = 0.0
        first_entry_time: Optional[datetime] = None
        for row in rows:
            action = str(row["action"]).upper()
            trade_qty = float(row["volume"] or 0.0)
            price = float(row["price"] or 0.0)
            if trade_qty <= 0 or price <= 0:
                continue
            if action == "BUY":
                new_quantity = quantity + trade_qty
                avg_price = ((avg_price * quantity) + (price * trade_qty)) / new_quantity
                quantity = new_quantity
                if first_entry_time is None:
                    first_entry_time = self._parse_trade_timestamp(row["timestamp"])
                continue
            if action == "SELL" and quantity > 0:
                quantity = max(quantity - trade_qty, 0.0)
                if quantity <= 1e-12:
                    quantity = 0.0
                    avg_price = 0.0
                    first_entry_time = None

        if quantity <= 1e-12 or avg_price <= 0:
            return None
        return {
            "symbol": symbol,
            "quantity": quantity,
            "entry_price": avg_price,
            "entry_time": first_entry_time
            or datetime.combine(target_date, datetime.min.time()) - timedelta(days=1),
            "source": "prior_trades",
        }

    def _seed_adapter_position(self, adapter, carry_position: Dict[str, Any]) -> None:
        from trading.strategies.components.models import Position

        entry_time = carry_position.get("entry_time") or datetime.now()
        if not isinstance(entry_time, datetime):
            entry_time = self._parse_trade_timestamp(str(entry_time))
        entry_ts_ms = int(entry_time.timestamp() * 1000)
        quantity = float(carry_position.get("quantity", 0.0) or 0.0)
        entry_price = float(carry_position.get("entry_price", 0.0) or 0.0)
        if quantity <= 0 or entry_price <= 0:
            return

        symbol = str(carry_position.get("symbol") or getattr(adapter, "symbol", "BTC"))
        strategy_name = str(getattr(adapter, "strategy_name", "backtest"))
        market = str(getattr(adapter, "market", "spot") or "spot")
        adapter.current_position = Position(
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            strategy=strategy_name,
            market=market,
            timestamp=entry_ts_ms,
            side="long",
            entry_time=entry_ts_ms,
        )
        adapter.high_water_mark = entry_price
        notify_position_opened = getattr(adapter, "_notify_position_opened", None)
        if callable(notify_position_opened):
            notify_position_opened(entry_ts_ms)
        self._prime_exit_candles_held(getattr(adapter, "exit_strategy", None), adapter.current_position)

    def _prime_exit_candles_held(self, exit_strategy, position) -> None:
        if exit_strategy is None or position is None:
            return
        if hasattr(exit_strategy, "_get_position_key") and hasattr(exit_strategy, "_candles_held"):
            key = exit_strategy._get_position_key(position)
            exit_strategy._candles_held[key] = max(
                int(exit_strategy._candles_held.get(key, 0) or 0),
                10_000,
            )
        for child_name in ("_protective", "_regime"):
            child = getattr(exit_strategy, child_name, None)
            if child is not None:
                self._prime_exit_candles_held(child, position)

    def _apply_replay_action(
        self,
        action: str,
        price: float,
        timestamp: Optional[datetime],
        state: Dict[str, float],
        trades: Optional[List[BacktestTrade]],
        allow_scale_in: bool,
        quantity: float,
    ) -> None:
        current_qty = float(state.get("quantity", 0.0) or 0.0)
        trade_qty = max(float(quantity), 1e-9)

        if action == "buy" and (current_qty <= 0 or allow_scale_in):
            new_qty = current_qty + trade_qty
            state["avg_price"] = (
                ((state.get("avg_price", 0.0) * current_qty) + (price * trade_qty))
                / new_qty
            )
            state["quantity"] = new_qty
            if trades is not None and timestamp is not None:
                trades.append(
                    BacktestTrade(
                        timestamp=timestamp,
                        action="buy",
                        price=price,
                        quantity=trade_qty,
                        profit_loss=None,
                        profit_loss_pct=None,
                    )
                )
            return

        if action == "sell" and current_qty > 0:
            avg_price = float(state.get("avg_price", 0.0) or price)
            pnl = (price - avg_price) * current_qty
            pnl_pct = ((price / avg_price) - 1.0) * 100 if avg_price > 0 else 0.0
            if trades is not None and timestamp is not None:
                trades.append(
                    BacktestTrade(
                        timestamp=timestamp,
                        action="sell",
                        price=price,
                        quantity=current_qty,
                        profit_loss=pnl,
                        profit_loss_pct=pnl_pct,
                    )
                )
            state["quantity"] = 0.0
            state["avg_price"] = 0.0

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
        win_rate = (winning / len(profits) * 100.0) if profits else 0.0
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
            raise DatabaseError(f"Failed to save report: {e}") from e

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
