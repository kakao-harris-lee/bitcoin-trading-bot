"""Base class for exit strategies.

Provides common functionality for all exit strategies:
- High water mark tracking
- Exit signal creation
- State management
- Position lifecycle hooks

Subclasses only need to implement check_exit() with their specific logic.
"""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from typing import Literal

from .models import Position, Signal, TradingContext
from trading.utils.pnl import calculate_pnl_pct, calculate_hwm_pnl_pct

logger = logging.getLogger(__name__)


class BaseExitStrategy(ABC):
    """Base class providing common exit strategy functionality.

    Attributes:
        _high_water_marks: Dict tracking highest price per position.
        _exit_stages: Dict tracking partial exit stage per position.

    Example:
        class MyExitStrategy(BaseExitStrategy):
            def check_exit(self, ctx, position):
                pnl = self._calculate_pnl(position, ctx.market.close)
                if pnl <= -5.0:  # Stop loss
                    return self._create_exit_signal(position, "Stop loss hit")
                return None
    """

    def __init__(self):
        """Initialize base exit strategy state."""
        self._high_water_marks: dict[str, float] = {}
        self._exit_stages: dict[str, int] = {}

    @abstractmethod
    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        """Check if position should be exited.

        Subclasses must implement this with their specific exit logic.

        Args:
            ctx: Current trading context with market data.
            position: Position to evaluate for exit.

        Returns:
            Exit Signal if conditions met, None otherwise.
        """
        pass

    # === Position Key Management ===

    def _get_position_key(self, position: Position) -> str:
        """Generate unique key for position state tracking.

        Args:
            position: Position to generate key for.

        Returns:
            Key in format "SYMBOL:strategy_name".
        """
        return f"{position.symbol}:{position.strategy}"

    # === PnL Calculations ===

    def _calculate_pnl(
        self,
        position: Position,
        current_price: float,
        side: Literal["long", "short"] = "long",
    ) -> float:
        """Calculate current PnL percentage.

        Args:
            position: Position with entry price.
            current_price: Current market price.
            side: Position side.

        Returns:
            PnL as percentage.
        """
        return calculate_pnl_pct(current_price, position.entry_price, side)

    def _calculate_hwm_pnl(self, position: Position, hwm: float) -> float:
        """Calculate PnL at high water mark.

        Args:
            position: Position with entry price.
            hwm: High water mark price.

        Returns:
            PnL at HWM as percentage.
        """
        return calculate_hwm_pnl_pct(hwm, position.entry_price)

    # === High Water Mark Management ===

    def _update_hwm(
        self,
        key: str,
        current_price: float,
        entry_price: float,
    ) -> float:
        """Update and return high water mark.

        Args:
            key: Position key.
            current_price: Current market price.
            entry_price: Position entry price (used as initial HWM).

        Returns:
            Updated high water mark.
        """
        hwm = self._high_water_marks.get(key, entry_price)
        if current_price > hwm:
            hwm = current_price
            self._high_water_marks[key] = hwm
        return hwm

    def _get_hwm(self, key: str, default: float = 0.0) -> float:
        """Get current high water mark.

        Args:
            key: Position key.
            default: Default value if not found.

        Returns:
            Current HWM or default.
        """
        return self._high_water_marks.get(key, default)

    # === Exit Stage Management ===

    def _get_exit_stage(self, key: str) -> int:
        """Get current exit stage for partial exits.

        Args:
            key: Position key.

        Returns:
            Current stage (0 = no exits yet).
        """
        return self._exit_stages.get(key, 0)

    def _set_exit_stage(self, key: str, stage: int) -> None:
        """Set exit stage after partial exit.

        Args:
            key: Position key.
            stage: New stage number.
        """
        self._exit_stages[key] = stage

    # === Signal Creation ===

    def _create_exit_signal(
        self,
        position: Position,
        reason: str,
        quantity: float = 1.0,
        side: Literal["sell", "buy"] = "sell",
    ) -> Signal:
        """Create standardized exit signal.

        Args:
            position: Position to exit.
            reason: Human-readable exit reason.
            quantity: Fraction to exit (1.0 = full, 0.5 = half).
            side: Exit side ("sell" for longs, "buy" for shorts).

        Returns:
            Exit Signal.
        """
        return Signal(
            symbol=position.symbol,
            side=side,
            market=position.market,
            quantity=quantity,
            reason=reason,
        )

    # === State Management ===

    def _clear_state(self, key: str) -> None:
        """Clear all state for a position.

        Called after full position exit.

        Args:
            key: Position key to clear.
        """
        self._high_water_marks.pop(key, None)
        self._exit_stages.pop(key, None)

    # === Lifecycle Hooks ===

    def on_position_opened(self, position: Position) -> None:
        """Called when a new position is opened.

        Initializes tracking state for the position.

        Args:
            position: Newly opened position.
        """
        key = self._get_position_key(position)
        self._high_water_marks[key] = position.entry_price
        self._exit_stages[key] = 0
        logger.debug(f"{position.symbol}: Position opened, HWM={position.entry_price:.2f}")

    def on_position_closed(self, symbol: str) -> None:
        """Called when a position is fully closed.

        Clears all tracking state for the symbol.

        Args:
            symbol: Symbol that was closed.
        """
        keys = [k for k in self._high_water_marks if k.startswith(f"{symbol}:")]
        for k in keys:
            self._clear_state(k)
        if keys:
            logger.debug(f"{symbol}: Position closed, state cleared")
