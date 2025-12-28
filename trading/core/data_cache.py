"""
DataCache - In-memory OHLCV cache with hybrid update strategy.

- Initial load from DB at startup
- Current candle aggregated from WebSocket ticks
- Background sync with DB every 5 minutes for historical accuracy
"""

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, Optional, Any, Literal

import pandas as pd

logger = logging.getLogger(__name__)


@dataclass
class OHLCV:
    """Single OHLCV candle."""
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "timestamp": self.timestamp.isoformat() if self.timestamp else None,
        }


class DataCache:
    """
    In-memory OHLCV cache with hybrid update strategy.

    Strategy:
    - Load historical data from DB at startup
    - Aggregate current candle from WebSocket ticks
    - Sync with DB every 5 minutes for historical accuracy
    - Memory limited to max_rows per timeframe
    """

    SUPPORTED_TIMEFRAMES = ["minute60", "day"]

    def __init__(
        self,
        max_rows: int = 5000,
        sync_interval: int = 300,  # 5 minutes
        initial_lookback_days: int = 365,
        exchange: Literal["upbit", "binance"] = "upbit",
    ):
        """
        Args:
            max_rows: Maximum rows to keep per timeframe
            sync_interval: DB sync interval in seconds
            initial_lookback_days: Days of history to load at startup
            exchange: Data source exchange
        """
        self._cache: Dict[str, pd.DataFrame] = {}
        self._current_candle: Dict[str, OHLCV] = {}
        self._candle_start: Dict[str, datetime] = {}
        self._max_rows = max_rows
        self._sync_interval = sync_interval
        self._initial_lookback_days = initial_lookback_days
        self._exchange = exchange
        self._started = False
        self._sync_task: Optional[asyncio.Task] = None
        self._last_sync: Dict[str, datetime] = {}
        self._tick_count: int = 0

    async def start(self) -> None:
        """Initialize cache with data from DB."""
        if self._started:
            return

        logger.info("DataCache starting - loading initial data from DB...")

        # Load initial data in thread pool (DB is blocking)
        await asyncio.to_thread(self._load_initial_data)

        # Start background sync loop
        self._sync_task = asyncio.create_task(self._db_sync_loop())
        self._started = True

        logger.info(f"DataCache started with {len(self._cache)} timeframes")

    async def stop(self) -> None:
        """Stop background sync."""
        if self._sync_task:
            self._sync_task.cancel()
            try:
                await self._sync_task
            except asyncio.CancelledError:
                pass
        self._started = False
        logger.info("DataCache stopped")

    def _load_initial_data(self) -> None:
        """Load initial data from DB (runs in thread)."""
        from core.data_loader import DataLoader

        start_date = (
            datetime.now() - timedelta(days=self._initial_lookback_days)
        ).strftime("%Y-%m-%d")

        try:
            loader = DataLoader(exchange=self._exchange)

            for tf in self.SUPPORTED_TIMEFRAMES:
                try:
                    df = loader.load_timeframe(tf, start_date=start_date)
                    if df is not None and len(df) > 0:
                        self._cache[tf] = df.tail(self._max_rows).copy()
                        self._last_sync[tf] = datetime.now()
                        logger.info(f"Loaded {len(self._cache[tf])} rows for {tf}")
                    else:
                        self._cache[tf] = pd.DataFrame()
                        logger.warning(f"No data found for {tf}")
                except Exception as e:
                    logger.error(f"Failed to load {tf}: {e}")
                    self._cache[tf] = pd.DataFrame()

            loader.close()
        except Exception as e:
            logger.error(f"DataLoader initialization failed: {e}")
            # Initialize empty caches
            for tf in self.SUPPORTED_TIMEFRAMES:
                self._cache[tf] = pd.DataFrame()

    async def _db_sync_loop(self) -> None:
        """Background loop to sync with DB periodically."""
        while True:
            await asyncio.sleep(self._sync_interval)
            try:
                await asyncio.to_thread(self._sync_from_db)
            except Exception as e:
                logger.error(f"DB sync failed: {e}")

    def _sync_from_db(self) -> None:
        """Refresh cache from DB (runs in thread)."""
        from core.data_loader import DataLoader

        start_date = (
            datetime.now() - timedelta(days=self._initial_lookback_days)
        ).strftime("%Y-%m-%d")

        try:
            loader = DataLoader(exchange=self._exchange)

            for tf in self.SUPPORTED_TIMEFRAMES:
                try:
                    df = loader.load_timeframe(tf, start_date=start_date)
                    if df is not None and len(df) > 0:
                        self._cache[tf] = df.tail(self._max_rows).copy()
                        self._last_sync[tf] = datetime.now()
                        logger.debug(f"Synced {len(self._cache[tf])} rows for {tf}")
                except Exception as e:
                    logger.error(f"Failed to sync {tf}: {e}")

            loader.close()
        except Exception as e:
            logger.error(f"DataLoader sync failed: {e}")

    def update_from_tick(
        self,
        price: float,
        volume: float,
        timestamp: Optional[datetime] = None
    ) -> None:
        """
        Aggregate tick into current candle.

        Args:
            price: Current price
            volume: Trade volume
            timestamp: Trade timestamp (defaults to now)
        """
        if timestamp is None:
            timestamp = datetime.now()

        self._tick_count += 1

        # Determine candle boundaries
        # minute60: start of hour
        hour_start = timestamp.replace(minute=0, second=0, microsecond=0)
        self._update_candle("minute60", hour_start, price, volume)

        # day: start of day
        day_start = timestamp.replace(hour=0, minute=0, second=0, microsecond=0)
        self._update_candle("day", day_start, price, volume)

    def _update_candle(
        self,
        timeframe: str,
        candle_start: datetime,
        price: float,
        volume: float
    ) -> None:
        """Update or create candle for timeframe."""
        current_start = self._candle_start.get(timeframe)

        if current_start != candle_start:
            # New candle period - finalize previous and start new
            if timeframe in self._current_candle and current_start is not None:
                self._finalize_candle(timeframe)

            # Start new candle
            self._current_candle[timeframe] = OHLCV(
                open=price,
                high=price,
                low=price,
                close=price,
                volume=volume,
                timestamp=candle_start,
            )
            self._candle_start[timeframe] = candle_start
        else:
            # Update existing candle
            candle = self._current_candle[timeframe]
            candle.high = max(candle.high, price)
            candle.low = min(candle.low, price)
            candle.close = price
            candle.volume += volume

    def _finalize_candle(self, timeframe: str) -> None:
        """Append completed candle to cache."""
        candle = self._current_candle.get(timeframe)
        if candle is None:
            return

        # Create row
        new_row = pd.DataFrame([{
            "timestamp": candle.timestamp,
            "open": candle.open,
            "high": candle.high,
            "low": candle.low,
            "close": candle.close,
            "volume": candle.volume,
        }])

        # Append to cache
        if timeframe in self._cache and len(self._cache[timeframe]) > 0:
            self._cache[timeframe] = pd.concat(
                [self._cache[timeframe], new_row],
                ignore_index=True
            )
            # Enforce max rows
            if len(self._cache[timeframe]) > self._max_rows:
                self._cache[timeframe] = self._cache[timeframe].tail(self._max_rows)
        else:
            self._cache[timeframe] = new_row

        logger.debug(f"Finalized candle for {timeframe}: {candle.close}")

    def get_df(
        self,
        timeframe: str,
        periods: int = 200
    ) -> pd.DataFrame:
        """
        Get DataFrame for timeframe (instant, from cache).

        Args:
            timeframe: "minute60" or "day"
            periods: Number of periods to return

        Returns:
            DataFrame with OHLCV columns, or empty DataFrame if not available
        """
        if timeframe not in self._cache:
            logger.warning(f"Timeframe {timeframe} not in cache")
            return pd.DataFrame()

        df = self._cache[timeframe]
        if len(df) == 0:
            return pd.DataFrame()

        return df.tail(periods).copy()

    def get_current_candle(self, timeframe: str) -> Optional[OHLCV]:
        """Get the current (incomplete) candle being built from ticks."""
        return self._current_candle.get(timeframe)

    def get_sizes(self) -> Dict[str, int]:
        """Get row counts per timeframe."""
        return {tf: len(df) for tf, df in self._cache.items()}

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "started": self._started,
            "exchange": self._exchange,
            "max_rows": self._max_rows,
            "sync_interval": self._sync_interval,
            "tick_count": self._tick_count,
            "timeframes": {
                tf: {
                    "rows": len(df),
                    "last_sync": self._last_sync.get(tf, None),
                    "current_candle": self._current_candle.get(tf) is not None,
                }
                for tf, df in self._cache.items()
            },
        }
