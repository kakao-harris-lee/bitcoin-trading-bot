"""Composite Strategy Task - assembles Entry/Exit components into a runnable task.

This is the bridge between the component-based strategy architecture and the
stream-based task system. It extends BaseStrategyTask and delegates entry/exit
logic to IEntryStrategy and IExitStrategy components.

Usage:
    entry = V35EntryStrategy(params)
    exit_strat = V35TrailingExitStrategy(params)

    task = CompositeStrategyTask(
        name="v35_long",
        symbols=["BTC", "ETH"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
    )

    await task.run()
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime
from typing import Any, TYPE_CHECKING

import pandas as pd
from trading.streams.base_strategy import BaseStrategyTask
from trading.indicators import add_all_indicators

from .interfaces import IEntryStrategy, IExitStrategy
from .models import build_market_context, MarketContext, MarketData, Position, Signal

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.core.event_emitter import EventEmitter

logger = logging.getLogger(__name__)


class CompositeStrategyTask(BaseStrategyTask):
    """Strategy task that delegates to Entry/Exit components.

    Bridges the component-based architecture with the stream-based task system.
    Entry and exit logic are fully delegated to the injected components.
    """

    def __init__(
        self,
        name: str,
        symbols: list[str],
        redis: RedisStreams,
        entry_strategy: IEntryStrategy,
        exit_strategy: IExitStrategy,
        market: str = "futures",
        buffer_size: int = 500,
        use_smart_exit: bool = False,
        config: dict | None = None,
        emit_events: bool = False,
    ):
        """Initialize composite strategy task.

        Args:
            name: Strategy name (e.g., "v35_long").
            symbols: List of symbols to trade.
            redis: Redis streams client.
            entry_strategy: Entry component implementing IEntryStrategy.
            exit_strategy: Exit component implementing IExitStrategy.
            market: Market type ("spot" or "futures").
            buffer_size: Price buffer size.
            use_smart_exit: Use smart exit stream.
            config: Additional configuration.
            emit_events: Whether to emit observability events to Redis streams.
        """
        super().__init__(
            name=name,
            symbols=symbols,
            redis=redis,
            market=market,
            buffer_size=buffer_size,
            use_smart_exit=use_smart_exit,
        )
        self.entry_strategy = entry_strategy
        self.exit_strategy = exit_strategy
        self.config = config or {}
        # Min data depends on indicators, typically 30-50, using 0 if we warm up
        self.min_data_points = 0
        self.history: dict[str, list[dict]] = {}
        # Track last recorded candle hour per symbol for decision logging
        self.last_decision_hour: dict[str, int] = {}
        # Event emission for observability
        self.emit_events = emit_events
        self.event_emitter: EventEmitter | None = None
        if emit_events:
            from trading.core.event_emitter import EventEmitter
            self.event_emitter = EventEmitter(redis=redis, enabled=True)

    async def run(self) -> None:
        """Main loop: warm-up then consume."""
        logger.info(f"Warming up composite strategy {self.name}...")

        # Determine interval based on name (simple heuristic for migration)
        interval = "1d"
        if "short" in self.name or "h4" in self.name:
            interval = "4h"

        for symbol in self.symbols:
            candles = await self.fetch_initial_candles(symbol, interval=interval, limit=200)
            if candles:
                self.history[symbol] = candles
                logger.info(f"Fetched {len(candles)} {interval} candles for {symbol}")
            else:
                logger.warning(f"Failed to fetch history for {symbol}")

        await super().run()

    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate entry conditions by delegating to entry component.

        Args:
            symbol: Trading symbol.

        Returns:
            Order intent dict or None.
        """
        buffer = self.price_buffer.get(symbol, [])

        if len(buffer) < self.min_data_points:
            return None

        # Build MarketData from indicators
        market_data = self._build_market_data(symbol)
        if market_data is None:
            return None

        # Build MarketContext for trend/volatility filtering
        context = self._build_market_context(market_data)

        # Record decision at candle close for dashboard visibility
        await self._check_and_record_decision(symbol, market_data, context)

        # Delegate to entry component with context
        signal = self.entry_strategy.check_entry(market_data, context)

        # Emit entry evaluation event for observability
        await self._emit_entry_evaluation(market_data, context, signal)

        if signal:
            # Apply dynamic sizing if configured
            quantity = await self._get_quantity(symbol, market_data.close, signal.quantity)
            return self._signal_to_dict(signal, quantity)

        return None

    async def evaluate_exit(self, symbol: str, position_dict: dict) -> dict[str, Any] | None:
        """Evaluate exit conditions by delegating to exit component.

        Args:
            symbol: Trading symbol.
            position_dict: Position dict from Redis.

        Returns:
            Order intent dict or None.
        """
        # Build MarketData from indicators
        market_data = self._build_market_data(symbol)
        if market_data is None:
            return None

        # Record decision at candle close for dashboard visibility (with position)
        await self._check_and_record_decision(symbol, market_data)

        # Build Position model from dict
        position = self._dict_to_position(position_dict)

        # Delegate to exit component
        # Handle both sync and async exit strategies using proper detection
        check_exit_method = self.exit_strategy.check_exit
        if asyncio.iscoroutinefunction(check_exit_method):
            signal = await check_exit_method(position, market_data)
        else:
            signal = check_exit_method(position, market_data)

        # Emit exit evaluation event for observability
        await self._emit_exit_evaluation(position, market_data, signal)

        if signal:
            return self._signal_to_dict(signal, signal.quantity)

        return None

    async def on_position_opened(self, symbol: str, position_dict: dict) -> None:
        """Notify exit strategy when position is opened.

        Called by _handle_message after entry order is filled.

        Args:
            symbol: Trading symbol.
            position_dict: Position dict from Redis.
        """
        position = self._dict_to_position(position_dict)

        # Notify exit strategy (for state initialization)
        on_opened_method = self.exit_strategy.on_position_opened
        if asyncio.iscoroutinefunction(on_opened_method):
            await on_opened_method(position)
        else:
            on_opened_method(position)

        logger.info(f"{symbol}: Notified exit strategy of position open")

    async def on_position_closed(self, symbol: str) -> None:
        """Notify exit strategy when position is closed.

        Args:
            symbol: Trading symbol.
        """
        on_closed_method = self.exit_strategy.on_position_closed
        if asyncio.iscoroutinefunction(on_closed_method):
            await on_closed_method(symbol)
        else:
            on_closed_method(symbol)

        logger.info(f"{symbol}: Notified exit strategy of position close")

    def _build_market_data(self, symbol: str) -> MarketData | None:
        """Build MarketData from current indicators (Memory + Pandas).

        Provides all indicators needed for V35 entry/exit strategies:
        - MFI, ADX, RSI for regime classification
        - MACD, MACD Signal for momentum entry/exit
        - Stochastic for conservative entry
        - High/Low/Volume for OHLCV
        - 20-period high/low for breakout/range detection
        - 20-period average volume for volume confirmation

        Args:
            symbol: Trading symbol.

        Returns:
            MarketData instance or None if indicators unavailable.
        """
        try:
            history = self.history.get(symbol)
            if not history:
                return None

            # Create DF and update last row
            df = pd.DataFrame(history)

            # Update last candle with current price
            buffer = self.price_buffer.get(symbol, [])
            if buffer:
                current_price = float(buffer[-1]["price"])
                idx = df.index[-1]
                # Ensure we have required columns before updating
                if 'close' in df.columns:
                    df.at[idx, "close"] = current_price
                if 'high' in df.columns:
                    df.at[idx, "high"] = max(df.at[idx, "high"], current_price)
                if 'low' in df.columns:
                    df.at[idx, "low"] = min(df.at[idx, "low"], current_price)
            else:
                current_price = df.iloc[-1]["close"]

            # Calculate indicators using pandas-ta/ta-lib wrapper
            df = add_all_indicators(df)
            last_row = df.iloc[-1]

            # Calculate 20-period lookback values for breakout/range detection
            lookback = 20
            if len(df) >= lookback:
                prev_df = df.iloc[-lookback-1:-1]  # Previous 20 candles (not including current)
                prev_high_20 = float(prev_df['high'].max())
                prev_low_20 = float(prev_df['low'].min())
                avg_volume_20 = float(prev_df['volume'].mean())
            else:
                prev_high_20 = 0.0
                prev_low_20 = 0.0
                avg_volume_20 = 0.0

            return MarketData(
                symbol=symbol,
                close=float(current_price),
                mfi=float(last_row.get("mfi", 50)),
                adx=float(last_row.get("adx", 20)),
                rsi=float(last_row.get("rsi", 50)),
                timestamp=int(buffer[-1].get("timestamp", 0) if buffer else 0),
                # OHLCV data
                high=float(last_row.get("high", current_price)),
                low=float(last_row.get("low", current_price)),
                volume=float(last_row.get("volume", 0)),
                # MACD indicators for momentum entry/exit
                macd=float(last_row.get("macd", 0)),
                macd_signal=float(last_row.get("macd_signal", 0)),
                # Stochastic for conservative entry
                stoch_k=float(last_row.get("stoch_k", 50)),
                stoch_d=float(last_row.get("stoch_d", 50)),
                # Bollinger Bands
                bb_upper=float(last_row.get("bb_upper", 0)),
                bb_lower=float(last_row.get("bb_lower", 0)),
                bb_middle=float(last_row.get("bb_middle", 0)),
                # ATR for volatility measurement
                atr=float(last_row.get("atr", 0)),
                # Historical reference points for breakout/range detection
                prev_high_20=prev_high_20,
                prev_low_20=prev_low_20,
                avg_volume_20=avg_volume_20,
            )
        except Exception as e:
            logger.error(f"Failed to build MarketData for {symbol}: {e}")
            return None

    def _build_market_context(self, market_data: MarketData) -> MarketContext:
        """Build MarketContext from MarketData.

        Uses MFI-based trend classification and ATR-based volatility scoring.

        Args:
            market_data: Current market state with indicators.

        Returns:
            MarketContext with trend and volatility analysis.
        """
        return build_market_context(
            mfi=market_data.mfi,
            adx=market_data.adx,
            atr=market_data.atr,
            close=market_data.close,
        )

    def _dict_to_position(self, position_dict: dict) -> Position:
        """Convert position dict to Position model.

        Args:
            position_dict: Position dict from Redis.

        Returns:
            Position instance.
        """
        return Position(
            symbol=position_dict.get("symbol", ""),
            entry_price=float(position_dict.get("entry_price", 0)),
            quantity=float(position_dict.get("quantity", 0)),
            strategy=position_dict.get("strategy", self.name),
            market=position_dict.get("market", self.market),
            timestamp=position_dict.get("timestamp", 0),
        )

    def _signal_to_dict(self, signal: Signal, quantity: float) -> dict[str, Any]:
        """Convert Signal model to order intent dict.

        Args:
            signal: Signal from component.
            quantity: Final quantity (may be adjusted).

        Returns:
            Order intent dict.
        """
        result = {
            "symbol": signal.symbol,
            "side": signal.side,
            "market": signal.market,
            "quantity": str(quantity),
            "reason": signal.reason,
        }

        if signal.trigger_price is not None:
            result["trigger_price"] = signal.trigger_price

        return result

    async def _get_quantity(
        self,
        symbol: str,
        price: float,
        default_quantity: float,
    ) -> float:
        """Get position quantity, using dynamic sizing if configured.

        Args:
            symbol: Trading symbol.
            price: Current price.
            default_quantity: Default quantity from signal.

        Returns:
            Final quantity.
        """
        use_dynamic = self.config.get("dynamic_sizing", False)

        if use_dynamic:
            position_pct = self.config.get("position_pct", 0.02)
            return await self.get_dynamic_position_size(symbol, price, position_pct)
        else:
            return self.config.get("position_size", default_quantity)

    async def _check_and_record_decision(
        self,
        symbol: str,
        market_data: MarketData,
        context: MarketContext | None = None,
    ) -> None:
        """Check if candle closed and record decision to Redis stream.

        Records strategy decision at hourly candle boundaries for dashboard visibility.

        Args:
            symbol: Trading symbol.
            market_data: Current market state with indicators.
            context: Optional pre-analyzed market context.
        """
        current_hour = datetime.now().hour
        last_hour = self.last_decision_hour.get(symbol, -1)

        # Only record once per hour per symbol
        if current_hour == last_hour:
            return

        self.last_decision_hour[symbol] = current_hour

        # Get regime from entry strategy if available
        regime = "UNKNOWN"
        if hasattr(self.entry_strategy, '_classify_regime'):
            regime = self.entry_strategy._classify_regime(market_data.mfi, market_data.adx)

        # Determine decision and reason based on position state
        position_key = f"positions:{symbol}:{self.market}"
        position = await self.redis._client.hgetall(position_key)

        # Get entry thresholds for detailed logging
        mfi_bull = 52.0
        mfi_bear = 48.0
        adx_trend = 20.0
        if hasattr(self.entry_strategy, 'params'):
            params = self.entry_strategy.params
            mfi_bull = getattr(params, 'mfi_bull', 52.0)
            mfi_bear = getattr(params, 'mfi_bear', 48.0)
            adx_trend = getattr(params, 'adx_trend', 20.0)

        if position and float(position.get('quantity', 0)) > 0:
            entry_price = float(position.get('entry_price', 0))
            quantity = float(position.get('quantity', 0))
            unrealized_pnl = (market_data.close - entry_price) * quantity
            unrealized_pnl_pct = ((market_data.close - entry_price) / entry_price * 100) if entry_price > 0 else 0
            price_change = market_data.close - entry_price

            decision = "HOLD"
            reason = (
                f"Position: {quantity:.6f} @ ${entry_price:,.2f} | "
                f"Current: ${market_data.close:,.2f} ({'+' if price_change >= 0 else ''}{price_change:,.2f}) | "
                f"P&L: {'+' if unrealized_pnl_pct >= 0 else ''}{unrealized_pnl_pct:.2f}%"
            )
            position_data = {
                "active": True,
                "entry_price": entry_price,
                "quantity": quantity,
                "unrealized_pnl": round(unrealized_pnl, 2),
                "unrealized_pnl_pct": round(unrealized_pnl_pct, 2),
            }
        else:
            # Check if conditions would trigger entry
            should_enter = hasattr(self.entry_strategy, '_should_enter') and \
                          self.entry_strategy._should_enter(regime)

            if should_enter:
                decision = "BUY"
                reason = f"Entry signal: {regime} (MFI={market_data.mfi:.1f} >= {mfi_bull}, ADX={market_data.adx:.1f} >= {adx_trend})"
            else:
                # Detailed reason why not entering
                reasons = []
                if market_data.mfi < mfi_bull:
                    reasons.append(f"MFI={market_data.mfi:.1f} < {mfi_bull}")
                if market_data.mfi > mfi_bear:
                    reasons.append(f"MFI={market_data.mfi:.1f} > {mfi_bear}")
                if market_data.adx < adx_trend:
                    reasons.append(f"ADX={market_data.adx:.1f} < {adx_trend}")

                decision = "WAIT"
                reason = f"No entry: {regime} | " + ", ".join(reasons) if reasons else f"No entry: {regime}"

            position_data = {"active": False}

        # Build decision record
        decision_record = {
            "timestamp": datetime.now().isoformat(),
            "symbol": symbol,
            "strategy": self.name,
            "market": self.market,
            "price": str(market_data.close),
            "mfi": str(round(market_data.mfi, 1)),
            "adx": str(round(market_data.adx, 1)),
            "regime": regime,
            "decision": decision,
            "reason": reason,
            "position": json.dumps(position_data),
        }

        # Add context info if available
        if context:
            decision_record["trend"] = context.trend
            decision_record["volatility_score"] = str(round(context.volatility_score, 4))
            decision_record["is_extreme_volatility"] = str(context.is_extreme_volatility)

        # Write to Redis stream with auto-trim (keep ~48 hours of hourly data)
        try:
            await self.redis._client.xadd(
                "strategy:decisions",
                decision_record,
                maxlen=5000,  # ~48h * 3 symbols * ~30 strategies
            )

            # Detailed log message
            log_lines = [
                f"{'='*60}",
                f"[{self.name.upper()}] {symbol} ({self.market}) - HOURLY DECISION",
                f"{'='*60}",
                f"  Time:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
                f"  Price:    ${market_data.close:,.2f}",
                f"  MFI:      {market_data.mfi:.1f} (Bull>{mfi_bull}, Bear<{mfi_bear})",
                f"  ADX:      {market_data.adx:.1f} (Trend>{adx_trend})",
                f"  Regime:   {regime}",
            ]
            # Add context info if available
            if context:
                vol_pct = context.volatility_score * 100
                vol_status = "EXTREME" if context.is_extreme_volatility else "normal"
                log_lines.append(f"  Trend:    {context.trend}")
                log_lines.append(f"  Volatility: {vol_pct:.2f}% ({vol_status})")
            log_lines.extend([
                f"  Decision: {decision}",
                f"  Reason:   {reason}",
            ])
            if position_data.get("active"):
                log_lines.append(f"  Position: {position_data['quantity']:.6f} @ ${position_data['entry_price']:,.2f}")
                log_lines.append(f"  P&L:      ${position_data['unrealized_pnl']:,.2f} ({position_data['unrealized_pnl_pct']:+.2f}%)")
            log_lines.append(f"{'='*60}")

            logger.info("\n".join(log_lines))
        except Exception as e:
            logger.error(f"Failed to record decision for {symbol}: {e}")

    async def _emit_entry_evaluation(
        self,
        market_data: MarketData,
        context: MarketContext,
        signal: Signal | None,
    ) -> None:
        """Emit entry evaluation event for observability.

        Args:
            market_data: Current market state.
            context: Market context with trend/volatility.
            signal: Entry signal or None.
        """
        if not self.emit_events or self.event_emitter is None:
            return

        from trading.core.event_emitter import EntryEvaluationEvent, SafetyRejectionEvent

        # Get thresholds from entry strategy params
        mfi_threshold = 52.0
        adx_threshold = 20.0
        volatility_threshold = 0.03
        if hasattr(self.entry_strategy, 'params'):
            params = self.entry_strategy.params
            mfi_threshold = getattr(params, 'mfi_bull', 52.0)
            adx_threshold = getattr(params, 'adx_trend', 20.0)

        # Determine filter pass status
        adx_passed = market_data.adx >= adx_threshold
        mfi_passed = market_data.mfi >= mfi_threshold
        volatility_passed = context.volatility_score <= volatility_threshold
        regime_allowed = context.regime in {"BULL_STRONG", "BULL_MODERATE"}
        macd_crossed = market_data.macd > market_data.macd_signal

        event = EntryEvaluationEvent(
            timestamp=datetime.now().isoformat(),
            strategy=self.name,
            symbol=market_data.symbol,
            market=self.market,
            adx=market_data.adx,
            adx_threshold=adx_threshold,
            adx_passed=adx_passed,
            regime=context.regime,
            regime_allowed=regime_allowed,
            volatility_score=context.volatility_score,
            volatility_threshold=volatility_threshold,
            volatility_passed=volatility_passed,
            mfi=market_data.mfi,
            mfi_threshold=mfi_threshold,
            mfi_passed=mfi_passed,
            macd=market_data.macd,
            macd_signal=market_data.macd_signal,
            macd_crossed=macd_crossed,
            rsi=market_data.rsi,
            signal_generated=signal is not None,
            reason=signal.reason if signal else "No entry signal",
        )

        await self.event_emitter.emit_entry_evaluation(event)

        # Emit safety rejection event if entry was blocked
        if signal is None:
            rejection_type = None
            reason = ""

            if not adx_passed:
                rejection_type = "weak_trend"
                reason = f"ADX={market_data.adx:.1f} < {adx_threshold} threshold"
            elif not regime_allowed:
                rejection_type = "wrong_regime"
                reason = f"Regime {context.regime} not allowed for entry"
            elif not volatility_passed:
                rejection_type = "extreme_volatility"
                reason = f"Volatility {context.volatility_score:.4f} > {volatility_threshold}"
            elif not mfi_passed:
                rejection_type = "weak_momentum"
                reason = f"MFI={market_data.mfi:.1f} < {mfi_threshold}"

            if rejection_type:
                safety_event = SafetyRejectionEvent(
                    timestamp=datetime.now().isoformat(),
                    strategy=self.name,
                    symbol=market_data.symbol,
                    market=self.market,
                    rejection_type=rejection_type,
                    reason=reason,
                    adx=market_data.adx,
                    mfi=market_data.mfi,
                    regime=context.regime,
                    volatility_score=context.volatility_score,
                )
                await self.event_emitter.emit_safety_rejection(safety_event)

    async def _emit_exit_evaluation(
        self,
        position: Position,
        market_data: MarketData,
        signal: Signal | None,
    ) -> None:
        """Emit exit evaluation event for observability.

        Args:
            position: Current position.
            market_data: Current market state.
            signal: Exit signal or None.
        """
        if not self.emit_events or self.event_emitter is None:
            return

        from trading.core.event_emitter import ExitEvaluationEvent

        # Calculate P&L
        unrealized_pnl = (market_data.close - position.entry_price) * position.quantity
        unrealized_pnl_pct = (
            (market_data.close - position.entry_price) / position.entry_price * 100
            if position.entry_price > 0 else 0
        )

        # Get exit parameters if available from strategy
        stop_loss_price = 0.0
        take_profit_price = 0.0
        trailing_stop_price = 0.0
        high_water_mark = market_data.close
        drawdown_from_hwm_pct = 0.0

        if hasattr(self.exit_strategy, 'params'):
            params = self.exit_strategy.params
            # Calculate stop loss/take profit from params if available
            stop_loss_pct = getattr(params, 'stop_loss_pct', 0.02)
            take_profit_pct = getattr(params, 'take_profit_pct', 0.05)
            stop_loss_price = position.entry_price * (1 - stop_loss_pct)
            take_profit_price = position.entry_price * (1 + take_profit_pct)

        # Get HWM from exit strategy state if available
        if hasattr(self.exit_strategy, 'state') and hasattr(self.exit_strategy.state, 'get'):
            hwm_state = self.exit_strategy.state.get(position.symbol, {})
            if isinstance(hwm_state, dict):
                high_water_mark = hwm_state.get('high_water_mark', market_data.close)
                trailing_stop_price = hwm_state.get('trailing_stop', 0.0)
                if high_water_mark > 0:
                    drawdown_from_hwm_pct = (high_water_mark - market_data.close) / high_water_mark * 100

        # Determine trigger status
        stop_loss_triggered = market_data.close <= stop_loss_price if stop_loss_price > 0 else False
        take_profit_triggered = market_data.close >= take_profit_price if take_profit_price > 0 else False
        trailing_stop_triggered = market_data.close <= trailing_stop_price if trailing_stop_price > 0 else False
        macd_exit_signal = market_data.macd < market_data.macd_signal

        event = ExitEvaluationEvent(
            timestamp=datetime.now().isoformat(),
            strategy=self.name,
            symbol=market_data.symbol,
            market=self.market,
            entry_price=position.entry_price,
            current_price=market_data.close,
            quantity=position.quantity,
            unrealized_pnl=unrealized_pnl,
            unrealized_pnl_pct=unrealized_pnl_pct,
            stop_loss_price=stop_loss_price,
            stop_loss_triggered=stop_loss_triggered,
            take_profit_price=take_profit_price,
            take_profit_triggered=take_profit_triggered,
            trailing_stop_price=trailing_stop_price,
            trailing_stop_triggered=trailing_stop_triggered,
            macd_exit_signal=macd_exit_signal,
            high_water_mark=high_water_mark,
            drawdown_from_hwm_pct=drawdown_from_hwm_pct,
            signal_generated=signal is not None,
            reason=signal.reason if signal else f"Holding: P&L {'+' if unrealized_pnl_pct >= 0 else ''}{unrealized_pnl_pct:.2f}%",
        )

        await self.event_emitter.emit_exit_evaluation(event)


async def create_composite_task(
    name: str,
    symbols: list[str],
    redis: RedisStreams,
    entry_strategy: IEntryStrategy,
    exit_strategy: IExitStrategy,
    config: dict | None = None,
    market: str = "futures",
    use_smart_exit: bool = False,
) -> CompositeStrategyTask:
    """Create a CompositeStrategyTask.

    Convenience function that also initializes persistent exit strategies.

    Args:
        name: Strategy name.
        symbols: List of symbols.
        redis: Redis streams client.
        entry_strategy: Entry component.
        exit_strategy: Exit component.
        config: Configuration.
        market: Market type.
        use_smart_exit: Use smart exit.

    Returns:
        Initialized CompositeStrategyTask.
    """
    task = CompositeStrategyTask(
        name=name,
        symbols=symbols,
        redis=redis,
        entry_strategy=entry_strategy,
        exit_strategy=exit_strategy,
        market=market,
        config=config,
        use_smart_exit=use_smart_exit,
    )

    # Initialize persistent exit strategy state
    if hasattr(exit_strategy, 'load_state'):
        await exit_strategy.load_state(symbols)
        logger.info(f"{name}: Loaded persistent state for {symbols}")

    return task
