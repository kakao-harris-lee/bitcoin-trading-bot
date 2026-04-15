"""Regime Long v2 entry strategy.

Long-only entry based on risk-on persistence over a rolling lookback window.
"""

from __future__ import annotations

import logging
import math
from collections import deque
from dataclasses import dataclass, field
from typing import Literal

from .models import BEAR_REGIMES, Signal, TradingContext
from .registry import entry_strategy
from .regime_long_cooldown import consume_cooldown

logger = logging.getLogger(__name__)


@dataclass
class RegimeLongV2EntryParams:
    """Parameters for regime-long v2 entry."""

    position_size: float = 1.0
    market: Literal["spot", "futures"] = "spot"

    cooldown_tag: str = "regime_long_v2"
    cooldown_bars: int = 30

    allowed_regimes: list[str] = field(
        default_factory=lambda: ["BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"]
    )
    block_bear_regime: bool = True
    block_extreme_volatility: bool = True

    entry_lookback_bars: int = 24
    entry_quorum_ratio: float = 0.75
    entry_quorum_min_hits: int = 0
    min_ready_bars: int = 12

    risk_on_score_min: int = 3
    adx_trend_threshold: float = 18.0
    require_close_above_ema20: bool = True
    require_close_above_ema120: bool = False
    require_ema5_above_ema20: bool = False
    require_ema20_above_ema120: bool = True
    require_rsi_above_50: bool = True
    require_mfi_above_50: bool = True
    require_adx_trend: bool = True
    min_volume_ratio: float = 0.0
    min_breakout_ratio: float = -1.0


@entry_strategy(params_class=RegimeLongV2EntryParams)
class RegimeLongV2EntryStrategy:
    """Enter long when risk-on persistence confirms trend."""

    def __init__(self, params: RegimeLongV2EntryParams | None = None):
        self.params = params or RegimeLongV2EntryParams()
        self._risk_on_history: dict[str, deque[int]] = {}
        self._last_rejection_reason: dict[str, str] = {}

    def get_last_rejection_reason(self, symbol: str) -> str | None:
        return self._last_rejection_reason.get(symbol)

    def _set_rejection_reason(self, symbol: str, reason: str) -> None:
        self._last_rejection_reason[symbol] = reason

    def _clear_rejection_reason(self, symbol: str) -> None:
        self._last_rejection_reason.pop(symbol, None)

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        p = self.params
        market = ctx.market
        regime = ctx.regime
        symbol = market.symbol

        cooldown_remaining = consume_cooldown(symbol, p.cooldown_tag, ctx.timestamp)
        if cooldown_remaining > 0:
            logger.debug(
                "%s: RegimeLongV2 entry blocked - cooldown=%d",
                symbol,
                cooldown_remaining,
            )
            self._set_rejection_reason(symbol, f"RegimeLongV2 cooldown active ({cooldown_remaining})")
            return None

        if p.block_bear_regime and regime.regime in BEAR_REGIMES:
            self._set_rejection_reason(symbol, f"RegimeLongV2 blocked by bear regime ({regime.regime})")
            return None

        if p.allowed_regimes and regime.regime not in set(p.allowed_regimes):
            self._set_rejection_reason(symbol, f"RegimeLongV2 regime not allowed ({regime.regime})")
            return None

        if p.block_extreme_volatility and regime.is_extreme_volatility:
            self._set_rejection_reason(symbol, "RegimeLongV2 blocked by extreme volatility")
            return None

        risk_on, score = self._compute_risk_on_score(ctx)
        history = self._risk_on_history.setdefault(
            symbol,
            deque(maxlen=max(int(p.entry_lookback_bars), 1)),
        )
        history.append(1 if risk_on else 0)

        if len(history) < max(int(p.min_ready_bars), 1):
            self._set_rejection_reason(
                symbol,
                f"RegimeLongV2 waiting for ready bars ({len(history)}/{max(int(p.min_ready_bars), 1)})",
            )
            return None

        hits = sum(history)
        if p.entry_quorum_min_hits > 0:
            required_hits = int(p.entry_quorum_min_hits)
        else:
            required_hits = int(
                math.ceil(len(history) * max(min(p.entry_quorum_ratio, 1.0), 0.0))
            )
            required_hits = max(required_hits, 1)

        if hits < required_hits:
            self._set_rejection_reason(
                symbol,
                f"RegimeLongV2 quorum miss ({hits}/{len(history)} < {required_hits}, score={score})",
            )
            return None

        reason = (
            f"RegimeLongV2 entry: regime={regime.regime}, "
            f"risk_on_hits={hits}/{len(history)} (need>={required_hits}), score={score}"
        )
        logger.info("%s: %s", symbol, reason)
        self._clear_rejection_reason(symbol)
        return Signal(
            symbol=symbol,
            side="buy",
            market=p.market,
            quantity=p.position_size,
            reason=reason,
        )

    def _compute_risk_on_score(self, ctx: TradingContext) -> tuple[bool, int]:
        p = self.params
        market = ctx.market

        checks: list[bool] = []
        if p.require_close_above_ema20:
            checks.append(market.ema_20 > 0 and market.close > market.ema_20)
        if p.require_close_above_ema120:
            checks.append(market.ema_120 > 0 and market.close > market.ema_120)
        if p.require_ema5_above_ema20:
            checks.append(market.ema_5 > 0 and market.ema_20 > 0 and market.ema_5 > market.ema_20)
        if p.require_ema20_above_ema120:
            checks.append(
                market.ema_20 > 0
                and market.ema_120 > 0
                and market.ema_20 > market.ema_120
            )
        if p.require_rsi_above_50:
            checks.append(market.rsi >= 50.0)
        if p.require_mfi_above_50:
            checks.append(market.mfi >= 50.0)
        if p.require_adx_trend:
            checks.append(market.adx >= p.adx_trend_threshold)
        if p.min_volume_ratio > 0:
            volume_ratio = (market.volume / market.avg_volume_20) if market.avg_volume_20 > 0 else 0.0
            checks.append(volume_ratio >= p.min_volume_ratio)
        if p.min_breakout_ratio > -1.0 and market.prev_high_20 > 0:
            breakout_ratio = (market.close / market.prev_high_20) - 1.0
            checks.append(breakout_ratio >= p.min_breakout_ratio)

        score = sum(1 for ok in checks if ok)
        return score >= int(p.risk_on_score_min), score
