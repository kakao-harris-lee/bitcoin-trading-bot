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
import time
from datetime import datetime
from types import MappingProxyType
from typing import Any, TYPE_CHECKING

import pandas as pd
from trading.streams.base_strategy import BaseStrategyTask
from trading.indicators import add_all_indicators

from .interfaces import IEntryStrategy, IExitStrategy
from .models import (
    build_market_context,
    MarketContext,
    MarketData,
    Position,
    Signal,
    TradingContext,
    RegimeSmoother,
    BEAR_REGIMES,
)
from .regime_filter import EnhancedRegimeRouter
from .rf_probability_service import RFProbabilityService
from trading.observability.structured_logger import trade_logger
from trading.risk.position_sizer import PositionSizer, RiskSizingConfig
from trading.risk.portfolio_risk_manager import PortfolioRiskManager, RiskCapConfig
from trading.risk.correlation_filter import CorrelationFilter, CorrelationConfig

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.core.event_emitter import EventEmitter
    from trading.indicators.indicator_service import IndicatorService
    from .context_builder import TradingContextBuilder

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
        indicator_service: IndicatorService | None = None,
        context_builder: TradingContextBuilder | None = None,
        regime_version: str = "v1",
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
            indicator_service: Shared indicator calculation service (reduces CPU).
            context_builder: Shared context builder for TradingContext.
            regime_version: Regime detection version ("v1" or "v2" enhanced).
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

        # Shared indicator service for centralized calculation (reduces CPU by ~75%)
        self.indicator_service: IndicatorService | None = indicator_service

        # Shared context builder for centralized TradingContext construction
        self.context_builder: TradingContextBuilder | None = context_builder

        # Evaluation throttling to reduce CPU usage (legacy, used if no indicator_service)
        # Only recalculate indicators at this interval (seconds), not on every tick
        self.evaluation_interval = self.config.get("evaluation_interval_seconds", 60)
        self._last_evaluation_time: dict[str, float] = {}
        self._market_data_cache: dict[str, MarketData] = {}

        # Regime smoothing to reduce noise (78% fewer transitions)
        # v1: Original RegimeSmoother (EMA + persistence)
        # v2: EnhancedRegimeRouter (BBW + MTF + Volume filters)
        self.regime_version = regime_version
        self.use_regime_smoothing = self.config.get("use_regime_smoothing", True)
        self._regime_smoothers: dict[str, RegimeSmoother] = {}
        self._enhanced_routers: dict[str, EnhancedRegimeRouter] = {}

        if self.regime_version == "v2":
            # Enhanced regime detection with BBW, MTF, and Volume filters
            bbw_block = self.config.get("bbw_block_threshold", 25)
            bbw_confirm = self.config.get("bbw_confirm_threshold", 50)
            volume_block = self.config.get("volume_block_ratio", 0.8)
            volume_boost = self.config.get("volume_boost_ratio", 1.2)
            mtf_enabled = self.config.get("mtf_enabled", True)
            for symbol in symbols:
                self._enhanced_routers[symbol] = EnhancedRegimeRouter(
                    bbw_block_threshold=bbw_block,
                    bbw_confirm_threshold=bbw_confirm,
                    volume_block_ratio=volume_block,
                    volume_boost_ratio=volume_boost,
                    mtf_enabled=mtf_enabled,
                )
            logger.info(f"{self.name} using enhanced regime detection v2")
        elif self.use_regime_smoothing:
            # Original v1 regime smoothing
            ema_alpha = self.config.get("regime_ema_alpha", 0.3)  # ~5-period EMA
            persistence = self.config.get("regime_persistence", 2)  # 2-tick confirmation
            for symbol in symbols:
                self._regime_smoothers[symbol] = RegimeSmoother(
                    ema_alpha=ema_alpha,
                    persistence=persistence,
                )

        # RF probability integration (optional)
        self._use_rf_probability = self.config.get("use_rf_probability", False)
        self._rf_service: RFProbabilityService | None = None
        self._rf_available = False
        self._rf_history_size = int(self.config.get("rf_history_size", 720))
        self._rf_min_history = int(self.config.get("rf_min_history", 60))
        if self._use_rf_probability:
            self._rf_service = RFProbabilityService.get_instance(
                lstm_path=self.config.get("lstm_model_path", "lstm_trainer/models/hybrid_lstm.pth"),
                rf_path=self.config.get("rf_model_path", "lstm_trainer/models/noise_filter_rf.pkl"),
            )
            self._rf_available = self._rf_service.is_available()

        # Entry gating and leverage controls
        self._cash_in_bear = self.config.get("cash_in_bear", False)
        self._cash_below_ema200 = self.config.get("cash_below_ema200", False)
        self._cooldown_candles = int(self.config.get("stop_loss_cooldown", 24))
        self._cooldown_remaining: dict[str, int] = {}
        self._max_consecutive_losses = int(self.config.get("max_consecutive_losses", 3))
        self._consecutive_losses: dict[str, int] = {}
        self._loss_pause_candles = int(self.config.get("loss_pause_candles", 48))
        self._loss_pause_remaining: dict[str, int] = {}
        self._v2_exit_on_filter = self.config.get("v2_exit_on_filter", False)
        self._panic_sell_below_ma120 = self.config.get("panic_sell_below_ma120", False)

        self._dynamic_leverage_enabled = self.config.get("dynamic_leverage", False)
        self._leverage_bull_strong = float(self.config.get("leverage_bull_strong", 3.0))
        self._leverage_bull_moderate = float(self.config.get("leverage_bull_moderate", 2.0))
        self._leverage_sideways = float(self.config.get("leverage_sideways", 1.0))
        self._leverage_bear = float(self.config.get("leverage_bear", 0.0))

        self._prob_leverage_enabled = self.config.get("prob_leverage_enabled", False)
        self._prob_leverage_max = float(self.config.get("prob_leverage_max", 3.0))
        self._prob_leverage_high = float(self.config.get("prob_leverage_high", 2.5))
        self._prob_leverage_mid = float(self.config.get("prob_leverage_mid", 2.0))
        self._prob_leverage_low = float(self.config.get("prob_leverage_low", 1.0))
        self._prob_leverage_min = float(self.config.get("prob_leverage_min", 0.5))

        self._bull_prob_threshold = float(self.config.get("bull_prob_threshold", 0.0))
        self._bull_prob_enabled = self._bull_prob_threshold > 0

        self._dynamic_position_sizing = self.config.get("dynamic_position_sizing", False)
        self._position_size_high = float(self.config.get("position_size_high", 0.30))
        self._position_size_mid = float(self.config.get("position_size_mid", 0.15))
        self._position_size_low = float(self.config.get("position_size_low", 0.05))
        self._position_conf_low = float(self.config.get("position_conf_low", 0.50))
        self._position_conf_high = float(self.config.get("position_conf_high", 0.70))

        # Drawdown protection (portfolio-level)
        self._drawdown_enabled = self.config.get("drawdown_enabled", False)
        self._drawdown_warning_pct = float(self.config.get("drawdown_warning_pct", 8.0))
        self._drawdown_reduce_pct = float(self.config.get("drawdown_reduce_pct", 10.0))
        self._drawdown_exit_pct = float(self.config.get("drawdown_exit_pct", 12.0))
        self._drawdown_leverage_reduction = float(self.config.get("drawdown_leverage_reduction", 0.5))
        self._drawdown_partial_exit_done: dict[str, bool] = {}
        self._drawdown_cache: tuple[float, float] = (0.0, 0.0)

        # Volatility breakout filter config (Larry Williams strategy)
        self.breakout_k = self.config.get("breakout_k", 0.5)  # k value for target_price
        self._prev_day_cache: dict[str, tuple[float, float, str]] = {}  # (high, low, date)

        # Risk-based position sizing (replaces percentage-based sizing)
        self._risk_based_sizing = self.config.get("risk_based_sizing", False)
        self._position_sizer: PositionSizer | None = None
        self._portfolio_risk_mgr: PortfolioRiskManager | None = None

        if self._risk_based_sizing:
            sizing_config = RiskSizingConfig.from_dict(self.config)
            self._position_sizer = PositionSizer(sizing_config)

            # Portfolio risk manager with correlation filter
            risk_cap_config = RiskCapConfig.from_dict(self.config)

            corr_filter = None
            if self.config.get("correlation_filter", True):
                corr_config = CorrelationConfig.from_dict(self.config)
                corr_filter = CorrelationFilter(corr_config, redis)

            self._portfolio_risk_mgr = PortfolioRiskManager(
                risk_cap_config, redis, corr_filter
            )
            logger.info(
                f"{self.name}: Risk-based sizing enabled "
                f"(risk={sizing_config.risk_per_trade_pct*100:.1f}%, "
                f"max_total={risk_cap_config.max_total_risk_pct*100:.1f}%)"
            )

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

                # Register history with shared indicator service if available
                if self.indicator_service:
                    self.indicator_service.update_history(symbol, candles)
            else:
                logger.warning(f"Failed to fetch history for {symbol}")

        await super().run()

    async def evaluate(self, symbol: str) -> dict[str, Any] | None:
        """Evaluate entry conditions by delegating to entry component.

        Uses TradingContextBuilder for centralized context (if available),
        which provides cached regime classification and cross-strategy positions.

        Args:
            symbol: Trading symbol.

        Returns:
            Order intent dict or None.
        """
        buffer = self.price_buffer.get(symbol, [])

        if len(buffer) < self.min_data_points:
            return None

        self._decrement_entry_blocks(symbol)

        # Build MarketData from indicators
        market_data = self._build_market_data(symbol)
        if market_data is None:
            return None

        # Build context locally to ensure v2 regime + RF features are applied
        context = self._build_market_context(market_data)
        positions = MappingProxyType({})
        if self.context_builder is not None:
            cached_ctx = self.context_builder.get_context(symbol, market_data.timestamp)
            if cached_ctx is not None:
                positions = cached_ctx.positions

        ctx = TradingContext(
            symbol=symbol,
            timestamp=market_data.timestamp,
            market=market_data,
            regime=context,
            positions=positions,
        )

        # Record decision at candle close for dashboard visibility
        await self._check_and_record_decision(symbol, market_data, context)

        # Entry gating (optional risk controls)
        if self._cash_in_bear and context.regime in BEAR_REGIMES:
            return None

        if self._cash_below_ema200 and market_data.ema_200 > 0:
            if market_data.close < market_data.ema_200:
                return None

        if self._loss_pause_remaining.get(symbol, 0) > 0:
            return None

        if self._cooldown_remaining.get(symbol, 0) > 0:
            return None

        if self._bull_prob_enabled:
            if self._use_rf_probability and context.rf_confidence > 0:
                bull_prob = context.rf_confidence
            else:
                bull_prob = market_data.mfi / 100.0
            if bull_prob < self._bull_prob_threshold:
                return None

        leverage = float(self.config.get("leverage", 1))
        if self._dynamic_leverage_enabled:
            if context.regime == "BULL_STRONG":
                leverage = self._leverage_bull_strong
            elif context.regime == "BULL_MODERATE":
                leverage = self._leverage_bull_moderate
            elif context.regime in ("SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN"):
                leverage = self._leverage_sideways
            else:
                leverage = self._leverage_bear
                if leverage <= 0:
                    return None

        if self._drawdown_enabled:
            drawdown_pct = await self._get_drawdown_pct()
            if drawdown_pct >= self._drawdown_warning_pct:
                leverage *= self._drawdown_leverage_reduction

        if self._prob_leverage_enabled:
            mfi = market_data.mfi
            if mfi >= 70:
                leverage = min(leverage, self._prob_leverage_max)
            elif mfi >= 60:
                leverage = min(leverage, self._prob_leverage_high)
            elif mfi >= 50:
                leverage = min(leverage, self._prob_leverage_mid)
            elif mfi >= 40:
                leverage = min(leverage, self._prob_leverage_low)
            elif mfi >= 30:
                leverage = min(leverage, self._prob_leverage_min)
            else:
                return None

        # Leverage must be >= 1 for futures; treat fractional leverage as 1x
        if 0 < leverage < 1:
            leverage = 1.0

        signal = self.entry_strategy.check_entry(ctx)

        # Emit entry evaluation event for observability
        await self._emit_entry_evaluation(market_data, context, signal)

        if signal:
            # Get quantity (risk-based or legacy)
            quantity, stop_price = await self._get_quantity(
                symbol, market_data.close, signal.quantity, context, market_data
            )

            if quantity <= 0:
                logger.debug(f"{symbol}: Quantity too small, skipping entry")
                return None

            # Portfolio risk check (if risk-based sizing enabled)
            if self._portfolio_risk_mgr and self._risk_based_sizing:
                equity = await self._get_account_equity()
                if equity <= 0:
                    logger.warning(f"{symbol}: Cannot get equity, skipping entry")
                    return None

                # Calculate proposed risk
                if stop_price and stop_price > 0:
                    stop_pct = abs(market_data.close - stop_price) / market_data.close
                else:
                    stop_pct = 0.03  # Default 3% if no stop

                proposed_risk = quantity * market_data.close * stop_pct

                risk_check = await self._portfolio_risk_mgr.can_open_trade(
                    symbol=symbol,
                    proposed_risk=proposed_risk,
                    equity=equity,
                )

                if not risk_check.allowed:
                    logger.info(
                        f"{symbol}: Entry blocked by portfolio risk - {risk_check.reason}"
                    )
                    return None

                # If correlation filter suggests reduced risk, recalculate quantity
                if risk_check.adjusted_risk_pct and self._position_sizer:
                    original_risk_pct = self.config.get("risk_per_trade_pct", 0.01)
                    reduction_factor = risk_check.adjusted_risk_pct / original_risk_pct
                    quantity = quantity * reduction_factor
                    logger.info(
                        f"{symbol}: Quantity reduced by correlation filter "
                        f"({reduction_factor:.2f}x) -> {quantity:.6f}"
                    )

            # Create order with stop_price for position tracking
            order = self._signal_to_dict(signal, quantity, leverage=leverage)

            # Include stop price for position tracking
            if stop_price and stop_price > 0:
                order["stop_price"] = stop_price

            return order

        return None

    async def evaluate_exit(self, symbol: str, position_dict: dict) -> dict[str, Any] | None:
        """Evaluate exit conditions by delegating to exit component.

        Uses TradingContextBuilder for centralized context (if available),
        which provides cached regime classification and cross-strategy positions.

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

        self._decrement_entry_blocks(symbol)

        # Record decision at candle close for dashboard visibility (with position)
        await self._check_and_record_decision(symbol, market_data)

        # Build Position model from dict
        position = self._dict_to_position(position_dict)

        # Build context locally to ensure v2 regime + RF features are applied
        context = self._build_market_context(market_data)
        positions = {self.name: position}
        if self.context_builder is not None:
            cached_ctx = self.context_builder.get_context(symbol, market_data.timestamp)
            if cached_ctx is not None:
                positions = {**cached_ctx.positions, self.name: position}

        ctx = TradingContext(
            symbol=symbol,
            timestamp=market_data.timestamp,
            market=market_data,
            regime=context,
            positions=MappingProxyType(positions),
        )

        # Drawdown-based exits (portfolio-level protection)
        if self._drawdown_enabled:
            drawdown_pct = await self._get_drawdown_pct()
            if drawdown_pct >= self._drawdown_exit_pct:
                if self._loss_pause_candles > 0:
                    self._loss_pause_remaining[symbol] = self._loss_pause_candles
                return {
                    "symbol": symbol,
                    "side": "sell",
                    "market": self.market,
                    "quantity": str(position.quantity),
                    "reason": f"DRAWDOWN_EXIT:{drawdown_pct:.1f}%>={self._drawdown_exit_pct:.1f}%",
                }

            if (
                drawdown_pct >= self._drawdown_reduce_pct
                and not self._drawdown_partial_exit_done.get(symbol, False)
            ):
                self._drawdown_partial_exit_done[symbol] = True
                exit_qty = position.quantity * 0.5
                if exit_qty > 0:
                    return {
                        "symbol": symbol,
                        "side": "sell",
                        "market": self.market,
                        "quantity": str(exit_qty),
                        "reason": f"DRAWDOWN_REDUCE:{drawdown_pct:.1f}%>={self._drawdown_reduce_pct:.1f}%",
                    }

        # V2 filter protective exit (optional)
        if self._v2_exit_on_filter and self.regime_version == "v2":
            router = self._enhanced_routers.get(symbol)
            if router is not None:
                volume_ratio = (
                    market_data.volume / market_data.avg_volume_20
                    if market_data.avg_volume_20 > 0
                    else 1.0
                )
                v2_entry_allowed = True
                if context.regime in ("BULL_STRONG", "BULL_MODERATE"):
                    if router._volume_filter.should_block(volume_ratio, context.regime):
                        v2_entry_allowed = False
                    bbw_boosted = router._volume_filter.is_boosted(volume_ratio)
                    if not bbw_boosted and router._bbw_filter.should_block():
                        v2_entry_allowed = False

                if not v2_entry_allowed:
                    return {
                        "symbol": symbol,
                        "side": "sell",
                        "market": self.market,
                        "quantity": str(position.quantity),
                        "reason": "v2_filter_protective_exit",
                    }

        # MA120 panic sell (optional)
        if self._panic_sell_below_ma120 and market_data.ema_120 > 0:
            if market_data.close < market_data.ema_120:
                return {
                    "symbol": symbol,
                    "side": "sell",
                    "market": self.market,
                    "quantity": str(position.quantity),
                    "reason": f"MA120 panic_sell: close={market_data.close:.0f} < ema120={market_data.ema_120:.0f}",
                }

        # Delegate to exit component
        # Handle both sync and async exit strategies using proper detection
        check_exit_method = self.exit_strategy.check_exit
        if asyncio.iscoroutinefunction(check_exit_method):
            signal = await check_exit_method(ctx, position)
        else:
            signal = check_exit_method(ctx, position)

        # Emit exit evaluation event for observability
        await self._emit_exit_evaluation(position, market_data, signal)

        if signal:
            reason = signal.reason or ""
            is_stop_loss = "stop loss" in reason.lower() or "stoploss" in reason.lower()
            if is_stop_loss:
                if self._cooldown_candles > 0:
                    self._cooldown_remaining[symbol] = self._cooldown_candles
                losses = self._consecutive_losses.get(symbol, 0) + 1
                if losses >= self._max_consecutive_losses:
                    if self._loss_pause_candles > 0:
                        self._loss_pause_remaining[symbol] = self._loss_pause_candles
                    losses = 0
                self._consecutive_losses[symbol] = losses
            else:
                self._consecutive_losses[symbol] = 0
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

        # Reset drawdown partial-exit tracking for this symbol
        self._drawdown_partial_exit_done[symbol] = False

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
        # Clear drawdown partial-exit tracking for this symbol
        self._drawdown_partial_exit_done.pop(symbol, None)

        on_closed_method = self.exit_strategy.on_position_closed
        if asyncio.iscoroutinefunction(on_closed_method):
            await on_closed_method(symbol)
        else:
            on_closed_method(symbol)

        logger.info(f"{symbol}: Notified exit strategy of position close")

    def _should_recalculate(self, symbol: str) -> bool:
        """Check if we should recalculate indicators for this symbol.

        Uses time-based throttling to reduce CPU usage. Indicators only need
        to be recalculated at the evaluation interval (e.g., once per minute),
        not on every price tick.

        Args:
            symbol: Trading symbol.

        Returns:
            True if indicators should be recalculated, False to use cache.
        """
        current_time = time.time()
        last_time = self._last_evaluation_time.get(symbol, 0)

        if current_time - last_time >= self.evaluation_interval:
            self._last_evaluation_time[symbol] = current_time
            return True
        return False

    def _calc_breakout_signal(self, symbol: str, df: pd.DataFrame, current_price: float) -> tuple[int, float]:
        """Calculate volatility breakout signal from history data.

        Uses Larry Williams' volatility breakout strategy:
        - target_price = today_open + (prev_day_range × k)
        - breakout_signal = 1 if close > target_price

        Args:
            symbol: Trading symbol.
            df: DataFrame with hourly OHLCV data.
            current_price: Current close price.

        Returns:
            Tuple of (breakout_signal, target_price).
        """
        try:
            if len(df) < 48:  # Need at least 2 days of hourly data
                return 0, 0.0

            # Add date column for grouping
            if 'timestamp' not in df.columns:
                return 0, 0.0

            df_copy = df.copy()
            df_copy['date'] = pd.to_datetime(df_copy['timestamp']).dt.date

            # Get unique dates
            dates = sorted(df_copy['date'].unique())
            if len(dates) < 2:
                return 0, 0.0

            today = dates[-1]
            yesterday = dates[-2]

            # Check cache
            cache_key = f"{symbol}_{yesterday}"
            cached = self._prev_day_cache.get(symbol)
            if cached and cached[2] == str(yesterday):
                prev_high, prev_low = cached[0], cached[1]
            else:
                # Calculate prev day high/low
                prev_day_df = df_copy[df_copy['date'] == yesterday]
                if prev_day_df.empty:
                    return 0, 0.0

                prev_high = float(prev_day_df['high'].max())
                prev_low = float(prev_day_df['low'].min())
                self._prev_day_cache[symbol] = (prev_high, prev_low, str(yesterday))

            # Get today's open
            today_df = df_copy[df_copy['date'] == today]
            if today_df.empty:
                return 0, 0.0

            today_open = float(today_df.iloc[0]['open'])

            # Calculate target price and signal
            prev_range = prev_high - prev_low
            target_price = today_open + (prev_range * self.breakout_k)
            breakout_signal = 1 if current_price > target_price else 0

            return breakout_signal, target_price

        except Exception as e:
            logger.debug(f"Failed to calculate breakout signal for {symbol}: {e}")
            return 0, 0.0

    def _build_market_data(self, symbol: str, force_recalculate: bool = False) -> MarketData | None:
        """Build MarketData from current indicators.

        If IndicatorService is available, uses centralized cached calculation
        shared across all strategies (75% CPU reduction).
        Otherwise, falls back to local calculation with per-strategy caching.

        Provides all indicators needed for V35 entry/exit strategies:
        - MFI, ADX, RSI for regime classification
        - MACD, MACD Signal for momentum entry/exit
        - Stochastic for conservative entry
        - High/Low/Volume for OHLCV
        - 20-period high/low for breakout/range detection
        - 20-period average volume for volume confirmation

        Args:
            symbol: Trading symbol.
            force_recalculate: Force recalculation even if within throttle interval.

        Returns:
            MarketData instance or None if indicators unavailable.
        """
        # Use shared IndicatorService if available (preferred - reduces CPU by ~75%)
        if self.indicator_service:
            buffer = self.price_buffer.get(symbol, [])
            current_price = float(buffer[-1]["price"]) if buffer else None
            # Update price buffer in service
            if buffer:
                self.indicator_service.add_price(symbol, buffer[-1])
            return self.indicator_service.get_market_data(symbol, current_price)

        # Fallback to local calculation (legacy path)
        try:
            # Check if we can use cached data
            should_recalc = force_recalculate or self._should_recalculate(symbol)

            # Get current price from buffer
            buffer = self.price_buffer.get(symbol, [])
            if buffer:
                current_price = float(buffer[-1]["price"])
                current_timestamp = int(buffer[-1].get("timestamp", 0))
            else:
                # No buffer, need history
                history = self.history.get(symbol)
                if not history:
                    return None
                current_price = float(history[-1]["close"])
                current_timestamp = 0

            # If we have cached data and shouldn't recalculate, update price and return
            cached = self._market_data_cache.get(symbol)
            if cached and not should_recalc:
                # Return cached data with updated close price for accurate P&L
                from dataclasses import replace
                return replace(cached, close=current_price, timestamp=current_timestamp)

            # Need to recalculate indicators
            history = self.history.get(symbol)
            if not history:
                return None

            # Create DF and update last row
            df = pd.DataFrame(history)

            # Update last candle with current price
            idx = df.index[-1]
            # Ensure we have required columns before updating
            if 'close' in df.columns:
                df.at[idx, "close"] = current_price
            if 'high' in df.columns:
                df.at[idx, "high"] = max(df.at[idx, "high"], current_price)
            if 'low' in df.columns:
                df.at[idx, "low"] = min(df.at[idx, "low"], current_price)

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

            # Calculate volatility breakout signal (Larry Williams strategy)
            breakout_signal, target_price = self._calc_breakout_signal(symbol, df, current_price)

            market_data = MarketData(
                symbol=symbol,
                open=float(last_row.get("open", current_price)),
                close=float(current_price),
                mfi=float(last_row.get("mfi", 50)),
                adx=float(last_row.get("adx", 20)),
                rsi=float(last_row.get("rsi", 50)),
                timestamp=current_timestamp,
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
                # EMA120 for MA120 panic sell
                ema_120=float(last_row.get("ema_120", 0)),
                # EMA200 for trend filter (bear market protection)
                ema_200=float(last_row.get("ema_200", 0)),
                # Market stress indicator (pause trading)
                market_stress=float(last_row.get("market_stress", 0)),
                # Historical reference points for breakout/range detection
                prev_high_20=prev_high_20,
                prev_low_20=prev_low_20,
                avg_volume_20=avg_volume_20,
                # 30-day high for drawdown-based BEAR detection
                high_30d=float(last_row.get("high_30d", 0)),
                # Volatility breakout (Larry Williams strategy)
                breakout_signal=breakout_signal,
                target_price=target_price,
            )

            # Cache the result
            self._market_data_cache[symbol] = market_data
            return market_data

        except Exception as e:
            logger.error(f"Failed to build MarketData for {symbol}: {e}")
        return None

    def _decrement_entry_blocks(self, symbol: str) -> None:
        """Decrement cooldown and loss pause counters for a symbol."""
        cooldown = self._cooldown_remaining.get(symbol, 0)
        if cooldown > 0:
            cooldown -= 1
            if cooldown <= 0:
                self._cooldown_remaining.pop(symbol, None)
            else:
                self._cooldown_remaining[symbol] = cooldown

        pause = self._loss_pause_remaining.get(symbol, 0)
        if pause > 0:
            pause -= 1
            if pause <= 0:
                self._loss_pause_remaining.pop(symbol, None)
            else:
                self._loss_pause_remaining[symbol] = pause

    def _get_rf_history_df(self, symbol: str) -> pd.DataFrame | None:
        """Get recent candle history for RF probability calculation."""
        if self.indicator_service is not None:
            df = self.indicator_service.get_history_df(symbol, limit=self._rf_history_size)
        else:
            history = self.history.get(symbol, [])
            if not history:
                return None
            df = pd.DataFrame(history[-self._rf_history_size:])

        if df is None or df.empty:
            return None
        return df

    def _get_rf_probability(self, symbol: str, market_data: MarketData, regime: str) -> dict[str, Any]:
        """Compute RF probability using recent candle history."""
        default_result = {
            "confidence": 0.0,
            "direction": "SIDEWAYS",
            "signal": "HOLD",
            "available": False,
        }

        if not self._use_rf_probability or self._rf_service is None or not self._rf_available:
            return default_result

        df = self._get_rf_history_df(symbol)
        if df is None or len(df) < self._rf_min_history:
            return default_result

        try:
            idx = df.index[-1]
            if "close" in df.columns:
                df.at[idx, "close"] = market_data.close
            if "high" in df.columns:
                df.at[idx, "high"] = max(df.at[idx, "high"], market_data.close)
            if "low" in df.columns:
                df.at[idx, "low"] = min(df.at[idx, "low"], market_data.close)
        except Exception:
            # Non-fatal if we can't update the last candle
            pass

        volatility = market_data.atr / market_data.close if market_data.close > 0 else 0.0
        return self._rf_service.get_probability(
            df=df,
            mfi=market_data.mfi,
            adx=market_data.adx,
            volatility=volatility,
            regime=regime,
            breakout_signal=market_data.breakout_signal,
        )

    async def _get_drawdown_pct(self) -> float:
        """Fetch portfolio drawdown percentage from Redis (cached)."""
        now = time.time()
        cache_time, cached_value = self._drawdown_cache
        if now - cache_time < self._cache_ttl:
            return cached_value

        drawdown_pct = 0.0
        try:
            state = await self.redis._client.hgetall("leverage:state")
            if state and "drawdown_pct" in state:
                drawdown_pct = float(state.get("drawdown_pct", 0.0))
            else:
                risk_state = await self.redis._client.hgetall("risk:state:daily")
                if risk_state and "current_drawdown" in risk_state:
                    drawdown_pct = float(risk_state.get("current_drawdown", 0.0))
        except Exception as e:
            logger.debug(f"Failed to read drawdown state: {e}")

        self._drawdown_cache = (now, drawdown_pct)
        return drawdown_pct

    async def _get_position(self, symbol: str) -> dict | None:
        """Get current position for symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC")

        Returns:
            Position dict or None if no position exists.
        """
        position = await self.redis.get_position(symbol, self.market)
        return position if position else None

    def _build_market_context(self, market_data: MarketData) -> MarketContext:
        """Build MarketContext from MarketData.

        Uses MFI-based trend classification and ATR-based volatility scoring.
        Includes drawdown-based BEAR detection (15% from recent high = BEAR).
        Optionally applies regime smoothing to reduce transition noise (78% reduction).

        Args:
            market_data: Current market state with indicators.

        Returns:
            MarketContext with trend and volatility analysis.
        """
        # Build base context with drawdown-based BEAR detection
        # Use 30-day high (high_30d) for drawdown calculation - better crash detection
        # Falls back to 20-period high if 30-day not available
        recent_high = market_data.high_30d if market_data.high_30d > 0 else market_data.prev_high_20
        context = build_market_context(
            mfi=market_data.mfi,
            adx=market_data.adx,
            atr=market_data.atr,
            close=market_data.close,
            volume=market_data.volume,
            avg_volume=market_data.avg_volume_20,
            recent_high=recent_high,  # Use 30-day high for drawdown BEAR detection
        )

        if self._use_rf_probability:
            rf_result = self._get_rf_probability(market_data.symbol, market_data, context.regime)
            if rf_result.get("available", False):
                context = build_market_context(
                    mfi=market_data.mfi,
                    adx=market_data.adx,
                    atr=market_data.atr,
                    close=market_data.close,
                    volume=market_data.volume,
                    avg_volume=market_data.avg_volume_20,
                    recent_high=recent_high,
                    rf_confidence=rf_result.get("confidence", 0.0),
                    rf_direction=rf_result.get("direction", "SIDEWAYS"),
                    rf_signal=rf_result.get("signal", "HOLD"),
                )

        # Apply regime filtering/smoothing based on version
        if self.regime_version == "v2" and market_data.symbol in self._enhanced_routers:
            # Enhanced regime detection v2: BBW + MTF + Volume filters
            router = self._enhanced_routers[market_data.symbol]
            volume_ratio = (
                market_data.volume / market_data.avg_volume_20
                if market_data.avg_volume_20 > 0
                else 1.0
            )
            filtered_regime = router.get_regime(
                mfi=market_data.mfi,
                adx=market_data.adx,
                bb_upper=market_data.bb_upper,
                bb_lower=market_data.bb_lower,
                bb_middle=market_data.bb_middle,
                volume_ratio=volume_ratio,
            )

            # Create new context with filtered regime
            final_regime = filtered_regime
            final_trend = context.trend

            # Preserve drawdown-based BEAR override
            if context.is_drawdown_bear and filtered_regime not in ("BEAR_STRONG", "BEAR_MODERATE"):
                final_regime = "BEAR_STRONG" if context.adx >= 25 else "BEAR_MODERATE"
                final_trend = "BEAR"

            # Determine trend from regime
            if final_regime in ("BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"):
                final_trend = "BULL"
            elif final_regime in ("BEAR_STRONG", "BEAR_MODERATE", "SIDEWAYS_DOWN"):
                final_trend = "BEAR"
            else:
                final_trend = "SIDEWAYS"

            context = MarketContext(
                trend=final_trend,
                regime=final_regime,
                volatility_score=context.volatility_score,
                is_extreme_volatility=context.is_extreme_volatility,
                adx=context.adx,
                volume_ratio=context.volume_ratio,
                is_high_volume=context.is_high_volume,
                drawdown=context.drawdown,
                is_drawdown_bear=context.is_drawdown_bear,
                rf_confidence=context.rf_confidence,
                rf_direction=context.rf_direction,
                rf_signal=context.rf_signal,
            )

        elif self.use_regime_smoothing and market_data.symbol in self._regime_smoothers:
            # v1: Original regime smoothing (EMA + persistence)
            smoother = self._regime_smoothers[market_data.symbol]
            smoothed_regime = smoother.update(market_data.mfi, market_data.adx)

            # Create new context with smoothed regime (MarketContext is frozen)
            # Preserve drawdown-based BEAR override even with smoothing
            final_regime = smoothed_regime
            final_trend = context.trend

            # If drawdown triggers BEAR, don't let smoothing override it
            if context.is_drawdown_bear and smoothed_regime not in ("BEAR_STRONG", "BEAR_MODERATE"):
                final_regime = "BEAR_STRONG" if context.adx >= 25 else "BEAR_MODERATE"
                final_trend = "BEAR"

            context = MarketContext(
                trend=final_trend,
                regime=final_regime,
                volatility_score=context.volatility_score,
                is_extreme_volatility=context.is_extreme_volatility,
                adx=context.adx,
                volume_ratio=context.volume_ratio,
                is_high_volume=context.is_high_volume,
                drawdown=context.drawdown,
                is_drawdown_bear=context.is_drawdown_bear,
                rf_confidence=context.rf_confidence,
                rf_direction=context.rf_direction,
                rf_signal=context.rf_signal,
            )

        return context

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

    def _signal_to_dict(
        self,
        signal: Signal,
        quantity: float,
        leverage: float | None = None,
    ) -> dict[str, Any]:
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
            "leverage": self.config.get("leverage", 1) if leverage is None else leverage,
        }

        if signal.trigger_price is not None:
            result["trigger_price"] = signal.trigger_price

        return result

    async def _get_quantity(
        self,
        symbol: str,
        price: float,
        default_quantity: float,
        context: MarketContext | None = None,
        market_data: MarketData | None = None,
    ) -> tuple[float, float | None]:
        """Get position quantity using risk-based or legacy sizing.

        Args:
            symbol: Trading symbol.
            price: Current price.
            default_quantity: Default quantity from signal.
            context: Market context for RF confidence.
            market_data: Market data for ATR-based stop calculation.

        Returns:
            Tuple of (quantity, stop_price). stop_price is None for legacy sizing.
        """
        # === Risk-based sizing (preferred) ===
        if self._risk_based_sizing and self._position_sizer and market_data:
            equity = await self._get_account_equity()
            if equity <= 0:
                logger.warning(f"{symbol}: Cannot get equity for risk sizing")
                return (0.0, None)

            # Get ATR for stop calculation
            atr = market_data.atr
            if atr <= 0:
                atr = price * 0.02  # Fallback: 2% of price

            leverage = int(self.config.get("leverage", 1))

            # Size position based on risk
            result = self._position_sizer.size_position(
                equity=equity,
                entry_price=price,
                atr=atr,
                symbol=symbol,
                leverage=leverage,
                direction="long",
            )

            if result.quantity == 0:
                logger.info(
                    f"{symbol}: Risk sizing rejected - {result.rejection_reason}"
                )
                return (0.0, None)

            # Calculate stop price for position tracking
            stop_price = price * (1 - result.stop_distance_pct / 100)

            logger.info(
                f"{symbol}: Risk-sized qty={result.quantity:.6f}, "
                f"risk=${result.risk_amount:.2f}, stop={result.stop_distance_pct:.1f}%"
            )

            return (result.quantity, stop_price)

        # === Legacy: Percentage-based sizing ===
        use_dynamic = self.config.get("dynamic_sizing", False)
        position_pct = float(self.config.get("position_pct", 0.02))

        if self._dynamic_position_sizing and use_dynamic and context is not None:
            rf_conf = context.rf_confidence if context.rf_confidence > 0 else 0.0
            if rf_conf >= self._position_conf_high:
                position_pct = self._position_size_high
            elif rf_conf >= self._position_conf_low:
                position_pct = self._position_size_mid
            else:
                position_pct = self._position_size_low

        if use_dynamic:
            qty = await self.get_dynamic_position_size(symbol, price, position_pct)
            return (qty, None)

        return (self.config.get("position_size", default_quantity), None)

    async def _get_account_equity(self) -> float:
        """Get current account equity from Redis.

        Returns:
            Account equity in USDT, or 0 if unavailable.
        """
        try:
            data = await self.redis._client.hgetall("account:live")
            if data:
                return float(data.get("futures_balance", 0))
            return 0.0
        except Exception as e:
            logger.warning(f"Failed to get account equity: {e}")
            return 0.0

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
        position = await self._get_position(symbol)

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

        # Get current mode from Redis
        risk_data = await self.redis._client.hgetall("risk")
        mode = risk_data.get("mode", "paper") if risk_data else "paper"

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
            "paper": "true" if mode == "paper" else "false",
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

            # Structured one-line JSON log for trade analysis
            trade_logger.decision(
                symbol=symbol,
                strategy=self.name,
                decision=decision,
                price=market_data.close,
                mfi=market_data.mfi,
                adx=market_data.adx,
                regime=regime,
                reason=reason[:100] if len(reason) > 100 else reason,
            )
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

        # Get thresholds from entry strategy params or config
        # Defaults match allocation.json defaults.market_context
        mfi_threshold = 52.0
        adx_threshold = 20.0
        volatility_threshold = 0.03
        if hasattr(self.entry_strategy, 'params'):
            params = self.entry_strategy.params
            # Use getattr with None check to avoid MagicMock issues in tests
            val = getattr(params, 'mfi_bull', None)
            if val is not None and isinstance(val, (int, float)):
                mfi_threshold = val
            val = getattr(params, 'adx_trend', None)
            if val is not None and isinstance(val, (int, float)):
                adx_threshold = val
            val = getattr(params, 'volatility_threshold', None)
            if val is not None and isinstance(val, (int, float)):
                volatility_threshold = val

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
    indicator_service: IndicatorService | None = None,
    context_builder: TradingContextBuilder | None = None,
    regime_version: str = "v1",
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
        indicator_service: Shared indicator service for CPU optimization.
        context_builder: Shared context builder for TradingContext.
        regime_version: Regime detection version ("v1" or "v2" enhanced).

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
        indicator_service=indicator_service,
        context_builder=context_builder,
        regime_version=regime_version,
    )

    # Initialize persistent exit strategy state
    if hasattr(exit_strategy, 'load_state'):
        await exit_strategy.load_state(symbols)
        logger.info(f"{name}: Loaded persistent state for {symbols}")

    return task
