"""Precision utilities for safe price and quantity calculations.

Solves Python float precision errors by using Decimal for all
PnL and quantity calculations. Provides Binance-compliant rounding.

Usage:
    from trading.utils.precision import PriceUtils, SymbolInfo

    # Basic decimal operations
    pnl = PriceUtils.calculate_pnl(entry="50000.00", exit="51500.00", quantity="0.01")
    # Returns Decimal('15.00')

    # Round to Binance step size
    qty = PriceUtils.round_down_to_step("0.123456", step_size="0.001")
    # Returns Decimal('0.123')

    # With symbol info
    info = SymbolInfo(
        symbol="BTCUSDT",
        price_precision=2,
        qty_precision=5,
        min_qty="0.00001",
        step_size="0.00001",
        tick_size="0.01",
        min_notional="10.0",
    )
    qty = PriceUtils.round_quantity("0.123456789", info)
    # Returns Decimal('0.12345')
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal, ROUND_DOWN, ROUND_HALF_UP, InvalidOperation
from typing import Union

logger = logging.getLogger(__name__)

# Type alias for values that can be converted to Decimal
DecimalInput = Union[str, int, float, Decimal]


@dataclass
class SymbolInfo:
    """Binance symbol trading rules from exchangeInfo.

    Contains precision and filter information for a trading pair.
    """

    symbol: str
    price_precision: int  # Decimal places for price
    qty_precision: int  # Decimal places for quantity
    min_qty: str  # Minimum order quantity
    step_size: str  # Quantity step size
    tick_size: str  # Price tick size
    min_notional: str  # Minimum order value (price * qty)

    @classmethod
    def from_exchange_info(cls, symbol: str, info: dict) -> "SymbolInfo":
        """Create SymbolInfo from Binance exchangeInfo response.

        Args:
            symbol: Trading pair symbol.
            info: Symbol info dict from exchangeInfo.

        Returns:
            SymbolInfo instance.
        """
        filters = {f["filterType"]: f for f in info.get("filters", [])}

        lot_size = filters.get("LOT_SIZE", {})
        price_filter = filters.get("PRICE_FILTER", {})
        notional = filters.get("MIN_NOTIONAL", filters.get("NOTIONAL", {}))

        return cls(
            symbol=symbol,
            price_precision=info.get("quotePrecision", 8),
            qty_precision=info.get("baseAssetPrecision", 8),
            min_qty=lot_size.get("minQty", "0.00001"),
            step_size=lot_size.get("stepSize", "0.00001"),
            tick_size=price_filter.get("tickSize", "0.01"),
            min_notional=notional.get("minNotional", "10.0"),
        )


class PriceUtils:
    """Utility class for precise price and quantity calculations.

    Uses Decimal internally to avoid float precision errors.
    All methods accept string, int, float, or Decimal inputs.
    """

    @staticmethod
    def to_decimal(value: DecimalInput) -> Decimal:
        """Convert value to Decimal safely.

        Args:
            value: Value to convert (str, int, float, or Decimal).

        Returns:
            Decimal representation.

        Note:
            For floats, converts via string to preserve displayed precision.
        """
        if isinstance(value, Decimal):
            return value
        if isinstance(value, float):
            # Convert float via string to avoid precision issues
            return Decimal(str(value))
        return Decimal(value)

    @staticmethod
    def round_down_to_step(
        value: DecimalInput,
        step_size: DecimalInput,
    ) -> Decimal:
        """Round value down to the nearest step size.

        Binance requires quantities to be multiples of step_size.

        Args:
            value: Value to round.
            step_size: Step size to round to.

        Returns:
            Rounded Decimal value.

        Example:
            >>> PriceUtils.round_down_to_step("0.123456", "0.001")
            Decimal('0.123')
        """
        value_dec = PriceUtils.to_decimal(value)
        step_dec = PriceUtils.to_decimal(step_size)

        if step_dec <= 0:
            return value_dec

        # Calculate number of steps and round down
        steps = value_dec / step_dec
        rounded_steps = steps.to_integral_value(rounding=ROUND_DOWN)
        return rounded_steps * step_dec

    @staticmethod
    def round_to_tick(
        value: DecimalInput,
        tick_size: DecimalInput,
    ) -> Decimal:
        """Round value to the nearest tick size.

        Binance requires prices to be multiples of tick_size.

        Args:
            value: Price to round.
            tick_size: Tick size to round to.

        Returns:
            Rounded Decimal value.

        Example:
            >>> PriceUtils.round_to_tick("50000.123", "0.01")
            Decimal('50000.12')
        """
        value_dec = PriceUtils.to_decimal(value)
        tick_dec = PriceUtils.to_decimal(tick_size)

        if tick_dec <= 0:
            return value_dec

        # Round to nearest tick
        steps = value_dec / tick_dec
        rounded_steps = steps.to_integral_value(rounding=ROUND_HALF_UP)
        return rounded_steps * tick_dec

    @staticmethod
    def round_quantity(
        quantity: DecimalInput,
        symbol_info: SymbolInfo,
    ) -> Decimal:
        """Round quantity to comply with Binance LOT_SIZE filter.

        Args:
            quantity: Quantity to round.
            symbol_info: Symbol trading rules.

        Returns:
            Rounded quantity compliant with step_size.
        """
        return PriceUtils.round_down_to_step(quantity, symbol_info.step_size)

    @staticmethod
    def round_price(
        price: DecimalInput,
        symbol_info: SymbolInfo,
    ) -> Decimal:
        """Round price to comply with Binance PRICE_FILTER.

        Args:
            price: Price to round.
            symbol_info: Symbol trading rules.

        Returns:
            Rounded price compliant with tick_size.
        """
        return PriceUtils.round_to_tick(price, symbol_info.tick_size)

    @staticmethod
    def calculate_pnl(
        entry: DecimalInput,
        exit: DecimalInput,
        quantity: DecimalInput,
        is_short: bool = False,
    ) -> Decimal:
        """Calculate profit/loss with Decimal precision.

        Args:
            entry: Entry price.
            exit: Exit price.
            quantity: Position quantity.
            is_short: True for short positions (profit when price drops).

        Returns:
            PnL in quote currency (e.g., USDT).

        Example:
            >>> PriceUtils.calculate_pnl("50000", "51500", "0.01")
            Decimal('15.00')
        """
        entry_dec = PriceUtils.to_decimal(entry)
        exit_dec = PriceUtils.to_decimal(exit)
        qty_dec = PriceUtils.to_decimal(quantity)

        if is_short:
            # Short: profit when price drops
            return (entry_dec - exit_dec) * qty_dec
        else:
            # Long: profit when price rises
            return (exit_dec - entry_dec) * qty_dec

    @staticmethod
    def calculate_pnl_percent(
        entry: DecimalInput,
        exit: DecimalInput,
        is_short: bool = False,
    ) -> Decimal:
        """Calculate PnL as percentage with Decimal precision.

        Args:
            entry: Entry price.
            exit: Exit/current price.
            is_short: True for short positions.

        Returns:
            PnL percentage (e.g., Decimal('3.00') for 3%).

        Example:
            >>> PriceUtils.calculate_pnl_percent("50000", "51500")
            Decimal('3.00')
        """
        entry_dec = PriceUtils.to_decimal(entry)
        exit_dec = PriceUtils.to_decimal(exit)

        if entry_dec == 0:
            return Decimal("0")

        if is_short:
            pnl_pct = ((entry_dec - exit_dec) / entry_dec) * 100
        else:
            pnl_pct = ((exit_dec - entry_dec) / entry_dec) * 100

        return pnl_pct.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    @staticmethod
    def calculate_position_value(
        price: DecimalInput,
        quantity: DecimalInput,
    ) -> Decimal:
        """Calculate position value (price * quantity).

        Args:
            price: Current price.
            quantity: Position quantity.

        Returns:
            Position value in quote currency.
        """
        price_dec = PriceUtils.to_decimal(price)
        qty_dec = PriceUtils.to_decimal(quantity)
        return price_dec * qty_dec

    @staticmethod
    def meets_min_notional(
        price: DecimalInput,
        quantity: DecimalInput,
        symbol_info: SymbolInfo,
    ) -> bool:
        """Check if order meets MIN_NOTIONAL filter.

        Args:
            price: Order price.
            quantity: Order quantity.
            symbol_info: Symbol trading rules.

        Returns:
            True if order value >= min_notional.
        """
        value = PriceUtils.calculate_position_value(price, quantity)
        min_notional = PriceUtils.to_decimal(symbol_info.min_notional)
        return value >= min_notional

    @staticmethod
    def meets_min_qty(
        quantity: DecimalInput,
        symbol_info: SymbolInfo,
    ) -> bool:
        """Check if quantity meets LOT_SIZE minQty filter.

        Args:
            quantity: Order quantity.
            symbol_info: Symbol trading rules.

        Returns:
            True if quantity >= min_qty.
        """
        qty_dec = PriceUtils.to_decimal(quantity)
        min_qty = PriceUtils.to_decimal(symbol_info.min_qty)
        return qty_dec >= min_qty

    @staticmethod
    def format_quantity(
        quantity: DecimalInput,
        precision: int,
    ) -> str:
        """Format quantity string with specified precision.

        Args:
            quantity: Quantity to format.
            precision: Number of decimal places.

        Returns:
            Formatted string without trailing zeros.
        """
        qty_dec = PriceUtils.to_decimal(quantity)
        quantized = qty_dec.quantize(
            Decimal(10) ** -precision,
            rounding=ROUND_DOWN,
        )
        # Remove trailing zeros
        return f"{quantized:f}".rstrip("0").rstrip(".")

    @staticmethod
    def format_price(
        price: DecimalInput,
        precision: int,
    ) -> str:
        """Format price string with specified precision.

        Args:
            price: Price to format.
            precision: Number of decimal places.

        Returns:
            Formatted string.
        """
        price_dec = PriceUtils.to_decimal(price)
        quantized = price_dec.quantize(
            Decimal(10) ** -precision,
            rounding=ROUND_HALF_UP,
        )
        return f"{quantized:f}"


# Default symbol info for common pairs (can be overridden with live data)
DEFAULT_SYMBOL_INFO = {
    "BTCUSDT": SymbolInfo(
        symbol="BTCUSDT",
        price_precision=2,
        qty_precision=5,
        min_qty="0.00001",
        step_size="0.00001",
        tick_size="0.01",
        min_notional="10.0",
    ),
    "ETHUSDT": SymbolInfo(
        symbol="ETHUSDT",
        price_precision=2,
        qty_precision=4,
        min_qty="0.0001",
        step_size="0.0001",
        tick_size="0.01",
        min_notional="10.0",
    ),
    "SOLUSDT": SymbolInfo(
        symbol="SOLUSDT",
        price_precision=2,
        qty_precision=2,
        min_qty="0.01",
        step_size="0.01",
        tick_size="0.01",
        min_notional="10.0",
    ),
}


def get_symbol_info(symbol: str) -> SymbolInfo:
    """Get symbol info (defaults, should be refreshed from exchange).

    Args:
        symbol: Trading symbol (e.g., "BTC" or "BTCUSDT").

    Returns:
        SymbolInfo for the symbol.
    """
    # Normalize symbol
    if not symbol.endswith("USDT"):
        symbol = f"{symbol}USDT"

    return DEFAULT_SYMBOL_INFO.get(
        symbol,
        SymbolInfo(
            symbol=symbol,
            price_precision=8,
            qty_precision=8,
            min_qty="0.00000001",
            step_size="0.00000001",
            tick_size="0.00000001",
            min_notional="10.0",
        ),
    )
