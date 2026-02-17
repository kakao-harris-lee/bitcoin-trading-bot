"""
LiquidationGuard - Monitors positions and triggers pre-emptive exits.

Calculates liquidation prices for isolated margin positions and
exits before reaching liquidation to protect capital.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


# Default Binance maintenance margin rates by position notional value
# https://www.binance.com/en/futures/trading-rules/perpetual/leverage-margin
DEFAULT_MAINTENANCE_MARGIN_RATES: list[tuple[float, float]] = [
    (50_000, 0.004),       # 0.4% for < $50k
    (250_000, 0.005),      # 0.5% for < $250k
    (1_000_000, 0.01),     # 1.0% for < $1M
    (5_000_000, 0.025),    # 2.5% for < $5M
    (float('inf'), 0.05),  # 5.0% for >= $5M
]


@dataclass
class LiquidationInfo:
    """Information about position liquidation risk."""

    symbol: str
    side: str
    entry_price: float
    current_price: float
    liquidation_price: float
    distance_pct: float  # Distance to liquidation as percentage
    should_exit: bool    # True if within danger zone


class LiquidationGuard:
    """Monitors positions and triggers pre-emptive exits before liquidation."""

    # Exit when price is within this % of liquidation distance
    EXIT_THRESHOLD_PCT = 20.0

    # Default maintenance margin rates (can be overridden via constructor)
    MAINTENANCE_MARGIN_RATES = DEFAULT_MAINTENANCE_MARGIN_RATES

    def __init__(
        self,
        exit_threshold_pct: Optional[float] = None,
        maintenance_margin_rates: Optional[list[tuple[float, float]]] = None,
    ):
        """Initialize LiquidationGuard.

        Args:
            exit_threshold_pct: Exit when within this % of liquidation. Default 20%.
            maintenance_margin_rates: Custom margin rates as list of (threshold, rate) tuples.
                Each tuple specifies (position_value_threshold, margin_rate).
                Default uses Binance rates.
        """
        self.exit_threshold_pct = exit_threshold_pct or self.EXIT_THRESHOLD_PCT
        self._maintenance_margin_rates = (
            maintenance_margin_rates
            if maintenance_margin_rates is not None
            else self.MAINTENANCE_MARGIN_RATES
        )

    def get_maintenance_margin_rate(self, position_value: float) -> float:
        """Get maintenance margin rate based on position size.

        Args:
            position_value: Position notional value in USDT.

        Returns:
            Maintenance margin rate as decimal (e.g., 0.004 for 0.4%).

        Raises:
            ValueError: If position_value is negative.
        """
        if position_value < 0:
            raise ValueError(f"Position value cannot be negative: {position_value}")

        for threshold, rate in self._maintenance_margin_rates:
            if position_value < threshold:
                return rate
        return self._maintenance_margin_rates[-1][1]

    def calculate_liquidation_price(
        self,
        entry_price: float,
        leverage: int,
        side: str,
        position_value: float,
    ) -> float:
        """Calculate liquidation price for isolated margin position.

        Args:
            entry_price: Position entry price.
            leverage: Leverage multiplier (e.g., 5 for 5x).
            side: "buy" for long, "sell" for short.
            position_value: Position notional value in USDT.

        Returns:
            Liquidation price.

        Raises:
            ValueError: If inputs are invalid (negative prices, zero leverage, etc.).
        """
        # Input validation
        if entry_price <= 0:
            raise ValueError(f"Entry price must be positive: {entry_price}")
        if leverage <= 0:
            raise ValueError(f"Leverage must be positive: {leverage}")
        if side not in ("buy", "sell"):
            raise ValueError(f"Side must be 'buy' or 'sell': {side}")
        if position_value < 0:
            raise ValueError(f"Position value cannot be negative: {position_value}")

        mmr = self.get_maintenance_margin_rate(position_value)

        if side == "buy":  # Long
            # Liquidation when price drops
            # Liq = Entry * (1 - 1/Leverage + MMR)
            liq_price = entry_price * (1 - (1 / leverage) + mmr)
        else:  # Short
            # Liquidation when price rises
            # Liq = Entry * (1 + 1/Leverage - MMR)
            liq_price = entry_price * (1 + (1 / leverage) - mmr)

        return liq_price

    def check_position_safety(
        self,
        entry_price: float,
        current_price: float,
        liquidation_price: float,
        side: str,
        symbol: str = "UNKNOWN",
    ) -> LiquidationInfo:
        """Check if position is in danger of liquidation.

        Args:
            entry_price: Position entry price.
            current_price: Current market price.
            liquidation_price: Pre-calculated liquidation price.
            side: "buy" for long, "sell" for short.
            symbol: Trading symbol for logging.

        Returns:
            LiquidationInfo with safety assessment.
        """
        if side == "buy":  # Long
            # Distance = how far current price is from liquidation
            # For longs, liquidation is below current price
            total_distance = entry_price - liquidation_price
            current_distance = current_price - liquidation_price
        else:  # Short
            # For shorts, liquidation is above current price
            total_distance = liquidation_price - entry_price
            current_distance = liquidation_price - current_price

        # Calculate distance as percentage of total range
        if total_distance > 0:
            distance_pct = (current_distance / total_distance) * 100
        else:
            distance_pct = 100.0  # Safe if no distance

        # Determine if should exit
        should_exit = distance_pct < self.exit_threshold_pct

        if should_exit:
            logger.warning(
                "LIQUIDATION WARNING: %s %s is %.1f%% from liquidation (threshold: %.1f%%)",
                symbol,
                side.upper(),
                distance_pct,
                self.exit_threshold_pct,
            )

        return LiquidationInfo(
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            current_price=current_price,
            liquidation_price=liquidation_price,
            distance_pct=distance_pct,
            should_exit=should_exit,
        )
