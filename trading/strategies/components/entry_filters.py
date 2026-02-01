"""Reusable entry filter checks.

Centralizes common entry filters used across 8+ entry strategies.
Each filter returns a FilterResult indicating pass/fail with reason.

Usage:
    result = EntryFilters.check_ema200(market_data, use_filter=True)
    if not result.passed:
        logger.debug(f"{symbol}: Skip - {result.reason}")
        return None
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from .models import MarketData, TradingContext


@dataclass
class FilterResult:
    """Result of a filter check.

    Attributes:
        passed: True if filter passed, False if blocked.
        reason: Human-readable rejection reason (None if passed).
    """

    passed: bool
    reason: Optional[str] = None

    def __bool__(self) -> bool:
        """Allow using FilterResult directly in boolean context."""
        return self.passed


class EntryFilters:
    """Collection of reusable entry filters.

    All methods are static and return FilterResult.
    Filters can be composed as needed by each strategy.
    """

    @staticmethod
    def check_ema200(
        market_data: MarketData,
        use_filter: bool = True,
    ) -> FilterResult:
        """Check if price is above EMA200 (trend filter).

        Args:
            market_data: Current market data with close and ema_200.
            use_filter: Whether to apply this filter.

        Returns:
            FilterResult indicating pass/fail.

        Example:
            >>> result = EntryFilters.check_ema200(market_data, use_filter=True)
            >>> if not result.passed:
            ...     return None  # Block entry
        """
        if not use_filter:
            return FilterResult(passed=True)

        if market_data.ema_200 > 0 and market_data.close < market_data.ema_200:
            return FilterResult(
                passed=False,
                reason=f"below EMA200 ({market_data.close:.0f} < {market_data.ema_200:.0f})",
            )
        return FilterResult(passed=True)

    @staticmethod
    def check_ema120(
        market_data: MarketData,
        use_filter: bool = True,
    ) -> FilterResult:
        """Check if price is above EMA120.

        Args:
            market_data: Current market data.
            use_filter: Whether to apply this filter.

        Returns:
            FilterResult indicating pass/fail.
        """
        if not use_filter:
            return FilterResult(passed=True)

        ema_120 = getattr(market_data, "ema_120", 0)
        if ema_120 > 0 and market_data.close < ema_120:
            return FilterResult(
                passed=False,
                reason=f"below EMA120 ({market_data.close:.0f} < {ema_120:.0f})",
            )
        return FilterResult(passed=True)

    @staticmethod
    def check_adx_strength(
        market_data: MarketData,
        min_adx: float,
    ) -> FilterResult:
        """Check if ADX indicates sufficient trend strength.

        Args:
            market_data: Current market data with adx.
            min_adx: Minimum ADX threshold.

        Returns:
            FilterResult indicating pass/fail.
        """
        if market_data.adx < min_adx:
            return FilterResult(
                passed=False,
                reason=f"weak trend (ADX={market_data.adx:.1f} < {min_adx})",
            )
        return FilterResult(passed=True)

    @staticmethod
    def check_not_bear_regime(
        regime: str,
        bear_regimes: set[str] | None = None,
    ) -> FilterResult:
        """Check if not in bear regime.

        Args:
            regime: Current market regime string.
            bear_regimes: Set of regime names to block. Defaults to BEAR_STRONG/MODERATE.

        Returns:
            FilterResult indicating pass/fail.
        """
        if bear_regimes is None:
            bear_regimes = {"BEAR_STRONG", "BEAR_MODERATE"}

        if regime in bear_regimes:
            return FilterResult(
                passed=False,
                reason=f"BEAR regime ({regime})",
            )
        return FilterResult(passed=True)

    @staticmethod
    def check_mfi_threshold(
        market_data: MarketData,
        min_mfi: float,
    ) -> FilterResult:
        """Check if MFI is above threshold.

        Args:
            market_data: Current market data with mfi.
            min_mfi: Minimum MFI threshold.

        Returns:
            FilterResult indicating pass/fail.
        """
        if market_data.mfi < min_mfi:
            return FilterResult(
                passed=False,
                reason=f"low MFI ({market_data.mfi:.1f} < {min_mfi})",
            )
        return FilterResult(passed=True)

    @staticmethod
    def check_mfi_range(
        market_data: MarketData,
        min_mfi: float,
        max_mfi: float,
    ) -> FilterResult:
        """Check if MFI is within range.

        Args:
            market_data: Current market data with mfi.
            min_mfi: Minimum MFI threshold.
            max_mfi: Maximum MFI threshold.

        Returns:
            FilterResult indicating pass/fail.
        """
        if market_data.mfi < min_mfi:
            return FilterResult(
                passed=False,
                reason=f"MFI too low ({market_data.mfi:.1f} < {min_mfi})",
            )
        if market_data.mfi > max_mfi:
            return FilterResult(
                passed=False,
                reason=f"MFI too high ({market_data.mfi:.1f} > {max_mfi})",
            )
        return FilterResult(passed=True)

    @staticmethod
    def check_volatility(
        volatility: float,
        min_vol: float = 0.0,
        max_vol: float = float("inf"),
    ) -> FilterResult:
        """Check if volatility is within acceptable range.

        Args:
            volatility: Current volatility measure.
            min_vol: Minimum volatility (block if too quiet).
            max_vol: Maximum volatility (block if too volatile).

        Returns:
            FilterResult indicating pass/fail.
        """
        if volatility < min_vol:
            return FilterResult(
                passed=False,
                reason=f"volatility too low ({volatility:.3f} < {min_vol})",
            )
        if volatility > max_vol:
            return FilterResult(
                passed=False,
                reason=f"volatility too high ({volatility:.3f} > {max_vol})",
            )
        return FilterResult(passed=True)
