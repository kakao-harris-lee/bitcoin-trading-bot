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


@exit_strategy(params_class=RegimeLongV2ExitParams)
class RegimeLongV2ExitStrategy(BaseExitStrategy):
    """Exit long position on structural risk deterioration."""

    def __init__(self, params: RegimeLongV2ExitParams | None = None):
        super().__init__()
        self.params = params or RegimeLongV2ExitParams()
        self._close_history: dict[str, deque[float]] = {}
        self._below_ema_streak: dict[str, int] = {}

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        p = self.params
        if position.entry_price <= 0 or position.quantity <= 0:
            return None

        key = self._get_position_key(position)
        candles_held = self._increment_candles_held(key)
        close = float(ctx.market.close)
        high = float(ctx.market.high) if ctx.market.high > 0 else close

        history = self._close_history.setdefault(
            key,
            deque(
                maxlen=max(
                    int(p.drop_3d_lookback_bars), int(p.drop_1d_lookback_bars), 1
                )
                + 2
            ),
        )
        history.append(close)

        if p.min_hold_bars > 0 and candles_held < p.min_hold_bars:
            return None

        hwm = self._update_hwm(key, high, position.entry_price)
        dd_from_hwm = (close / hwm) - 1.0 if hwm > 0 else 0.0

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

        ema_slow = float(getattr(ctx.market, p.ema_slow_field, 0.0) or 0.0)
        if ema_slow > 0 and close < ema_slow:
            self._below_ema_streak[key] = self._below_ema_streak.get(key, 0) + 1
        else:
            self._below_ema_streak[key] = 0

        if self._below_ema_streak.get(key, 0) >= max(
            int(p.ema_slow_consecutive_bars), 1
        ):
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

    def on_position_closed(self, symbol: str) -> None:
        super().on_position_closed(symbol)
        stale_hist = [k for k in self._close_history if k.startswith(f"{symbol}:")]
        stale_streak = [k for k in self._below_ema_streak if k.startswith(f"{symbol}:")]
        for key in stale_hist:
            self._close_history.pop(key, None)
        for key in stale_streak:
            self._below_ema_streak.pop(key, None)

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

    def _make_exit(self, position: Position, key: str, reason: str) -> Signal:
        p = self.params
        if p.cooldown_bars > 0:
            activate_cooldown(position.symbol, p.cooldown_tag, int(p.cooldown_bars))
        logger.info("%s: %s", position.symbol, reason)
        self._clear_state(key)
        self._close_history.pop(key, None)
        self._below_ema_streak.pop(key, None)
        return self._create_exit_signal(position=position, reason=reason)
