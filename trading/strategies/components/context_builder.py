"""TradingContext builder for centralized context construction.

This module provides the TradingContextBuilder class that builds
TradingContext objects once per symbol per tick, caching results
to avoid redundant computation across multiple strategies.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import TradingContext, build_market_context

if TYPE_CHECKING:
    from trading.indicators.indicator_service import IndicatorService

logger = logging.getLogger(__name__)


class PositionManager:
    """Manages position lookups from Redis.

    Provides a clean interface for retrieving positions across strategies.
    """

    def __init__(self, redis_client):
        """Initialize with Redis client.

        Args:
            redis_client: Async Redis client instance.
        """
        self._redis = redis_client

    def get_positions_for_symbol(self, symbol: str) -> dict:
        """Get all positions for a symbol across strategies.

        Note: This is a synchronous method that uses cached position data.
        Position data is updated asynchronously by the executor.

        Args:
            symbol: Trading symbol (BTC, ETH, SOL).

        Returns:
            Dict mapping strategy_name -> Position for this symbol.
        """
        # Import here to avoid circular dependency
        from .models import Position

        positions = {}

        # Position key pattern: positions:{symbol}:futures
        # Value is a hash with strategy as the grouping
        # For now, we return empty - will be populated by CompositeStrategyTask
        # which already has position access via Redis

        return positions


class TradingContextBuilder:
    """Builds TradingContext once per symbol per tick.

    Caches results by timestamp to avoid redundant computation when
    multiple strategies request context for the same symbol.

    Usage:
        builder = TradingContextBuilder(indicator_service, position_manager)

        # In strategy evaluation loop:
        ctx = builder.get_context("BTC", timestamp=current_timestamp)
        # ctx is cached - subsequent calls with same timestamp return same object
    """

    def __init__(
        self,
        indicator_service: IndicatorService,
        position_manager: PositionManager | None = None,
    ):
        """Initialize context builder.

        Args:
            indicator_service: Shared indicator calculation service.
            position_manager: Optional position manager for cross-strategy awareness.
        """
        self._indicators = indicator_service
        self._positions = position_manager

        # Cache: symbol -> TradingContext
        self._cache: dict[str, TradingContext] = {}
        self._cache_timestamp: int = 0

        logger.info("TradingContextBuilder initialized")

    def get_context(self, symbol: str, timestamp: int) -> TradingContext | None:
        """Get or build context for symbol.

        Cache invalidates when timestamp changes (new tick).

        Args:
            symbol: Trading symbol (BTC, ETH, SOL).
            timestamp: Current tick timestamp in milliseconds.

        Returns:
            TradingContext with market data, regime, and positions.
            None if market data unavailable.
        """
        # Invalidate cache on new tick
        if timestamp != self._cache_timestamp:
            self._cache.clear()
            self._cache_timestamp = timestamp

        # Return cached context if available
        if symbol in self._cache:
            return self._cache[symbol]

        # Build new context
        ctx = self._build(symbol, timestamp)

        if ctx is not None:
            self._cache[symbol] = ctx

        return ctx

    def _build(self, symbol: str, timestamp: int) -> TradingContext | None:
        """Build TradingContext from components.

        Args:
            symbol: Trading symbol.
            timestamp: Current timestamp.

        Returns:
            TradingContext or None if market data unavailable.
        """
        # 1. Get market data from IndicatorService (already cached)
        market_data = self._indicators.get_market_data(symbol)
        if market_data is None:
            logger.debug(f"TradingContextBuilder: No market data for {symbol}")
            return None

        # 2. Build regime context (computed once here)
        regime = build_market_context(
            mfi=market_data.mfi,
            adx=market_data.adx,
            atr=market_data.atr,
            close=market_data.close,
            volume=market_data.volume,
            avg_volume=market_data.avg_volume_20,
        )

        # 3. Get positions for cross-strategy awareness
        positions = {}
        if self._positions is not None:
            positions = self._positions.get_positions_for_symbol(symbol)

        return TradingContext(
            symbol=symbol,
            timestamp=timestamp,
            market=market_data,
            regime=regime,
            positions=positions,
        )

    def invalidate(self, symbol: str | None = None) -> None:
        """Invalidate cache for a symbol or all symbols.

        Args:
            symbol: Symbol to invalidate, or None for all.
        """
        if symbol:
            self._cache.pop(symbol, None)
        else:
            self._cache.clear()

    def update_position(self, symbol: str, strategy: str, position) -> None:
        """Update position in cache for cross-strategy awareness.

        Called by CompositeStrategyTask when positions change.

        Args:
            symbol: Trading symbol.
            strategy: Strategy name.
            position: Position object or None to remove.
        """
        if symbol in self._cache:
            ctx = self._cache[symbol]
            # Create new positions dict (immutable update)
            new_positions = dict(ctx.positions)
            if position is None:
                new_positions.pop(strategy, None)
            else:
                new_positions[strategy] = position

            # Create new context with updated positions
            from dataclasses import replace
            self._cache[symbol] = replace(ctx, positions=new_positions)
