"""TradingContext builder for centralized context construction.

This module provides the TradingContextBuilder class that builds
TradingContext objects once per symbol per tick, caching results
to avoid redundant computation across multiple strategies.
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import replace
from types import MappingProxyType
from typing import TYPE_CHECKING

from .models import TradingContext, Position, build_market_context

if TYPE_CHECKING:
    from trading.indicators.indicator_service import IndicatorService

logger = logging.getLogger(__name__)


class PositionManager:
    """Manages position lookups from Redis.

    Provides a clean interface for retrieving positions across strategies.
    """

    def __init__(self, redis_client, cache_ttl_seconds: float = 1.0):
        """Initialize with Redis client.

        Args:
            redis_client: Async Redis client instance.
        """
        self._redis = redis_client
        self._cache_ttl_seconds = cache_ttl_seconds
        self._cache_ts: float = 0.0
        self._positions_by_symbol: dict[str, dict[str, Position]] = {}
        self._portfolio_positions: dict[str, Position] = {}
        try:
            self._stream_symbol_scan_count = max(
                50,
                int(os.getenv("POSITION_EVENT_SCAN_COUNT", "512")),
            )
        except ValueError:
            self._stream_symbol_scan_count = 512

    @staticmethod
    def _parse_position(
        symbol: str,
        market: str,
        raw: dict,
    ) -> Position | None:
        """Parse Redis hash into Position."""
        try:
            quantity = float(raw.get("quantity", 0.0))
            entry_price = float(raw.get("entry_price", 0.0))
            entry_time = int(raw.get("entry_time", 0) or 0)
            timestamp = int(raw.get("timestamp", 0) or 0)
            if timestamp <= 0:
                timestamp = entry_time
            strategy = raw.get("strategy", f"{symbol}_{market}")
            side = raw.get("side", "buy")
            leverage = int(raw.get("leverage", 1))
            liquidation_price = float(raw.get("liquidation_price", 0.0))
        except (TypeError, ValueError):
            return None

        if quantity <= 0 or entry_price <= 0:
            return None

        return Position(
            symbol=symbol,
            entry_price=entry_price,
            quantity=quantity,
            strategy=strategy,
            market=market,  # type: ignore[arg-type]
            timestamp=timestamp,
            side=side,
            leverage=leverage,
            liquidation_price=liquidation_price,
            entry_time=entry_time if entry_time > 0 else None,
        )

    async def refresh(
        self,
        symbols: list[str] | None = None,
        force: bool = False,
    ) -> None:
        """Refresh cached positions from Redis."""
        now = time.time()
        if not force and now - self._cache_ts < self._cache_ttl_seconds:
            return

        symbols = symbols or await self._discover_symbols()
        if not symbols:
            return

        by_symbol: dict[str, dict[str, Position]] = {}
        portfolio: dict[str, Position] = {}
        for symbol in symbols:
            symbol_positions = await self._load_symbol_positions(symbol)
            by_symbol[symbol] = symbol_positions
            portfolio.update(self._portfolio_entries_for_symbol(symbol_positions))

        self._positions_by_symbol = by_symbol
        self._portfolio_positions = portfolio
        self._cache_ts = now

    async def _discover_symbols(self) -> list[str]:
        return await self._discover_symbols_from_events()

    async def _discover_symbols_from_events(self) -> list[str]:
        """Discover recently active symbols from position event stream first."""
        try:
            events = await self._redis.xrevrange(
                "positions:events",
                count=self._stream_symbol_scan_count,
            )
        except Exception:
            return []

        symbols: set[str] = set()
        for _msg_id, payload in events:
            symbol = str(payload.get("symbol", "")).strip().upper()
            if symbol:
                symbols.add(symbol)
        return sorted(symbols)

    async def _load_symbol_positions(self, symbol: str) -> dict[str, Position]:
        symbol_positions: dict[str, Position] = {}
        for market in ("spot", "futures"):
            key = f"positions:{symbol}:{market}"
            raw = await self._redis.hgetall(key)
            parsed = self._parse_position(symbol, market, raw) if raw else None
            if parsed is None:
                continue
            symbol_positions[parsed.strategy] = parsed
        return symbol_positions

    def _portfolio_entries_for_symbol(
        self, symbol_positions: dict[str, Position]
    ) -> dict[str, Position]:
        entries: dict[str, Position] = {}
        for strategy, position in symbol_positions.items():
            cache_key = f"{position.symbol}:{position.market}:{strategy}"
            entries[cache_key] = position
        return entries

    def get_positions_for_symbol(self, symbol: str) -> dict[str, Position]:
        """Get all positions for a symbol across strategies.

        Note: This is a synchronous method that uses cached position data.
        Position data is updated asynchronously by the executor.

        Args:
            symbol: Trading symbol (BTC, ETH, SOL).

        Returns:
            Dict mapping strategy_name -> Position for this symbol.
        """
        return dict(self._positions_by_symbol.get(symbol, {}))

    def get_portfolio_positions(self) -> dict[str, Position]:
        """Get all open positions across symbols/markets."""
        return dict(self._portfolio_positions)

    def update_cached_position(
        self,
        symbol: str,
        strategy: str,
        position: Position | None,
    ) -> None:
        """Update local cache after position open/close events."""
        per_symbol = dict(self._positions_by_symbol.get(symbol, {}))
        if position is None:
            per_symbol.pop(strategy, None)
            stale_keys = [k for k, p in self._portfolio_positions.items() if p.symbol == symbol and p.strategy == strategy]
            for key in stale_keys:
                self._portfolio_positions.pop(key, None)
        else:
            per_symbol[strategy] = position
            cache_key = f"{symbol}:{position.market}:{strategy}"
            self._portfolio_positions[cache_key] = position
        self._positions_by_symbol[symbol] = per_symbol


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
        regime_thresholds: dict[str, float] | None = None,
    ):
        """Initialize context builder.

        Args:
            indicator_service: Shared indicator calculation service.
            position_manager: Optional position manager for cross-strategy awareness.
            regime_thresholds: Optional dict of MFI/ADX thresholds for regime classification.
        """
        self._indicators = indicator_service
        self._positions = position_manager
        self._regime_thresholds = regime_thresholds or {}

        # Cache: symbol -> TradingContext
        self._cache: dict[str, TradingContext] = {}
        self._cache_timestamp: int = 0

        logger.info("TradingContextBuilder initialized")

    async def refresh_positions(
        self,
        symbols: list[str] | None = None,
        force: bool = False,
    ) -> None:
        """Refresh PositionManager snapshot from Redis."""
        if self._positions is None:
            return
        await self._positions.refresh(symbols=symbols, force=force)

    def get_portfolio_positions(self) -> dict[str, Position]:
        """Get portfolio position snapshot (all symbols)."""
        if self._positions is None:
            return {}
        return self._positions.get_portfolio_positions()

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
            logger.debug("TradingContextBuilder: No market data for %s", symbol)
            return None

        # 2. Build regime context (computed once here)
        # Includes drawdown-based BEAR detection (15% from 30-day high = BEAR override)
        # Use 30-day high for better crash detection (falls back to 20-period if not available)
        recent_high = market_data.high_30d if market_data.high_30d > 0 else market_data.prev_high_20
        regime = build_market_context(
            mfi=market_data.mfi,
            adx=market_data.adx,
            atr=market_data.atr,
            close=market_data.close,
            volume=market_data.volume,
            avg_volume=market_data.avg_volume_20,
            recent_high=recent_high,  # For drawdown-based BEAR detection
            **self._regime_thresholds,
        )

        # 3. Get positions for cross-strategy awareness
        positions: dict[str, Position] = {}
        if self._positions is not None:
            positions = self._positions.get_positions_for_symbol(symbol)

        # Use MappingProxyType for immutable positions view
        return TradingContext(
            symbol=symbol,
            timestamp=timestamp,
            market=market_data,
            regime=regime,
            positions=MappingProxyType(positions),
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

    def update_position(self, symbol: str, strategy: str, position: Position | None) -> None:
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

            # Create new context with updated positions (immutable)
            self._cache[symbol] = replace(ctx, positions=MappingProxyType(new_positions))
        if self._positions is not None:
            self._positions.update_cached_position(symbol, strategy, position)
