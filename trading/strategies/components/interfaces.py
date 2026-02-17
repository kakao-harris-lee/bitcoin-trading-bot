"""Strategy component interfaces using Protocol for structural subtyping.

These protocols define the contracts for entry and exit strategy components.
Implementations don't need to inherit - they just need to implement the methods
(duck typing via typing.Protocol).
"""
# pylint: disable=unnecessary-ellipsis

from typing import Protocol

from .models import Position, Signal, TradingContext


class IEntryStrategy(Protocol):
    """Interface for entry logic only.

    Entry strategies analyze market conditions and decide when to open
    a position. They are stateless and don't track open positions.
    """

    def check_entry(
        self,
        ctx: TradingContext,
    ) -> Signal | None:
        """Analyze market conditions and return entry signal.

        Args:
            ctx: Complete trading context containing:
                - market: MarketData with indicators
                - regime: MarketContext with trend/volatility analysis
                - positions: Cross-strategy position info

        Returns:
            Signal with side="buy" for long, side="sell" for short
            None if no entry conditions met
        """
        ...


class IExitStrategy(Protocol):
    """Interface for exit logic only.

    Exit strategies manage open positions and decide when to close them.
    They may be stateful (e.g., tracking high water mark for trailing stops).
    """

    def check_exit(
        self,
        ctx: TradingContext,
        position: Position,
    ) -> Signal | None:
        """Evaluate exit conditions for existing position.

        Args:
            ctx: Complete trading context (now includes regime!)
            position: This strategy's open position

        Returns:
            Signal to close position, or None to hold
        """
        ...

    def on_position_opened(self, position: Position) -> None:
        """Called when a new position is opened.

        Use this to initialize state (e.g., set initial high water mark).

        Args:
            position: The newly opened position
        """
        ...

    def on_position_closed(self, symbol: str) -> None:
        """Called when position is closed.

        Use this to clean up state (e.g., reset high water mark).

        Args:
            symbol: The symbol whose position was closed
        """
        ...
