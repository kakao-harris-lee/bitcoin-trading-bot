#!/usr/bin/env python3
"""
backtester.py
백테스팅 엔진 - 가격 데이터 기반 거래 시뮬레이션

Supports:
- Legacy callback-based strategies (strategy_func)
- Component-based strategies (IEntryStrategy + IExitStrategy)
- StrategyFactory for creating strategies from configuration
"""

from __future__ import annotations

import pandas as pd
import numpy as np
from typing import Dict, List, Optional, Callable, Any, TYPE_CHECKING, Protocol, Union
from dataclasses import dataclass
from datetime import datetime

from core.backtest_result import BacktestResult
from core.metrics import calculate_benchmark, calculate_sharpe_ratio, calculate_max_drawdown
from core.mlflow_config import MLflowConfig
from core.backtest_logger import BacktestLogger, build_candle_state

if TYPE_CHECKING:
    from trading.strategies.components.interfaces import IEntryStrategy, IExitStrategy
    from trading.strategies.components.models import MarketData, Position, Signal

# Lazy-loaded model classes to avoid circular imports
# These are cached on first use for performance in hot loops
_MarketData = None
_MarketContext = None
_Position = None
_build_market_context = None


def _get_model_classes():
    """Lazily import model classes to avoid circular imports.

    Returns cached classes after first import for performance.
    """
    global _MarketData, _MarketContext, _Position, _build_market_context
    if _MarketData is None:
        from trading.strategies.components.models import (
            MarketData,
            MarketContext,
            Position,
            build_market_context,
        )
        _MarketData = MarketData
        _MarketContext = MarketContext
        _Position = Position
        _build_market_context = build_market_context
    return _MarketData, _MarketContext, _Position, _build_market_context


# Indicator library is imported lazily to avoid circular import issues
# (trading/__init__.py -> TradingEngine -> trading.strategies.components)
_add_all_indicators = None


def _get_add_all_indicators():
    """Lazily import add_all_indicators to avoid circular imports.

    Returns:
        The add_all_indicators function, or None if not available.
    """
    global _add_all_indicators
    if _add_all_indicators is None:
        try:
            from trading.indicators import add_all_indicators
            _add_all_indicators = add_all_indicators
        except ImportError:
            pass
    return _add_all_indicators

@dataclass
class Trade:
    """거래 기록"""
    entry_time: datetime
    entry_price: float
    quantity: float
    side: str  # 'buy' or 'sell'
    exit_time: Optional[datetime] = None
    exit_price: Optional[float] = None
    profit_loss: Optional[float] = None
    profit_loss_pct: Optional[float] = None
    reason: str = ""


