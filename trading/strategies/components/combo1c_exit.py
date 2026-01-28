"""Combo1-C Exit Strategy: End-of-day close.

Implements the paper-described exit logic:
- Sell all positions at end of day (first bar of next trading day)

This is a pure time-based exit without trailing stops or profit targets,
matching the original Volatility Breakout Strategy research methodology.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .models import Position, Signal, TradingContext
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class Combo1CExitParams:
    """Parameters for Combo1-C exit strategy."""

    # Core parameter: exit at day close (always True for paper methodology)
    exit_at_day_close: bool = True

    # Optional safety parameters (can be disabled for pure day-close exit)
    emergency_stop_loss_pct: float | None = 5.0  # Emergency stop loss (5%)
    max_hold_hours: float | None = 24.0  # Maximum hold time (fallback)

    # Trailing stop for profit protection
    trailing_enabled: bool = True  # Enable by default for MDD defense
    trailing_activation_pct: float = 2.0  # Activate at +2%
    trailing_distance_pct: float = 1.5    # Trail 1.5% below HWM

    market: Literal["futures"] = "futures"


@exit_strategy(params_class=Combo1CExitParams)
class Combo1CExitStrategy:
    """Exit positions at the first bar of the next trading day.

    Implements the paper's exit methodology:
    - Enter on breakout during the day
    - Exit at next day's open (first bar of new day)

    This ensures all positions are closed within 24 hours, as the
    Volatility Breakout Strategy is designed for intraday profit capture.
    """

    def __init__(self, params: Combo1CExitParams | None = None):
        self.params = params or Combo1CExitParams()

        # Track entry day for each symbol
        self._entry_day: dict[str, object] = {}  # symbol -> date
        self._entry_info: dict[str, dict[str, float]] = {}  # symbol -> {timestamp, price}
        self._high_water_mark: dict[str, float] = {}  # Track HWM for trailing stop

        # Statistics
        self._stats: dict[str, int] = {}

    def on_position_opened(self, position: Position) -> None:
        """Record position entry for day tracking.

        Args:
            position: The opened position.
        """
        ts = position.timestamp
        day = datetime.utcfromtimestamp(ts / 1000).date()
        self._entry_day[position.symbol] = day
        self._entry_info[position.symbol] = {
            "timestamp": position.timestamp,
            "price": position.entry_price,
        }
        # Initialize HWM to entry price
        self._high_water_mark[position.symbol] = position.entry_price
        logger.debug(
            f"[Combo1C Exit] {position.symbol}: Position opened on {day} at {position.entry_price:.2f}"
        )

    def on_position_closed(self, symbol: str) -> None:
        """Clean up state when position is closed.

        Args:
            symbol: The closed position's symbol.
        """
        self._entry_day.pop(symbol, None)
        self._entry_info.pop(symbol, None)
        self._high_water_mark.pop(symbol, None)
        logger.debug(f"[Combo1C Exit] {symbol}: Position closed, state cleared")

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        """Check if position should be exited.

        Exit conditions (checked in order):
        1. Emergency stop loss (if configured)
        2. Trailing stop (if enabled and activated)
        3. Max hold time exceeded (if configured)
        4. New trading day started (primary exit condition)

        Args:
            ctx: Trading context with current market data.
            position: The position to evaluate.

        Returns:
            Exit signal or None.
        """
        symbol = position.symbol
        entry_info = self._entry_info.get(symbol)

        # Ensure we have entry info
        if entry_info is None:
            # Position opened before strategy initialized, record now
            self.on_position_opened(position)
            entry_info = self._entry_info[symbol]

        current_price = ctx.market.close
        entry_price = entry_info["price"]
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Update high water mark
        hwm = self._high_water_mark.get(symbol, entry_price)
        if current_price > hwm:
            hwm = current_price
            self._high_water_mark[symbol] = hwm
        hwm_pnl_pct = ((hwm - entry_price) / entry_price) * 100

        # 1. Emergency stop loss (optional safety)
        if self.params.emergency_stop_loss_pct:
            if pnl_pct <= -self.params.emergency_stop_loss_pct:
                reason = f"combo1c_exit emergency_stop_loss ({pnl_pct:.2f}%)"
                logger.info(f"[Combo1C Exit] {symbol}: {reason}")
                return self._build_exit(symbol, position, reason)

        # 2. Trailing stop (profit protection)
        if self.params.trailing_enabled:
            if hwm_pnl_pct >= self.params.trailing_activation_pct:
                trailing_stop_price = hwm * (1 - self.params.trailing_distance_pct / 100)
                if current_price <= trailing_stop_price:
                    locked_pnl = ((trailing_stop_price - entry_price) / entry_price) * 100
                    reason = f"combo1c_exit trailing_stop ({locked_pnl:.2f}% locked, HWM={hwm_pnl_pct:.2f}%)"
                    logger.info(f"[Combo1C Exit] {symbol}: {reason}")
                    return self._build_exit(symbol, position, reason)

        # 3. Max hold time exceeded (fallback safety)
        if self.params.max_hold_hours:
            delta_hours = (ctx.market.timestamp - entry_info["timestamp"]) / 1000 / 3600
            if delta_hours >= self.params.max_hold_hours:
                reason = f"combo1c_exit max_hold ({delta_hours:.1f}h, pnl: {pnl_pct:.2f}%)"
                logger.info(f"[Combo1C Exit] {symbol}: {reason}")
                return self._build_exit(symbol, position, reason)

        # 4. Day close exit (primary condition - as per paper)
        if self.params.exit_at_day_close:
            entry_day = self._entry_day.get(symbol)
            if entry_day is None:
                return None

            current_day = datetime.utcfromtimestamp(ctx.market.timestamp / 1000).date()

            # Exit on first bar of new day
            if current_day != entry_day:
                reason = f"combo1c_exit day_close (entry: {entry_day}, now: {current_day}, pnl: {pnl_pct:.2f}%)"
                logger.info(f"[Combo1C Exit] {symbol}: {reason}")
                return self._build_exit(symbol, position, reason)

        return None

    def _build_exit(
        self,
        symbol: str,
        position: Position,
        reason: str,
    ) -> Signal:
        """Build exit signal.

        Args:
            symbol: Trading symbol.
            position: Position to exit.
            reason: Exit reason string.

        Returns:
            Exit signal.
        """
        # Track stats
        exit_type = reason.split()[0] + "_" + reason.split()[1] if len(reason.split()) > 1 else reason
        self._stats[exit_type] = self._stats.get(exit_type, 0) + 1

        return Signal(
            symbol=symbol,
            side="sell",
            market=self.params.market,
            quantity=position.quantity,
            reason=reason,
        )

    def get_stats(self) -> dict[str, int]:
        """Get exit statistics.

        Returns:
            Dict with exit reason counts.
        """
        return dict(self._stats)

    def reset_stats(self) -> None:
        """Reset statistics counters."""
        self._stats.clear()
