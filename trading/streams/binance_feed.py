# trading/streams/binance_feed.py
"""Binance-specific price feed implementation."""
# pylint: disable=broad-exception-caught
from __future__ import annotations
import json
import logging
from typing import Any, AsyncIterator, TYPE_CHECKING
from contextlib import asynccontextmanager

import aiohttp

from .feed_task import SymbolFeedTask
from .data_warmup import DataWarmup

if TYPE_CHECKING:
    from .redis_streams import RedisStreams

logger = logging.getLogger(__name__)

BINANCE_SPOT_WS = "wss://stream.binance.com:9443/ws"
BINANCE_FUTURES_WS = "wss://fstream.binance.com/ws"


class BinanceFeedTask(SymbolFeedTask):
    """Feed task for Binance spot or futures."""

    def __init__(
        self,
        symbol: str,
        redis: RedisStreams,
        market: str = "futures",
        warmup_enabled: bool = True,
        warmup_limit: int = 200,
        warmup_interval: str = "1h",
        **kwargs,
    ):
        super().__init__(symbol=symbol, redis=redis, **kwargs)
        self.market = market
        self._warmup_enabled = warmup_enabled
        self._warmup_limit = warmup_limit
        self._warmup_interval = warmup_interval
        self._warmed_up = False

    async def run(self) -> None:
        """Main loop with warm-up: fetch historical data, then stream live."""
        # Warm-up: fetch historical candles before starting WebSocket
        # (Skip if already done via explicit warmup() call)
        if self._warmup_enabled and not self._warmed_up:
            await self.warmup()

        # Call parent run() for WebSocket streaming
        await super().run()

    async def warmup(self) -> None:
        """Public warmup method - can be called externally before run().

        Fetches historical candles and publishes to Redis stream.
        Safe to call multiple times - only runs once.
        """
        if self._warmed_up:
            return
        await self._do_warmup()

    async def _do_warmup(self) -> None:
        """Fetch and publish historical candles for immediate indicator calculation.

        This eliminates the need to wait for 180+ candles after restart.
        """
        logger.info(
            "Feed %s (%s): Starting warm-up (%d %s candles)",
            self.symbol,
            self.market,
            self._warmup_limit,
            self._warmup_interval,
        )

        try:
            warmup = DataWarmup()
            messages = await warmup.warmup_symbol(
                symbol=self.symbol,
                market=self.market,
                limit=self._warmup_limit,
                interval=self._warmup_interval,
            )

            if not messages:
                logger.warning("Feed %s: No warm-up data received", self.symbol)
                return

            # Publish historical data to Redis stream
            for msg in messages:
                await self.redis.publish("market:prices", msg)

            self._warmed_up = True
            logger.info(
                "Feed %s (%s): Warm-up complete, published %d historical prices",
                self.symbol,
                self.market,
                len(messages),
            )

        except Exception as e:
            logger.error("Feed %s: Warm-up failed: %s", self.symbol, e)
            # Continue anyway - WebSocket will provide live data

    def _build_ws_url(self) -> str:
        """Build WebSocket URL for symbol.

        Uses @miniTicker stream which updates once per second with price data.
        This is much more efficient than @trade stream which sends every trade
        (potentially thousands per second for BTC).
        """
        pair = f"{self.symbol.lower()}usdt"
        # Use miniTicker for efficiency - updates once per second
        stream = f"{pair}@miniTicker"

        if self.market == "futures":
            return f"{BINANCE_FUTURES_WS}/{stream}"
        return f"{BINANCE_SPOT_WS}/{stream}"

    def _parse_ticker_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Parse Binance miniTicker message.

        miniTicker fields:
        - c: Close price (last price)
        - o: Open price
        - h: High price
        - l: Low price
        - v: Total traded base asset volume
        - q: Total traded quote asset volume
        """
        return {
            "price": msg["c"],  # Close price
            "market": self.market,
        }

    @asynccontextmanager
    async def _connect_websocket(self) -> AsyncIterator[AsyncIterator[dict]]:
        """Connect to Binance WebSocket."""
        url = self._build_ws_url()
        logger.info("Connecting to %s", url)

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                async def message_iterator():
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            # miniTicker has event type "24hrMiniTicker"
                            if data.get("e") == "24hrMiniTicker":
                                yield self._parse_ticker_message(data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise ConnectionError(f"WebSocket error: {ws.exception()}")

                yield message_iterator()
