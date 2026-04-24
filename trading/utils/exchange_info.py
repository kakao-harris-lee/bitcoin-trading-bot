"""Exchange info cache for Binance symbol trading rules.

Fetches and caches exchangeInfo from Binance REST API for precision
and filter compliance.

Usage:
    cache = ExchangeInfoCache()

    # Fetch and cache info for symbols
    await cache.refresh(["BTC", "ETH", "SOL"])

    # Get symbol info
    info = cache.get("BTC")
    qty = PriceUtils.round_quantity("0.123456", info)
"""
# pylint: disable=broad-exception-caught

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp

from .precision import SymbolInfo, get_default_symbol_info

logger = logging.getLogger(__name__)

BINANCE_SPOT_API = "https://api.binance.com"
# Cache TTL in seconds (1 hour)
CACHE_TTL = 3600


class ExchangeInfoCache:
    """Caches Binance exchangeInfo for symbol precision and filters.

    Provides SymbolInfo objects with accurate trading rules fetched
    from the exchange. Falls back to defaults if fetch fails.
    """

    def __init__(self, market: str = "spot", ttl: int = CACHE_TTL):
        """Initialize cache.

        Args:
            market: Market type ("spot" only).
            ttl: Cache time-to-live in seconds.
        """
        self._market = "spot"
        self._ttl = ttl
        self._cache: dict[str, SymbolInfo] = {}
        self._last_refresh: float = 0
        self._lock = asyncio.Lock()

    @property
    def is_stale(self) -> bool:
        """Check if cache needs refresh."""
        return time.time() - self._last_refresh > self._ttl

    async def refresh(self, symbols: list[str] | None = None) -> None:
        """Fetch exchangeInfo from Binance and update cache.

        Args:
            symbols: Optional list of symbols to fetch. If None, fetches all.
        """
        async with self._lock:
            try:
                info = await self._fetch_exchange_info()
                if info:
                    self._parse_exchange_info(info, symbols)
                    self._last_refresh = time.time()
                    logger.info("ExchangeInfoCache: Refreshed %d symbols", len(self._cache))
            except Exception as e:
                logger.error("ExchangeInfoCache: Refresh failed: %s", e)

    async def _fetch_exchange_info(self) -> dict[str, Any] | None:
        """Fetch exchangeInfo from Binance API."""
        url = f"{BINANCE_SPOT_API}/api/v3/exchangeInfo"

        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error("Binance API error: %s - %s", response.status, error)
                        return None
                    return await response.json()
        except aiohttp.ClientError as e:
            logger.error("Failed to fetch exchangeInfo: %s", e)
            return None

    def _parse_exchange_info(
        self,
        info: dict[str, Any],
        symbols: list[str] | None = None,
    ) -> None:
        """Parse exchangeInfo response into SymbolInfo objects."""
        symbols_data = info.get("symbols", [])

        # Normalize symbols to USDT pairs
        target_symbols = None
        if symbols:
            target_symbols = {
                f"{s.upper()}USDT" if not s.endswith("USDT") else s.upper()
                for s in symbols
            }

        for sym_info in symbols_data:
            symbol = sym_info.get("symbol", "")

            # Filter to requested symbols if specified
            if target_symbols and symbol not in target_symbols:
                continue

            # Only process USDT pairs
            if not symbol.endswith("USDT"):
                continue

            try:
                self._cache[symbol] = SymbolInfo.from_exchange_info(symbol, sym_info)
            except Exception as e:
                logger.warning("Failed to parse symbol %s: %s", symbol, e)

    def get(self, symbol: str) -> SymbolInfo:
        """Get SymbolInfo for a symbol.

        Falls back to defaults if not in cache.

        Args:
            symbol: Trading symbol (e.g., "BTC" or "BTCUSDT").

        Returns:
            SymbolInfo for the symbol.
        """
        # Normalize symbol
        if not symbol.endswith("USDT"):
            symbol = f"{symbol.upper()}USDT"
        else:
            symbol = symbol.upper()

        # Try cache first
        if symbol in self._cache:
            return self._cache[symbol]

        # Fall back to defaults
        defaults = get_default_symbol_info()
        if symbol in defaults:
            return defaults[symbol]

        # Generic fallback
        logger.warning("No symbol info for %s, using generic defaults", symbol)
        return SymbolInfo(
            symbol=symbol,
            price_precision=8,
            qty_precision=8,
            min_qty="0.00000001",
            step_size="0.00000001",
            tick_size="0.00000001",
            min_notional="10.0",
        )

    def get_all(self) -> dict[str, SymbolInfo]:
        """Get all cached symbol info."""
        return self._cache.copy()

    async def ensure_loaded(self, symbols: list[str]) -> None:
        """Ensure symbols are loaded, refreshing if needed.

        Args:
            symbols: List of symbols to ensure are cached.
        """
        # Check if all symbols are cached
        missing = []
        for sym in symbols:
            normalized = f"{sym.upper()}USDT" if not sym.endswith("USDT") else sym.upper()
            if normalized not in self._cache:
                missing.append(sym)

        # Refresh if missing symbols or cache is stale
        if missing or self.is_stale:
            await self.refresh(symbols)


# Global cache instances
_CACHE_BY_MARKET: dict[str, ExchangeInfoCache | None] = {"spot": None}


def get_exchange_cache(market: str = "spot") -> ExchangeInfoCache:
    """Get the global exchange info cache.

    Args:
        market: Market type ("spot" only).

    Returns:
        ExchangeInfoCache instance.
    """
    del market
    cache = _CACHE_BY_MARKET["spot"]
    if cache is None:
        cache = ExchangeInfoCache(market="spot")
        _CACHE_BY_MARKET["spot"] = cache
    return cache


async def get_symbol_info_live(
    symbol: str,
    market: str = "spot",
) -> SymbolInfo:
    """Get symbol info, fetching from exchange if needed.

    Args:
        symbol: Trading symbol.
        market: Market type ("spot" only).

    Returns:
        SymbolInfo for the symbol.
    """
    cache = get_exchange_cache(market)
    await cache.ensure_loaded([symbol])
    return cache.get(symbol)
