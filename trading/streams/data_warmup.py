"""Data Warm-up - fetch recent candles from Binance REST API.

Solves the problem of waiting 180 candles to calculate indicators after restart.
Fetches historical data via REST API to immediately populate strategy buffers.

Usage:
    warmup = DataWarmup()

    # Fetch recent 1-hour candles
    candles = await warmup.fetch_recent_candles("BTC", limit=200, interval="1h")

    # Convert to price messages for Redis
    messages = warmup.candles_to_price_messages(candles, symbol="BTC", market="spot")
"""

from __future__ import annotations

import logging
import time
from typing import Any

import aiohttp

logger = logging.getLogger(__name__)

# Binance REST API endpoints
BINANCE_SPOT_API = "https://api.binance.com"
BINANCE_FUTURES_API = "https://fapi.binance.com"


class DataWarmup:
    """Fetch recent candles from Binance REST API for warm-up.

    Uses Binance klines endpoint to get historical OHLCV data.
    """

    # Interval mapping to milliseconds
    INTERVAL_MS = {
        "1m": 60 * 1000,
        "3m": 3 * 60 * 1000,
        "5m": 5 * 60 * 1000,
        "15m": 15 * 60 * 1000,
        "30m": 30 * 60 * 1000,
        "1h": 60 * 60 * 1000,
        "4h": 4 * 60 * 60 * 1000,
        "1d": 24 * 60 * 60 * 1000,
    }

    def __init__(self, timeout: int = 30):
        """Initialize warm-up loader.

        Args:
            timeout: Request timeout in seconds.
        """
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def fetch_recent_candles(
        self,
        symbol: str,
        limit: int = 200,
        interval: str = "1h",
        market: str = "spot",
    ) -> list[dict[str, Any]]:
        """Fetch recent candles from Binance REST API.

        Args:
            symbol: Trading symbol (e.g., "BTC", "ETH").
            limit: Number of candles to fetch (max 1000).
            interval: Candle interval (1m, 5m, 15m, 1h, 4h, 1d).
            market: Market type ("spot" or "futures").

        Returns:
            List of candle dicts with keys:
            - timestamp: Unix timestamp in ms
            - open, high, low, close: Prices
            - volume: Trading volume
        """
        pair = f"{symbol.upper()}USDT"

        # Select API endpoint
        if market == "futures":
            base_url = BINANCE_FUTURES_API
            endpoint = "/fapi/v1/klines"
        else:
            base_url = BINANCE_SPOT_API
            endpoint = "/api/v3/klines"

        url = f"{base_url}{endpoint}"
        params = {
            "symbol": pair,
            "interval": interval,
            "limit": min(limit, 1000),  # Binance max is 1000
        }

        try:
            async with aiohttp.ClientSession(timeout=self._timeout) as session:
                async with session.get(url, params=params) as response:
                    if response.status != 200:
                        error = await response.text()
                        logger.error(f"Binance API error: {response.status} - {error}")
                        return []

                    data = await response.json()

            candles = []
            for kline in data:
                # Binance kline format:
                # [open_time, open, high, low, close, volume, close_time, ...]
                candles.append({
                    "timestamp": int(kline[0]),
                    "open": float(kline[1]),
                    "high": float(kline[2]),
                    "low": float(kline[3]),
                    "close": float(kline[4]),
                    "volume": float(kline[5]),
                })

            logger.info(
                f"Fetched {len(candles)} {interval} candles for {symbol} ({market})"
            )
            return candles

        except aiohttp.ClientError as e:
            logger.error(f"Failed to fetch candles for {symbol}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error fetching candles for {symbol}: {e}")
            return []

    def candles_to_price_messages(
        self,
        candles: list[dict[str, Any]],
        symbol: str,
        market: str = "spot",
    ) -> list[dict[str, Any]]:
        """Convert candles to price message format for Redis.

        Uses the close price from each candle as the price.

        Args:
            candles: List of candle dicts from fetch_recent_candles.
            symbol: Trading symbol.
            market: Market type.

        Returns:
            List of price message dicts compatible with Redis stream format.
        """
        messages = []
        for candle in candles:
            messages.append({
                "symbol": symbol,
                "price": str(candle["close"]),
                "source": "binance",
                "market": market,
                "timestamp": str(candle["timestamp"]),
                # Include OHLCV for indicator calculation
                "open": str(candle["open"]),
                "high": str(candle["high"]),
                "low": str(candle["low"]),
                "close": str(candle["close"]),
                "volume": str(candle["volume"]),
                "warmup": "true",  # Flag to identify warm-up data
            })
        return messages

    async def warmup_symbol(
        self,
        symbol: str,
        market: str = "spot",
        limit: int = 200,
        interval: str = "1h",
    ) -> list[dict[str, Any]]:
        """Convenience method to fetch and convert candles.

        Args:
            symbol: Trading symbol.
            market: Market type.
            limit: Number of candles.
            interval: Candle interval.

        Returns:
            List of price messages ready for Redis.
        """
        candles = await self.fetch_recent_candles(
            symbol=symbol,
            limit=limit,
            interval=interval,
            market=market,
        )
        return self.candles_to_price_messages(candles, symbol, market)


async def fetch_warmup_data(
    symbols: list[str],
    market: str = "spot",
    limit: int = 200,
    interval: str = "1h",
) -> dict[str, list[dict[str, Any]]]:
    """Fetch warm-up data for multiple symbols.

    Convenience function for bulk warm-up.

    Args:
        symbols: List of symbols.
        market: Market type.
        limit: Number of candles per symbol.
        interval: Candle interval.

    Returns:
        Dict mapping symbol -> list of price messages.
    """
    warmup = DataWarmup()
    result = {}

    for symbol in symbols:
        messages = await warmup.warmup_symbol(
            symbol=symbol,
            market=market,
            limit=limit,
            interval=interval,
        )
        result[symbol] = messages

    return result
