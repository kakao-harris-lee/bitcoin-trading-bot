"""V35 Trailing Exit Strategy - extracted from V35LongTask.

Implements IExitStrategy protocol for V35 exit logic with:
- Stop loss
- Take profit
- Trailing stop (activated after threshold, locks in gains)
- Regime change exit (bearish regime with profit)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Literal

from .models import MarketData, Position, Signal
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class V35ExitParams:
    """Parameters for V35 exit strategy."""

    # Stop loss percentage (negative P&L threshold)
    stop_loss_pct: float = 1.5

    # Take profit percentage
    take_profit_pct: float = 3.0

    # Trailing stop settings
    trailing_enabled: bool = True
    trailing_activation: float = 2.0  # Activate after this % gain
    trailing_distance: float = 1.5  # Trail this % below high water mark

    # Regime classification for exit
    mfi_bull: float = 52.0
    mfi_bear: float = 48.0
    adx_trend: float = 20.0
    adx_weak: float = 15.0

    market: Literal["spot", "futures"] = "spot"


@exit_strategy(params_class=V35ExitParams)
class V35TrailingExitStrategy:
    """V35 Exit strategy with trailing stop.

    Exit conditions (checked in order):
    1. Stop Loss: P&L <= -stop_loss_pct
    2. Take Profit: P&L >= take_profit_pct
    3. Trailing Stop: Activated when P&L >= trailing_activation,
       triggers when price drops trailing_distance% below high water mark
    4. Regime Change: Exit on bearish regime if in profit

    State:
    - high_water_mark: Tracks highest price since position opened

    Implements IExitStrategy protocol (structural subtyping).
    """

    def __init__(self, params: V35ExitParams | None = None):
        """Initialize with exit parameters.

        Args:
            params: Exit parameters. Uses defaults if not provided.
        """
        self.params = params or V35ExitParams()
        # Track high water mark per symbol
        self._high_water_mark: dict[str, float] = {}

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

        # Update high water mark
        self._update_high_water_mark(symbol, current_price)
        hwm = self._high_water_mark[symbol]
        hwm_pnl = ((hwm - entry_price) / entry_price) * 100

        # Exit condition 1: Stop loss
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"V35 exit: Stop loss {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(symbol)
            return self._create_exit_signal(position, reason)

        # Exit condition 2: Take profit
        if pnl_pct >= p.take_profit_pct:
            reason = f"V35 exit: Take profit {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(symbol)
            return self._create_exit_signal(position, reason)

        # Exit condition 3: Trailing stop
        if p.trailing_enabled and hwm_pnl >= p.trailing_activation:
            trailing_stop_price = hwm * (1 - p.trailing_distance / 100)
            if current_price <= trailing_stop_price:
                locked_pnl = ((trailing_stop_price - entry_price) / entry_price) * 100
                reason = f"V35 exit: Trailing stop {locked_pnl:.2f}% (HWM={hwm_pnl:.2f}%)"
                logger.info(f"{symbol}: {reason}")
                self._clear_state(symbol)
                return self._create_exit_signal(position, reason, trailing_stop_price)

        # Exit condition 4: Regime change to bearish (only if in profit)
        regime = self._classify_regime(market_data.mfi, market_data.adx)
        if regime in ("BEAR_STRONG", "BEAR_MODERATE") and pnl_pct > 0:
            reason = f"V35 exit: Regime change to {regime}, locking {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            self._clear_state(symbol)
            return self._create_exit_signal(position, reason)

        return None

    def on_position_opened(self, position: Position) -> None:
        """Initialize state when position is opened.

        Sets initial high water mark to entry price.

        Args:
            position: The newly opened position.
        """
        self._high_water_mark[position.symbol] = position.entry_price
        logger.debug(
            f"{position.symbol}: Position opened, "
            f"HWM initialized to {position.entry_price:.2f}"
        )

    def on_position_closed(self, symbol: str) -> None:
        """Clean up state when position is closed.

        Removes high water mark tracking for symbol.

        Args:
            symbol: The symbol whose position was closed.
        """
        self._clear_state(symbol)
        logger.debug(f"{symbol}: Position closed, state cleared")

    def _update_high_water_mark(self, symbol: str, current_price: float) -> None:
        """Update high water mark if current price is higher.

        Args:
            symbol: Trading symbol.
            current_price: Current market price.
        """
        if symbol not in self._high_water_mark:
            self._high_water_mark[symbol] = current_price
        else:
            old_hwm = self._high_water_mark[symbol]
            new_hwm = max(old_hwm, current_price)
            if new_hwm > old_hwm:
                logger.debug(
                    f"{symbol}: HWM updated {old_hwm:.2f} -> {new_hwm:.2f}"
                )
            self._high_water_mark[symbol] = new_hwm

    def _clear_state(self, symbol: str) -> None:
        """Clear state for symbol.

        Args:
            symbol: Trading symbol.
        """
        self._high_water_mark.pop(symbol, None)

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify market regime for exit decision.

        Simplified classification focusing on bearish detection.

        Args:
            mfi: Money Flow Index value.
            adx: Average Directional Index value.

        Returns:
            Regime classification string.
        """
        p = self.params

        if mfi >= p.mfi_bull:
            return "BULL"
        elif mfi <= p.mfi_bear:
            if adx >= p.adx_trend:
                return "BEAR_STRONG"
            elif adx >= p.adx_weak:
                return "BEAR_MODERATE"
            else:
                return "SIDEWAYS_BEAR"
        else:
            return "SIDEWAYS_NEUTRAL"

    def _create_exit_signal(
        self,
        position: Position,
        reason: str,
        trigger_price: float | None = None,
    ) -> Signal:
        """Create exit signal for position.

        Args:
            position: Position to close.
            reason: Exit reason for logging.
            trigger_price: Optional trigger price for trailing stop.

        Returns:
            Signal to close the position.
        """
        return Signal(
            symbol=position.symbol,
            side="sell",
            market=position.market,
            quantity=position.quantity,
            reason=reason,
            trigger_price=trigger_price,
        )

    @property
    def high_water_mark(self) -> dict[str, float]:
        """Get current high water marks (read-only view)."""
        return self._high_water_mark.copy()
