"""
DataCache - In-memory DataFrame caching for performance.

Eliminates repeated database loads by caching DataFrames
with configurable refresh intervals.
"""
# pylint: disable=broad-exception-caught

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, Optional
from threading import Lock

import pandas as pd

from core.data_loader import DataLoader

logger = logging.getLogger(__name__)


class DataCache:
    """
    In-memory DataFrame cache for trading data.

    Features:
    - Configurable refresh intervals per timeframe
    - Thread-safe access
    - Async refresh support
    - Fallback to sync loading if async not available
    """

    DEFAULT_REFRESH_INTERVALS = {
        "day": 60,        # Refresh daily data every 60 minutes
        "minute60": 5,    # Refresh hourly data every 5 minutes
        "minute15": 2,    # Refresh 15-min data every 2 minutes
        "minute5": 1,     # Refresh 5-min data every 1 minute
    }

    def __init__(
        self,
        refresh_intervals: Optional[Dict[str, int]] = None,
        lookback_days: int = 180,
    ):
        """
        Initialize DataCache.

        Args:
            refresh_intervals: Dict of timeframe -> refresh interval in minutes
            lookback_days: Days of historical data to load
        """
        self._cache: Dict[str, pd.DataFrame] = {}
        self._last_refresh: Dict[str, datetime] = {}
        self._refresh_intervals = {
            **self.DEFAULT_REFRESH_INTERVALS,
            **(refresh_intervals or {}),
        }
        self._lookback_days = lookback_days
        self._lock = Lock()
        self._loading: Dict[str, bool] = {}

    def get(self, timeframe: str, periods: Optional[int] = None) -> pd.DataFrame:
        """
        Get cached DataFrame for timeframe.

        Args:
            timeframe: One of "day", "minute60", "minute15", "minute5"
            periods: Optional number of recent periods to return

        Returns:
            Cached DataFrame (empty if not loaded yet)
        """
        with self._lock:
            df = self._cache.get(timeframe, pd.DataFrame())

        if periods and not df.empty:
            return df.tail(periods).copy()

        return df.copy()

    def get_daily(self, periods: Optional[int] = None) -> pd.DataFrame:
        """Convenience method for daily data."""
        return self.get("day", periods)

    def get_hourly(self, periods: int = 200) -> pd.DataFrame:
        """Convenience method for hourly data."""
        return self.get("minute60", periods)

    def is_stale(self, timeframe: str) -> bool:
        """Check if cache for timeframe needs refresh."""
        last = self._last_refresh.get(timeframe)
        if last is None:
            return True

        interval = self._refresh_intervals.get(timeframe, 5)
        return (datetime.now() - last) > timedelta(minutes=interval)

    def needs_refresh(self) -> bool:
        """Check if any timeframe needs refresh."""
        return any(self.is_stale(tf) for tf in self._refresh_intervals.keys())

    def refresh_sync(self, timeframe: str) -> bool:
        """
        Synchronously refresh cache for timeframe.

        Args:
            timeframe: Timeframe to refresh

        Returns:
            True if successful
        """
        if self._loading.get(timeframe, False):
            return False

        try:
            self._loading[timeframe] = True

            with DataLoader() as loader:
                start_date = (datetime.now() - timedelta(days=self._lookback_days)).strftime("%Y-%m-%d")
                df = loader.load_timeframe(timeframe, start_date=start_date)

            with self._lock:
                self._cache[timeframe] = df
                self._last_refresh[timeframe] = datetime.now()

            logger.debug("Cache refreshed: %s (%d rows)", timeframe, len(df))
            return True

        except Exception as e:
            logger.error("Cache refresh failed for %s: %s", timeframe, e)
            return False

        finally:
            self._loading[timeframe] = False

    async def refresh_async(self, timeframe: str) -> bool:
        """
        Asynchronously refresh cache for timeframe.

        Runs the DB load in a thread pool to avoid blocking.
        """
        if self._loading.get(timeframe, False):
            return False

        try:
            self._loading[timeframe] = True
            loop = asyncio.get_event_loop()

            def _load():
                with DataLoader() as loader:
                    start_date = (datetime.now() - timedelta(days=self._lookback_days)).strftime("%Y-%m-%d")
                    return loader.load_timeframe(timeframe, start_date=start_date)

            df = await loop.run_in_executor(None, _load)

            with self._lock:
                self._cache[timeframe] = df
                self._last_refresh[timeframe] = datetime.now()

            logger.debug("Cache refreshed (async): %s (%d rows)", timeframe, len(df))
            return True

        except Exception as e:
            logger.error("Async cache refresh failed for %s: %s", timeframe, e)
            return False

        finally:
            self._loading[timeframe] = False

    def refresh_if_stale_sync(self) -> None:
        """Synchronously refresh all stale caches."""
        for timeframe in self._refresh_intervals.keys():
            if self.is_stale(timeframe):
                self.refresh_sync(timeframe)

    async def refresh_if_stale_async(self) -> None:
        """Asynchronously refresh all stale caches."""
        tasks = []
        for timeframe in self._refresh_intervals.keys():
            if self.is_stale(timeframe):
                tasks.append(self.refresh_async(timeframe))

        if tasks:
            await asyncio.gather(*tasks)

    def preload_sync(self, timeframes: Optional[list] = None) -> None:
        """
        Preload specified timeframes into cache.

        Args:
            timeframes: List of timeframes to load, or None for all
        """
        if timeframes is None:
            timeframes = list(self._refresh_intervals.keys())

        for tf in timeframes:
            if tf not in self._cache:
                self.refresh_sync(tf)

    async def preload_async(self, timeframes: Optional[list] = None) -> None:
        """Async version of preload."""
        if timeframes is None:
            timeframes = list(self._refresh_intervals.keys())

        tasks = [self.refresh_async(tf) for tf in timeframes if tf not in self._cache]
        if tasks:
            await asyncio.gather(*tasks)

    def clear(self, timeframe: Optional[str] = None) -> None:
        """Clear cache for timeframe or all."""
        with self._lock:
            if timeframe:
                self._cache.pop(timeframe, None)
                self._last_refresh.pop(timeframe, None)
            else:
                self._cache.clear()
                self._last_refresh.clear()

    def get_stats(self) -> Dict:
        """Get cache statistics."""
        stats = {}
        for tf in self._refresh_intervals.keys():
            df = self._cache.get(tf)
            last = self._last_refresh.get(tf)
            stats[tf] = {
                "rows": len(df) if df is not None else 0,
                "last_refresh": last.isoformat() if last else None,
                "is_stale": self.is_stale(tf),
                "refresh_interval_min": self._refresh_intervals.get(tf),
            }
        return stats


# Singleton instance for global access
_CACHE_STATE: Dict[str, Optional[DataCache]] = {"instance": None}


def get_data_cache() -> DataCache:
    """Get or create global DataCache instance."""
    cache = _CACHE_STATE["instance"]
    if cache is None:
        cache = DataCache()
        _CACHE_STATE["instance"] = cache
    return cache
