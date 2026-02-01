"""PnL calculation utilities.

Centralizes profit/loss calculations used across exit strategies.
Eliminates duplicate implementations in 13+ strategy files.
"""
from typing import Literal


def calculate_pnl_pct(
    current_price: float,
    entry_price: float,
    side: Literal["long", "short"] = "long",
) -> float:
    """Calculate profit/loss percentage.

    Args:
        current_price: Current market price.
        entry_price: Position entry price.
        side: Position side ("long" or "short").

    Returns:
        PnL as percentage (e.g., 5.0 for +5%, -3.0 for -3%).

    Examples:
        >>> calculate_pnl_pct(105, 100, "long")
        5.0
        >>> calculate_pnl_pct(95, 100, "long")
        -5.0
        >>> calculate_pnl_pct(95, 100, "short")
        5.0
    """
    if entry_price <= 0:
        return 0.0

    if side == "long":
        return ((current_price - entry_price) / entry_price) * 100
    else:
        return ((entry_price - current_price) / entry_price) * 100


def calculate_hwm_pnl_pct(
    high_water_mark: float,
    entry_price: float,
) -> float:
    """Calculate PnL percentage at high water mark.

    Args:
        high_water_mark: Highest price since entry.
        entry_price: Position entry price.

    Returns:
        PnL percentage at HWM.

    Examples:
        >>> calculate_hwm_pnl_pct(110, 100)
        10.0
    """
    if entry_price <= 0:
        return 0.0
    return ((high_water_mark - entry_price) / entry_price) * 100


def calculate_drawdown_from_hwm(
    current_price: float,
    high_water_mark: float,
) -> float:
    """Calculate drawdown percentage from high water mark.

    Args:
        current_price: Current market price.
        high_water_mark: Highest price since entry.

    Returns:
        Drawdown as positive percentage (e.g., 5.0 for 5% drawdown).

    Examples:
        >>> calculate_drawdown_from_hwm(95, 100)
        5.0
        >>> calculate_drawdown_from_hwm(100, 100)
        0.0
    """
    if high_water_mark <= 0:
        return 0.0
    return ((high_water_mark - current_price) / high_water_mark) * 100
