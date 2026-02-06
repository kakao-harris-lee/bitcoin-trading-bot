"""Bear Short Exit Strategy - conservative exit for bear short positions.

Exit conditions (checked in order):
1. Stop Loss: Price rose 3% (short P&L <= -3%)
2. Take Profit: Price dropped 5% (short P&L >= 5%)
3. Regime Change: Regime left BEAR zone (not BEAR_STRONG or BEAR_MODERATE)

Simpler than short_v1 exit: no RSI oversold exit, no profit-required regime exit.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import BEAR_REGIMES, Position, Signal, TradingContext
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class BearShortExitParams:
    """Parameters for Bear Short exit strategy."""

    # Stop loss: price rose this much (loss for short)
    stop_loss_pct: float = 3.0

    # Take profit: price dropped this much (profit for short)
    take_profit_pct: float = 5.0

    market: Literal["futures"] = "futures"


@exit_strategy(params_class=BearShortExitParams)
class BearShortExitStrategy:
    """Conservative exit strategy for bear short positions.

    Exit conditions (checked in order):
    1. Stop Loss: Price rose too much (short P&L <= -stop_loss_pct)
    2. Take Profit: Price dropped enough (short P&L >= take_profit_pct)
    3. Regime Change: Not in BEAR_STRONG or BEAR_MODERATE anymore

    For shorts: P&L = (entry - current) / entry * 100
    Exit side is "buy" to cover the short position.

    Stateless - no trailing stop tracking needed.
    Implements IExitStrategy protocol (structural subtyping).
    """

    def __init__(self, params: BearShortExitParams | None = None):
        self.params = params or BearShortExitParams()

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

        if entry_price <= 0 or quantity <= 0:
            return None

        p = self.params

        # For shorts: profit when price drops, loss when price rises
        pnl_pct = ((entry_price - current_price) / entry_price) * 100

        # Exit 1: Stop loss (price rose too much)
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"BearShort exit: Stop loss {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        # Exit 2: Take profit (price dropped enough)
        if pnl_pct >= p.take_profit_pct:
            reason = f"BearShort exit: Take profit {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        # Exit 3: Regime change (no longer in BEAR zone)
        regime = ctx.regime.regime
        if regime not in BEAR_REGIMES:
            reason = (
                f"BearShort exit: Regime change to {regime}, "
                f"P&L={pnl_pct:.2f}%"
            )
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        return None

    def on_position_opened(self, position: Position) -> None:
        """Called when a new short position is opened."""
        logger.debug(
            f"{position.symbol}: BearShort position opened at {position.entry_price}"
        )

    def on_position_closed(self, symbol: str) -> None:
        """Called when short position is closed."""
        logger.debug(f"{symbol}: BearShort position closed")

    def _create_exit_signal(self, position: Position, reason: str) -> Signal:
        """Create exit signal for short position (buy to cover)."""
        return Signal(
            symbol=position.symbol,
            side="buy",
            market=position.market,
            quantity=position.quantity,
            reason=reason,
        )