class BacktestAdapter:
    """Adapter to bridge IEntryStrategy/IExitStrategy with backtester.

    Converts component-based strategies to the callback interface expected
    by Backtester.run(). Manages position state and indicator calculation.

    Usage:
        from trading.strategies.components import StrategyFactory

        factory = StrategyFactory()
        entry, exit_strat = factory.create_components("short_v1", config)

        adapter = BacktestAdapter(
            entry_strategy=entry,
            exit_strategy=exit_strat,
            symbol="BTC",
        )

        results = backtester.run(df, adapter)
    """

    def __init__(
        self,
        entry_strategy: "IEntryStrategy",
        exit_strategy: "IExitStrategy",
        symbol: str = "BTC",
        market: str = "futures",
        position_size: float = 0.01,
    ):
        """Initialize the adapter.

        Args:
            entry_strategy: Entry component implementing IEntryStrategy.
            exit_strategy: Exit component implementing IExitStrategy.
            symbol: Trading symbol for MarketData.
            market: Market type (must be "futures").
            position_size: Default position size as fraction of capital.
        """
        self.entry_strategy = entry_strategy
        self.exit_strategy = exit_strategy
        self.symbol = symbol
        self.market = market
        self.position_size = position_size

        # Position state for exit evaluation
        self._position: Optional[Dict[str, Any]] = None
        self._indicators_df: Optional[pd.DataFrame] = None
        self._min_data_points = 200  # For indicator calculation

    def __call__(
        self,
        df: pd.DataFrame,
        i: int,
        params: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Callable interface for backtester strategy_func.

        Args:
            df: Price DataFrame with OHLCV data.
            i: Current row index.
            params: Strategy parameters (unused, for compatibility).

        Returns:
            Action dict: {'action': 'buy'/'sell'/'hold', 'fraction': float, 'reason': str}
        """
        # Ensure indicators are calculated
        if self._indicators_df is None or len(self._indicators_df) != len(df):
            self._calculate_indicators(df)

        # Check minimum data
        if i < self._min_data_points:
            return {'action': 'hold'}

        # Build MarketData from current row
        market_data = self._build_market_data(i)
        if market_data is None:
            return {'action': 'hold'}

        row = df.iloc[i]

        # If we have a position, check exit first
        if self._position is not None:
            position = self._build_position()
            signal = self.exit_strategy.check_exit(position, market_data)

            if signal:
                self._position = None
                self.exit_strategy.on_position_closed(self.symbol)
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': signal.reason,
                }

        # No position, check entry
        if self._position is None:
            # Build MarketContext for context-aware filtering
            context = self._build_market_context(i)
            signal = self.entry_strategy.check_entry(market_data, context)

            if signal:
                # Create position state for exit evaluation
                self._position = {
                    'symbol': self.symbol,
                    'entry_price': float(row['close']),
                    'quantity': signal.quantity,
                    'strategy': 'backtest',
                    'market': self.market,
                    'timestamp': row.get('timestamp', i),
                }
                self.exit_strategy.on_position_opened(self._build_position())
                return {
                    'action': 'buy',
                    'fraction': self.position_size,
                    'reason': signal.reason,
                }

        return {'action': 'hold'}

    def reset(self) -> None:
        """Reset adapter state for new backtest run."""
        self._position = None
        self._indicators_df = None

    def _calculate_indicators(self, df: pd.DataFrame) -> None:
        """Calculate all indicators for the DataFrame.

        Args:
            df: Price DataFrame with OHLCV data.
        """
        add_all_indicators = _get_add_all_indicators()
        if add_all_indicators is None:
            raise RuntimeError(
                "Indicator library not available. "
                "Install trading.indicators module."
            )

        # Make a copy to avoid modifying original
        self._indicators_df = add_all_indicators(df.copy())

    def _build_market_data(self, i: int) -> Optional[Any]:
        """Build MarketData from current indicators.

        Args:
            i: Current row index.

        Returns:
            MarketData instance or None if data unavailable.
        """
        if self._indicators_df is None:
            return None

        # Use cached import for performance in hot loop
        MarketData, _, _, _ = _get_model_classes()

        row = self._indicators_df.iloc[i]

        # Check if indicators are available (not NaN)
        if pd.isna(row.get('mfi')) or pd.isna(row.get('adx')):
            return None

        open_val = row.get('open', row['close'])
        if pd.isna(open_val):
            open_val = row['close']

        return MarketData(
            symbol=self.symbol,
            open=float(open_val),
            close=float(row['close']),
            mfi=float(row.get('mfi', 50)),
            adx=float(row.get('adx', 20)),
            rsi=float(row.get('rsi', 50)),
            timestamp=row.get('timestamp', i),
            atr=float(row.get('atr', 0)),
            macd=float(row.get('macd', 0)),
            macd_signal=float(row.get('macd_signal', 0)),
            stoch_k=float(row.get('stoch_k', 50)),
            volume=float(row.get('volume', 0)),
            high=float(row.get('high', row['close'])),
            low=float(row.get('low', row['close'])),
            prev_high_20=float(row.get('prev_high_20', 0)),
            prev_low_20=float(row.get('prev_low_20', 0)),
            avg_volume_20=float(row.get('avg_volume_20', 0)),
            ema_200=float(row.get('ema_200', 0)),
            market_stress=float(row.get('market_stress', 0)),
            high_30d=float(row.get('high_30d', 0)),
            breakout_signal=int(row.get('breakout_signal', 0)) if pd.notna(row.get('breakout_signal')) else 0,
            target_price=float(row.get('target_price', 0.0)) if pd.notna(row.get('target_price')) else 0.0,
        )

    def _build_market_context(self, i: int) -> Any:
        """Build MarketContext from current indicators.

        Args:
            i: Current row index.

        Returns:
            MarketContext instance for context-aware filtering.
        """
        # Use cached imports for performance in hot loop
        _, MarketContext, _, build_market_context = _get_model_classes()

        if self._indicators_df is None:
            # Return a neutral context if no data
            return MarketContext(
                trend="NEUTRAL",
                regime="SIDEWAYS_FLAT",  # Default neutral regime
                volatility_score=0.0,
                is_extreme_volatility=False,
                adx=20.0,
            )

        row = self._indicators_df.iloc[i]

        mfi = float(row.get('mfi', 50))
        adx = float(row.get('adx', 20))
        atr = float(row.get('atr', 0))
        close = float(row['close'])
        volume = float(row.get('volume', 0))
        avg_volume = float(row.get('avg_volume_20', 0))
        # Use 30-day high for drawdown detection (fall back to 20-period if not available)
        high_30d = float(row.get('high_30d', 0))
        recent_high = high_30d if high_30d > 0 else float(row.get('prev_high_20', 0))

        return build_market_context(
            mfi=mfi,
            adx=adx,
            atr=atr,
            close=close,
            volume=volume,
            avg_volume=avg_volume,
            recent_high=recent_high,  # For drawdown-based BEAR detection (30-day high)
        )

    def _build_position(self) -> Any:
        """Build Position from current state.

        Returns:
            Position instance.
        """
        # Use cached import for performance
        _, _, Position, _ = _get_model_classes()

        if self._position is None:
            raise ValueError("No position to build")

        return Position(
            symbol=self._position['symbol'],
            entry_price=self._position['entry_price'],
            quantity=self._position['quantity'],
            strategy=self._position['strategy'],
            market=self._position['market'],
            timestamp=self._position['timestamp'],
        )


class Backtester:
    """백테스팅 엔진"""

    def __init__(
        self,
        initial_capital: float = 10_000,
        fee_rate: float = None,  # Auto-detect from market if None
        slippage: float = 0.0004,   # 0.04%
        min_order_amount: float = 10,
        market: str = "futures",
    ):
        """
        Args:
            initial_capital: Initial capital in USD (default $10,000).
            fee_rate: Fee rate (None = auto-detect: spot=0.1%, futures=0.05%).
            slippage: Slippage rate (default 0.04%).
            min_order_amount: Minimum order amount in USD (default $10).
            market: Market type ("spot" or "futures").
        """
        self.initial_capital = initial_capital
        self.market = market

        # Auto-detect fee rate based on market
        if fee_rate is None:
            self.fee_rate = 0.001 if market == "spot" else 0.0005
        else:
            self.fee_rate = fee_rate

        self.slippage = slippage
        self.min_order_amount = min_order_amount

        # Spot has no leverage
        self.leverage = 1 if market == "spot" else 3

        # 상태 변수
        self.cash = initial_capital
        self.position = 0.0  # 보유 수량
        self.position_value = 0.0
        self.trades: List[Trade] = []
        self.equity_curve = []

    def reset(self):
        """상태 초기화"""
        self.cash = self.initial_capital
        self.position = 0.0
        self.position_value = 0.0
        self.trades = []
        self.equity_curve = []

    def run(
        self,
        df: pd.DataFrame,
        strategy_func: Callable,
        strategy_params: Dict = None,
        csv_log: bool = False,
        csv_log_dir: str = "backtest_logs",
        strategy_name: str = "unknown",
        symbol: str = "BTC",
    ) -> Dict:
        """
        백테스팅 실행

        Args:
            df: 가격 데이터 (timestamp, open, high, low, close, volume)
            strategy_func: 전략 함수 (df, i, params) -> {'action': 'buy'/'sell'/'hold', 'fraction': 0.5}
            strategy_params: 전략 파라미터
            csv_log: Whether to generate CSV log file for analysis.
            csv_log_dir: Directory to save CSV logs.
            strategy_name: Strategy name for CSV filename.
            symbol: Trading symbol for CSV filename.

        Returns:
            백테스팅 결과 딕셔너리
        """
        self.reset()

        strategy_params = strategy_params or {}
        logger = BacktestLogger(strategy_name, symbol, csv_log_dir) if csv_log else None

        for i in range(len(df)):
            row = df.iloc[i]
            timestamp = row['timestamp']
            price = row['close']

            self._update_strategy_equity(strategy_func, price)
            signal = strategy_func(df, i, strategy_params)
            action = signal.get('action', 'hold')
            fraction = signal.get('fraction', 1.0)
            self._execute_action(action, timestamp, price, fraction)
            total_equity = self._record_equity_snapshot(timestamp, price)
            if logger is not None:
                self._log_backtest_candle(
                    logger=logger,
                    row=row,
                    signal=signal,
                    action=action,
                    strategy_func=strategy_func,
                    total_equity=total_equity,
                    price=price,
                )

        self._liquidate_remaining_position(df)

        results = self._generate_results()

        # Flush CSV log and add path to results
        if logger is not None:
            csv_path = logger.flush()
            results['csv_log_path'] = csv_path

        return results

    def _update_strategy_equity(self, strategy_func: Callable, price: float) -> None:
        """Update strategy equity callback for drawdown-aware strategies."""
        if not hasattr(strategy_func, "update_equity"):
            return
        current_equity = self.cash + (self.position * price if self.position != 0 else 0.0)
        strategy_func.update_equity(current_equity)

    def _execute_action(self, action: str, timestamp: Any, price: float, fraction: float) -> None:
        """Execute buy/sell/short action for the current candle."""
        if action == 'buy':
            self._execute_buy(timestamp, price, fraction)
            return
        if action == 'sell':
            self._execute_sell(timestamp, price, fraction)
            return
        if action == 'open_short':
            self._execute_open_short(timestamp, price, fraction)
            return
        if action == 'close_short':
            self._execute_close_short(timestamp, price, fraction)

    def _record_equity_snapshot(self, timestamp: Any, price: float) -> float:
        """Update position value and append equity curve snapshot."""
        if self.position > 0:
            # Long: position value is qty * price
            self.position_value = self.position * price
        elif self.position < 0:
            # Short: unrealized PnL = (entry_price - current_price) * abs(qty)
            # Cash already includes collateral; position_value is the unrealized PnL
            self.position_value = self.position * price  # negative qty * price = negative
        else:
            self.position_value = 0.0
        total_equity = self.cash + self.position_value
        self.equity_curve.append({
            'timestamp': timestamp,
            'cash': self.cash,
            'position_value': self.position_value,
            'total_equity': total_equity,
        })
        return total_equity

    def _log_backtest_candle(
        self,
        logger: BacktestLogger,
        row: pd.Series,
        signal: Dict[str, Any],
        action: str,
        strategy_func: Callable,
        total_equity: float,
        price: float,
    ) -> None:
        """Log per-candle backtest state to CSV logger."""
        peak_equity, drawdown, drawdown_pct = self._compute_equity_drawdown(total_equity)
        position_type, entry_price = self._current_position_snapshot()
        unrealized_pnl = self._compute_unrealized_pnl(price, entry_price)
        cumulative_pnl = self._compute_cumulative_pnl()
        regime = signal.get('regime', '')
        trend = self._extract_strategy_trend(strategy_func)

        state = build_candle_state(
            row=row.to_dict(),
            position=position_type,
            position_qty=self.position,
            entry_price=entry_price,
            portfolio_value=total_equity,
            cash=self.cash,
            unrealized_pnl=unrealized_pnl,
            realized_pnl=signal.get('realized_pnl', 0.0),
            cumulative_pnl=cumulative_pnl,
            drawdown=drawdown,
            drawdown_pct=drawdown_pct,
            high_water_mark=peak_equity,
            signal=action,
            signal_reason=signal.get('reason', ''),
            regime=regime,
            trend=trend,
            rf_confidence=signal.get('rf_confidence', ''),
        )
        logger.log_candle(state)

    def _compute_equity_drawdown(self, total_equity: float) -> tuple[float, float, float]:
        peak_equity = max(eq['total_equity'] for eq in self.equity_curve) if self.equity_curve else total_equity
        drawdown = peak_equity - total_equity
        drawdown_pct = (drawdown / peak_equity * 100) if peak_equity > 0 else 0.0
        return peak_equity, drawdown, drawdown_pct

    def _current_position_snapshot(self) -> tuple[str, float]:
        if self.position == 0:
            return "none", 0.0
        if not self.trades:
            return ("long" if self.position > 0 else "short"), 0.0
        last_trade = self.trades[-1]
        if last_trade.exit_time is None:
            side = "long" if self.position > 0 else "short"
            return side, last_trade.entry_price
        return "none", 0.0

    def _compute_unrealized_pnl(self, price: float, entry_price: float) -> float:
        if self.position == 0 or entry_price <= 0:
            return 0.0
        if self.position > 0:
            return (price - entry_price) * self.position
        # Short: profit when price drops
        return (entry_price - price) * abs(self.position)

    def _compute_cumulative_pnl(self) -> float:
        return sum(t.profit_loss for t in self.trades if t.profit_loss is not None)

    def _extract_strategy_trend(self, strategy_func: Callable) -> str:
        if hasattr(strategy_func, 'current_position') and hasattr(strategy_func, 'config'):
            return getattr(strategy_func, '_current_trend', '')
        return ''

    def _liquidate_remaining_position(self, df: pd.DataFrame) -> None:
        """Close remaining position at final candle close."""
        if self.position <= 0:
            return
        last_row = df.iloc[-1]
        self._execute_sell(last_row['timestamp'], last_row['close'], 1.0)

    def run_strategy(
        self,
        df: pd.DataFrame,
        strategy_name: str,
        config: Optional[Dict[str, Any]] = None,
        symbol: str = "BTC",
        return_backtest_result: bool = False,
        mlflow_config: Optional[MLflowConfig] = None,
        csv_log: bool = False,
        csv_log_dir: str = "backtest_logs",
    ) -> Union[Dict, BacktestResult]:
        """Run backtest using StrategyFactory to create strategy.

        Convenience method that uses StrategyFactory to create entry/exit
        components from configuration, wraps them in BacktestAdapter, and
        runs the backtest.

        Args:
            df: Price DataFrame (timestamp, open, high, low, close, volume).
            strategy_name: Strategy name (e.g., "short_v1", "sideways_v2").
            config: Configuration parameters for the strategy.
            symbol: Trading symbol for MarketData.
            return_backtest_result: If True, return BacktestResult dataclass
                instead of dict. Default False for backward compatibility.
            mlflow_config: MLflow configuration for auto-logging. If provided,
                results are automatically logged to MLflow. Default None (no logging).
            csv_log: Whether to generate CSV log file for analysis.
            csv_log_dir: Directory to save CSV logs (default: "backtest_logs").

        Returns:
            Backtest results dictionary or BacktestResult if return_backtest_result=True.

        Raises:
            ValueError: If strategy name is not registered in factory.
            RuntimeError: If indicator library is not available.

        Example:
            # Legacy dict return
            results = backtester.run_strategy(
                df,
                strategy_name="short_v1",
                config={"stop_loss_pct": 2.0, "take_profit_pct": 4.0},
            )

            # New BacktestResult return with benchmark
            result = backtester.run_strategy(
                df,
                strategy_name="short_v1",
                config={"stop_loss_pct": 2.0},
                return_backtest_result=True,
            )
            print(f"Sharpe: {result.sharpe_ratio}, Benchmark: {result.benchmark_return_pct}%")

            # With MLflow auto-logging
            from core.mlflow_config import MLflowConfig
            result = backtester.run_strategy(
                df,
                strategy_name="short_v1",
                config={"stop_loss_pct": 2.0},
                return_backtest_result=True,
                mlflow_config=MLflowConfig(),
            )
        """
        from trading.strategies.components import StrategyFactory

        factory = StrategyFactory()
        entry, exit_strat = factory.create_components(
            strategy_name,
            config or {},
            persistent=False,  # No Redis in backtest
        )

        market = factory.get_market(strategy_name)
        position_size = (config or {}).get("position_size", 0.01)

        adapter = BacktestAdapter(
            entry_strategy=entry,
            exit_strategy=exit_strat,
            symbol=symbol,
            market=market,
            position_size=position_size,
        )

        results = self.run(
            df,
            adapter,
            csv_log=csv_log,
            csv_log_dir=csv_log_dir,
            strategy_name=strategy_name,
            symbol=symbol,
        )

        # Calculate benchmark
        benchmark_curve, benchmark_return_pct = calculate_benchmark(
            df, self.initial_capital, price_column="close"
        )

        # Add benchmark to results
        results["benchmark_curve"] = benchmark_curve
        results["benchmark_return_pct"] = benchmark_return_pct

        # Create BacktestResult for MLflow logging
        backtest_result = BacktestResult.from_dict(
            results,
            strategy_name=strategy_name,
            symbol=symbol,
            params=config or {},
        )

        # Auto-log to MLflow if config provided
        if mlflow_config is not None:
            from core.mlflow_tracker import MLflowTracker
            from core.backtest_visualizer import BacktestVisualizer

            tracker = MLflowTracker(mlflow_config)
            if tracker.enabled:
                # Generate chart for artifact
                visualizer = BacktestVisualizer()
                chart_path = visualizer.create_chart(backtest_result)

                # Log to MLflow
                tracker.log_run(backtest_result, chart_path=chart_path)

        if return_backtest_result:
            return backtest_result

        return results

    def run_components(
        self,
        df: pd.DataFrame,
        entry_strategy: "IEntryStrategy",
        exit_strategy: "IExitStrategy",
        symbol: str = "BTC",
        market: str = "futures",
        position_size: float = 0.01,
    ) -> Dict:
        """Run backtest with pre-created entry/exit components.

        Lower-level method for running with already-instantiated strategy
        components without using StrategyFactory.

        Args:
            df: Price DataFrame (timestamp, open, high, low, close, volume).
            entry_strategy: Entry component implementing IEntryStrategy.
            exit_strategy: Exit component implementing IExitStrategy.
            symbol: Trading symbol for MarketData.
            market: Market type ("spot" or "futures").
            position_size: Position size as fraction of capital.

        Returns:
            Backtest results dictionary.

        Example:
            from trading.strategies.components import (
                ShortEntryStrategy,
                ShortExitStrategy,
            )

            entry = ShortEntryStrategy()
            exit_strat = ShortExitStrategy()

            results = backtester.run_components(
                df, entry, exit_strat, symbol="ETH"
            )
        """
        adapter = BacktestAdapter(
            entry_strategy=entry_strategy,
            exit_strategy=exit_strategy,
            symbol=symbol,
            market=market,
            position_size=position_size,
        )

        return self.run(df, adapter)

    def _execute_buy(self, timestamp: datetime, price: float, fraction: float):
        """매수 실행"""
        # 투자 가능 금액
        available_cash = self.cash * fraction

        if available_cash < self.min_order_amount:
            return  # 최소 주문 금액 미달

        # 슬리피지 적용 (매수 시 불리하게)
        execution_price = price * (1 + self.slippage)

        # 수수료 포함 구매 가능 수량
        quantity = available_cash / (execution_price * (1 + self.fee_rate))

        # 실제 사용 금액
        cost = quantity * execution_price * (1 + self.fee_rate)

        if cost > self.cash:
            return  # 잔액 부족

        # 매수 실행
        self.cash -= cost
        self.position += quantity

        # 거래 기록
        trade = Trade(
            entry_time=timestamp,
            entry_price=execution_price,
            quantity=quantity,
            side='buy',
            reason=f'Buy {fraction*100:.1f}% of cash'
        )
        self.trades.append(trade)

    def _execute_sell(self, timestamp: datetime, price: float, fraction: float):
        """매도 실행"""
        if self.position <= 0:
            return  # 보유 없음

        # 매도 수량
        quantity = self.position * fraction

        # 슬리피지 적용 (매도 시 불리하게)
        execution_price = price * (1 - self.slippage)

        # 수수료 차감 후 수령 금액
        proceeds = quantity * execution_price * (1 - self.fee_rate)

        if proceeds < self.min_order_amount:
            return  # 최소 주문 금액 미달

        # 매도 실행
        self.cash += proceeds
        self.position -= quantity
        if abs(self.position) < 1e-12:
            self.position = 0.0
            # Keep position_value in sync when closing at end-of-run liquidation.
            self.position_value = 0.0

        # 매칭되는 매수 거래 찾기 (FIFO)
        for trade in self.trades:
            if trade.side == 'buy' and trade.exit_time is None:
                # 손익 계산
                trade.exit_time = timestamp
                trade.exit_price = execution_price
                trade.profit_loss = (execution_price - trade.entry_price) * trade.quantity
                trade.profit_loss_pct = ((execution_price - trade.entry_price) / trade.entry_price) * 100
                trade.reason += f' -> Sell {fraction*100:.1f}%'
                break

    def _execute_open_short(self, timestamp: datetime, price: float, fraction: float):
        """Open a short position (futures margin model).

        Margin model: selling borrowed asset.
        cash += proceeds from short sale (qty * price)
        position = -qty (we owe shares)
        equity = cash + position * price (stays ~constant at open, moves with price)
        When price drops: position * price becomes less negative → equity rises (profit).
        """
        if self.position != 0:
            return  # Already in a position

        available_cash = self.cash * fraction

        if available_cash < self.min_order_amount:
            return

        # Slippage: unfavorable for shorts (we sell lower)
        execution_price = price * (1 - self.slippage)

        # Quantity we can short with available margin (leverage applied)
        effective_cash = available_cash * self.leverage
        quantity = effective_cash / (execution_price * (1 + self.fee_rate))

        # Receive proceeds from short sale, minus fee
        proceeds = quantity * execution_price * (1 - self.fee_rate)
        self.cash += proceeds

        # Track negative position
        self.position = -quantity

        trade = Trade(
            entry_time=timestamp,
            entry_price=execution_price,
            quantity=quantity,
            side='short',
            reason=f'Short {fraction*100:.1f}% (leverage={self.leverage}x)',
        )
        self.trades.append(trade)

    def _execute_close_short(self, timestamp: datetime, price: float, fraction: float):
        """Close (cover) a short position."""
        if self.position >= 0:
            return  # No short position

        quantity = abs(self.position) * fraction

        # Slippage: unfavorable for covering (price rises)
        execution_price = price * (1 + self.slippage)

        # Cost to buy back + fees
        cover_cost = quantity * execution_price * (1 + self.fee_rate)

        if cover_cost < self.min_order_amount:
            return

        self.cash -= cover_cost
        self.position += quantity  # Moves toward 0
        if abs(self.position) < 1e-12:
            self.position = 0.0
            self.position_value = 0.0

        # Match the open short trade (FIFO)
        for trade in self.trades:
            if trade.side == 'short' and trade.exit_time is None:
                trade.exit_time = timestamp
                trade.exit_price = execution_price
                # Short profit: (entry - exit) * qty
                trade.profit_loss = (trade.entry_price - execution_price) * trade.quantity
                trade.profit_loss_pct = ((trade.entry_price - execution_price) / trade.entry_price) * 100
                trade.reason += f' -> Cover {fraction*100:.1f}%'
                break

    def _generate_results(self) -> Dict:
        """결과 생성

        Returns dictionary with all metrics including sharpe_ratio and max_drawdown_pct.
        """
        # Guard against stale position_value after final forced liquidation.
        if self.position == 0:
            self.position_value = 0.0
        final_equity = self.cash + self.position_value
        total_return = ((final_equity - self.initial_capital) / self.initial_capital) * 100
        equity_df = pd.DataFrame(self.equity_curve)
        sharpe_ratio = calculate_sharpe_ratio(equity_df) if not equity_df.empty else 0.0
        max_drawdown_pct = calculate_max_drawdown(equity_df) if not equity_df.empty else 0.0
        closed_trades = [t for t in self.trades if t.exit_time is not None]
        if not closed_trades:
            return self._build_results_without_trades(
                final_equity, total_return, sharpe_ratio, max_drawdown_pct, equity_df
            )
        return self._build_results_with_trades(
            final_equity, total_return, sharpe_ratio, max_drawdown_pct, equity_df, closed_trades
        )

    def _build_results_without_trades(
        self,
        final_equity: float,
        total_return: float,
        sharpe_ratio: float,
        max_drawdown_pct: float,
        equity_df: pd.DataFrame,
    ) -> Dict:
        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_equity,
            'total_return': total_return,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown_pct': max_drawdown_pct,
            'profit_factor': 0.0,
            'equity_curve': equity_df,
        }

    def _build_results_with_trades(
        self,
        final_equity: float,
        total_return: float,
        sharpe_ratio: float,
        max_drawdown_pct: float,
        equity_df: pd.DataFrame,
        closed_trades: List[Trade],
    ) -> Dict:
        stats = self._summarize_closed_trades(closed_trades)
        return {
            'initial_capital': self.initial_capital,
            'final_capital': final_equity,
            'total_return': total_return,
            'total_trades': len(closed_trades),
            'winning_trades': stats['winning_trades'],
            'losing_trades': stats['losing_trades'],
            'win_rate': stats['win_rate'],
            'avg_profit': stats['avg_profit'],
            'avg_loss': stats['avg_loss'],
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown_pct': max_drawdown_pct,
            'profit_factor': stats['profit_factor'],
            'trades': closed_trades,
            'equity_curve': equity_df,
        }

    def _summarize_closed_trades(self, closed_trades: List[Trade]) -> Dict[str, float]:
        winning_profits, losing_profits = self._split_trade_profits(closed_trades)
        avg_profit = self._mean_or_zero(winning_profits)
        avg_loss = abs(self._mean_or_zero(losing_profits))
        gross_profit = sum(winning_profits)
        gross_loss = abs(sum(losing_profits))
        win_rate = len(winning_profits) / len(closed_trades) if closed_trades else 0.0
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0
        return {
            'winning_trades': len(winning_profits),
            'losing_trades': len(losing_profits),
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,
        }

    def _split_trade_profits(self, closed_trades: List[Trade]) -> tuple[List[float], List[float]]:
        winning: List[float] = []
        losing: List[float] = []
        for trade in closed_trades:
            profit = trade.profit_loss
            if profit > 0:
                winning.append(profit)
            else:
                losing.append(profit)
        return winning, losing

    def _mean_or_zero(self, values: List[float]) -> float:
        if not values:
            return 0.0
        return float(np.mean(values))


# Usage examples
if __name__ == "__main__":
    from data_loader import DataLoader

    def print_results(results: Dict, title: str = "백테스팅 결과") -> None:
        """Print backtest results."""
        print(f"\n{'='*50}")
        print(f"✅ {title}:")
        print(f"   초기 자본: {results['initial_capital']:,.0f}원")
        print(f"   최종 자본: {results['final_capital']:,.0f}원")
        print(f"   총 수익률: {results['total_return']:.2f}%")
        print(f"   총 거래: {results['total_trades']}회")
        if results['total_trades'] > 0:
            print(f"   승률: {results['win_rate']:.1%}")
            print(f"   Profit Factor: {results['profit_factor']:.2f}")
        print(f"{'='*50}\n")

    # Example 1: Legacy callback-based strategy (RSI)
    def simple_rsi_strategy(df, i, params):
        """RSI 30 이하 매수, 70 이상 매도"""
        if i < 14:
            return {'action': 'hold'}

        window = 14
        delta = df['close'].diff()
        gain = delta.where(delta > 0, 0).rolling(window=window).mean()
        loss = -delta.where(delta < 0, 0).rolling(window=window).mean()
        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        current_rsi = rsi.iloc[i]

        if current_rsi < 30:
            return {'action': 'buy', 'fraction': 0.5}
        elif current_rsi > 70:
            return {'action': 'sell', 'fraction': 1.0}
        else:
            return {'action': 'hold'}

    # Load data
    with DataLoader() as loader:
        df = loader.load_timeframe("minute5", start_date="2024-01-01", end_date="2024-01-31")

    backtester = Backtester()

    # Run legacy strategy
    results1 = backtester.run(df, simple_rsi_strategy)
    print_results(results1, "Legacy RSI Strategy")

    # Example 2: Component-based strategy using StrategyFactory
    # This uses the new IEntryStrategy/IExitStrategy architecture
    try:
        results2 = backtester.run_strategy(
            df,
            strategy_name="short_v1",
            config={
                "stop_loss_pct": 2.0,
                "take_profit_pct": 4.0,
                "trailing_enabled": True,
                "position_size": 0.5,  # 50% of capital
            },
            symbol="BTC",
        )
        print_results(results2, "Short V1 Strategy (via StrategyFactory)")
    except Exception as e:
        print(f"Note: Component-based strategy requires trading.strategies.components: {e}")
