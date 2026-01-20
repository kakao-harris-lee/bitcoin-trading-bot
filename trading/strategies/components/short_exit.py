"""ShortV1 Exit Strategy - extracted from ShortV1Task.

Implements IExitStrategy protocol for short position exit.
Exit conditions: Stop loss, take profit, RSI oversold, or regime change to bull.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Position, Signal, TradingContext, BULL_REGIMES
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class ShortExitParams:
    """Parameters for Short exit strategy."""

    # Stop loss: price rose this much (loss for short)
    stop_loss_pct: float = 2.0

    # Take profit: price dropped this much (profit for short)
    take_profit_pct: float = 3.0

    # RSI threshold for covering short (oversold = mean reversion done)
    rsi_oversold: float = 30.0

    # Regime classification thresholds
    mfi_bear: float = 48.0
    mfi_bull: float = 52.0
    adx_trend: float = 20.0

    market: Literal["futures"] = "futures"


@exit_strategy(params_class=ShortExitParams)
class ShortExitStrategy:
    """Short position exit strategy.

    Exit conditions (checked in order):
    1. Stop Loss: Price rose too much (short P&L <= -stop_loss_pct)
    2. Take Profit: Price dropped enough (short P&L >= take_profit_pct)
    3. RSI Oversold: Mean reversion complete, cover short
    4. Regime Change: Bull regime with profit, lock in gains

    Note: For shorts, P&L = (entry - current) / entry * 100
    Exit side is "buy" to cover the short position.

    Stateless - no trailing stop tracking needed.

    Implements IExitStrategy protocol (structural subtyping).
    """

    def __init__(self, params: ShortExitParams | None = None):
        """Initialize with exit parameters.

        Args:
            params: Exit parameters. Uses defaults if not provided.
        """
        self.params = params or ShortExitParams()

    def check_exit(
        self,
        ctx: TradingContext,
        position: Position,
    ) -> Signal | None:
        """Evaluate exit conditions for short position.

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
        # P&L % = (entry - current) / entry * 100
        pnl_pct = ((entry_price - current_price) / entry_price) * 100

        # Exit condition 1: Stop loss (price rose too much)
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"ShortV1 exit: Stop loss {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        # Exit condition 2: Take profit (price dropped enough)
        if pnl_pct >= p.take_profit_pct:
            reason = f"ShortV1 exit: Take profit {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        # Exit condition 3: RSI oversold (mean reversion complete)
        if market_data.rsi <= p.rsi_oversold:
            reason = f"ShortV1 exit: RSI={market_data.rsi:.1f} (oversold), P&L={pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        # Exit condition 4: Regime change to bullish (only if in profit)
        # Use centralized regime from TradingContext
        regime = ctx.regime.regime
        if regime in BULL_REGIMES and pnl_pct > 0:
            reason = f"ShortV1 exit: Regime change to {regime}, locking {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        return None

    def on_position_opened(self, position: Position) -> None:
        """Called when a new short position is opened.

        No state initialization needed for this stateless strategy.

        Args:
            position: The newly opened position.
        """
        logger.debug(f"{position.symbol}: ShortV1 position opened at {position.entry_price}")

    def on_position_closed(self, symbol: str) -> None:
        """Called when short position is closed.

        No state cleanup needed for this stateless strategy.

        Args:
            symbol: The symbol whose position was closed.
        """
        logger.debug(f"{symbol}: ShortV1 position closed")

    def _create_exit_signal(self, position: Position, reason: str) -> Signal:
        """Create exit signal for short position.

        Note: Exit side is "buy" to cover the short.

        Args:
            position: Position to close.
            reason: Exit reason for logging.

        Returns:
            Signal to cover (close) the short position.
        """
        return Signal(
            symbol=position.symbol,
            side="buy",  # Buy to cover short
            market=position.market,
            quantity=position.quantity,
            reason=reason,
        )
