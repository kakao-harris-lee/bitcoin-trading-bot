"""
MultiAssetDataCache - Partitioned OHLCV cache for multiple assets.

Wraps multiple DataCache instances, one per symbol.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any

import pandas as pd

from trading.core.data_cache import DataCache

logger = logging.getLogger(__name__)


class MultiAssetDataCache:
    """
    Multi-asset data cache with per-symbol partitioning.

    Each symbol gets its own DataCache instance with separate
    DB connection and in-memory storage.
    """

    def __init__(
        self,
        symbols: List[str],
        db_paths: Dict[str, str],
        max_rows: int = 5000,
        sync_interval: int = 300,
        initial_lookback_days: int = 365,
    ):
        """
        Args:
            symbols: List of asset symbols (e.g., ["BTC", "ETH", "SOL"])
            db_paths: Map of symbol to DB path
            max_rows: Maximum rows per timeframe per symbol
            sync_interval: DB sync interval in seconds
            initial_lookback_days: Days of history to load
        """
        self._symbols = symbols
        self._caches: Dict[str, DataCache] = {}
        self._started = False

        # Create a DataCache for each symbol
        for symbol in symbols:
            db_path = db_paths.get(symbol)
            if not db_path:
                logger.warning(f"No DB path for {symbol}, skipping")
                continue

            # DataCache uses exchange parameter for DB path resolution
            # We'll need to patch this or use a custom loader
            self._caches[symbol] = DataCache(
                max_rows=max_rows,
                sync_interval=sync_interval,
                initial_lookback_days=initial_lookback_days,
                exchange="upbit",  # Default, will be overridden by db_path
            )
            # Store db_path for later use
            self._caches[symbol]._db_path = db_path

        logger.info(f"MultiAssetDataCache initialized with symbols: {symbols}")

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "MultiAssetDataCache":
        """
        Create MultiAssetDataCache from allocation config.

        Args:
            config: Allocation config with "assets" section

        Returns:
            Configured MultiAssetDataCache
        """
        assets = config.get("assets", {})
        symbols = []
        db_paths = {}

        for symbol, asset_config in assets.items():
            if asset_config.get("enabled", False):
                symbols.append(symbol)
                db_paths[symbol] = asset_config.get("db_path", f"data/upbit_{symbol.lower()}.db")

        return cls(symbols=symbols, db_paths=db_paths)

    async def start(self) -> None:
        """Start all data caches concurrently."""
        if self._started:
            return

        logger.info(f"Starting MultiAssetDataCache for {len(self._caches)} symbols...")

        # Start all caches in parallel
        await asyncio.gather(*[
            cache.start() for cache in self._caches.values()
        ])

        self._started = True
        logger.info("MultiAssetDataCache started")

    async def stop(self) -> None:
        """Stop all data caches."""
        await asyncio.gather(*[
            cache.stop() for cache in self._caches.values()
        ])
        self._started = False
        logger.info("MultiAssetDataCache stopped")

    def update_from_tick(
        self,
        symbol: str,
        price: float,
        volume: float,
        timestamp=None
    ) -> None:
        """
        Update tick for a specific symbol.

        Args:
            symbol: Asset symbol (e.g., "BTC")
            price: Current price
            volume: Trade volume
            timestamp: Trade timestamp
        """
        if symbol not in self._caches:
            logger.warning(f"Unknown symbol: {symbol}")
            return

        self._caches[symbol].update_from_tick(price, volume, timestamp)

    def get_df(
        self,
        symbol: str,
        timeframe: str,
        periods: int = 200
    ) -> pd.DataFrame:
        """
        Get DataFrame for specific symbol and timeframe.

        Args:
            symbol: Asset symbol
            timeframe: "minute60" or "day"
            periods: Number of periods

        Returns:
            DataFrame with OHLCV columns
        """
        if symbol not in self._caches:
            logger.warning(f"Unknown symbol: {symbol}")
            return pd.DataFrame()

        return self._caches[symbol].get_df(timeframe, periods)

    def get_current_candle(self, symbol: str, timeframe: str):
        """Get current incomplete candle for symbol."""
        if symbol not in self._caches:
            return None
        return self._caches[symbol].get_current_candle(timeframe)

    def get_symbols(self) -> List[str]:
        """Get list of tracked symbols."""
        return list(self._caches.keys())

    def get_cache(self, symbol: str) -> Optional[DataCache]:
        """Get DataCache for specific symbol."""
        return self._caches.get(symbol)

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for all caches."""
        return {
            "started": self._started,
            "symbols": self._symbols,
            "caches": {
                symbol: cache.get_stats()
                for symbol, cache in self._caches.items()
            },
        }

    def get_sizes(self) -> Dict[str, int]:
        """
        Get combined row counts per timeframe across all symbols.

        Returns aggregated sizes for health check compatibility.
        """
        combined: Dict[str, int] = {}
        for symbol, cache in self._caches.items():
            for tf, size in cache.get_sizes().items():
                key = f"{symbol}:{tf}"
                combined[key] = size
        return combined
