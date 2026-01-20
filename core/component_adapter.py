"""Adapter to bridge Component-based Strategies with the Functional Backtester.

This allows the historical backtester to run the exact same logic as live trading.
"""
from typing import Dict, Any, Callable, Optional
import pandas as pd
from trading.strategies.components import StrategyFactory
from trading.strategies.components.models import MarketData, Position, Signal, MarketContext
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.strategies.volatility_tracker import VolatilityTracker

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
        self.market = factory.get_market(strategy_name)
        self.current_position: Optional[Position] = None
        self.high_water_mark: Optional[float] = None
        self.symbol = "BTC" # Default, will be updated if possible
        self.vol_tracker = VolatilityTracker(window=20)

    def _determine_regime(self, mfi: float, adx: float) -> str:
        """Determine market regime using strategy-specific logic if available."""
        # Try to use the component's internal classification logic
        if hasattr(self.entry_strategy, '_classify_regime'):
            return self.entry_strategy._classify_regime(mfi, adx)

        # Fallback: Simple classification (should match default expectation)
        return "UNKNOWN"

    def __call__(self, df: pd.DataFrame, i: int, params: Dict = None) -> Dict[str, Any]:
        """Callable interface for Backtester.run(strategy_func)."""

        row = df.iloc[i]

        # Update Volatility
        self.vol_tracker.add_price(row['close'])
        vol_score = self.vol_tracker.get_volatility()
        vol_score = vol_score if vol_score is not None else 0.0

        is_extreme = vol_score > self.vol_tracker.HIGH_VOL_THRESHOLD

        # Determine Regime
        mfi = row.get('mfi', 50.0)
        adx = row.get('adx', 0.0)
        regime = self._determine_regime(mfi, adx)

        # Build Context
        context = MarketContext(
            regime=regime,
            trend="neutral", # Placeholder
            volatility_score=vol_score,
            is_extreme_volatility=is_extreme
        )

        # Extract indicators
        indicators = {}
        for k, v in row.items():
            if isinstance(k, str) and k.startswith(('ema', 'adx', 'rsi', 'plus', 'minus', 'bb')):
                indicators[k] = v

        # Explicit mapping for ShortV1 alias 'ema_fast'/'ema_slow'
        if self.config:
            ema_fast_len = self.config.get('ema_fast')
            ema_slow_len = self.config.get('ema_slow')
            if ema_fast_len:
                col = f"ema_{ema_fast_len}"
                if col in row: indicators['ema_fast'] = row[col]
            if ema_slow_len:
                col = f"ema_{ema_slow_len}"
                if col in row: indicators['ema_slow'] = row[col]

            # Map DI/ADX slope if needed and present
            if 'plus_di' in row: indicators['plus_di'] = row['plus_di']
            if 'minus_di' in row: indicators['minus_di'] = row['minus_di']
            if 'adx_slope' in row: indicators['adx_slope'] = row['adx_slope']

        # 1. efficient MarketData construction
        market_data = MarketData(
            symbol=self.symbol,
            close=row['close'],
            timestamp=row['timestamp'],
            mfi=mfi,
            adx=adx,
            rsi=row.get('rsi', 50.0),
            indicators=indicators,
            high_water_mark=self.high_water_mark
        )

        # 2. Check Exits first (if we have a position)
        if self.current_position:
            # Update high water mark
            is_long = getattr(self.current_position, 'side', 'long') == 'long'

            if is_long:
                if self.high_water_mark is None or row['close'] > self.high_water_mark:
                    self.high_water_mark = row['close']
            else:
                if self.high_water_mark is None or row['close'] < self.high_water_mark:
                    self.high_water_mark = row['close']

            market_data.high_water_mark = self.high_water_mark

            # Check exit
            signal = self.exit_strategy.check_exit(self.current_position, market_data)

            if signal:
                self.current_position = None
                self.high_water_mark = None
                action = 'close_short' if not is_long else 'sell'
                return {
                    'action': action,
                    'fraction': 1.0,
                    'reason': signal.reason
                }

            return {'action': 'hold'}

        # 3. Check Entries (if no position)
        else:
            signal = self.entry_strategy.check_entry(market_data, context)

            if signal:
                is_short = signal.side == 'sell'
                pos_side = 'short' if is_short else 'long'

                # Create simulated position
                # Assuming timestamp is a pandas Timestamp or similar, convert to ms
                ts_ms = int(row['timestamp'].timestamp() * 1000) if hasattr(row['timestamp'], 'timestamp') else 0

                self.current_position = Position(
                    symbol=self.symbol,
                    quantity=1.0,
                    entry_price=row['close'],
                    side=pos_side,
                    strategy=self.strategy_name,
                    market="futures",  # Default for backtesting context unless specified
                    timestamp=ts_ms
                )
                self.high_water_mark = row['close']

                return {
                    "action": "sell" if is_short else "buy",
                    "price": row['close'],
                    "reason": signal.reason,
                    "confidence": signal.strength
                }

        return {"action": "hold"}
