"""
FXRateCache - Real-time USD/KRW exchange rate with auto-refresh.

Uses exchangerate-api.com free tier (1500 requests/month).
Refreshes every 5 minutes, with fallback to last known rate.
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional, Dict, Any, Callable

import aiohttp

logger = logging.getLogger(__name__)


class FXRateCache:
    """
    USD/KRW exchange rate cache with background refresh.

    Features:
    - Auto-refresh every 5 minutes
    - Fallback to last known rate on API failure
    - Callback to notify PriceHub of rate changes
    - Stale detection for monitoring
    """

    # exchangerate-api.com free tier
    DEFAULT_API_URL = "https://api.exchangerate-api.com/v4/latest/USD"

    # Backup APIs (in case primary fails)
    BACKUP_APIS = [
        # Open Exchange Rates (free tier)
        "https://open.er-api.com/v6/latest/USD",
    ]

    def __init__(
        self,
        default_rate: float = 1450.0,
        refresh_interval: int = 300,  # 5 minutes
        api_url: Optional[str] = None,
        on_rate_change: Optional[Callable[[float], None]] = None,
    ):
        """
        Args:
            default_rate: Fallback rate if API fails
            refresh_interval: Refresh interval in seconds
            api_url: Custom API URL (optional)
            on_rate_change: Callback when rate changes (for PriceHub)
        """
        self._rate: float = default_rate
        self._default_rate: float = default_rate
        self._refresh_interval: int = refresh_interval
        self._api_url: str = api_url or self.DEFAULT_API_URL
        self._on_rate_change: Optional[Callable[[float], None]] = on_rate_change

        self._updated_at: Optional[datetime] = None
        self._started: bool = False
        self._refresh_task: Optional[asyncio.Task] = None
        self._session: Optional[aiohttp.ClientSession] = None

        # Statistics
        self._fetch_count: int = 0
        self._error_count: int = 0
        self._last_error: Optional[str] = None

    async def start(self) -> None:
        """Start background refresh loop."""
        if self._started:
            return

        self._session = aiohttp.ClientSession(
            timeout=aiohttp.ClientTimeout(total=10)
        )

        # Initial fetch
        await self._fetch_rate()

        # Start background refresh
        self._refresh_task = asyncio.create_task(self._refresh_loop())
        self._started = True

        logger.info(f"FXRateCache started: {self._rate:.2f} KRW/USD")

    async def stop(self) -> None:
        """Stop background refresh."""
        if self._refresh_task:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except asyncio.CancelledError:
                pass

        if self._session:
            await self._session.close()
            self._session = None

        self._started = False
        logger.info("FXRateCache stopped")

    async def _refresh_loop(self) -> None:
        """Background loop to refresh rate periodically."""
        while True:
            await asyncio.sleep(self._refresh_interval)
            try:
                await self._fetch_rate()
            except Exception as e:
                self._error_count += 1
                self._last_error = str(e)
                logger.warning(f"FX rate fetch failed: {e}, using {self._rate:.2f}")

    async def _fetch_rate(self) -> None:
        """Fetch rate from API."""
        if not self._session:
            return

        # Try primary API
        rate = await self._try_fetch(self._api_url)

        # Try backups if primary failed
        if rate is None:
            for backup_url in self.BACKUP_APIS:
                rate = await self._try_fetch(backup_url)
                if rate is not None:
                    logger.info(f"Using backup API: {backup_url}")
                    break

        if rate is not None:
            old_rate = self._rate
            self._rate = rate
            self._updated_at = datetime.now()
            self._fetch_count += 1

            # Notify callback if rate changed significantly (>0.1%)
            if self._on_rate_change and old_rate > 0:
                if abs(rate - old_rate) / old_rate > 0.001:
                    self._on_rate_change(rate)

            logger.info(f"FX rate updated: {self._rate:.2f} KRW/USD")
        else:
            self._error_count += 1
            logger.warning(f"All FX APIs failed, using last rate: {self._rate:.2f}")

    async def _try_fetch(self, url: str) -> Optional[float]:
        """Try to fetch rate from a single API."""
        try:
            async with self._session.get(url) as resp:
                if resp.status != 200:
                    logger.debug(f"API returned {resp.status}: {url}")
                    return None

                data = await resp.json()

                # Handle different API response formats
                if "rates" in data:
                    # exchangerate-api.com format
                    krw = data["rates"].get("KRW")
                    if krw:
                        return float(krw)

                logger.debug(f"Unexpected API response format: {url}")
                return None

        except asyncio.TimeoutError:
            logger.debug(f"API timeout: {url}")
            return None
        except aiohttp.ClientError as e:
            logger.debug(f"API client error: {url} - {e}")
            return None
        except Exception as e:
            logger.debug(f"API error: {url} - {e}")
            return None

    @property
    def rate(self) -> float:
        """Get current USD/KRW rate."""
        return self._rate

    @property
    def updated_at(self) -> Optional[datetime]:
        """Get last update time."""
        return self._updated_at

    @property
    def is_stale(self) -> bool:
        """Check if rate is stale (>2x refresh interval)."""
        if self._updated_at is None:
            return True
        age = (datetime.now() - self._updated_at).total_seconds()
        return age > self._refresh_interval * 2

    @property
    def age_seconds(self) -> Optional[float]:
        """Get age of rate in seconds."""
        if self._updated_at is None:
            return None
        return (datetime.now() - self._updated_at).total_seconds()

    def get_stats(self) -> Dict[str, Any]:
        """Get cache statistics."""
        return {
            "rate": self._rate,
            "updated_at": self._updated_at.isoformat() if self._updated_at else None,
            "age_seconds": self.age_seconds,
            "is_stale": self.is_stale,
            "started": self._started,
            "refresh_interval": self._refresh_interval,
            "fetch_count": self._fetch_count,
            "error_count": self._error_count,
            "last_error": self._last_error,
            "api_url": self._api_url,
        }


async def main():
    """Test the FX rate cache."""
    logging.basicConfig(level=logging.INFO)

    cache = FXRateCache(refresh_interval=10)  # 10s for testing

    try:
        await cache.start()
        print(f"Initial rate: {cache.rate:.2f} KRW/USD")

        # Wait for a few refreshes
        for i in range(3):
            await asyncio.sleep(12)
            print(f"Rate after {(i+1)*12}s: {cache.rate:.2f} KRW/USD")
            print(f"Stats: {cache.get_stats()}")

    finally:
        await cache.stop()


if __name__ == "__main__":
    asyncio.run(main())
