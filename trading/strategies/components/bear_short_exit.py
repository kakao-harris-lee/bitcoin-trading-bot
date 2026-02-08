"""Bear Short Exit Strategy - exit for bear short positions with trailing stop.

Exit conditions (checked in order):
1. Stop Loss: Price rose too much (short P&L <= -stop_loss_pct)
2. Take Profit: Price dropped enough (short P&L >= take_profit_pct)
3. Trailing Stop: Price bounced from Low Water Mark (locks profit on extended bear moves)
4. Regime Change: Regime turned bullish for N consecutive candles (grace period)

SIDEWAYS_DOWN is allowed by default (still bearish-leaning).
Only BULL_* regimes trigger the exit, with a configurable grace period
to avoid premature exits from regime flickering.

Extends BaseExitStrategy for state management (LWM tracking, position lifecycle).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .base_exit import BaseExitStrategy
from .models import BEAR_REGIMES, Position, Signal, TradingContext
from .registry import exit_strategy

logger = logging.getLogger(__name__)


# Regimes where short positions are allowed to stay open
BEAR_SHORT_HOLD_REGIMES = {
    "BEAR_STRONG", "BEAR_MODERATE", "SIDEWAYS_DOWN", "SIDEWAYS_FLAT",
}


@dataclass
class BearShortExitParams:
    """Parameters for Bear Short exit strategy."""

    # Stop loss: price rose this much (loss for short)
    stop_loss_pct: float = 3.0

    # Take profit: price dropped this much (profit for short)
    take_profit_pct: float = 5.0

    # Trailing stop: activate after this much profit (% from entry)
    trailing_enabled: bool = True
    trailing_activation: float = 2.0  # activate after 2% short profit
    trailing_distance: float = 1.5    # trail 1.5% above LWM

    # Regime exit: only exit after N consecutive non-hold candles
    regime_exit_grace: int = 3  # candles to wait before regime exit

    market: Literal["futures"] = "futures"


@exit_strategy(params_class=BearShortExitParams)
class BearShortExitStrategy(BaseExitStrategy):
    """Exit strategy for bear short positions with trailing stop.

    Exit conditions (checked in order):
    1. Stop Loss: Price rose too much (short P&L <= -stop_loss_pct)
    2. Take Profit: Price dropped enough (short P&L >= take_profit_pct)
    3. Trailing Stop: Price bounced from LWM beyond trailing_distance
    4. Regime Change: Not in BEAR_STRONG or BEAR_MODERATE anymore

    For shorts: P&L = (entry - current) / entry * 100
    Exit side is "buy" to cover the short position.

    Low Water Mark (LWM) tracks the lowest price seen — the mirror of HWM for longs.
    When price bounces above LWM + trailing_distance%, profit is locked.

    Inherits from BaseExitStrategy for position state management.
    """

    def __init__(self, params: BearShortExitParams | None = None):
        super().__init__()
        self.params = params or BearShortExitParams()
        # Low Water Marks: track lowest price per position (shorts profit from price drops)
        self._low_water_marks: dict[str, float] = {}
        # Regime exit grace: count consecutive non-hold candles per position
        self._regime_exit_count: dict[str, int] = {}

    def check_exit(
        self,
        ctx: TradingContext,
        position: Position,
    ) -> Signal | None:
        """Evaluate exit conditions for bear short position.

        Args:
            ctx: Trading context with market data and regime.
            position: Current open short position.

        Returns:
            Signal to close (cover) position, or None to hold.
        """
        market_data = ctx.market
        symbol = position.symbol
        entry_price = position.entry_price
        quantity = position.quantity
        current_price = market_data.close
        key = self._get_position_key(position)

        if entry_price <= 0 or quantity <= 0:
            return None

        p = self.params

        # For shorts: profit when price drops, loss when price rises
        pnl_pct = ((entry_price - current_price) / entry_price) * 100

        # Update Low Water Mark (lowest price seen = best profit point for shorts)
        lwm = self._update_lwm(key, current_price, entry_price)

        # Exit 1: Stop loss (price rose too much)
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"BearShort exit: Stop loss {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason, quantity=position.quantity, side="buy")

        # Exit 2: Take profit (price dropped enough)
        if pnl_pct >= p.take_profit_pct:
            reason = f"BearShort exit: Take profit {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(key)
            return self._create_exit_signal(position, reason, quantity=position.quantity, side="buy")

        # Exit 3: Trailing stop (lock profit on bounce from low)
        if p.trailing_enabled and lwm > 0:
            lwm_pnl = ((entry_price - lwm) / entry_price) * 100  # profit % at LWM
            if lwm_pnl >= p.trailing_activation:
                trailing_stop_price = lwm * (1 + p.trailing_distance / 100)
                if current_price >= trailing_stop_price:
                    locked_pnl = ((entry_price - trailing_stop_price) / entry_price) * 100
                    reason = (
                        f"BearShort exit: Trailing stop {pnl_pct:.2f}% "
                        f"(LWM profit={lwm_pnl:.2f}%, locked~{locked_pnl:.2f}%)"
                    )
                    logger.info(f"{symbol}: {reason}")
                    self._clear_state(key)
                    return self._create_exit_signal(position, reason, quantity=position.quantity, side="buy")

        # Exit 4: Regime change (no longer in bearish/sideways zone)
        regime = ctx.regime.regime
        if regime not in BEAR_SHORT_HOLD_REGIMES:
            self._regime_exit_count[key] = self._regime_exit_count.get(key, 0) + 1
            if self._regime_exit_count[key] >= p.regime_exit_grace:
                reason = (
                    f"BearShort exit: Regime {regime} for "
                    f"{self._regime_exit_count[key]} candles, P&L={pnl_pct:.2f}%"
                )
                logger.info(f"{symbol}: {reason}")
                self._clear_state(key)
                return self._create_exit_signal(position, reason, quantity=position.quantity, side="buy")
        else:
            # Reset counter when regime returns to hold zone
            self._regime_exit_count.pop(key, None)

        return None

    # === Low Water Mark Management (mirror of HWM for shorts) ===

    def _update_lwm(self, key: str, current_price: float, entry_price: float) -> float:
        """Update and return Low Water Mark (lowest price seen).

        Args:
            key: Position key.
            current_price: Current market price.
            entry_price: Position entry price (used as initial LWM).

        Returns:
            Updated low water mark.
        """
        lwm = self._low_water_marks.get(key, entry_price)
        if current_price < lwm:
            lwm = current_price
            self._low_water_marks[key] = lwm
        return lwm

    def _get_lwm(self, key: str, default: float = 0.0) -> float:
        """Get current Low Water Mark."""
        return self._low_water_marks.get(key, default)

    # === Lifecycle Overrides ===

    def on_position_opened(self, position: Position) -> None:
        """Called when a new short position is opened."""
        super().on_position_opened(position)
        key = self._get_position_key(position)
        # Initialize LWM to entry price
        self._low_water_marks[key] = position.entry_price
        logger.debug(
            f"{position.symbol}: BearShort position opened at {position.entry_price}"
        )

    def on_position_closed(self, symbol: str) -> None:
        """Called when short position is closed."""
        super().on_position_closed(symbol)
        # Clear LWM and regime counter state for all keys with this symbol
        for store in (self._low_water_marks, self._regime_exit_count):
            keys = [k for k in store if k.startswith(f"{symbol}:")]
            for k in keys:
                store.pop(k, None)
        logger.debug(f"{symbol}: BearShort position closed")

    def _clear_state(self, key: str) -> None:
        """Clear all state for a position including LWM and regime counter."""
        super()._clear_state(key)
        self._low_water_marks.pop(key, None)
        self._regime_exit_count.pop(key, None)
