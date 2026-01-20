"""SidewaysV2 Exit Strategy - extracted from SidewaysV2Task.

Implements IExitStrategy protocol for sideways/mean-reversion exit.
Exit conditions: Take profit, stop loss, or RSI mean reversion complete.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Position, Signal
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class SidewaysExitParams:
    """Parameters for Sideways exit strategy."""

    # Take profit percentage
    take_profit_pct: float = 1.5

    # Stop loss percentage
    stop_loss_pct: float = 1.0

    # RSI threshold for mean reversion exit
    rsi_mean: float = 50.0

    market: Literal["futures"] = "futures"


@exit_strategy(params_class=SidewaysExitParams)
class SidewaysExitStrategy:
    """Sideways/mean-reversion exit strategy.

    Exit conditions (checked in order):
    1. Take Profit: P&L >= take_profit_pct
    2. Stop Loss: P&L <= -stop_loss_pct
    3. Mean Reversion Complete: RSI >= rsi_mean

    Stateless - no high water mark tracking needed.

    Implements IExitStrategy protocol (structural subtyping).
    """

    def __init__(self, params: SidewaysExitParams | None = None):
        """Initialize with exit parameters.

        Args:
            params: Exit parameters. Uses defaults if not provided.
        """
        self.params = params or SidewaysExitParams()

    def check_exit(
        self,
        position: Position,
        market_data: MarketData,
    ) -> Signal | None:
        """Evaluate exit conditions for position.

        Args:
            position: Current open position.
            market_data: Current market state.

        Returns:
            Signal to close position, or None to hold.
        """
        symbol = position.symbol
        entry_price = position.entry_price
        quantity = position.quantity
        current_price = market_data.close

        if entry_price <= 0 or quantity <= 0:
            return None

        p = self.params

        # Calculate P&L percentage
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Exit condition 1: Take profit
        if pnl_pct >= p.take_profit_pct:
            reason = f"SidewaysV2 exit: Take profit {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        # Exit condition 2: Stop loss
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"SidewaysV2 exit: Stop loss {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        # Exit condition 3: RSI mean reversion complete
        if market_data.rsi >= p.rsi_mean:
            reason = f"SidewaysV2 exit: RSI={market_data.rsi:.1f} (mean reversion)"
            logger.info(f"{symbol}: {reason}")
            return self._create_exit_signal(position, reason)

        return None

    def on_position_opened(self, position: Position) -> None:
        """Called when a new position is opened.

        No state initialization needed for this stateless strategy.

        Args:
            position: The newly opened position.
        """
        logger.debug(f"{position.symbol}: SidewaysV2 position opened")

    def on_position_closed(self, symbol: str) -> None:
        """Called when position is closed.

        No state cleanup needed for this stateless strategy.

        Args:
            symbol: The symbol whose position was closed.
        """
        logger.debug(f"{symbol}: SidewaysV2 position closed")

    def _create_exit_signal(self, position: Position, reason: str) -> Signal:
        """Create exit signal for position.

        Args:
            position: Position to close.
            reason: Exit reason for logging.

        Returns:
            Signal to close the position.
        """
        return Signal(
            symbol=position.symbol,
            side="sell",
            market=position.market,
            quantity=position.quantity,
            reason=reason,
        )
