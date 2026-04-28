"""Protective long exit strategy used by LLM entry strategies."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

import numpy as np

from .base_exit import BaseExitStrategy
from .models import BULL_REGIMES, MarketData, Position, Signal, TradingContext
from .registry import exit_strategy
from trading.utils.pnl import calculate_hwm_pnl_pct, calculate_pnl_pct

logger = logging.getLogger(__name__)


@dataclass
class LLMDirectionExitParams:
    """Protective exit params for LLM-driven long entries."""

    stop_loss_pct: float = 10.0

    fwin_exit_enabled: bool = True
    fwin_periods: int = 2

    atr_stop_enabled: bool = False
    atr_stop_multiplier: float = 3.0
    atr_stop_min_pct: float = 5.0
    atr_stop_max_pct: float = 15.0

    trailing_enabled: bool = False
    trailing_activation: float = 10.0
    trailing_distance: float = 5.0

    take_profit_enabled: bool = False
    take_profit_pct: float = 25.0

    trix_protective_exit_enabled: bool = False
    trix_exit_requires_below_ema200: bool = True
    trix_exit_min_hold_bars: int = 0

    ema_deadcross_exit_enabled: bool = False
    ema_deadcross_consecutive_bars: int = 2
    ema_deadcross_require_below_ema20: bool = True
    ema_deadcross_min_hold_bars: int = 0
    ema_deadcross_blocked_regimes: list[str] | None = None

    market: Literal["spot"] = "spot"

    runtime_switch_enabled: bool = False
    switch_mfi_threshold: float = 50.0
    switch_adx_threshold: float = 18.0
    switch_require_above_ema200: bool = True
    risk_on_stop_loss_pct: float = 0.0
    risk_off_stop_loss_pct: float = 0.0

    intrabar_stop_requires_post_entry_candle: bool = True
    intrabar_stop_grace_bars_after_entry: int = 0
    intrabar_stop_grace_seconds_after_entry: int = 0
    intrabar_stop_hard_exit_pct: float = 0.0
    intrabar_stop_blocked_regimes: list[str] | None = None
    intrabar_stop_require_close_below_stop_in_blocked_regimes: bool = False
    intrabar_stop_require_fast_below_slow_in_blocked_regimes: bool = False
    intrabar_stop_fast_field: str = "ema_20"
    intrabar_stop_slow_field: str = "ema_120"


@exit_strategy(params_class=LLMDirectionExitParams)
class LLMDirectionExitStrategy(BaseExitStrategy):
    """Protective exit stack for LLM entry strategies.

    This keeps the non-model exit logic from the legacy long stack:
    stop loss, ATR stop, TRIX protective exit, EMA deadcross, FWin,
    take profit, and trailing stop. Model-based SELL exits are removed.
    """

    def __init__(self, params: LLMDirectionExitParams | None = None):
        super().__init__()
        self.params = params or LLMDirectionExitParams()
        self._ema_deadcross_streaks: dict[str, int] = {}

    def _is_risk_on(self, market_data: MarketData, p: LLMDirectionExitParams) -> bool:
        if market_data.mfi < p.switch_mfi_threshold:
            return False
        if market_data.adx < p.switch_adx_threshold:
            return False
        if p.switch_require_above_ema200 and market_data.ema_200 > 0:
            if market_data.close < market_data.ema_200:
                return False
        return True

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        market_data = ctx.market
        if position.entry_price <= 0 or position.quantity <= 0:
            return None

        key = self._get_position_key(position)
        candles_held = self._increment_candles_held(key)
        pnl_pct, hwm, hwm_pnl = self._compute_position_metrics(position, market_data, key)

        stop_signal = self._check_stop_loss_exit(ctx, position, pnl_pct, key)
        if stop_signal:
            return stop_signal

        ema_deadcross_signal = self._check_ema_deadcross_exit(
            ctx=ctx,
            position=position,
            key=key,
            candles_held=candles_held,
        )
        if ema_deadcross_signal:
            return ema_deadcross_signal

        trix_signal = self._check_trix_protective_exit(
            ctx=ctx,
            position=position,
            key=key,
            candles_held=candles_held,
        )
        if trix_signal:
            return trix_signal

        fwin_signal = self._check_fwin_exit_if_enabled(ctx, position, pnl_pct, key)
        if fwin_signal:
            return fwin_signal

        take_profit_signal = self._check_take_profit_exit(position, pnl_pct, key)
        if take_profit_signal:
            return take_profit_signal

        trailing_signal = self._check_trailing_stop_exit(
            position=position,
            current_price=market_data.close,
            hwm=hwm,
            hwm_pnl=hwm_pnl,
            key=key,
        )
        if trailing_signal:
            return trailing_signal

        return None

    def _compute_position_metrics(
        self,
        position: Position,
        market_data: MarketData,
        key: str,
    ) -> tuple[float, float, float]:
        current_price = market_data.close
        entry_price = position.entry_price
        pnl_pct = calculate_pnl_pct(current_price, entry_price, "long")
        check_price = market_data.high if market_data.high > 0 else current_price
        hwm = self._update_hwm(key, check_price, entry_price)
        hwm_pnl = calculate_hwm_pnl_pct(hwm, entry_price)
        return pnl_pct, hwm, hwm_pnl

    def _check_stop_loss_exit(
        self,
        ctx: TradingContext,
        position: Position,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        stop_pct = self._calculate_stop_loss(ctx, ctx.market, position.entry_price)
        stop_price = position.entry_price * (1.0 - (stop_pct / 100.0))
        close_price = ctx.market.close
        low_price = ctx.market.low if ctx.market.low > 0 else close_price
        intrabar_hit = low_price <= stop_price
        close_below_stop = close_price <= stop_price or pnl_pct <= -stop_pct
        position_age_seconds, elapsed_candles = self._entry_elapsed_metrics(ctx, position)
        hard_intrabar_allowed = self._is_hard_intrabar_hit(position.entry_price, low_price)
        if intrabar_hit and not close_below_stop:
            if (
                self.params.intrabar_stop_requires_post_entry_candle
                and elapsed_candles < 1.0
                and not hard_intrabar_allowed
            ):
                intrabar_hit = False
            elif not self._allow_intrabar_stop(
                ctx=ctx,
                position=position,
                stop_price=stop_price,
                low_price=low_price,
                close_price=close_price,
                position_age_seconds=position_age_seconds,
                elapsed_candles=elapsed_candles,
            ):
                intrabar_hit = False

        if not intrabar_hit and not close_below_stop:
            return None

        if intrabar_hit and not close_below_stop:
            trigger_pnl_pct = ((stop_price - position.entry_price) / position.entry_price) * 100.0
            reason = (
                f"LLMDirection exit: Stop loss intrabar {trigger_pnl_pct:.2f}% "
                f"(limit: -{stop_pct:.1f}%, trigger={stop_price:.2f})"
            )
            trigger_price = stop_price
        else:
            reason = f"LLMDirection exit: Stop loss {pnl_pct:.2f}% (limit: -{stop_pct:.1f}%)"
            trigger_price = None

        logger.info("%s: %s", position.symbol, reason)
        self._clear_all_state(key)
        return self._create_exit_signal(position, reason, trigger_price=trigger_price)

    def _is_hard_intrabar_hit(self, entry_price: float, low_price: float) -> bool:
        hard_exit_pct = abs(float(self.params.intrabar_stop_hard_exit_pct))
        if hard_exit_pct <= 0 or entry_price <= 0:
            return False
        hard_stop_price = entry_price * (1.0 - (hard_exit_pct / 100.0))
        return low_price <= hard_stop_price

    def _entry_elapsed_metrics(self, ctx: TradingContext, position: Position) -> tuple[int, float]:
        entry_ts = int(getattr(position, "entry_time", 0) or 0)
        current_ts = int(getattr(ctx.market, "timestamp", 0) or getattr(ctx, "timestamp", 0) or 0)
        if entry_ts <= 0 or current_ts <= 0 or current_ts <= entry_ts:
            return 0, 0.0
        elapsed_ms = current_ts - entry_ts
        candle_ms = int(getattr(ctx, "candle_ms", 4 * 60 * 60 * 1000) or (4 * 60 * 60 * 1000))
        elapsed_candles = (elapsed_ms / candle_ms) if candle_ms > 0 else 0.0
        return int(elapsed_ms / 1000), elapsed_candles

    def _allow_intrabar_stop(
        self,
        *,
        ctx: TradingContext,
        position: Position,
        stop_price: float,
        low_price: float,
        close_price: float,
        position_age_seconds: int,
        elapsed_candles: float,
    ) -> bool:
        p = self.params
        if self._is_hard_intrabar_hit(position.entry_price, low_price):
            return True

        if int(p.intrabar_stop_grace_bars_after_entry) > 0 and elapsed_candles < int(p.intrabar_stop_grace_bars_after_entry):
            return False
        if int(p.intrabar_stop_grace_seconds_after_entry) > 0 and position_age_seconds < int(p.intrabar_stop_grace_seconds_after_entry):
            return False

        blocked_regimes = set(p.intrabar_stop_blocked_regimes or [])
        if blocked_regimes and ctx.regime.regime in blocked_regimes:
            if p.intrabar_stop_require_close_below_stop_in_blocked_regimes and close_price > stop_price:
                if p.intrabar_stop_require_fast_below_slow_in_blocked_regimes:
                    ema_fast = float(getattr(ctx.market, p.intrabar_stop_fast_field, 0.0) or 0.0)
                    ema_slow = float(getattr(ctx.market, p.intrabar_stop_slow_field, 0.0) or 0.0)
                    if ema_fast > 0 and ema_slow > 0 and ema_fast < ema_slow:
                        return True
                return False

        return True

    def _check_fwin_exit_if_enabled(
        self,
        ctx: TradingContext,
        position: Position,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        if not self.params.fwin_exit_enabled:
            return None
        return self._check_fwin_exit(ctx, position, pnl_pct, key)

    def _check_ema_deadcross_exit(
        self,
        ctx: TradingContext,
        position: Position,
        key: str,
        candles_held: int,
    ) -> Signal | None:
        p = self.params
        if not p.ema_deadcross_exit_enabled:
            return None
        blocked_regimes = set(p.ema_deadcross_blocked_regimes or [])
        if blocked_regimes and ctx.regime.regime in blocked_regimes:
            self._ema_deadcross_streaks[key] = 0
            return None
        if p.ema_deadcross_min_hold_bars > 0 and candles_held < p.ema_deadcross_min_hold_bars:
            return None

        market = ctx.market
        ema_5 = float(getattr(market, "ema_5", 0.0))
        ema_10 = float(getattr(market, "ema_10", 0.0))
        ema_20 = float(getattr(market, "ema_20", 0.0))
        close = float(market.close)

        if not all(np.isfinite(v) and v > 0 for v in (ema_5, ema_10, ema_20, close)):
            self._ema_deadcross_streaks[key] = 0
            return None

        deadcross = ema_5 < ema_10 < ema_20
        if p.ema_deadcross_require_below_ema20:
            deadcross = deadcross and close < ema_20

        if deadcross:
            self._ema_deadcross_streaks[key] = self._ema_deadcross_streaks.get(key, 0) + 1
        else:
            self._ema_deadcross_streaks[key] = 0
            return None

        required_bars = max(int(p.ema_deadcross_consecutive_bars), 1)
        streak = self._ema_deadcross_streaks.get(key, 0)
        if streak < required_bars:
            return None

        reason = (
            "LLMDirection exit: EMA deadcross "
            f"(ema5={ema_5:.2f} < ema10={ema_10:.2f} < ema20={ema_20:.2f}, "
            f"close={close:.2f}, streak={streak}/{required_bars})"
        )
        logger.info("%s: %s", position.symbol, reason)
        self._clear_all_state(key)
        return self._create_exit_signal(position, reason)

    def _check_trix_protective_exit(
        self,
        ctx: TradingContext,
        position: Position,
        key: str,
        candles_held: int,
    ) -> Signal | None:
        p = self.params
        if not p.trix_protective_exit_enabled:
            return None
        if p.trix_exit_min_hold_bars > 0 and candles_held < p.trix_exit_min_hold_bars:
            return None

        market = ctx.market
        trix = float(getattr(market, "trix", 0.0))
        trix_signal = float(getattr(market, "trix_signal", 0.0))

        if not np.isfinite(trix) or not np.isfinite(trix_signal):
            return None
        if trix >= trix_signal:
            return None

        if p.trix_exit_requires_below_ema200 and market.ema_200 > 0 and market.close >= market.ema_200:
            return None

        reason = (
            f"LLMDirection exit: TRIX protective exit "
            f"(trix={trix:.5f} < signal={trix_signal:.5f})"
        )
        if p.trix_exit_requires_below_ema200 and market.ema_200 > 0:
            reason += f", close={market.close:.2f} < ema200={market.ema_200:.2f}"
        logger.info("%s: %s", position.symbol, reason)
        self._clear_all_state(key)
        return self._create_exit_signal(position, reason)

    def _check_take_profit_exit(
        self,
        position: Position,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        p = self.params
        if not p.take_profit_enabled or pnl_pct < p.take_profit_pct:
            return None
        reason = (
            f"LLMDirection exit: Take profit {pnl_pct:.2f}% "
            f"(target: +{p.take_profit_pct:.1f}%)"
        )
        logger.info("%s: %s", position.symbol, reason)
        self._clear_all_state(key)
        return self._create_exit_signal(position, reason)

    def _check_trailing_stop_exit(
        self,
        position: Position,
        current_price: float,
        hwm: float,
        hwm_pnl: float,
        key: str,
    ) -> Signal | None:
        p = self.params
        if not p.trailing_enabled or hwm_pnl < p.trailing_activation:
            return None
        trailing_stop_price = hwm * (1 - p.trailing_distance / 100)
        if current_price > trailing_stop_price:
            return None
        locked_pnl = ((trailing_stop_price - position.entry_price) / position.entry_price) * 100
        reason = f"LLMDirection exit: Trailing stop {locked_pnl:.2f}% (HWM={hwm_pnl:.2f}%)"
        logger.info("%s: %s", position.symbol, reason)
        self._clear_all_state(key)
        return self._create_exit_signal(position, reason)

    def _calculate_stop_loss(
        self,
        ctx: TradingContext,
        market_data: MarketData,
        entry_price: float,
    ) -> float:
        p = self.params
        base_stop_pct = p.stop_loss_pct
        risk_on = False
        if p.runtime_switch_enabled:
            risk_on = self._is_risk_on(ctx.market, p)
            if risk_on:
                if p.risk_on_stop_loss_pct > 0:
                    base_stop_pct = p.risk_on_stop_loss_pct
            else:
                if p.risk_off_stop_loss_pct > 0:
                    base_stop_pct = p.risk_off_stop_loss_pct

        if p.atr_stop_enabled and market_data.atr > 0 and entry_price > 0:
            atr_pct = (market_data.atr / entry_price) * 100
            dynamic_stop_pct = p.atr_stop_multiplier * atr_pct
            effective_stop_pct = max(p.atr_stop_min_pct, min(p.atr_stop_max_pct, dynamic_stop_pct))
            if p.runtime_switch_enabled:
                if risk_on and p.risk_on_stop_loss_pct > 0:
                    effective_stop_pct = max(effective_stop_pct, p.risk_on_stop_loss_pct)
                elif (not risk_on) and p.risk_off_stop_loss_pct > 0:
                    effective_stop_pct = min(effective_stop_pct, p.risk_off_stop_loss_pct)
            return effective_stop_pct

        return base_stop_pct

    def _check_fwin_exit(
        self,
        ctx: TradingContext,
        position: Position,
        pnl_pct: float,
        key: str,
    ) -> Signal | None:
        p = self.params
        symbol = position.symbol
        market_data = ctx.market
        entry_ts = getattr(position, "entry_time", None)
        if entry_ts is None:
            logger.debug("%s: FWin exit skipped - no entry_time in position", symbol)
            return None

        current_ts = getattr(market_data, "timestamp", None)
        if current_ts is None:
            return None

        candle_ms = getattr(ctx, "candle_ms", 4 * 60 * 60 * 1000)
        elapsed_ms = current_ts - entry_ts
        elapsed_candles = elapsed_ms / candle_ms

        if elapsed_candles >= p.fwin_periods:
            reason = (
                f"LLMDirection exit: FWin exit after {elapsed_candles:.1f} candles "
                f"(FWin={p.fwin_periods}), P&L={pnl_pct:.2f}%"
            )
            logger.info("%s: %s", symbol, reason)
            self._clear_all_state(key)
            return self._create_exit_signal(position, reason)

        return None

    def on_position_opened(self, position: Position, entry_timestamp: int | None = None) -> None:
        _ = entry_timestamp
        super().on_position_opened(position)
        key = self._get_position_key(position)
        self._ema_deadcross_streaks[key] = 0
        logger.debug("%s: LLMDirection position opened at %.2f", position.symbol, position.entry_price)

    def on_position_closed(self, symbol: str) -> None:
        super().on_position_closed(symbol)
        stale_keys = [k for k in self._ema_deadcross_streaks if k.startswith(f"{symbol}:")]
        for key in stale_keys:
            self._ema_deadcross_streaks.pop(key, None)
        logger.debug("%s: LLMDirection position closed", symbol)

    def _clear_all_state(self, key: str) -> None:
        self._clear_state(key)
        self._ema_deadcross_streaks.pop(key, None)

    @property
    def high_water_mark(self) -> dict[str, float]:
        return self._high_water_marks.copy()
