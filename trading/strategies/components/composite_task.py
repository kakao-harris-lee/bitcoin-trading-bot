"""Composite Strategy Task - assembles Entry/Exit components into a runnable task.

This is the bridge between the component-based strategy architecture and the
stream-based task system. It extends BaseStrategyTask and delegates entry/exit
logic to IEntryStrategy and IExitStrategy components.

Usage:
    entry = LLMDecisionEntryStrategy(params)
    exit_strat = LLMHybridExitStrategy(params)

    task = CompositeStrategyTask(
        name="llm_direction_btc",
        symbols=["BTC"],
        redis=redis,
        entry_strategy=entry,
        exit_strategy=exit_strat,
    )

    await task.run()
"""

# pylint: disable=logging-fstring-interpolation,protected-access,broad-exception-caught,attribute-defined-outside-init

from __future__ import annotations

import asyncio
from collections import deque
import json
import logging
import time
from dataclasses import replace
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
    BEAR_REGIMES,
)
from .regime_filter import EnhancedRegimeRouter, MTFCandle
from .symbol_selector import DynamicSymbolSelector, SymbolSelectorConfig
from trading.observability.structured_logger import trade_logger
from trading.risk.position_sizer import PositionSizer, RiskSizingConfig
from trading.risk.portfolio_risk_manager import PortfolioRiskManager, RiskCapConfig
from trading.risk.correlation_filter import CorrelationFilter, CorrelationConfig
from trading.regime.runtime import RuntimeRegimeOverlay, RuntimeRegimePrediction
from trading.utils.precision import PriceUtils, get_symbol_info

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
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
        market: str = "spot",
        buffer_size: int = 500,
        use_smart_exit: bool = False,
        config: dict | None = None,
        emit_events: bool = False,
        indicator_service: IndicatorService | None = None,
        context_builder: TradingContextBuilder | None = None,
        regime_version: str = "v2",
    ):
        """Initialize composite strategy task.

        Args:
            name: Strategy name (e.g., "llm_direction_btc").
            symbols: List of symbols to trade.
            redis: Redis streams client.
            entry_strategy: Entry component implementing IEntryStrategy.
            exit_strategy: Exit component implementing IExitStrategy.
            market: Market type ("spot").
            buffer_size: Price buffer size.
            use_smart_exit: Use smart exit stream.
            config: Additional configuration.
            emit_events: Whether to emit observability events to Redis streams.
            indicator_service: Shared indicator calculation service (reduces CPU).
            context_builder: Shared context builder for TradingContext.
            regime_version: Regime detection version ("v2" enhanced).
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
        self._init_eventing(emit_events, redis)
        self._init_shared_services(indicator_service, context_builder)
        self._init_evaluation_config()
        self._init_regime_detectors(symbols, regime_version)
        self._init_runtime_regime_overlay()
        self._init_entry_and_leverage_controls()
        self._init_drawdown_and_breakout_controls()
        self._init_risk_controls(redis)
        self._init_volatility_sizing()
        self._init_symbol_selector()
        self._init_data_quality_controls()

    def _init_eventing(self, emit_events: bool, redis: RedisStreams) -> None:
        self.emit_events = emit_events
        self.event_emitter: EventEmitter | None = None
        if not emit_events:
            return
        from trading.core.event_emitter import EventEmitter

        self.event_emitter = EventEmitter(redis=redis, enabled=True)

    def _init_shared_services(
        self,
        indicator_service: IndicatorService | None,
        context_builder: TradingContextBuilder | None,
    ) -> None:
        self.indicator_service = indicator_service
        self.context_builder = context_builder

    def _init_evaluation_config(self) -> None:
        self.evaluation_interval = self.config.get("evaluation_interval_seconds", 60)
        self._last_evaluation_time: dict[str, float] = {}
        self._market_data_cache: dict[str, MarketData] = {}
        self._entry_on_candle_close = self.config.get("entry_on_candle_close", True)
        self._entry_eval_fallback_seconds = float(
            self.config.get("entry_evaluation_interval_seconds", self.evaluation_interval)
        )
        self._last_entry_candle_ts: dict[str, int] = {}
        self._last_entry_gate_reason: dict[str, str] = {}
        self._entry_decision_hint: dict[str, dict[str, Any]] = {}
        self._last_entry_order_build_reason: dict[str, str] = {}
        self._pending_entry_funnel_payload: dict[str, dict[str, Any]] = {}
        self._entry_decision_hint_ttl_seconds = max(
            120.0,
            self._entry_eval_fallback_seconds * 2.0,
        )
        self._regime_snapshot_interval_seconds = float(
            self.config.get("regime_snapshot_interval_seconds", 60)
        )
        self._last_regime_snapshot_time: dict[str, float] = {}

    def _init_regime_detectors(self, symbols: list[str], regime_version: str) -> None:
        self.regime_version = regime_version
        self._enhanced_routers: dict[str, EnhancedRegimeRouter] = {}
        self._init_enhanced_routers(symbols)
        logger.info(f"{self.name} using enhanced regime detection v2")

    def _init_runtime_regime_overlay(self) -> None:
        overlay_cfg = self.config.get("regime_runtime_overlay", {})
        self._runtime_regime_overlay = RuntimeRegimeOverlay(overlay_cfg)
        self._runtime_regime_cache: dict[str, dict[str, Any]] = {}

    def _init_enhanced_routers(self, symbols: list[str]) -> None:
        bbw_block = self.config.get("bbw_block_threshold", 25)
        bbw_confirm = self.config.get("bbw_confirm_threshold", 50)
        volume_block = self.config.get("volume_block_ratio", 0.8)
        volume_boost = self.config.get("volume_boost_ratio", 1.2)
        mtf_enabled = self.config.get("mtf_enabled", True)
        bbw_enabled = self.config.get("bbw_enabled", True)
        volume_filter_enabled = self.config.get("volume_filter_enabled", True)
        mtf_candles_per_period = self.config.get("mtf_candles_per_period")
        if mtf_candles_per_period is None:
            interval = self._resolve_warmup_interval()
            if interval == "4h":
                mtf_candles_per_period = 6  # 4h x 6 = 1 day
            elif interval == "1h":
                mtf_candles_per_period = 4  # 1h x 4 = 4h
            else:
                mtf_candles_per_period = 4
        for symbol in symbols:
            self._enhanced_routers[symbol] = EnhancedRegimeRouter(
                bbw_block_threshold=bbw_block,
                bbw_confirm_threshold=bbw_confirm,
                volume_block_ratio=volume_block,
                volume_boost_ratio=volume_boost,
                mtf_enabled=mtf_enabled,
                bbw_enabled=bbw_enabled,
                volume_filter_enabled=volume_filter_enabled,
                mtf_candles_per_period=mtf_candles_per_period,
            )

    def _resolve_config_param(
        self,
        key: str,
        default: Any,
        include_exit: bool = True,
    ) -> Any:
        value = self.config.get(key)
        if value is not None:
            return value

        entry_params = self.config.get("entry", {}).get("params", {})
        value = entry_params.get(key)
        if value is not None:
            return value

        if include_exit:
            exit_params = self.config.get("exit", {}).get("params", {})
            value = exit_params.get(key)
            if value is not None:
                return value

        return default

    def _init_entry_and_leverage_controls(self) -> None:
        self._regime_thresholds = self._load_regime_thresholds()
        self._cash_in_bear = self.config.get("cash_in_bear", False)
        self._cash_below_ema200 = self.config.get("cash_below_ema200", False)
        self._exit_on_bear_regime = bool(self.config.get("exit_on_bear_regime", False))
        self._cooldown_candles = int(self.config.get("stop_loss_cooldown", 24))
        self._cooldown_remaining: dict[str, int] = {}
        self._max_consecutive_losses = int(self.config.get("max_consecutive_losses", 3))
        self._consecutive_losses: dict[str, int] = {}
        self._loss_pause_candles = int(self.config.get("loss_pause_candles", 48))
        self._loss_pause_remaining: dict[str, int] = {}
        self._v2_exit_on_filter = self.config.get("v2_exit_on_filter", False)
        self._panic_sell_below_ma120 = self.config.get("panic_sell_below_ma120", False)
        self._drawdown_bear_threshold = float(self.config.get("drawdown_bear_threshold", 0.15))

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

    def _load_regime_thresholds(self) -> dict[str, float]:
        thresholds = self.config.get("regime_thresholds", {})
        if not isinstance(thresholds, dict):
            return {}
        normalized: dict[str, float] = {}
        for key, value in thresholds.items():
            try:
                normalized[str(key)] = float(value)
            except (TypeError, ValueError):
                continue
        return normalized

    def _init_drawdown_and_breakout_controls(self) -> None:
        self._drawdown_enabled = self.config.get("drawdown_enabled", False)
        self._drawdown_warning_pct = float(self.config.get("drawdown_warning_pct", 8.0))
        self._drawdown_reduce_pct = float(self.config.get("drawdown_reduce_pct", 10.0))
        self._drawdown_exit_pct = float(self.config.get("drawdown_exit_pct", 12.0))
        self._drawdown_leverage_reduction = float(self.config.get("drawdown_leverage_reduction", 0.5))
        self._drawdown_partial_exit_done: dict[str, bool] = {}
        self._drawdown_cache: tuple[float, float] = (0.0, 0.0)
        self.breakout_k = self.config.get("breakout_k", 0.5)
        self._prev_day_cache: dict[str, tuple[float, float, str]] = {}

    def _init_risk_controls(self, redis: RedisStreams) -> None:
        self._risk_based_sizing = self.config.get("risk_based_sizing", False)
        self._position_sizer: PositionSizer | None = None
        self._portfolio_risk_mgr: PortfolioRiskManager | None = None
        self._correlation_filter: CorrelationFilter | None = None
        self._context_risk_enabled = self.config.get("context_risk_enabled", True)
        self._context_max_open_positions = int(
            self.config.get("context_max_open_positions", self.config.get("max_open_positions", 5))
        )
        self._context_max_symbol_positions = int(self.config.get("context_max_symbol_positions", 1))
        self._context_max_total_exposure_pct = float(self.config.get("context_max_total_exposure_pct", 1.0))
        self._context_max_symbol_exposure_pct = float(self.config.get("context_max_symbol_exposure_pct", 0.5))
        self._context_corr_enabled = bool(
            self.config.get("context_corr_enabled", self.config.get("correlation_filter", True))
        )
        if self._context_corr_enabled and self.config.get("correlation_filter", True):
            corr_config = CorrelationConfig.from_dict(self.config)
            self._correlation_filter = CorrelationFilter(corr_config, redis)
        if self._risk_based_sizing:
            self._init_risk_based_sizing(redis)

    def _init_risk_based_sizing(self, redis: RedisStreams) -> None:
        sizing_config = RiskSizingConfig.from_dict(self.config)
        self._position_sizer = PositionSizer(sizing_config)
        risk_cap_config = RiskCapConfig.from_dict(self.config)
        global_symbols = self.config.get("_global_symbols", ["BTC", "ETH", "SOL", "BNB"])
        self._portfolio_risk_mgr = PortfolioRiskManager(
            risk_cap_config,
            redis,
            self._correlation_filter,
            symbols=global_symbols,
        )
        logger.info(
            f"{self.name}: Risk-based sizing enabled "
            f"(risk={sizing_config.risk_per_trade_pct*100:.1f}%, "
            f"max_total={risk_cap_config.max_total_risk_pct*100:.1f}%)"
        )

    def _init_volatility_sizing(self) -> None:
        vol_cfg = self.config.get("volatility_sizing", {})
        self._vol_sizing_enabled = vol_cfg.get("enabled", False)
        self._vol_target = vol_cfg.get("target_vol", 0.02)
        self._vol_min_scale = vol_cfg.get("min_scale", 0.25)
        self._vol_max_scale = vol_cfg.get("max_scale", 1.0)

    def _init_symbol_selector(self) -> None:
        raw_selector_cfg = self.config.get("symbol_selector") or {}
        selector_cfg = SymbolSelectorConfig.from_dict(raw_selector_cfg)
        self._selector_event_maxlen = max(
            2000,
            int((raw_selector_cfg if isinstance(raw_selector_cfg, dict) else {}).get("event_maxlen", 50000) or 50000),
        )
        self._symbol_selector = DynamicSymbolSelector(
            config=selector_cfg,
            fallback_symbols=sorted(self.symbols),
        )
        self._selector_market_data: dict[str, MarketData] = {}
        self._selector_context: dict[str, MarketContext] = {}

    def _init_data_quality_controls(self) -> None:
        dq_cfg = self.config.get("data_quality", {})
        self._dq_enabled = bool(dq_cfg.get("enabled", False))
        self._dq_started_at = time.time()
        self._dq_startup_grace_seconds = max(
            0.0,
            float(dq_cfg.get("startup_grace_seconds", 0.0) or 0.0),
        )
        self._dq_max_price_age_seconds = max(
            0.0,
            float(dq_cfg.get("max_price_age_seconds", 0.0) or 0.0),
        )
        self._dq_min_ticks_per_minute = max(
            0.0,
            float(dq_cfg.get("min_ticks_per_minute", 0.0) or 0.0),
        )
        self._dq_tick_window_seconds = max(
            30.0,
            float(dq_cfg.get("tick_window_seconds", 300.0) or 300.0),
        )
        self._dq_eviction_cooldown_seconds = max(
            10.0,
            float(dq_cfg.get("eviction_cooldown_seconds", 900.0) or 900.0),
        )
        self._dq_cooldown_on_low_tick_rate = bool(
            dq_cfg.get("cooldown_on_low_tick_rate", False)
        )
        self._dq_tier_thresholds = {
            "high": max(
                0.0,
                float((dq_cfg.get("tier_thresholds", {}) or {}).get("high", 24.0) or 24.0),
            ),
            "medium": max(
                0.0,
                float((dq_cfg.get("tier_thresholds", {}) or {}).get("medium", 12.0) or 12.0),
            ),
        }
        if self._dq_tier_thresholds["high"] < self._dq_tier_thresholds["medium"]:
            self._dq_tier_thresholds["high"] = self._dq_tier_thresholds["medium"]

        tier_scale_cfg = dq_cfg.get("tier_position_scale", {}) or {}
        self._dq_position_scales = {
            "high": max(
                0.0,
                min(
                    1.0,
                    float(tier_scale_cfg.get("high", 1.0) or 1.0),
                ),
            ),
            "medium": max(
                0.0,
                min(
                    1.0,
                    float(tier_scale_cfg.get("medium", 0.75) or 0.75),
                ),
            ),
            "low": max(
                0.0,
                min(
                    1.0,
                    float(tier_scale_cfg.get("low", 0.45) or 0.45),
                ),
            ),
        }
        self._dq_tick_times: dict[str, deque[float]] = {}
        self._dq_blocked_until: dict[str, float] = {}
        self._dq_entry_assessment: dict[str, dict[str, Any]] = {}

    async def run(self) -> None:
        """Main loop: warm-up then consume."""
        logger.info(f"Warming up composite strategy {self.name}...")

        interval = self._resolve_warmup_interval()

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

    def _resolve_warmup_interval(self) -> str:
        """Resolve warm-up candle interval for this strategy.

        Priority:
        1. Explicit strategy config (`warmup_interval`)
        2. Explicit timeframe hint (`timeframe`)
        3. Strategy-name fallback heuristic
        """
        configured = self.config.get("warmup_interval")
        if isinstance(configured, str) and configured.strip():
            return configured.strip()

        timeframe = str(self.config.get("timeframe", "")).strip().lower()
        if timeframe in {"minute240", "4h", "240m"}:
            return "4h"
        if timeframe in {"minute60", "1h", "60m"}:
            return "1h"
        if timeframe in {"day", "1d", "daily"}:
            return "1d"

        name_lower = self.name.lower()
        if name_lower.startswith("llm_direction") or "short" in name_lower or "h4" in name_lower:
            return "4h"
        return "1d"

    def _update_buffer(self, symbol: str, msg: dict[str, Any]) -> None:
        """Update local buffer and shared indicator service tick stream."""
        super()._update_buffer(symbol, msg)
        if self.indicator_service is not None and msg.get("warmup") != "true":
            self.indicator_service.add_price(symbol, msg)
        if msg.get("warmup") != "true":
            self._record_data_quality_tick(symbol, msg)

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        """Handle message and keep monitoring state fresh outside entry gates.

        BaseStrategyTask throttles entry/exit evaluation by candle-close/time
        interval. Dashboard regime status and selector snapshots are decoupled so
        visibility stays fresh even when trading evaluation is intentionally skipped.
        """
        await super()._handle_message(msg)
        await self._post_message_monitoring_refresh(msg)

    async def _publish_order(self, signal: dict[str, Any]) -> None:
        """Publish order and mirror selector-to-order funnel attribution."""
        await super()._publish_order(signal)
        symbol = str(signal.get("symbol", ""))
        payload = self._pending_entry_funnel_payload.pop(symbol, None)
        if not payload:
            return
        await self._emit_entry_funnel_event(
            symbol=symbol,
            context=payload["context"],
            dq_assessment=payload.get("dq_assessment"),
            gate_passed=True,
            gate_reason="passed",
            leverage_allowed=True,
            leverage_reason="passed",
            entry_signal_generated=True,
            entry_route=str(payload.get("entry_route", "")),
            entry_rejection_reason="",
            order_build_result="built",
            order_drop_reason="",
            order_published=True,
        )

    def _is_regime_snapshot_due(self, symbol: str, now: float | None = None) -> bool:
        interval = self._regime_snapshot_interval_seconds
        if interval <= 0:
            return True
        current_time = time.time() if now is None else now
        last_snapshot = self._last_regime_snapshot_time.get(symbol, 0.0)
        return (current_time - last_snapshot) >= interval

    async def _post_message_monitoring_refresh(self, msg: dict[str, Any]) -> None:
        if msg.get("warmup") == "true":
            return

        symbol = msg.get("symbol")
        if symbol not in self.symbols:
            return

        now = time.time()
        snapshot_due = self._is_regime_snapshot_due(symbol, now=now)
        selector_due = self._symbol_selector.enabled and self._symbol_selector.should_refresh(now)
        if not snapshot_due and not selector_due:
            return

        market_data = self._build_market_data(symbol)
        if market_data is None:
            return
        context = self._build_market_context(market_data)

        if snapshot_due:
            await self._update_regime_snapshot(symbol, market_data, context)

        if not selector_due:
            return
        self._update_symbol_selector_inputs(symbol, market_data, context)
        await self._refresh_symbol_selector_if_due()

    def _should_evaluate_entry(self, symbol: str, msg: dict[str, Any]) -> bool:
        """Evaluate entry at candle close when enabled, else fallback interval."""
        if self._entry_on_candle_close and self.indicator_service is not None:
            candle_ts = self.indicator_service.get_latest_candle_timestamp(symbol)
            if candle_ts is None:
                return False
            previous_ts = self._last_entry_candle_ts.get(symbol)
            if previous_ts == candle_ts:
                return False
            self._last_entry_candle_ts[symbol] = int(candle_ts)
            self._last_entry_evaluation_time[symbol] = time.time()
            return True

        current_time = time.time()
        last_time = self._last_entry_evaluation_time.get(symbol, 0)
        if current_time - last_time >= self._entry_eval_fallback_seconds:
            self._last_entry_evaluation_time[symbol] = current_time
            return True
        return False

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

        if self.context_builder is not None:
            await self.context_builder.refresh_positions(symbols=self.symbols)

        await self._refresh_indicator_history(symbol)

        # Build MarketData from indicators
        market_data = self._build_market_data(symbol)
        if market_data is None:
            return None

        context, ctx = self._build_entry_context(symbol, market_data)
        await self._prepare_entry_strategy(ctx)
        self._update_symbol_selector_inputs(symbol, market_data, context)
        await self._refresh_symbol_selector_if_due()

        # Keep dashboard regime status fresh even between hourly decision records.
        await self._update_regime_snapshot(symbol, market_data, context)

        dq_assessment = self._dq_entry_assessment.get(symbol)

        if not self._passes_entry_gates(symbol, market_data, context):
            dq_assessment = self._dq_entry_assessment.get(symbol) or dq_assessment
            gate_reason = self._last_entry_gate_reason.get(symbol, "Entry blocked by gates")
            self._update_entry_decision_hint(symbol, should_enter=False, reason=gate_reason)
            await self._check_and_record_decision(symbol, market_data, context)
            await self._emit_entry_funnel_event(
                symbol=symbol,
                context=context,
                dq_assessment=dq_assessment,
                gate_passed=False,
                gate_reason=gate_reason,
                leverage_allowed=False,
                leverage_reason="not_evaluated",
                entry_signal_generated=False,
                entry_route="",
                entry_rejection_reason=gate_reason,
                order_build_result="not_attempted",
                order_drop_reason="",
                order_published=False,
            )
            return None

        leverage = await self._resolve_entry_leverage(context, market_data)
        if leverage is None:
            dq_assessment = self._dq_entry_assessment.get(symbol) or dq_assessment
            leverage_reason = "Entry blocked: leverage or regime leverage policy"
            self._update_entry_decision_hint(
                symbol,
                should_enter=False,
                reason=leverage_reason,
            )
            await self._check_and_record_decision(symbol, market_data, context)
            await self._emit_entry_funnel_event(
                symbol=symbol,
                context=context,
                dq_assessment=dq_assessment,
                gate_passed=True,
                gate_reason="passed",
                leverage_allowed=False,
                leverage_reason=leverage_reason,
                entry_signal_generated=False,
                entry_route="",
                entry_rejection_reason=leverage_reason,
                order_build_result="not_attempted",
                order_drop_reason="",
                order_published=False,
            )
            return None

        signal = self.entry_strategy.check_entry(ctx)
        no_signal_reason = ""
        if signal is None:
            no_signal_reason = self._resolve_entry_rejection_reason(symbol)
            self._update_entry_decision_hint(symbol, should_enter=False, reason=no_signal_reason)
        else:
            self._update_entry_decision_hint(symbol, should_enter=True, reason=signal.reason)

        # Emit entry evaluation event for observability
        await self._emit_entry_evaluation(
            market_data,
            context,
            signal,
            no_signal_reason=no_signal_reason,
        )

        # Record decision at candle close for dashboard visibility
        await self._check_and_record_decision(symbol, market_data, context)

        if not signal:
            dq_assessment = self._dq_entry_assessment.get(symbol) or dq_assessment
            await self._emit_entry_funnel_event(
                symbol=symbol,
                context=context,
                dq_assessment=dq_assessment,
                gate_passed=True,
                gate_reason="passed",
                leverage_allowed=True,
                leverage_reason="passed",
                entry_signal_generated=False,
                entry_route="",
                entry_rejection_reason=no_signal_reason or "No entry signal",
                order_build_result="not_attempted",
                order_drop_reason="",
                order_published=False,
            )
            return None

        self._last_entry_order_build_reason.pop(symbol, None)
        order = await self._build_entry_order(
            symbol=symbol,
            signal=signal,
            market_data=market_data,
            context=context,
            leverage=leverage,
        )
        dq_assessment = self._dq_entry_assessment.get(symbol) or dq_assessment
        if order is None:
            order_drop_reason = self._last_entry_order_build_reason.pop(symbol, "unknown")
            await self._emit_entry_funnel_event(
                symbol=symbol,
                context=context,
                dq_assessment=dq_assessment,
                gate_passed=True,
                gate_reason="passed",
                leverage_allowed=True,
                leverage_reason="passed",
                entry_signal_generated=True,
                entry_route=self._entry_route_from_reason(signal.reason),
                entry_rejection_reason="",
                order_build_result="dropped",
                order_drop_reason=order_drop_reason,
                order_published=False,
            )
            return None

        self._pending_entry_funnel_payload[symbol] = {
            "context": context,
            "dq_assessment": dq_assessment or {},
            "entry_route": self._entry_route_from_reason(signal.reason),
        }
        return order

    async def evaluate_exit(self, symbol: str, position: dict) -> dict[str, Any] | None:
        """Evaluate exit conditions by delegating to exit component.

        Uses TradingContextBuilder for centralized context (if available),
        which provides cached regime classification and cross-strategy positions.

        Args:
            symbol: Trading symbol.
            position: Position dict from Redis.

        Returns:
            Order intent dict or None.
        """
        await self._refresh_indicator_history(symbol)

        if self.context_builder is not None:
            await self.context_builder.refresh_positions(symbols=self.symbols)

        # Build MarketData from indicators
        market_data = self._build_market_data(symbol)
        if market_data is None:
            return None

        self._decrement_entry_blocks(symbol)

        # Build Position model from dict
        position = self._dict_to_position(position)

        context, ctx = self._build_exit_context(symbol, position, market_data)
        self._update_symbol_selector_inputs(symbol, market_data, context)
        await self._refresh_symbol_selector_if_due()

        # Keep dashboard regime status fresh even between hourly decision records.
        await self._update_regime_snapshot(symbol, market_data, context)

        # Record decision at candle close for dashboard visibility (with position)
        await self._check_and_record_decision(symbol, market_data, context)

        protective_exit = await self._check_protective_exit_conditions(
            symbol=symbol,
            position=position,
            market_data=market_data,
            context=context,
        )
        if protective_exit:
            return protective_exit

        signal = await self._evaluate_exit_signal(ctx, position)

        # Emit exit evaluation event for observability
        await self._emit_exit_evaluation(position, market_data, signal)

        if not signal:
            return None

        exit_quantity = self._resolve_exit_order_quantity(position=position, signal=signal)
        if exit_quantity <= 0:
            logger.warning(
                "%s: Skip exit order due to non-positive resolved qty "
                "(signal_qty=%s, position_qty=%.8f, reason=%s)",
                symbol,
                signal.quantity,
                position.quantity,
                signal.reason,
            )
            return None

        self._update_exit_loss_tracking(symbol, signal)
        order = self._signal_to_dict(signal, exit_quantity)
        try:
            order_qty = float(order.get("quantity", 0.0))
        except (TypeError, ValueError):
            order_qty = 0.0
        if order_qty <= 0.0:
            logger.info(
                "%s: Skip exit order after lot-size rounding "
                "(resolved_qty=%.12f, order_qty=%s, reason=%s)",
                symbol,
                exit_quantity,
                order.get("quantity"),
                signal.reason,
            )
            return None
        return order

    async def _refresh_indicator_history(self, symbol: str) -> None:
        if self.indicator_service and self.indicator_service.needs_refresh(symbol):
            try:
                market = self.config.get("market", "spot") if self.config else "spot"
                await self.indicator_service.refresh_history(symbol, market=market)
            except Exception as e:
                logger.warning(f"Candle refresh failed for {symbol}: {e}")

    def _build_entry_context(
        self,
        symbol: str,
        market_data: MarketData,
    ) -> tuple[MarketContext, TradingContext]:
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
        return context, ctx

    async def _prepare_entry_strategy(self, ctx: TradingContext) -> None:
        prepare_async = getattr(self.entry_strategy, "prepare_entry_decision_async", None)
        if not callable(prepare_async):
            return

        history_df = self._get_history_df(ctx.market.symbol)
        if history_df is not None:
            history_df = history_df.copy()
            self._update_latest_history_candle(history_df, ctx.market)

        try:
            await prepare_async(ctx, history_df)
        except Exception as e:
            logger.warning("%s: entry decision preparation failed: %s", self.name, e)

    def _update_symbol_selector_inputs(
        self,
        symbol: str,
        market_data: MarketData,
        context: MarketContext,
    ) -> None:
        if not self._symbol_selector.enabled:
            return
        self._selector_market_data[symbol] = market_data
        self._selector_context[symbol] = context

    async def _refresh_symbol_selector_if_due(self) -> None:
        if not self._symbol_selector.enabled:
            return
        now = time.time()
        if not self._symbol_selector.should_refresh(now):
            return

        self._hydrate_symbol_selector_inputs()
        changed = self._symbol_selector.refresh(
            now=now,
            symbols=sorted(self.symbols),
            market_data=self._selector_market_data,
            contexts=self._selector_context,
        )
        if changed:
            selected = sorted(self._symbol_selector.selected_symbols)
            ranking = ", ".join(
                f"{row.symbol}:{row.score:.3f}" for row in self._symbol_selector.ranking[:5]
            )
            logger.debug(
                "%s: symbol selector updated selected=%s ranking=[%s]",
                self.name,
                selected,
                ranking,
            )
        await self._persist_symbol_selector_state(changed=changed)

    async def _persist_symbol_selector_state(self, changed: bool) -> None:
        selected = sorted(self._symbol_selector.selected_symbols)
        evaluations = self._symbol_selector.evaluations
        ranked = self._symbol_selector.ranking
        signal_events = self._symbol_selector.signal_events
        top_scores = [
            {
                "symbol": row.symbol,
                "score": round(float(row.score), 6),
                "regime": row.regime,
                "ignition": round(float(row.ignition_score), 6),
                "breakout_ratio": round(float(row.breakout_ratio), 6),
                "volume_ratio": round(float(row.volume_burst), 6),
                "compression": round(float(row.compression_score), 6),
            }
            for row in ranked[:5]
        ]
        signal_event_payload = [
            {
                "type": row.event_type,
                "symbol": row.symbol,
                "score": round(float(row.score), 6),
                "reason": row.reason,
                "delta": round(float(row.delta), 6),
            }
            for row in signal_events
        ]
        rejected = [
            {
                "symbol": row.symbol,
                "reason": row.reason,
                "regime": row.regime,
            }
            for row in evaluations
            if not row.eligible
        ]
        rejection_counts: dict[str, int] = {}
        for row in evaluations:
            if row.eligible:
                continue
            rejection_counts[row.reason] = rejection_counts.get(row.reason, 0) + 1

        data_quality_summary = self._build_data_quality_summary()

        payload = {
            "timestamp": datetime.now().isoformat(),
            "strategy": self.name,
            "market": self.market,
            "changed": "true" if changed else "false",
            "selected_symbols": json.dumps(selected),
            "top_scores": json.dumps(top_scores),
            "signal_events": json.dumps(signal_event_payload),
            "rejected": json.dumps(rejected[:20]),
            "rejection_counts": json.dumps(rejection_counts),
            "universe_size": str(len(self.symbols)),
            "selected_count": str(len(selected)),
            "data_quality": json.dumps(data_quality_summary),
            "dq_blocked_count": str(int(data_quality_summary.get("blocked_count", 0))),
            "dq_enabled": "true" if self._dq_enabled else "false",
        }
        try:
            await self.redis.publish_event(
                "strategy:selector:events",
                payload,
                maxlen=self._selector_event_maxlen,
            )
            await self.redis.set_selector_snapshot(self.name, payload)
        except Exception as e:
            logger.debug("%s: failed to persist symbol selector state: %s", self.name, e)

    def _hydrate_symbol_selector_inputs(self) -> None:
        for symbol in self.symbols:
            market_data = self._selector_market_data.get(symbol)
            if market_data is None:
                market_data = self._build_market_data(symbol)
                if market_data is None:
                    continue
                self._selector_market_data[symbol] = market_data

            if symbol not in self._selector_context:
                self._selector_context[symbol] = self._build_market_context(market_data)

    def _record_data_quality_tick(self, symbol: str, msg: dict[str, Any]) -> None:
        if not self._dq_enabled:
            return
        raw_ts = msg.get("timestamp")
        tick_ts = 0.0
        try:
            if raw_ts is not None:
                tick_ts = float(raw_ts) / 1000.0
        except (TypeError, ValueError):
            tick_ts = 0.0
        if tick_ts <= 0:
            tick_ts = time.time()

        ticks = self._dq_tick_times.setdefault(symbol, deque())
        ticks.append(tick_ts)
        cutoff = tick_ts - self._dq_tick_window_seconds
        while ticks and ticks[0] < cutoff:
            ticks.popleft()

    def _assess_data_quality(
        self,
        symbol: str,
        market_data: MarketData,
        *,
        mutate: bool = True,
    ) -> dict[str, Any]:
        if not self._dq_enabled:
            return {
                "allowed": True,
                "reason": "disabled",
                "price_age_seconds": 0.0,
                "ticks_per_minute": 0.0,
                "tier": "high",
                "position_scale": 1.0,
            }

        now = time.time()
        startup_grace_remaining = self._dq_startup_grace_remaining(now)
        if startup_grace_remaining > 0:
            return {
                "allowed": False,
                "reason": "startup_warmup",
                "price_age_seconds": round(self._price_age_seconds(market_data.timestamp, now), 3),
                "ticks_per_minute": round(self._ticks_per_minute(symbol, now), 3),
                "tier": "low",
                "position_scale": self._dq_position_scales["low"],
                "startup_grace_remaining_seconds": round(startup_grace_remaining, 2),
            }

        price_age_seconds = self._price_age_seconds(market_data.timestamp, now)
        ticks_per_minute = self._ticks_per_minute(symbol, now)
        blocked_until = self._dq_blocked_until.get(symbol, 0.0)
        if blocked_until > now:
            stale_ok = (
                self._dq_max_price_age_seconds <= 0
                or price_age_seconds <= self._dq_max_price_age_seconds
            )
            ticks_ok = (
                self._dq_min_ticks_per_minute <= 0
                or ticks_per_minute >= self._dq_min_ticks_per_minute
            )
            if stale_ok and ticks_ok:
                if mutate:
                    self._dq_blocked_until.pop(symbol, None)
            else:
                return {
                    "allowed": False,
                    "reason": "cooldown_block",
                    "price_age_seconds": round(price_age_seconds, 3),
                    "ticks_per_minute": round(ticks_per_minute, 3),
                    "tier": "low",
                    "position_scale": self._dq_position_scales["low"],
                    "blocked_for_seconds": round(blocked_until - now, 2),
                }

        if (
            self._dq_max_price_age_seconds > 0
            and price_age_seconds > self._dq_max_price_age_seconds
        ):
            if mutate:
                self._dq_blocked_until[symbol] = now + self._dq_eviction_cooldown_seconds
            return {
                "allowed": False,
                "reason": "stale_price",
                "price_age_seconds": round(price_age_seconds, 3),
                "ticks_per_minute": round(ticks_per_minute, 3),
                "tier": "low",
                "position_scale": self._dq_position_scales["low"],
            }

        if (
            self._dq_min_ticks_per_minute > 0
            and ticks_per_minute < self._dq_min_ticks_per_minute
        ):
            if mutate and self._dq_cooldown_on_low_tick_rate:
                self._dq_blocked_until[symbol] = now + self._dq_eviction_cooldown_seconds
            return {
                "allowed": False,
                "reason": "low_tick_rate",
                "price_age_seconds": round(price_age_seconds, 3),
                "ticks_per_minute": round(ticks_per_minute, 3),
                "tier": "low",
                "position_scale": self._dq_position_scales["low"],
            }

        tier = "high"
        if ticks_per_minute < self._dq_tier_thresholds["medium"]:
            tier = "low"
        elif ticks_per_minute < self._dq_tier_thresholds["high"]:
            tier = "medium"

        return {
            "allowed": True,
            "reason": "ok",
            "price_age_seconds": round(price_age_seconds, 3),
            "ticks_per_minute": round(ticks_per_minute, 3),
            "tier": tier,
            "position_scale": self._dq_position_scales[tier],
        }

    def _ticks_per_minute(self, symbol: str, now: float | None = None) -> float:
        if not self._dq_enabled:
            return 0.0
        timestamp_now = now if now is not None else time.time()
        ticks = self._dq_tick_times.setdefault(symbol, deque())
        cutoff = timestamp_now - self._dq_tick_window_seconds
        while ticks and ticks[0] < cutoff:
            ticks.popleft()
        if self._dq_tick_window_seconds <= 0:
            return 0.0
        return len(ticks) * (60.0 / self._dq_tick_window_seconds)

    def _dq_startup_grace_remaining(self, now: float | None = None) -> float:
        if self._dq_startup_grace_seconds <= 0:
            return 0.0
        current = now if now is not None else time.time()
        elapsed = current - self._dq_started_at
        return max(0.0, self._dq_startup_grace_seconds - elapsed)

    @staticmethod
    def _price_age_seconds(timestamp_ms: int, now: float | None = None) -> float:
        if timestamp_ms <= 0:
            return 0.0
        current = now if now is not None else time.time()
        return max(0.0, current - (float(timestamp_ms) / 1000.0))

    def _build_data_quality_summary(self) -> dict[str, Any]:
        if not self._dq_enabled:
            return {
                "enabled": False,
                "blocked_count": 0,
                "tier_counts": {},
                "top_stale_symbols": [],
            }

        now = time.time()
        startup_grace_remaining = self._dq_startup_grace_remaining(now)
        if startup_grace_remaining > 0:
            return {
                "enabled": True,
                "startup_warmup": True,
                "startup_grace_remaining_seconds": round(startup_grace_remaining, 2),
                "blocked_count": 0,
                "tier_counts": {"warmup": len(self.symbols)},
                "blocked_samples": [],
                "top_stale_symbols": [],
                "window_seconds": self._dq_tick_window_seconds,
                "max_price_age_seconds": self._dq_max_price_age_seconds,
                "min_ticks_per_minute": self._dq_min_ticks_per_minute,
            }

        assessments: list[dict[str, Any]] = []
        for symbol in sorted(self.symbols):
            market_data = self._selector_market_data.get(symbol) or self._market_data_cache.get(symbol)
            if market_data is None:
                assessments.append(
                    {
                        "symbol": symbol,
                        "allowed": False,
                        "reason": "missing_market_data",
                        "price_age_seconds": 0.0,
                        "ticks_per_minute": round(self._ticks_per_minute(symbol, now), 3),
                        "tier": "low",
                    }
                )
                continue
            assessment = self._assess_data_quality(symbol, market_data, mutate=False)
            assessments.append({"symbol": symbol, **assessment})

        tier_counts: dict[str, int] = {}
        blocked: list[dict[str, Any]] = []
        for row in assessments:
            tier = str(row.get("tier", "unknown"))
            tier_counts[tier] = tier_counts.get(tier, 0) + 1
            if not bool(row.get("allowed", False)):
                blocked.append(
                    {
                        "symbol": row["symbol"],
                        "reason": row.get("reason", "unknown"),
                        "age": round(float(row.get("price_age_seconds", 0.0)), 3),
                        "tpm": round(float(row.get("ticks_per_minute", 0.0)), 3),
                    }
                )

        top_stale = sorted(
            (
                {
                    "symbol": row["symbol"],
                    "age": round(float(row.get("price_age_seconds", 0.0)), 3),
                    "tpm": round(float(row.get("ticks_per_minute", 0.0)), 3),
                }
                for row in assessments
            ),
            key=lambda item: float(item["age"]),
            reverse=True,
        )[:10]

        return {
            "enabled": True,
            "blocked_count": len(blocked),
            "tier_counts": tier_counts,
            "blocked_samples": blocked[:20],
            "top_stale_symbols": top_stale,
            "window_seconds": self._dq_tick_window_seconds,
            "max_price_age_seconds": self._dq_max_price_age_seconds,
            "min_ticks_per_minute": self._dq_min_ticks_per_minute,
        }

    def _passes_entry_gates(
        self,
        symbol: str,
        market_data: MarketData,
        context: MarketContext,
    ) -> bool:
        dq_assessment = self._assess_data_quality(symbol, market_data, mutate=True)
        self._dq_entry_assessment[symbol] = dq_assessment
        if not dq_assessment["allowed"]:
            dq_reason = str(dq_assessment.get("reason", "unknown"))
            self._last_entry_gate_reason[symbol] = f"Entry blocked by data quality: {dq_reason}"
            logger.debug(
                "%s: entry blocked by data_quality (%s, age=%.2fs, tpm=%.2f)",
                symbol,
                dq_reason,
                float(dq_assessment.get("price_age_seconds", 0.0)),
                float(dq_assessment.get("ticks_per_minute", 0.0)),
            )
            return False
        if not self._symbol_selector.is_symbol_allowed(symbol):
            self._last_entry_gate_reason[symbol] = "Entry blocked by selector: symbol not selected"
            return False
        if self._cash_in_bear and context.regime in BEAR_REGIMES:
            self._last_entry_gate_reason[symbol] = (
                f"Entry blocked by cash_in_bear: regime={context.regime}"
            )
            return False
        if self._cash_below_ema200 and market_data.ema_200 > 0 and market_data.close < market_data.ema_200:
            self._last_entry_gate_reason[symbol] = (
                f"Entry blocked by EMA200 cash guard: close={market_data.close:.4f} < ema200={market_data.ema_200:.4f}"
            )
            return False
        if self._loss_pause_remaining.get(symbol, 0) > 0:
            self._last_entry_gate_reason[symbol] = (
                f"Entry blocked by loss pause: remaining={self._loss_pause_remaining[symbol]}"
            )
            return False
        if self._cooldown_remaining.get(symbol, 0) > 0:
            self._last_entry_gate_reason[symbol] = (
                f"Entry blocked by cooldown: remaining={self._cooldown_remaining[symbol]}"
            )
            return False
        if self._bull_prob_enabled and (market_data.mfi / 100.0) < self._bull_prob_threshold:
            self._last_entry_gate_reason[symbol] = (
                f"Entry blocked by bull_prob gate: mfi_prob={market_data.mfi/100.0:.2f} "
                f"< threshold={self._bull_prob_threshold:.2f}"
            )
            return False
        self._last_entry_gate_reason.pop(symbol, None)
        return True

    def _update_entry_decision_hint(self, symbol: str, should_enter: bool, reason: str) -> None:
        self._entry_decision_hint[symbol] = {
            "timestamp": time.time(),
            "should_enter": should_enter,
            "reason": reason,
        }

    def _get_entry_decision_hint(self, symbol: str) -> dict[str, Any] | None:
        hint = self._entry_decision_hint.get(symbol)
        if not hint:
            return None
        hint_ts = float(hint.get("timestamp", 0.0))
        if (time.time() - hint_ts) > self._entry_decision_hint_ttl_seconds:
            return None
        return hint

    def _selector_funnel_snapshot(self, symbol: str) -> dict[str, Any]:
        selected = symbol in self._symbol_selector.selected_symbols
        selector_reason = ""
        selector_rank = 0
        selector_score = 0.0
        for index, row in enumerate(self._symbol_selector.ranking, start=1):
            if row.symbol != symbol:
                continue
            selector_rank = index
            selector_score = float(row.score)
            selector_reason = str(row.reason)
            break

        if not selector_reason:
            for row in self._symbol_selector.evaluations:
                if row.symbol == symbol:
                    selector_reason = str(row.reason)
                    if selector_score == 0.0 and row.score > -999:
                        selector_score = float(row.score)
                    break

        event_types = [
            str(item.event_type)
            for item in self._symbol_selector.signal_events
            if item.symbol == symbol and item.event_type
        ]
        return {
            "selector_selected": selected,
            "selector_rank": selector_rank,
            "selector_score": round(selector_score, 6),
            "selector_reason": selector_reason,
            "selector_event_types": "|".join(event_types),
        }

    @staticmethod
    def _entry_route_from_reason(reason: str) -> str:
        text = str(reason or "")
        if text.startswith("HybridLong["):
            closing = text.find("]")
            if closing > len("HybridLong["):
                return text[len("HybridLong["):closing]
        if text.startswith("LLMDirection"):
            return "llm"
        if text.startswith("MLPDirection"):
            return "legacy_mlp"
        if text.startswith("RegimeLongV2"):
            return "regime"
        return ""

    @staticmethod
    def _categorize_entry_rejection_reason(reason: str) -> str:
        text = str(reason or "").lower()
        if not text or text == "no entry signal":
            return "no_signal"
        if "data quality" in text:
            return "gate_data_quality"
        if "selector" in text and "not selected" in text:
            return "gate_selector"
        if "cash_in_bear" in text or "bear regime" in text:
            return "gate_regime"
        if "ema200 cash guard" in text:
            return "gate_ema200_cash_guard"
        if "loss pause" in text:
            return "gate_loss_pause"
        if "cooldown" in text:
            return "gate_cooldown"
        if "bull_prob gate" in text:
            return "gate_bull_prob"
        if "leverage" in text:
            return "leverage_blocked"
        if "model unavailable" in text or "prediction unavailable" in text or "warmup" in text:
            return "model_unavailable"
        if "not buy" in text or "predicted hold" in text or "predicted sell" in text:
            return "model_non_buy"
        if "low llm confidence" in text or "low mlp confidence" in text or "low confidence" in text:
            return "model_low_confidence"
        if "filter" in text or "blocked by regime" in text or "weak adx" in text or "below ema200" in text:
            return "model_filter_block"
        if "risk cap" in text:
            return "order_risk_cap"
        if "quantity too small" in text or "volatility sizing" in text:
            return "order_quantity_zero"
        if "portfolio risk" in text:
            return "order_portfolio_risk"
        return "other"

    async def _emit_entry_funnel_event(
        self,
        *,
        symbol: str,
        context: MarketContext,
        dq_assessment: dict[str, Any] | None,
        gate_passed: bool,
        gate_reason: str,
        leverage_allowed: bool,
        leverage_reason: str,
        entry_signal_generated: bool,
        entry_route: str,
        entry_rejection_reason: str,
        order_build_result: str,
        order_drop_reason: str,
        order_published: bool,
    ) -> None:
        if not self.emit_events or self.event_emitter is None:
            return

        from trading.core.event_emitter import EntryFunnelEvent

        selector = self._selector_funnel_snapshot(symbol)
        dq = dq_assessment or {}
        event = EntryFunnelEvent(
            timestamp=datetime.now().isoformat(),
            strategy=self.name,
            symbol=symbol,
            market=self.market,
            regime=context.regime,
            selector_selected=bool(selector.get("selector_selected", False)),
            selector_rank=int(selector.get("selector_rank", 0) or 0),
            selector_score=float(selector.get("selector_score", 0.0) or 0.0),
            selector_reason=str(selector.get("selector_reason", "")),
            selector_event_types=str(selector.get("selector_event_types", "")),
            dq_allowed=bool(dq.get("allowed", False)) if dq else False,
            dq_reason=str(dq.get("reason", "")) if dq else "",
            dq_tier=str(dq.get("tier", "")) if dq else "",
            dq_price_age_seconds=float(dq.get("price_age_seconds", 0.0) or 0.0) if dq else 0.0,
            dq_ticks_per_minute=float(dq.get("ticks_per_minute", 0.0) or 0.0) if dq else 0.0,
            gate_passed=gate_passed,
            gate_reason=gate_reason,
            leverage_allowed=leverage_allowed,
            leverage_reason=leverage_reason,
            entry_signal_generated=entry_signal_generated,
            entry_route=entry_route,
            entry_rejection_category=self._categorize_entry_rejection_reason(entry_rejection_reason),
            entry_rejection_reason=entry_rejection_reason,
            order_build_result=order_build_result,
            order_drop_reason=order_drop_reason,
            order_published=order_published,
        )
        await self.event_emitter.emit_entry_funnel(event)

    def _resolve_entry_rejection_reason(self, symbol: str) -> str:
        get_reason = getattr(self.entry_strategy, "get_last_rejection_reason", None)
        reason: str | None = None

        if callable(get_reason):
            try:
                reason = get_reason(symbol)
            except TypeError:
                reason = get_reason()
            except Exception:
                reason = None

        if not reason:
            fallback_reason = getattr(self.entry_strategy, "last_rejection_reason", None)
            if isinstance(fallback_reason, str) and fallback_reason.strip():
                reason = fallback_reason.strip()

        if not reason:
            return "No entry signal"
        return str(reason)

    async def _resolve_entry_leverage(
        self,
        context: MarketContext,
        market_data: MarketData,
    ) -> float | None:
        leverage = float(self.config.get("leverage", 1))
        if self._dynamic_leverage_enabled:
            leverage = self._get_dynamic_leverage_for_regime(context.regime)
            if leverage is None:
                return None

        if self._drawdown_enabled:
            drawdown_pct = await self._get_drawdown_pct()
            if drawdown_pct >= self._drawdown_warning_pct:
                leverage *= self._drawdown_leverage_reduction

        leverage = self._apply_probability_leverage(leverage, market_data.mfi)
        if leverage is None:
            return None

        if 0 < leverage < 1:
            return 1.0
        return leverage

    def _get_dynamic_leverage_for_regime(self, regime: str) -> float | None:
        if regime == "BULL_STRONG":
            return self._leverage_bull_strong
        if regime == "BULL_MODERATE":
            return self._leverage_bull_moderate
        if regime in ("SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN"):
            return self._leverage_sideways
        leverage = self._leverage_bear
        if leverage <= 0:
            return None
        return leverage

    def _apply_probability_leverage(self, leverage: float, mfi: float) -> float | None:
        if not self._prob_leverage_enabled:
            return leverage
        if mfi >= 70:
            return min(leverage, self._prob_leverage_max)
        if mfi >= 60:
            return min(leverage, self._prob_leverage_high)
        if mfi >= 50:
            return min(leverage, self._prob_leverage_mid)
        if mfi >= 40:
            return min(leverage, self._prob_leverage_low)
        if mfi >= 30:
            return min(leverage, self._prob_leverage_min)
        return None

    async def _build_entry_order(
        self,
        symbol: str,
        signal: Signal,
        market_data: MarketData,
        context: MarketContext,
        leverage: float,
    ) -> dict[str, Any] | None:
        quantity, stop_price = await self._get_quantity(
            symbol, market_data.close, signal.quantity, context, market_data
        )

        dq_assessment = self._dq_entry_assessment.get(symbol) or self._assess_data_quality(
            symbol,
            market_data,
            mutate=False,
        )
        scale = float(dq_assessment.get("position_scale", 1.0))
        if scale <= 0:
            logger.info("%s: entry blocked by data_quality scale <= 0", symbol)
            self._last_entry_order_build_reason[symbol] = "dq_scale_zero"
            return None
        if scale < 0.999:
            quantity *= scale
            logger.info(
                "%s: Data-quality sizing tier=%s scale=%.2f age=%.2fs tpm=%.2f qty=%.6f",
                symbol,
                dq_assessment.get("tier", "unknown"),
                scale,
                float(dq_assessment.get("price_age_seconds", 0.0)),
                float(dq_assessment.get("ticks_per_minute", 0.0)),
                quantity,
            )

        allowed, reason = await self._passes_context_risk_caps(
            symbol=symbol,
            quantity=quantity,
            price=market_data.close,
        )
        if not allowed:
            logger.info(f"{symbol}: Context risk cap blocked entry - {reason}")
            self._last_entry_order_build_reason[symbol] = f"risk_cap:{reason}"
            return None

        quantity = await self._apply_volatility_sizing(symbol, quantity, market_data)
        if quantity <= 0:
            logger.debug(f"{symbol}: Quantity too small, skipping entry")
            self._last_entry_order_build_reason[symbol] = "volatility_sizing_zero"
            return None

        if self._portfolio_risk_mgr and self._risk_based_sizing:
            quantity = await self._apply_portfolio_risk_checks(
                symbol=symbol,
                quantity=quantity,
                market_data=market_data,
                stop_price=stop_price,
            )
            if quantity <= 0:
                self._last_entry_order_build_reason[symbol] = "portfolio_risk_zero"
                return None

        order = self._signal_to_dict(signal, quantity, leverage=leverage)
        self._last_entry_order_build_reason.pop(symbol, None)
        order["data_quality_tier"] = str(dq_assessment.get("tier", "unknown"))
        order["data_quality_age_seconds"] = str(
            round(float(dq_assessment.get("price_age_seconds", 0.0)), 3)
        )
        order["data_quality_ticks_per_minute"] = str(
            round(float(dq_assessment.get("ticks_per_minute", 0.0)), 3)
        )
        if stop_price and stop_price > 0:
            order["stop_price"] = stop_price
        if hasattr(self.exit_strategy, "params"):
            slp = getattr(self.exit_strategy.params, "stop_loss_pct", None)
            if slp is not None:
                order["stop_loss_pct"] = slp
        return order

    async def _apply_volatility_sizing(
        self,
        symbol: str,
        quantity: float,
        market_data: MarketData,
    ) -> float:
        if not self._vol_sizing_enabled or market_data.atr <= 0:
            return quantity

        from trading.risk.volatility_scaler import compute_volatility_scale

        vol_scale = compute_volatility_scale(
            atr=market_data.atr,
            price=market_data.close,
            target_vol=self._vol_target,
            min_scale=self._vol_min_scale,
            max_scale=self._vol_max_scale,
        )
        quantity *= vol_scale
        logger.info(
            f"{symbol}: Vol sizing: ATR%={market_data.atr/market_data.close*100:.2f}%, "
            f"scale={vol_scale:.2f}, qty={quantity:.6f}"
        )

        allowed, reason = await self._passes_context_risk_caps(
            symbol=symbol,
            quantity=quantity,
            price=market_data.close,
        )
        if not allowed:
            logger.info(f"{symbol}: Context risk cap blocked entry - {reason}")
            return 0.0

        return quantity

    async def _apply_portfolio_risk_checks(
        self,
        symbol: str,
        quantity: float,
        market_data: MarketData,
        stop_price: float | None,
    ) -> float:
        equity = await self._get_account_equity()
        if equity <= 0:
            logger.warning(f"{symbol}: Cannot get equity, skipping entry")
            return 0.0

        if stop_price and stop_price > 0:
            stop_pct = abs(market_data.close - stop_price) / market_data.close
        else:
            stop_pct = 0.03
        proposed_risk = quantity * market_data.close * stop_pct

        risk_check = await self._portfolio_risk_mgr.can_open_trade(
            symbol=symbol,
            proposed_risk=proposed_risk,
            equity=equity,
        )
        if not risk_check.allowed:
            logger.info(f"{symbol}: Entry blocked by portfolio risk - {risk_check.reason}")
            return 0.0

        if risk_check.adjusted_risk_pct and self._position_sizer:
            original_risk_pct = self.config.get("risk_per_trade_pct", 0.01)
            reduction_factor = risk_check.adjusted_risk_pct / original_risk_pct
            quantity = quantity * reduction_factor
            logger.info(
                f"{symbol}: Quantity reduced by correlation filter "
                f"({reduction_factor:.2f}x) -> {quantity:.6f}"
            )

        return quantity

    def _build_exit_context(
        self,
        symbol: str,
        position: Position,
        market_data: MarketData,
    ) -> tuple[MarketContext, TradingContext]:
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
        return context, ctx

    async def _check_protective_exit_conditions(
        self,
        symbol: str,
        position: Position,
        market_data: MarketData,
        context: MarketContext,
    ) -> dict[str, Any] | None:
        bear_exit = self._check_bear_regime_exit(symbol, position, context)
        if bear_exit:
            return bear_exit

        drawdown_exit = await self._check_drawdown_protection_exit(symbol, position)
        if drawdown_exit:
            return drawdown_exit

        v2_filter_exit = self._check_v2_filter_protective_exit(symbol, position, market_data, context)
        if v2_filter_exit:
            return v2_filter_exit

        return self._check_ma120_panic_exit(symbol, position, market_data)

    def _check_bear_regime_exit(
        self,
        symbol: str,
        position: Position,
        context: MarketContext,
    ) -> dict[str, Any] | None:
        if not self._exit_on_bear_regime:
            return None
        if context.regime not in BEAR_REGIMES:
            return None
        exit_qty = self._spot_adjusted_qty(symbol, position.quantity)
        if exit_qty <= 0:
            return None
        return {
            "symbol": symbol,
            "side": "sell",
            "market": self.market,
            "quantity": str(exit_qty),
            "reason": f"bear_regime_exit:{context.regime}",
        }

    async def _check_drawdown_protection_exit(
        self,
        symbol: str,
        position: Position,
    ) -> dict[str, Any] | None:
        if not self._drawdown_enabled:
            return None
        drawdown_pct = await self._get_drawdown_pct()
        if drawdown_pct >= self._drawdown_exit_pct:
            if self._loss_pause_candles > 0:
                self._loss_pause_remaining[symbol] = self._loss_pause_candles
            exit_qty = self._spot_adjusted_qty(symbol, position.quantity)
            if exit_qty <= 0:
                return None
            return {
                "symbol": symbol,
                "side": "sell",
                "market": self.market,
                "quantity": str(exit_qty),
                "reason": f"DRAWDOWN_EXIT:{drawdown_pct:.1f}%>={self._drawdown_exit_pct:.1f}%",
            }

        if (
            drawdown_pct >= self._drawdown_reduce_pct
            and not self._drawdown_partial_exit_done.get(symbol, False)
        ):
            self._drawdown_partial_exit_done[symbol] = True
            exit_qty = self._spot_adjusted_qty(symbol, position.quantity * 0.5)
            if exit_qty > 0:
                return {
                    "symbol": symbol,
                    "side": "sell",
                    "market": self.market,
                    "quantity": str(exit_qty),
                    "reason": f"DRAWDOWN_REDUCE:{drawdown_pct:.1f}%>={self._drawdown_reduce_pct:.1f}%",
                }

        return None

    def _check_v2_filter_protective_exit(
        self,
        symbol: str,
        position: Position,
        market_data: MarketData,
        context: MarketContext,
    ) -> dict[str, Any] | None:
        if not (self._v2_exit_on_filter and self.regime_version == "v2"):
            return None

        router = self._enhanced_routers.get(symbol)
        if router is None:
            return None

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

        if v2_entry_allowed:
            return None

        exit_qty = self._spot_adjusted_qty(symbol, position.quantity)
        if exit_qty <= 0:
            return None
        return {
            "symbol": symbol,
            "side": "sell",
            "market": self.market,
            "quantity": str(exit_qty),
            "reason": "v2_filter_protective_exit",
        }

    def _check_ma120_panic_exit(
        self,
        symbol: str,
        position: Position,
        market_data: MarketData,
    ) -> dict[str, Any] | None:
        if not self._panic_sell_below_ma120 or market_data.ema_120 <= 0:
            return None
        if market_data.close >= market_data.ema_120:
            return None
        exit_qty = self._spot_adjusted_qty(symbol, position.quantity)
        if exit_qty <= 0:
            return None
        return {
            "symbol": symbol,
            "side": "sell",
            "market": self.market,
            "quantity": str(exit_qty),
            "reason": (
                f"MA120 panic_sell: close={market_data.close:.0f} < "
                f"ema120={market_data.ema_120:.0f}"
            ),
        }

    async def _evaluate_exit_signal(
        self,
        ctx: TradingContext,
        position: Position,
    ) -> Signal | None:
        check_exit_method = self.exit_strategy.check_exit
        if asyncio.iscoroutinefunction(check_exit_method):
            return await check_exit_method(ctx, position)
        return check_exit_method(ctx, position)

    def _update_exit_loss_tracking(self, symbol: str, signal: Signal) -> None:
        reason = signal.reason or ""
        is_stop_loss = "stop loss" in reason.lower() or "stoploss" in reason.lower()
        if not is_stop_loss:
            self._consecutive_losses[symbol] = 0
            return

        if self._cooldown_candles > 0:
            self._cooldown_remaining[symbol] = self._cooldown_candles

        losses = self._consecutive_losses.get(symbol, 0) + 1
        if losses >= self._max_consecutive_losses:
            if self._loss_pause_candles > 0:
                self._loss_pause_remaining[symbol] = self._loss_pause_candles
            losses = 0
        self._consecutive_losses[symbol] = losses

    async def on_position_opened(self, symbol: str, position: dict) -> None:
        """Notify exit strategy when position is opened.

        Called by _handle_message after entry order is filled.

        Args:
            symbol: Trading symbol.
            position: Position dict from Redis.
        """
        position = self._dict_to_position(position)

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

        Provides all indicators needed for entry/exit strategies:
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
        service_data = self._build_market_data_from_service(symbol)
        if service_data is not None:
            return service_data

        # Fallback to local calculation (legacy path)
        try:
            price_point = self._resolve_current_price_point(symbol)
            if price_point is None:
                return None
            current_price, current_timestamp = price_point

            cached = self._resolve_cached_market_data(
                symbol=symbol,
                current_price=current_price,
                current_timestamp=current_timestamp,
                force_recalculate=force_recalculate,
            )
            if cached is not None:
                return cached

            prepared = self._prepare_market_indicator_frame(symbol, current_price)
            if prepared is None:
                return None
            df, last_row = prepared
            prev_high_20, prev_low_20, avg_volume_20 = self._calculate_lookback_stats(df)
            breakout_signal, target_price = self._calc_breakout_signal(symbol, df, current_price)

            market_data = self._create_market_data_snapshot(
                symbol=symbol,
                current_price=current_price,
                current_timestamp=current_timestamp,
                last_row=last_row,
                prev_high_20=prev_high_20,
                prev_low_20=prev_low_20,
                avg_volume_20=avg_volume_20,
                breakout_signal=breakout_signal,
                target_price=target_price,
            )
            self._market_data_cache[symbol] = market_data
            return market_data

        except Exception as e:
            logger.error(f"Failed to build MarketData for {symbol}: {e}")
        return None

    def _build_market_data_from_service(self, symbol: str) -> MarketData | None:
        if not self.indicator_service:
            return None
        buffer = self.price_buffer.get(symbol, [])
        current_price = float(buffer[-1]["price"]) if buffer else None
        return self.indicator_service.get_market_data(symbol, current_price)

    def _resolve_current_price_point(self, symbol: str) -> tuple[float, int] | None:
        buffer = self.price_buffer.get(symbol, [])
        if buffer:
            return float(buffer[-1]["price"]), int(buffer[-1].get("timestamp", 0))

        history = self.history.get(symbol)
        if not history:
            return None
        return float(history[-1]["close"]), 0

    def _resolve_cached_market_data(
        self,
        symbol: str,
        current_price: float,
        current_timestamp: int,
        force_recalculate: bool,
    ) -> MarketData | None:
        should_recalc = force_recalculate or self._should_recalculate(symbol)
        cached = self._market_data_cache.get(symbol)
        if cached and not should_recalc:
            return replace(cached, close=current_price, timestamp=current_timestamp)
        return None

    def _prepare_market_indicator_frame(
        self,
        symbol: str,
        current_price: float,
    ) -> tuple[pd.DataFrame, pd.Series] | None:
        history = self.history.get(symbol)
        if not history:
            return None
        df = pd.DataFrame(history)
        self._update_indicator_frame_with_current_price(df, current_price)
        df = add_all_indicators(df)
        return df, df.iloc[-1]

    def _update_indicator_frame_with_current_price(self, df: pd.DataFrame, current_price: float) -> None:
        idx = df.index[-1]
        if "close" in df.columns:
            df.at[idx, "close"] = current_price
        if "high" in df.columns:
            df.at[idx, "high"] = max(df.at[idx, "high"], current_price)
        if "low" in df.columns:
            df.at[idx, "low"] = min(df.at[idx, "low"], current_price)

    def _calculate_lookback_stats(self, df: pd.DataFrame, lookback: int = 20) -> tuple[float, float, float]:
        if len(df) >= lookback:
            prev_df = df.iloc[-lookback - 1 : -1]
            return (
                float(prev_df["high"].max()),
                float(prev_df["low"].min()),
                float(prev_df["volume"].mean()),
            )
        return 0.0, 0.0, 0.0

    def _create_market_data_snapshot(
        self,
        symbol: str,
        current_price: float,
        current_timestamp: int,
        last_row: pd.Series,
        prev_high_20: float,
        prev_low_20: float,
        avg_volume_20: float,
        breakout_signal: int,
        target_price: float,
    ) -> MarketData:
        return MarketData(
            symbol=symbol,
            open=float(last_row.get("open", current_price)),
            close=float(current_price),
            mfi=float(last_row.get("mfi", 50)),
            adx=float(last_row.get("adx", 20)),
            rsi=float(last_row.get("rsi", 50)),
            timestamp=current_timestamp,
            high=float(last_row.get("high", current_price)),
            low=float(last_row.get("low", current_price)),
            volume=float(last_row.get("volume", 0)),
            macd=float(last_row.get("macd", 0)),
            macd_signal=float(last_row.get("macd_signal", 0)),
            stoch_k=float(last_row.get("stoch_k", 50)),
            stoch_d=float(last_row.get("stoch_d", 50)),
            bb_upper=float(last_row.get("bb_upper", 0)),
            bb_lower=float(last_row.get("bb_lower", 0)),
            bb_middle=float(last_row.get("bb_middle", 0)),
            atr=float(last_row.get("atr", 0)),
            ema_5=float(last_row.get("ema_5", 0)),
            ema_10=float(last_row.get("ema_10", 0)),
            ema_20=float(last_row.get("ema_20", 0)),
            ema_120=float(last_row.get("ema_120", 0)),
            ema_200=float(last_row.get("ema_200", 0)),
            market_stress=float(last_row.get("market_stress", 0)),
            prev_high_20=prev_high_20,
            prev_low_20=prev_low_20,
            avg_volume_20=avg_volume_20,
            high_30d=float(last_row.get("high_30d", 0)),
            breakout_signal=breakout_signal,
            target_price=target_price,
            trix=float(last_row.get("trix", 0)),
            trix_signal=float(last_row.get("trix_signal", 0)),
            trix_hist=float(last_row.get("trix_hist", 0)),
        )

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

    def _get_history_df(self, symbol: str) -> pd.DataFrame | None:
        """Get recent indicator/candle history for model-backed entry logic."""
        if self.indicator_service is not None:
            df = self.indicator_service.get_history_df(symbol)
        else:
            history = self.history.get(symbol, [])
            if not history:
                return None
            df = pd.DataFrame(history)

        if df is None or df.empty:
            return None
        return df

    def _get_mlp_history_df(self, symbol: str) -> pd.DataFrame | None:
        """Backward-compatible alias for legacy runtime helpers."""
        return self._get_history_df(symbol)

    def _get_latest_candle_timestamp(
        self,
        symbol: str,
        market_data: MarketData,
    ) -> int:
        """Get stable per-candle timestamp for cache keys."""
        if self.indicator_service is not None:
            ts = self.indicator_service.get_latest_candle_timestamp(symbol)
            if ts is not None and ts > 0:
                return int(ts)
        return int(market_data.timestamp)

    def _update_latest_history_candle(self, df: pd.DataFrame, market_data: MarketData) -> None:
        try:
            idx = df.index[-1]
            if "close" in df.columns:
                df.at[idx, "close"] = market_data.close
            if "high" in df.columns:
                df.at[idx, "high"] = max(df.at[idx, "high"], market_data.close)
            if "low" in df.columns:
                df.at[idx, "low"] = min(df.at[idx, "low"], market_data.close)
            if "timestamp" in df.columns and market_data.timestamp:
                df.at[idx, "timestamp"] = market_data.timestamp
        except Exception:
            # Non-fatal if we can't update last candle
            pass

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
        Applies optional runtime model overlay, then enhanced regime detection v2.

        Args:
            market_data: Current market state with indicators.

        Returns:
            MarketContext with trend and volatility analysis.
        """
        context = self._build_base_market_context(market_data)

        runtime_pred = self._predict_runtime_regime(market_data)
        if runtime_pred is not None:
            context = self._context_with_regime(
                context,
                runtime_pred.regime_7,
                trend=self._trend_from_regime(runtime_pred.regime_7),
                rf_confidence=runtime_pred.rf_confidence,
                rf_direction=runtime_pred.regime_3,
                rf_signal=runtime_pred.rf_signal,
            )
            if not self._runtime_regime_overlay.apply_v2_filters:
                return context

        if market_data.symbol in self._enhanced_routers:
            return self._apply_v2_regime_context(context, market_data)
        return context

    def _predict_runtime_regime(self, market_data: MarketData) -> RuntimeRegimePrediction | None:
        symbol = market_data.symbol
        overlay = self._runtime_regime_overlay
        if not overlay.is_enabled_for(symbol):
            return None

        candle_ts = self._get_latest_candle_timestamp(symbol, market_data)
        cached = self._runtime_regime_cache.get(symbol)
        if cached and int(cached.get("candle_timestamp", -1)) == candle_ts:
            pred = cached.get("prediction")
            if isinstance(pred, RuntimeRegimePrediction):
                return pred

        history_df = self._get_history_df(symbol)
        prediction = overlay.predict(
            symbol=symbol,
            market_data=market_data,
            history_df=history_df,
        )
        if prediction is not None:
            self._runtime_regime_cache[symbol] = {
                "candle_timestamp": candle_ts,
                "prediction": prediction,
            }
            logger.info(
                "%s: runtime regime overlay -> model=%s regime=%s conf=%.3f",
                symbol,
                prediction.model,
                prediction.regime_7,
                prediction.confidence,
            )
        return prediction

    def _build_base_market_context(self, market_data: MarketData) -> MarketContext:
        recent_high = market_data.high_30d if market_data.high_30d > 0 else market_data.prev_high_20
        return build_market_context(
            mfi=market_data.mfi,
            adx=market_data.adx,
            atr=market_data.atr,
            close=market_data.close,
            volume=market_data.volume,
            avg_volume=market_data.avg_volume_20,
            recent_high=recent_high,
            drawdown_bear_threshold=self._drawdown_bear_threshold,
            **self._regime_thresholds,
        )

    def _apply_v2_regime_context(self, context: MarketContext, market_data: MarketData) -> MarketContext:
        router = self._enhanced_routers[market_data.symbol]
        candle_ts = self._get_latest_candle_timestamp(market_data.symbol, market_data)
        router.update_from_lower_candle(
            MTFCandle(
                open=market_data.open,
                high=market_data.high,
                low=market_data.low,
                close=market_data.close,
                volume=market_data.volume,
                mfi=market_data.mfi,
                adx=market_data.adx,
            ),
            candle_ts=candle_ts,
        )
        volume_ratio = market_data.volume / market_data.avg_volume_20 if market_data.avg_volume_20 > 0 else 1.0
        filtered_regime = router.get_regime(
            mfi=market_data.mfi,
            adx=market_data.adx,
            bb_upper=market_data.bb_upper,
            bb_lower=market_data.bb_lower,
            bb_middle=market_data.bb_middle,
            volume_ratio=volume_ratio,
        )
        final_regime = self._resolve_regime_with_drawdown(context, filtered_regime)
        return self._context_with_regime(context, final_regime, trend=self._trend_from_regime(final_regime))

    def _resolve_regime_with_drawdown(self, context: MarketContext, regime: str) -> str:
        if not context.is_drawdown_bear or regime in ("BEAR_STRONG", "BEAR_MODERATE"):
            return regime
        return "BEAR_STRONG" if context.adx >= 25 else "BEAR_MODERATE"

    def _trend_from_regime(self, regime: str) -> str:
        if regime in ("BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"):
            return "BULL"
        if regime in ("BEAR_STRONG", "BEAR_MODERATE", "SIDEWAYS_DOWN"):
            return "BEAR"
        return "SIDEWAYS"

    def _context_with_regime(
        self,
        context: MarketContext,
        regime: str,
        trend: str,
        rf_confidence: float | None = None,
        rf_direction: str | None = None,
        rf_signal: str | None = None,
    ) -> MarketContext:
        return MarketContext(
            trend=trend,
            regime=regime,
            volatility_score=context.volatility_score,
            is_extreme_volatility=context.is_extreme_volatility,
            adx=context.adx,
            volume_ratio=context.volume_ratio,
            is_high_volume=context.is_high_volume,
            drawdown=context.drawdown,
            is_drawdown_bear=context.is_drawdown_bear,
            rf_confidence=context.rf_confidence if rf_confidence is None else rf_confidence,
            rf_direction=context.rf_direction if rf_direction is None else rf_direction,
            rf_signal=context.rf_signal if rf_signal is None else rf_signal,
        )

    def _dict_to_position(self, position_dict: dict) -> Position:
        """Convert position dict to Position model.

        Args:
            position_dict: Position dict from Redis.

        Returns:
            Position instance.
        """
        entry_time = int(position_dict.get("entry_time", 0) or 0)
        timestamp = int(position_dict.get("timestamp", 0) or 0)
        if timestamp <= 0:
            timestamp = entry_time
        return Position(
            symbol=position_dict.get("symbol", ""),
            entry_price=float(position_dict.get("entry_price", 0)),
            quantity=float(position_dict.get("quantity", 0)),
            strategy=position_dict.get("strategy", self.name),
            market=position_dict.get("market", self.market),
            timestamp=timestamp,
            side=position_dict.get("side", "buy"),
            leverage=int(position_dict.get("leverage", 1) or 1),
            entry_time=entry_time if entry_time > 0 else None,
        )

    def _spot_adjusted_qty(self, symbol: str, qty: float) -> float:
        """Adjust spot exit quantity to exchange LOT_SIZE filters."""
        if self.market != "spot":
            return qty
        try:
            qty_dec = PriceUtils.to_decimal(qty)
            if qty_dec <= 0:
                return 0.0
            symbol_info = get_symbol_info(symbol)
            rounded_qty = PriceUtils.round_quantity(qty_dec, symbol_info)
            if not PriceUtils.meets_min_qty(rounded_qty, symbol_info):
                return 0.0
            return float(rounded_qty)
        except Exception as exc:
            logger.warning("%s: spot qty adjustment failed: %s", symbol, exc)
            return max(float(qty), 0.0)

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
        # Adjust spot exit quantities for exchange LOT_SIZE compliance.
        if signal.side == "sell":
            quantity = self._spot_adjusted_qty(signal.symbol, quantity)

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

    def _resolve_exit_order_quantity(self, position: Position, signal: Signal) -> float:
        """Resolve exit signal quantity to absolute order quantity.

        Exit components currently emit two quantity styles:
        - Fractional (<= 1.0): BaseExitStrategy convention (1.0=full, 0.5=half)
        - Absolute (> 1.0): legacy/custom absolute quantity

        Always clamp to current position quantity to avoid oversize sell attempts.
        """
        position_qty = max(float(position.quantity), 0.0)
        raw_qty = float(signal.quantity)
        if position_qty <= 0.0 or raw_qty <= 0.0:
            return 0.0

        if raw_qty <= 1.0 + 1e-9:
            resolved_qty = position_qty * min(max(raw_qty, 0.0), 1.0)
        else:
            resolved_qty = raw_qty

        return min(resolved_qty, position_qty)

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
        _ = context
        risk_sized = await self._get_risk_sized_quantity(symbol, price, market_data)
        if risk_sized is not None:
            return risk_sized
        return await self._get_legacy_quantity(symbol, price, default_quantity)

    async def _get_risk_sized_quantity(
        self,
        symbol: str,
        price: float,
        market_data: MarketData | None,
    ) -> tuple[float, float | None] | None:
        if not (self._risk_based_sizing and self._position_sizer and market_data):
            return None

        equity = await self._get_account_equity()
        if equity <= 0:
            logger.warning(f"{symbol}: Cannot get equity for risk sizing")
            return (0.0, None)

        atr = market_data.atr if market_data.atr > 0 else price * 0.02
        leverage = int(self.config.get("leverage", 1))
        result = self._position_sizer.size_position(
            equity=equity,
            entry_price=price,
            atr=atr,
            symbol=symbol,
            leverage=leverage,
            direction="long",
        )

        if result.quantity == 0:
            logger.info(f"{symbol}: Risk sizing rejected - {result.rejection_reason}")
            return (0.0, None)

        stop_price = price * (1 - result.stop_distance_pct / 100)
        logger.info(
            f"{symbol}: Risk-sized qty={result.quantity:.6f}, "
            f"risk=${result.risk_amount:.2f}, stop={result.stop_distance_pct:.1f}%"
        )
        return (result.quantity, stop_price)

    async def _get_legacy_quantity(
        self,
        symbol: str,
        price: float,
        default_quantity: float,
    ) -> tuple[float, float | None]:
        use_dynamic = self.config.get("dynamic_sizing", False)
        position_pct = float(self.config.get("position_pct", 0.02))
        if use_dynamic:
            qty = await self.get_dynamic_position_size(symbol, price, position_pct)
            return (qty, None)

        configured_size = self._resolve_configured_position_size(default_quantity)
        if configured_size <= 0:
            return (0.0, None)
        if configured_size <= 1.0:
            quantity = await self._resolve_fractional_quantity(symbol, price, configured_size)
            return (quantity, None)
        return (configured_size, None)

    def _resolve_configured_position_size(self, default_quantity: float) -> float:
        use_signal_quantity = bool(self.config.get("use_signal_quantity", False))
        if use_signal_quantity:
            return float(default_quantity)
        return float(self.config.get("position_size", default_quantity))

    async def _resolve_fractional_quantity(
        self,
        symbol: str,
        price: float,
        configured_size: float,
    ) -> float:
        equity = await self._get_account_equity()
        if equity <= 0:
            logger.warning(
                f"{symbol}: Cannot resolve equity for fractional position_size={configured_size:.3f}"
            )
            return 0.0
        notional = equity * configured_size
        return notional / price if price > 0 else 0.0

    async def _get_account_equity(self) -> float:
        """Get current account equity from Redis.

        Returns:
            Account equity in USDT, or 0 if unavailable.
        """
        try:
            live = await self.redis._client.hgetall("account:live")
            if live:
                total = float(live.get("total_equity", 0))
                if total > 0:
                    return total
                spot = float(live.get("spot_balance", 0))
                if spot > 0:
                    return spot

            paper = await self.redis._client.hgetall("account:paper")
            if paper:
                spot = float(paper.get("spot_balance", 0))
                if spot > 0:
                    return spot

            # Last fallback for paper mode cold start
            return float(self.config.get("paper", {}).get("initial_balance", 0))
        except Exception as e:
            logger.warning(f"Failed to get account equity: {e}")
            return 0.0

    async def _passes_context_risk_caps(
        self,
        symbol: str,
        quantity: float,
        price: float,
    ) -> tuple[bool, str]:
        """Context-level exposure/correlation guard before order publish."""
        if not self._context_risk_enabled:
            return True, "DISABLED"
        if quantity <= 0 or price <= 0:
            return False, "INVALID_PROPOSED_NOTIONAL"
        if self.context_builder is None:
            return True, "NO_CONTEXT_BUILDER"

        open_positions, open_symbols, symbol_positions = self._get_context_portfolio_state(symbol)

        allowed, reason = self._passes_context_position_count_caps(
            symbol=symbol,
            open_symbols=open_symbols,
            symbol_positions=symbol_positions,
        )
        if not allowed:
            return False, reason

        proposed_notional = abs(quantity * price)
        allowed, reason = await self._passes_context_exposure_caps(
            proposed_notional=proposed_notional,
            open_positions=open_positions,
            symbol_positions=symbol_positions,
        )
        if not allowed:
            return False, reason

        allowed, reason = await self._passes_context_correlation_caps(symbol, open_symbols)
        if not allowed:
            return False, reason

        return True, "OK"

    def _get_context_portfolio_state(
        self, symbol: str
    ) -> tuple[list[Position], list[str], list[Position]]:
        portfolio = self.context_builder.get_portfolio_positions()
        open_positions = [p for p in portfolio.values() if p.quantity > 0]
        open_symbols = sorted({p.symbol for p in open_positions})
        symbol_positions = [p for p in open_positions if p.symbol == symbol]
        return open_positions, open_symbols, symbol_positions

    def _passes_context_position_count_caps(
        self,
        symbol: str,
        open_symbols: list[str],
        symbol_positions: list[Position],
    ) -> tuple[bool, str]:
        if symbol not in open_symbols and len(open_symbols) >= self._context_max_open_positions:
            return (
                False,
                f"CTX_MAX_OPEN_POSITIONS:{len(open_symbols)}>={self._context_max_open_positions}",
            )
        if len(symbol_positions) >= self._context_max_symbol_positions:
            return (
                False,
                f"CTX_MAX_SYMBOL_POSITIONS:{len(symbol_positions)}>={self._context_max_symbol_positions}",
            )
        return True, "OK"

    async def _passes_context_exposure_caps(
        self,
        proposed_notional: float,
        open_positions: list[Position],
        symbol_positions: list[Position],
    ) -> tuple[bool, str]:
        total_notional = sum(abs(p.quantity * p.entry_price) for p in open_positions)
        symbol_notional = sum(abs(p.quantity * p.entry_price) for p in symbol_positions)

        equity = await self._get_account_equity()
        if equity <= 0:
            return True, "OK"

        new_total_exposure = (total_notional + proposed_notional) / equity
        new_symbol_exposure = (symbol_notional + proposed_notional) / equity

        if new_total_exposure > self._context_max_total_exposure_pct:
            return (
                False,
                f"CTX_TOTAL_EXPOSURE:{new_total_exposure:.2f}>{self._context_max_total_exposure_pct:.2f}",
            )
        if new_symbol_exposure > self._context_max_symbol_exposure_pct:
            return (
                False,
                f"CTX_SYMBOL_EXPOSURE:{new_symbol_exposure:.2f}>{self._context_max_symbol_exposure_pct:.2f}",
            )
        return True, "OK"

    async def _passes_context_correlation_caps(
        self,
        symbol: str,
        open_symbols: list[str],
    ) -> tuple[bool, str]:
        if not self._context_corr_enabled or self._correlation_filter is None:
            return True, "OK"
        existing_symbols = [s for s in open_symbols if s != symbol]
        if not existing_symbols:
            return True, "OK"
        blocked, reason = await self._correlation_filter.should_block(symbol, existing_symbols)
        if blocked:
            return False, f"CTX_{reason}"
        return True, "OK"

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

        regime = self._get_decision_regime(market_data, context)
        position = await self._get_position(symbol)
        mfi_bull, mfi_bear, adx_trend = self._get_entry_thresholds_for_decision()
        decision, reason, position_data = self._build_decision_snapshot(
            market_data=market_data,
            regime=regime,
            position=position,
            mfi_bull=mfi_bull,
            mfi_bear=mfi_bear,
            adx_trend=adx_trend,
        )

        # Get current mode from Redis
        risk_data = await self.redis._client.hgetall("risk")
        mode = risk_data.get("mode", "paper") if risk_data else "paper"

        decision_record = self._build_decision_record(
            symbol=symbol,
            market_data=market_data,
            regime=regime,
            decision=decision,
            reason=reason,
            position_data=position_data,
            mode=mode,
            context=context,
        )

        try:
            await self.redis._client.xadd(
                "strategy:decisions",
                decision_record,
                maxlen=5000,  # ~48h * 3 symbols * ~30 strategies
            )
            self._log_decision_details(
                market_data=market_data,
                decision=decision,
                reason=reason,
                position_data=position_data,
                regime=regime,
                mfi_bull=mfi_bull,
                mfi_bear=mfi_bear,
                adx_trend=adx_trend,
                context=context,
            )
            self._emit_structured_decision_log(
                symbol=symbol,
                market_data=market_data,
                decision=decision,
                regime=regime,
                reason=reason,
            )
        except Exception as e:
            logger.error(f"Failed to record decision for {symbol}: {e}")

    async def _update_regime_snapshot(
        self,
        symbol: str,
        market_data: MarketData,
        context: MarketContext | None = None,
    ) -> None:
        """Publish latest per-symbol regime snapshot for dashboard freshness."""
        interval = self._regime_snapshot_interval_seconds
        if interval <= 0:
            return

        now_sec = time.time()
        last_sec = self._last_regime_snapshot_time.get(symbol, 0.0)
        if now_sec - last_sec < interval:
            return
        self._last_regime_snapshot_time[symbol] = now_sec

        regime = self._get_decision_regime(market_data, context)
        trend = context.trend if context is not None else self._trend_from_regime(regime)
        now_ms = int(now_sec * 1000)
        payload = {
            "symbol": symbol,
            "strategy": self.name,
            "market": self.market,
            "regime": regime,
            "trend": trend,
            "price": round(float(market_data.close), 8),
            "timestamp_ms": now_ms,
            "timestamp": datetime.fromtimestamp(now_ms / 1000).isoformat(),
        }

        try:
            await self.redis.set_regime_snapshot(symbol, payload)
        except Exception as exc:
            logger.debug("%s: failed to update regime snapshot: %s", symbol, exc)

    def _get_decision_regime(
        self,
        market_data: MarketData,
        context: MarketContext | None,
    ) -> str:
        if context is not None:
            return context.regime
        return self._build_market_context(market_data).regime

    def _get_entry_thresholds_for_decision(self) -> tuple[float, float, float]:
        mfi_bull = 52.0
        mfi_bear = 48.0
        adx_trend = 20.0
        if hasattr(self.entry_strategy, "params"):
            params = self.entry_strategy.params
            mfi_bull = getattr(params, "mfi_bull", 52.0)
            mfi_bear = getattr(params, "mfi_bear", 48.0)
            adx_trend = getattr(params, "adx_trend", 20.0)
        return mfi_bull, mfi_bear, adx_trend

    def _build_decision_snapshot(
        self,
        market_data: MarketData,
        regime: str,
        position: dict | None,
        mfi_bull: float,
        mfi_bear: float,
        adx_trend: float,
    ) -> tuple[str, str, dict[str, Any]]:
        if position and float(position.get("quantity", 0)) > 0:
            return self._build_hold_decision_snapshot(market_data, position)
        return self._build_entry_decision_snapshot(
            market_data=market_data,
            regime=regime,
            mfi_bull=mfi_bull,
            mfi_bear=mfi_bear,
            adx_trend=adx_trend,
        )

    def _build_hold_decision_snapshot(
        self,
        market_data: MarketData,
        position: dict,
    ) -> tuple[str, str, dict[str, Any]]:
        entry_price = float(position.get("entry_price", 0))
        quantity = float(position.get("quantity", 0))
        unrealized_pnl = (market_data.close - entry_price) * quantity
        unrealized_pnl_pct = ((market_data.close - entry_price) / entry_price * 100) if entry_price > 0 else 0
        price_change = market_data.close - entry_price

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
        return "HOLD", reason, position_data

    def _build_entry_decision_snapshot(
        self,
        market_data: MarketData,
        regime: str,
        mfi_bull: float,
        mfi_bear: float,
        adx_trend: float,
    ) -> tuple[str, str, dict[str, Any]]:
        hint = self._get_entry_decision_hint(market_data.symbol)
        if hint:
            hint_reason = str(hint.get("reason", "")).strip()
            if hint_reason:
                decision = "BUY" if bool(hint.get("should_enter", False)) else "WAIT"
                return decision, hint_reason, {"active": False}

        should_enter = hasattr(self.entry_strategy, "_should_enter") and self.entry_strategy._should_enter(regime)

        if should_enter:
            reason = (
                f"Entry signal: {regime} (MFI={market_data.mfi:.1f} >= {mfi_bull}, "
                f"ADX={market_data.adx:.1f} >= {adx_trend})"
            )
            return "BUY", reason, {"active": False}

        reasons = []
        if market_data.mfi < mfi_bull:
            reasons.append(f"MFI={market_data.mfi:.1f} < {mfi_bull}")
        if market_data.mfi > mfi_bear:
            reasons.append(f"MFI={market_data.mfi:.1f} > {mfi_bear}")
        if market_data.adx < adx_trend:
            reasons.append(f"ADX={market_data.adx:.1f} < {adx_trend}")
        reason = f"No entry: {regime} | " + ", ".join(reasons) if reasons else f"No entry: {regime}"
        return "WAIT", reason, {"active": False}

    def _build_decision_record(
        self,
        symbol: str,
        market_data: MarketData,
        regime: str,
        decision: str,
        reason: str,
        position_data: dict[str, Any],
        mode: str,
        context: MarketContext | None,
    ) -> dict[str, str]:
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

        if context:
            decision_record["trend"] = context.trend
            decision_record["volatility_score"] = str(round(context.volatility_score, 4))
            decision_record["is_extreme_volatility"] = str(context.is_extreme_volatility)
        return decision_record

    def _log_decision_details(
        self,
        market_data: MarketData,
        decision: str,
        reason: str,
        position_data: dict[str, Any],
        regime: str,
        mfi_bull: float,
        mfi_bear: float,
        adx_trend: float,
        context: MarketContext | None,
    ) -> None:
        log_lines = [
            f"{'='*60}",
            f"[{self.name.upper()}] {market_data.symbol} ({self.market}) - HOURLY DECISION",
            f"{'='*60}",
            f"  Time:     {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"  Price:    ${market_data.close:,.2f}",
            f"  MFI:      {market_data.mfi:.1f} (Bull>{mfi_bull}, Bear<{mfi_bear})",
            f"  ADX:      {market_data.adx:.1f} (Trend>{adx_trend})",
            f"  Regime:   {regime}",
        ]
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
            log_lines.append(
                f"  Position: {position_data['quantity']:.6f} @ ${position_data['entry_price']:,.2f}"
            )
            log_lines.append(
                f"  P&L:      ${position_data['unrealized_pnl']:,.2f} "
                f"({position_data['unrealized_pnl_pct']:+.2f}%)"
            )
        log_lines.append(f"{'='*60}")
        logger.debug("\n".join(log_lines))

    def _emit_structured_decision_log(
        self,
        symbol: str,
        market_data: MarketData,
        decision: str,
        regime: str,
        reason: str,
    ) -> None:
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

    async def _emit_entry_evaluation(
        self,
        market_data: MarketData,
        context: MarketContext,
        signal: Signal | None,
        no_signal_reason: str = "",
    ) -> None:
        """Emit entry evaluation event for observability.

        Args:
            market_data: Current market state.
            context: Market context with trend/volatility.
            signal: Entry signal or None.
            no_signal_reason: Detailed reason when signal is None.
        """
        if not self.emit_events or self.event_emitter is None:
            return

        from trading.core.event_emitter import EntryEvaluationEvent, SafetyRejectionEvent

        thresholds = self._resolve_entry_thresholds()
        checks = self._build_entry_filter_checks(market_data, context, thresholds)

        event = EntryEvaluationEvent(
            timestamp=datetime.now().isoformat(),
            strategy=self.name,
            symbol=market_data.symbol,
            market=self.market,
            adx=market_data.adx,
            adx_threshold=thresholds["adx"],
            adx_passed=checks["adx_passed"],
            regime=context.regime,
            regime_allowed=checks["regime_allowed"],
            volatility_score=context.volatility_score,
            volatility_threshold=thresholds["volatility"],
            volatility_passed=checks["volatility_passed"],
            mfi=market_data.mfi,
            mfi_threshold=thresholds["mfi"],
            mfi_passed=checks["mfi_passed"],
            macd=market_data.macd,
            macd_signal=market_data.macd_signal,
            macd_crossed=checks["macd_crossed"],
            rsi=market_data.rsi,
            signal_generated=signal is not None,
            reason=signal.reason if signal else (no_signal_reason or "No entry signal"),
        )

        await self.event_emitter.emit_entry_evaluation(event)

        if signal is not None:
            return
        rejection = self._resolve_entry_rejection(market_data, context, thresholds, checks)
        if rejection is None:
            return
        rejection_type, reason = rejection
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

        pnl = self._calculate_unrealized_pnl(position, market_data.close)
        exit_levels = self._resolve_exit_levels(position, market_data)
        triggers = self._build_exit_triggers(market_data, exit_levels)
        reason = signal.reason if signal else (
            f"Holding: P&L {'+' if pnl['pct'] >= 0 else ''}{pnl['pct']:.2f}%"
        )

        event = ExitEvaluationEvent(
            timestamp=datetime.now().isoformat(),
            strategy=self.name,
            symbol=market_data.symbol,
            market=self.market,
            entry_price=position.entry_price,
            current_price=market_data.close,
            quantity=position.quantity,
            unrealized_pnl=pnl["value"],
            unrealized_pnl_pct=pnl["pct"],
            stop_loss_price=exit_levels["stop_loss_price"],
            stop_loss_triggered=triggers["stop_loss_triggered"],
            take_profit_price=exit_levels["take_profit_price"],
            take_profit_triggered=triggers["take_profit_triggered"],
            trailing_stop_price=exit_levels["trailing_stop_price"],
            trailing_stop_triggered=triggers["trailing_stop_triggered"],
            macd_exit_signal=triggers["macd_exit_signal"],
            high_water_mark=exit_levels["high_water_mark"],
            drawdown_from_hwm_pct=exit_levels["drawdown_from_hwm_pct"],
            signal_generated=signal is not None,
            reason=reason,
        )

        await self.event_emitter.emit_exit_evaluation(event)

    def _resolve_entry_thresholds(self) -> dict[str, float]:
        thresholds = {"mfi": 52.0, "adx": 20.0, "volatility": 0.03}
        if not hasattr(self.entry_strategy, "params"):
            return thresholds
        params = self.entry_strategy.params
        mfi = getattr(params, "mfi_bull", None)
        adx = getattr(params, "adx_trend", None)
        volatility = getattr(params, "volatility_threshold", None)
        if isinstance(mfi, (int, float)):
            thresholds["mfi"] = float(mfi)
        if isinstance(adx, (int, float)):
            thresholds["adx"] = float(adx)
        if isinstance(volatility, (int, float)):
            thresholds["volatility"] = float(volatility)
        return thresholds

    def _build_entry_filter_checks(
        self, market_data: MarketData, context: MarketContext, thresholds: dict[str, float]
    ) -> dict[str, bool]:
        return {
            "adx_passed": market_data.adx >= thresholds["adx"],
            "mfi_passed": market_data.mfi >= thresholds["mfi"],
            "volatility_passed": context.volatility_score <= thresholds["volatility"],
            "regime_allowed": context.regime in {"BULL_STRONG", "BULL_MODERATE"},
            "macd_crossed": market_data.macd > market_data.macd_signal,
        }

    def _resolve_entry_rejection(
        self,
        market_data: MarketData,
        context: MarketContext,
        thresholds: dict[str, float],
        checks: dict[str, bool],
    ) -> tuple[str, str] | None:
        if not checks["adx_passed"]:
            return "weak_trend", f"ADX={market_data.adx:.1f} < {thresholds['adx']} threshold"
        if not checks["regime_allowed"]:
            return "wrong_regime", f"Regime {context.regime} not allowed for entry"
        if not checks["volatility_passed"]:
            return (
                "extreme_volatility",
                f"Volatility {context.volatility_score:.4f} > {thresholds['volatility']}",
            )
        if not checks["mfi_passed"]:
            return "weak_momentum", f"MFI={market_data.mfi:.1f} < {thresholds['mfi']}"
        return None

    def _calculate_unrealized_pnl(self, position: Position, close: float) -> dict[str, float]:
        pnl = (close - position.entry_price) * position.quantity
        pnl_pct = ((close - position.entry_price) / position.entry_price * 100) if position.entry_price > 0 else 0.0
        return {"value": pnl, "pct": pnl_pct}

    def _resolve_exit_levels(self, position: Position, market_data: MarketData) -> dict[str, float]:
        levels = {
            "stop_loss_price": 0.0,
            "take_profit_price": 0.0,
            "trailing_stop_price": 0.0,
            "high_water_mark": market_data.close,
            "drawdown_from_hwm_pct": 0.0,
        }
        if hasattr(self.exit_strategy, "params"):
            params = self.exit_strategy.params
            stop_loss_pct = getattr(params, "stop_loss_pct", 0.02)
            take_profit_pct = getattr(params, "take_profit_pct", 0.05)
            levels["stop_loss_price"] = position.entry_price * (1 - stop_loss_pct)
            levels["take_profit_price"] = position.entry_price * (1 + take_profit_pct)
        if hasattr(self.exit_strategy, "state") and hasattr(self.exit_strategy.state, "get"):
            hwm_state = self.exit_strategy.state.get(position.symbol, {})
            if isinstance(hwm_state, dict):
                levels["high_water_mark"] = hwm_state.get("high_water_mark", market_data.close)
                levels["trailing_stop_price"] = hwm_state.get("trailing_stop", 0.0)
                if levels["high_water_mark"] > 0:
                    levels["drawdown_from_hwm_pct"] = (
                        (levels["high_water_mark"] - market_data.close) / levels["high_water_mark"] * 100
                    )
        return levels

    def _build_exit_triggers(self, market_data: MarketData, levels: dict[str, float]) -> dict[str, bool]:
        return {
            "stop_loss_triggered": market_data.close <= levels["stop_loss_price"] if levels["stop_loss_price"] > 0 else False,
            "take_profit_triggered": market_data.close >= levels["take_profit_price"] if levels["take_profit_price"] > 0 else False,
            "trailing_stop_triggered": market_data.close <= levels["trailing_stop_price"] if levels["trailing_stop_price"] > 0 else False,
            "macd_exit_signal": market_data.macd < market_data.macd_signal,
        }


async def create_composite_task(
    name: str,
    symbols: list[str],
    redis: RedisStreams,
    entry_strategy: IEntryStrategy,
    exit_strategy: IExitStrategy,
    config: dict | None = None,
    market: str = "spot",
    use_smart_exit: bool = False,
    emit_events: bool = False,
    indicator_service: IndicatorService | None = None,
    context_builder: TradingContextBuilder | None = None,
    regime_version: str = "v2",
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
        emit_events: Whether to emit observability events to Redis streams.
        indicator_service: Shared indicator service for CPU optimization.
        context_builder: Shared context builder for TradingContext.
        regime_version: Regime detection version ("v2" enhanced).

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
        emit_events=emit_events,
        indicator_service=indicator_service,
        context_builder=context_builder,
        regime_version=regime_version,
    )

    # Initialize persistent exit strategy state
    if hasattr(exit_strategy, 'load_state'):
        await exit_strategy.load_state(symbols)
        logger.info(f"{name}: Loaded persistent state for {symbols}")

    return task
