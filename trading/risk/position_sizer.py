"""Risk-based position sizing.

Calculates position quantity based on risk budget and stop distance,
ensuring each trade risks a fixed percentage of equity.

Formula:
    qty = risk_budget / (stop_distance * entry_price)

Where:
    risk_budget = equity * risk_pct (default 1%)
    stop_distance = abs(entry_price - stop_price) / entry_price
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Dict, Optional

logger = logging.getLogger(__name__)


# Binance Futures minimum order requirements
EXCHANGE_LIMITS: Dict[str, Dict[str, float]] = {
    "BTC": {"min_qty": 0.001, "qty_step": 0.001, "min_notional": 10.0},
    "ETH": {"min_qty": 0.01, "qty_step": 0.01, "min_notional": 10.0},
    "SOL": {"min_qty": 0.1, "qty_step": 0.1, "min_notional": 10.0},
    # Fallback for unknown symbols
    "DEFAULT": {"min_qty": 0.001, "qty_step": 0.001, "min_notional": 10.0},
}


@dataclass
class SizingResult:
    """Position sizing calculation result."""

    quantity: float
    """Calculated quantity (exchange-compliant)."""

    risk_amount: float
    """Expected loss at stop (USDT)."""

    stop_distance_pct: float
    """Stop distance as percentage."""

    position_value: float
    """Notional position value (USDT)."""

    margin_required: float
    """Required margin for this position (USDT)."""

    rejection_reason: Optional[str] = None
    """Why sizing was rejected (if quantity=0)."""


def round_to_step(value: float, step: float) -> float:
    """Round value to exchange step size."""
    if step <= 0:
        return value
    return round(value / step) * step


def get_exchange_limits(symbol: str) -> Dict[str, float]:
    """Get exchange limits for symbol."""
    return EXCHANGE_LIMITS.get(symbol, EXCHANGE_LIMITS["DEFAULT"])


def calculate_quantity(
    equity: float,
    entry_price: float,
    stop_price: float,
    symbol: str = "BTC",
    risk_pct: float = 0.01,
    leverage: int = 1,
    fee_pct: float = 0.001,
) -> SizingResult:
    """Calculate position quantity based on risk budget.

    The core principle: 1% is the maximum LOSS per trade, not the position size.

    Args:
        equity: Total account equity (USDT).
        entry_price: Expected entry price.
        stop_price: Stop loss price.
        symbol: Trading symbol (for exchange limits).
        risk_pct: Risk per trade as decimal (0.01 = 1%).
        leverage: Leverage multiplier (1-125).
        fee_pct: Trading fee per side (0.001 = 0.1%).

    Returns:
        SizingResult with calculated quantity and risk metrics.

    Example:
        equity=$10,000, entry=$100,000, stop=$97,000 (3%), risk=1%
        risk_budget = $100
        stop_distance = 3%
        qty = $100 / (0.03 * $100,000) = 0.033 BTC
    """
    # Validate inputs
    if equity <= 0:
        return SizingResult(0, 0, 0, 0, 0, "ZERO_EQUITY")

    if entry_price <= 0:
        return SizingResult(0, 0, 0, 0, 0, "INVALID_ENTRY_PRICE")

    if stop_price <= 0:
        return SizingResult(0, 0, 0, 0, 0, "INVALID_STOP_PRICE")

    # Calculate stop distance
    stop_distance = abs(entry_price - stop_price) / entry_price

    if stop_distance < 0.001:  # Less than 0.1%
        return SizingResult(0, 0, stop_distance * 100, 0, 0, "STOP_DISTANCE_TOO_SMALL")

    if stop_distance > 0.50:  # More than 50%
        return SizingResult(0, 0, stop_distance * 100, 0, 0, "STOP_DISTANCE_TOO_LARGE")

    # Risk budget (max loss we're willing to take)
    risk_budget = equity * risk_pct

    # Adjust for fees (entry + exit = 2x fee)
    # This ensures even if stopped out, we don't exceed risk_budget
    total_fee_drag = fee_pct * 2
    effective_stop = stop_distance + total_fee_drag

    # Calculate raw quantity
    # qty = risk_budget / (stop_distance * price)
    # With leverage: price change is amplified, so position can be smaller
    # But we keep risk_budget constant
    raw_qty = risk_budget / (effective_stop * entry_price)

    # Get exchange limits
    limits = get_exchange_limits(symbol)

    # Round to exchange step
    quantity = round_to_step(raw_qty, limits["qty_step"])

    # Check minimum quantity
    if quantity < limits["min_qty"]:
        logger.debug(
            f"{symbol}: qty {quantity} < min {limits['min_qty']}, "
            f"risk_budget=${risk_budget:.2f}, stop={stop_distance*100:.2f}%"
        )
        return SizingResult(
            0, 0, stop_distance * 100, 0, 0,
            f"QTY_BELOW_MIN:{quantity:.6f}<{limits['min_qty']}"
        )

    # Check minimum notional
    position_value = quantity * entry_price
    if position_value < limits["min_notional"]:
        return SizingResult(
            0, 0, stop_distance * 100, position_value, 0,
            f"NOTIONAL_BELOW_MIN:{position_value:.2f}<{limits['min_notional']}"
        )

    # Calculate actual risk (after rounding)
    actual_risk = quantity * entry_price * effective_stop

    # Calculate margin required
    margin_required = position_value / leverage

    # Check if margin fits in equity (with 20% buffer)
    if margin_required > equity * 0.8:
        return SizingResult(
            0, 0, stop_distance * 100, position_value, margin_required,
            f"INSUFFICIENT_MARGIN:{margin_required:.2f}>{equity*0.8:.2f}"
        )

    logger.info(
        f"{symbol}: risk-sized qty={quantity:.6f} "
        f"(risk=${actual_risk:.2f}, stop={stop_distance*100:.2f}%, "
        f"value=${position_value:.2f}, margin=${margin_required:.2f})"
    )

    return SizingResult(
        quantity=quantity,
        risk_amount=actual_risk,
        stop_distance_pct=stop_distance * 100,
        position_value=position_value,
        margin_required=margin_required,
    )


def calculate_stop_price(
    entry_price: float,
    atr: float,
    atr_multiplier: float = 3.5,
    min_stop_pct: float = 0.02,
    max_stop_pct: float = 0.08,
    direction: str = "long",
) -> float:
    """Calculate stop price based on ATR.

    Args:
        entry_price: Entry price.
        atr: Average True Range value.
        atr_multiplier: ATR multiplier for stop distance.
        min_stop_pct: Minimum stop distance (decimal).
        max_stop_pct: Maximum stop distance (decimal).
        direction: "long" or "short".

    Returns:
        Stop price.
    """
    # ATR-based stop distance
    atr_stop_distance = (atr * atr_multiplier) / entry_price

    # Clamp to min/max
    stop_distance = max(min_stop_pct, min(max_stop_pct, atr_stop_distance))

    if direction == "long":
        return entry_price * (1 - stop_distance)
    else:
        return entry_price * (1 + stop_distance)


@dataclass
class RiskSizingConfig:
    """Configuration for risk-based position sizing."""

    risk_per_trade_pct: float = 0.01
    """Risk per trade as decimal (0.01 = 1%)."""

    atr_multiplier: float = 3.5
    """ATR multiplier for stop calculation."""

    min_stop_pct: float = 0.02
    """Minimum stop distance (2%)."""

    max_stop_pct: float = 0.08
    """Maximum stop distance (8%)."""

    fee_pct: float = 0.001
    """Trading fee per side (0.1%)."""

    @classmethod
    def from_dict(cls, config: Dict) -> "RiskSizingConfig":
        """Create from allocation.json config."""
        return cls(
            risk_per_trade_pct=config.get("risk_per_trade_pct", 0.01),
            atr_multiplier=config.get("atr_stop_multiplier", 3.5),
            min_stop_pct=config.get("atr_stop_min_pct", 3.0) / 100,
            max_stop_pct=config.get("atr_stop_max_pct", 5.0) / 100,
            fee_pct=config.get("fee_pct", 0.001),
        )


class PositionSizer:
    """Stateful position sizer with caching and config."""

    def __init__(self, config: RiskSizingConfig):
        self.config = config

    def size_position(
        self,
        equity: float,
        entry_price: float,
        atr: float,
        symbol: str,
        leverage: int = 1,
        direction: str = "long",
    ) -> SizingResult:
        """Calculate position size with ATR-based stop.

        This is the main entry point for position sizing.

        Args:
            equity: Account equity (USDT).
            entry_price: Expected entry price.
            atr: Current ATR value.
            symbol: Trading symbol.
            leverage: Leverage multiplier.
            direction: "long" or "short".

        Returns:
            SizingResult with calculated quantity.
        """
        # Calculate stop price from ATR
        stop_price = calculate_stop_price(
            entry_price=entry_price,
            atr=atr,
            atr_multiplier=self.config.atr_multiplier,
            min_stop_pct=self.config.min_stop_pct,
            max_stop_pct=self.config.max_stop_pct,
            direction=direction,
        )

        # Calculate quantity
        return calculate_quantity(
            equity=equity,
            entry_price=entry_price,
            stop_price=stop_price,
            symbol=symbol,
            risk_pct=self.config.risk_per_trade_pct,
            leverage=leverage,
            fee_pct=self.config.fee_pct,
        )

    def size_position_with_stop(
        self,
        equity: float,
        entry_price: float,
        stop_price: float,
        symbol: str,
        leverage: int = 1,
    ) -> SizingResult:
        """Calculate position size with explicit stop price.

        Use this when stop price is already known.
        """
        return calculate_quantity(
            equity=equity,
            entry_price=entry_price,
            stop_price=stop_price,
            symbol=symbol,
            risk_pct=self.config.risk_per_trade_pct,
            leverage=leverage,
            fee_pct=self.config.fee_pct,
        )
