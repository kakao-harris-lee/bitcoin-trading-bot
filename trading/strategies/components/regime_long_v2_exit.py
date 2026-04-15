"""Regime Long v2 exit strategy.

Protective long-only exit rules:
- Bear regime transition
- Peak drawdown breach
- 1-day / 3-day return shocks
- Consecutive close below slow EMA
"""

from __future__ import annotations

import logging
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from .base_exit import BaseExitStrategy
from .models import Position, Signal, TradingContext
from .registry import exit_strategy
from .regime_long_cooldown import activate_cooldown

logger = logging.getLogger(__name__)


@dataclass
class RegimeLongV2ExitParams:
    """Parameters for regime-long v2 exit."""

    market: Literal["spot", "futures"] = "spot"
    cooldown_tag: str = "regime_long_v2"
    cooldown_bars: int = 30

    min_hold_bars: int = 1

    exit_on_bear_regime: bool = True
    bear_regimes: list[str] = field(
        default_factory=lambda: ["BEAR_STRONG", "BEAR_MODERATE"]
    )

    peak_drawdown_exit_pct: float = 0.15  # 15% drawdown from post-entry peak

    drop_1d_lookback_bars: int = 6
    drop_1d_threshold_pct: float = -0.07
    drop_3d_lookback_bars: int = 18
    drop_3d_threshold_pct: float = -0.10

    ema_slow_field: str = "ema_120"
    ema_slow_consecutive_bars: int = 2
    ema_fast_field: str = "ema_20"
    ema_slow_grace_bars_after_entry: int = 0
    ema_slow_grace_seconds_after_entry: int = 0
    ema_slow_min_drawdown_from_hwm_pct: float = 0.0
    ema_slow_require_fast_below_slow: bool = False
    ema_slow_blocked_regimes: list[str] = field(default_factory=list)


