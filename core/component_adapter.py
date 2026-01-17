"""Adapter to bridge Component-based Strategies with the Functional Backtester.

This allows the historical backtester to run the exact same logic as live trading.
"""
from typing import Dict, Any, Callable, Optional
import pandas as pd
from trading.strategies.components import StrategyFactory
from trading.strategies.components.models import MarketData, Position, Signal
from trading.strategies.components.strategy_factory import StrategyFactory

class ComponentStrategyAdapter:
    """Adapts a StrategyFactory strategy into a Backtester-compatible function."""

    def __init__(self, factory: StrategyFactory, strategy_name: str, config: Dict[str, Any]):
        """
        Args:
            factory: Initialized StrategyFactory
            strategy_name: Name of the strategy to run (e.g., "v35_long")
            config: Configuration dictionary for the strategy
        """
        self.strategy_name = strategy_name
        self.entry_strategy, self.exit_strategy = factory.create_components(
            strategy_name=strategy_name,
            config=config,
            persistent=False  # Backtesting is always non-persistent (stateless run)
        )
        self.current_position: Optional[Position] = None
        self.symbol = "BTC" # Default, will be updated if possible

    def __call__(self, df: pd.DataFrame, i: int, params: Dict = None) -> Dict[str, Any]:
        """Callable interface for Backtester.run(strategy_func)."""

        row = df.iloc[i]

        # 1. efficient MarketData construction
        # Note: df must have these columns pre-calculated!
        market_data = MarketData(
            symbol=self.symbol,
            close=row['close'],
            timestamp=row['timestamp'],
            mfi=row.get('mfi', 50.0),      # Default to neural
            adx=row.get('adx', 0.0),       # Default to no trend
            rsi=row.get('rsi', 50.0),      # Default to neutral
            high_water_mark=self.current_position.high_water_mark if self.current_position else None
        )

        # 2. Check Exits first (if we have a position)
        if self.current_position:
            # Update current price in position for calculation context
            # (In live trading, position updates happen via Redis, here we simulate)

            # Check exit
            signal = self.exit_strategy.check_exit(self.current_position, market_data)

            if signal and signal.signal_type != "NEUTRAL":
                # Close position
                self.current_position = None
                return {
                    'action': 'sell',
                    'fraction': 1.0,  # Simplify to full exit for now
                    'reason': signal.reason
                }

            # If no exit, update high water mark if needed (for trailing stops)
            # This mimics the Redis persistence in live trading
            if row['close'] > self.current_position.high_water_mark:
                self.current_position.high_water_mark = row['close']

            return {'action': 'hold'}

        # 3. Check Entries (if no position)
        else:
            signal = self.entry_strategy.check_entry(market_data)

            if signal and signal.signal_type == "BUY":
                # Create simulated position
                self.current_position = Position(
                    symbol=self.symbol,
                    quantity=1.0, # Placeholder
                    entry_price=row['close'],
                    side="LONG",
                    strategy=self.strategy_name,
                    timestamp=int(row['timestamp'].timestamp()),
                    current_price=row['close'],
                    high_water_mark=row['close'],
                    stop_loss=None # Strategy manages this internally usually
                )
                return {
                    'action': 'buy',
                    'fraction': 1.0,
                    'reason': signal.reason
                }

        return {'action': 'hold'}
