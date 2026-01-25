"""Adapter to bridge Component-based Strategies with the Functional Backtester.

This allows the historical backtester to run the exact same logic as live trading.
"""
from dataclasses import replace
from types import MappingProxyType
from typing import Dict, Any, Callable, Optional
import pandas as pd
from trading.strategies.components.models import MarketData, Position, Signal, MarketContext, TradingContext, build_market_context
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
        self.config = config
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

        # Extract indicators for context building
        mfi = row.get('mfi', 50.0)
        adx = row.get('adx', 20.0)
        atr = row.get('atr', 0.0)
        close = row['close']
        volume = row.get('volume', 0.0)
        avg_volume = row.get('avg_volume_20', 0.0)

        # Build Context using the standard function (ensures consistent regime/trend classification)
        context = build_market_context(
            mfi=mfi,
            adx=adx,
            atr=atr,
            close=close,
            volume=volume,
            avg_volume=avg_volume,
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

        # 1. MarketData construction with all fields needed by entry strategies
        # Handle timestamp conversion
        ts = row.get('timestamp', 0)
        if hasattr(ts, 'timestamp'):
            ts = int(ts.timestamp() * 1000)
        else:
            ts = int(ts) if ts else 0

        market_data = MarketData(
            symbol=self.symbol,
            close=close,
            timestamp=ts,
            mfi=mfi,
            adx=adx,
            rsi=row.get('rsi', 50.0),
            # OHLCV for breakout/sequence models
            high=row.get('high', 0.0) or 0.0,
            low=row.get('low', 0.0) or 0.0,
            volume=volume,
            # MACD for momentum entry
            macd=row.get('macd', 0.0),
            macd_signal=row.get('macd_signal', 0.0),
            # Stochastic for conservative entry
            stoch_k=row.get('stoch_k', 50.0),
            stoch_d=row.get('stoch_d', 50.0),
            # Bollinger Bands for range entry
            bb_upper=row.get('bb_upper', 0.0),
            bb_lower=row.get('bb_lower', 0.0),
            bb_middle=row.get('bb_middle', 0.0),
            # Volume for breakout entry
            avg_volume_20=avg_volume,
            # Support/resistance levels
            prev_high_20=row.get('prev_high_20', 0.0),
            prev_low_20=row.get('prev_low_20', 0.0),
            # ATR for volatility
            atr=atr,
            # Indicators map and HWM
            indicators=indicators,
            high_water_mark=self.high_water_mark
        )

        # 2. Check Exits first (if we have a position)
        if self.current_position:
            # Update high water mark
            is_long = getattr(self.current_position, 'side', 'long') == 'long'

            if is_long:
                if self.high_water_mark is None or close > self.high_water_mark:
                    self.high_water_mark = close
            else:
                if self.high_water_mark is None or close < self.high_water_mark:
                    self.high_water_mark = close

            # Create new MarketData with updated HWM (frozen dataclass)
            market_data = replace(market_data, high_water_mark=self.high_water_mark)

            # Build TradingContext for new interface (immutable positions)
            positions = {self.strategy_name: self.current_position}
            ctx = TradingContext(
                symbol=self.symbol,
                timestamp=market_data.timestamp,
                market=market_data,
                regime=context,
                positions=MappingProxyType(positions),
            )
            signal = self.exit_strategy.check_exit(ctx, self.current_position)

            if signal:
                self.current_position = None
                self.high_water_mark = None
                try:
                    self.exit_strategy.on_position_closed(self.symbol)
                except Exception:
                    pass
                action = 'close_short' if not is_long else 'sell'
                return {
                    'action': action,
                    'fraction': 1.0,
                    'reason': signal.reason
                }

            return {'action': 'hold'}

        # 3. Check Entries (if no position)
        else:
            # Build TradingContext for new interface (immutable positions)
            ctx = TradingContext(
                symbol=self.symbol,
                timestamp=market_data.timestamp,
                market=market_data,
                regime=context,
                positions=MappingProxyType({}),  # No position when checking entry
            )
            signal = self.entry_strategy.check_entry(ctx)

            if signal:
                is_short = signal.side == 'sell'
                pos_side = 'short' if is_short else 'long'

                # Create simulated position
                ts_ms = int(row['timestamp'].timestamp() * 1000) if hasattr(row['timestamp'], 'timestamp') else 0

                self.current_position = Position(
                    symbol=self.symbol,
                    quantity=getattr(signal, "quantity", 1.0) or 1.0,
                    entry_price=row['close'],
                    side=pos_side,
                    strategy=self.strategy_name,
                    market="futures",  # Default for backtesting context unless specified
                    timestamp=ts_ms
                )
                self.high_water_mark = row['close']

                # Notify exit strategy (stateful exits may track entry)
                try:
                    self.exit_strategy.on_position_opened(self.current_position)
                except Exception:
                    pass

                # Use action names expected by backtest_runner:
                # 'buy' for opening long, 'open_short' for opening short
                action = "open_short" if is_short else "buy"
                fraction = getattr(signal, "quantity", 1.0) or 1.0
                return {
                    "action": action,
                    "fraction": fraction,
                    "price": close,
                    "reason": signal.reason,
                }

        return {"action": "hold"}