@exit_strategy(params_class=RegimeLongV2ExitParams)
class RegimeLongV2ExitStrategy(BaseExitStrategy):
    """Exit long position on structural risk deterioration."""

    def __init__(self, params: RegimeLongV2ExitParams | None = None):
        super().__init__()
        self.params = params or RegimeLongV2ExitParams()
        self._close_history: dict[str, deque[float]] = {}
        self._below_ema_streak: dict[str, int] = {}
        self._last_candle_ts: dict[str, int] = {}

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        p = self.params
        if position.entry_price <= 0 or position.quantity <= 0:
            return None

        key = self._get_position_key(position)
        candle_ts = int(getattr(ctx.market, "timestamp", 0) or 0)
        is_new_candle = self._is_new_candle(key, candle_ts)
        if candle_ts > 0:
            candles_held = self._increment_candles_held(key) if is_new_candle else self._get_candles_held(key)
        else:
            candles_held = self._increment_candles_held(key)
            is_new_candle = True
        close = float(ctx.market.close)
        high = float(ctx.market.high) if ctx.market.high > 0 else close
        position_age_seconds = self._position_age_seconds(ctx, position, candle_ts)

        history = self._close_history.setdefault(
            key,
            deque(
                maxlen=max(
                    int(p.drop_3d_lookback_bars), int(p.drop_1d_lookback_bars), 1
                )
                + 2
            ),
        )
        if is_new_candle:
            history.append(close)

        hwm = self._update_hwm(key, high, position.entry_price)
        dd_from_hwm = (close / hwm) - 1.0 if hwm > 0 else 0.0

        if p.min_hold_bars > 0 and candles_held < p.min_hold_bars:
            return None

        if p.exit_on_bear_regime and ctx.regime.regime in set(p.bear_regimes):
            return self._make_exit(
                position=position,
                key=key,
                reason=f"RegimeLongV2 risk exit: bear regime ({ctx.regime.regime})",
            )

        if dd_from_hwm <= -abs(p.peak_drawdown_exit_pct):
            return self._make_exit(
                position=position,
                key=key,
                reason=(
                    "RegimeLongV2 risk exit: peak drawdown "
                    f"{dd_from_hwm*100:.2f}% <= -{abs(p.peak_drawdown_exit_pct)*100:.2f}%"
                ),
            )

        ret_1d = self._return_over_bars(history, p.drop_1d_lookback_bars)
        if ret_1d is not None and ret_1d <= p.drop_1d_threshold_pct:
            return self._make_exit(
                position=position,
                key=key,
                reason=(
                    "RegimeLongV2 risk exit: 1d shock "
                    f"{ret_1d*100:.2f}% <= {p.drop_1d_threshold_pct*100:.2f}%"
                ),
            )

        ret_3d = self._return_over_bars(history, p.drop_3d_lookback_bars)
        if ret_3d is not None and ret_3d <= p.drop_3d_threshold_pct:
            return self._make_exit(
                position=position,
                key=key,
                reason=(
                    "RegimeLongV2 risk exit: 3d shock "
                    f"{ret_3d*100:.2f}% <= {p.drop_3d_threshold_pct*100:.2f}%"
                ),
            )

        if is_new_candle:
            ema_slow = float(getattr(ctx.market, p.ema_slow_field, 0.0) or 0.0)
            if ema_slow > 0 and close < ema_slow:
                self._below_ema_streak[key] = self._below_ema_streak.get(key, 0) + 1
            else:
                self._below_ema_streak[key] = 0

        if self._below_ema_streak.get(key, 0) >= max(
            int(p.ema_slow_consecutive_bars), 1
        ):
            if int(p.ema_slow_grace_bars_after_entry) > 0 and candles_held < int(
                p.ema_slow_grace_bars_after_entry
            ):
                return None
            if (
                int(p.ema_slow_grace_seconds_after_entry) > 0
                and position_age_seconds < int(p.ema_slow_grace_seconds_after_entry)
            ):
                return None
            if ctx.regime.regime in set(p.ema_slow_blocked_regimes or []):
                return None
            if (
                abs(float(p.ema_slow_min_drawdown_from_hwm_pct)) > 0
                and dd_from_hwm > -abs(float(p.ema_slow_min_drawdown_from_hwm_pct))
            ):
                return None
            if p.ema_slow_require_fast_below_slow:
                ema_fast = float(getattr(ctx.market, p.ema_fast_field, 0.0) or 0.0)
                ema_slow = float(getattr(ctx.market, p.ema_slow_field, 0.0) or 0.0)
                if ema_fast > 0 and ema_slow > 0 and ema_fast >= ema_slow:
                    return None
            return self._make_exit(
                position=position,
                key=key,
                reason=(
                    "RegimeLongV2 risk exit: below "
                    f"{p.ema_slow_field} streak={self._below_ema_streak[key]}"
                ),
            )

        return None

    def on_position_opened(self, position: Position) -> None:
        super().on_position_opened(position)
        key = self._get_position_key(position)
        history = self._close_history.setdefault(key, deque(maxlen=64))
        if not history:
            history.append(float(position.entry_price))
        self._below_ema_streak[key] = 0
        self._last_candle_ts.pop(key, None)

    def on_position_closed(self, symbol: str) -> None:
        super().on_position_closed(symbol)
        stale_hist = [k for k in self._close_history if k.startswith(f"{symbol}:")]
        stale_streak = [k for k in self._below_ema_streak if k.startswith(f"{symbol}:")]
        stale_candle_ts = [k for k in self._last_candle_ts if k.startswith(f"{symbol}:")]
        for key in stale_hist:
            self._close_history.pop(key, None)
        for key in stale_streak:
            self._below_ema_streak.pop(key, None)
        for key in stale_candle_ts:
            self._last_candle_ts.pop(key, None)

    def _return_over_bars(self, history: deque[float], lookback: int) -> float | None:
        n = int(lookback)
        if n <= 0:
            return None
        if len(history) <= n:
            return None
        ref = float(history[-(n + 1)])
        cur = float(history[-1])
        if ref <= 0:
            return None
        return (cur / ref) - 1.0

    @staticmethod
    def _position_age_seconds(
        ctx: TradingContext,
        position: Position,
        candle_ts: int,
    ) -> int:
        current_ts = int(getattr(ctx, "timestamp", 0) or candle_ts or 0)
        entry_ts = int(position.entry_time or position.timestamp or 0)
        if current_ts <= 0 or entry_ts <= 0 or current_ts <= entry_ts:
            return 0
        return int((current_ts - entry_ts) / 1000)

    def _make_exit(self, position: Position, key: str, reason: str) -> Signal:
        p = self.params
        if p.cooldown_bars > 0:
            activate_cooldown(position.symbol, p.cooldown_tag, int(p.cooldown_bars))
        logger.info("%s: %s", position.symbol, reason)
        self._clear_state(key)
        self._close_history.pop(key, None)
        self._below_ema_streak.pop(key, None)
        self._last_candle_ts.pop(key, None)
        return self._create_exit_signal(position=position, reason=reason)

    def _is_new_candle(self, key: str, candle_ts: int) -> bool:
        if candle_ts <= 0:
            return True
        last_ts = self._last_candle_ts.get(key)
        if last_ts is None:
            self._last_candle_ts[key] = candle_ts
            return False
        if candle_ts > last_ts:
            self._last_candle_ts[key] = candle_ts
            return True
        return False
