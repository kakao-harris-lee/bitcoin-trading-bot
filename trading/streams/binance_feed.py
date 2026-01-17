# trading/streams/binance_feed.py
"""Binance-specific price feed implementation."""
from __future__ import annotations
import asyncio
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
        market: str = "spot",
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
            f"Feed {self.symbol} ({self.market}): Starting warm-up "
            f"({self._warmup_limit} {self._warmup_interval} candles)"
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
                logger.warning(f"Feed {self.symbol}: No warm-up data received")
                return

            # Publish historical data to Redis stream
            for msg in messages:
                await self.redis.publish("market:prices", msg)

            self._warmed_up = True
            logger.info(
                f"Feed {self.symbol} ({self.market}): Warm-up complete, "
                f"published {len(messages)} historical prices"
            )

        except Exception as e:
            logger.error(f"Feed {self.symbol}: Warm-up failed: {e}")
            # Continue anyway - WebSocket will provide live data

    def _build_ws_url(self) -> str:
        """Build WebSocket URL for symbol."""
        pair = f"{self.symbol.lower()}usdt"
        stream = f"{pair}@trade"

        if self.market == "futures":
            return f"{BINANCE_FUTURES_WS}/{stream}"
        return f"{BINANCE_SPOT_WS}/{stream}"

    def _parse_trade_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Parse Binance trade message."""
        return {
            "price": msg["p"],
            "market": self.market,
        }

    @asynccontextmanager
    async def _connect_websocket(self) -> AsyncIterator[AsyncIterator[dict]]:
        """Connect to Binance WebSocket."""
        url = self._build_ws_url()
        logger.info(f"Connecting to {url}")

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                async def message_iterator():
                    async for msg in ws:
                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if data.get("e") == "trade":
                                yield self._parse_trade_message(data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise ConnectionError(f"WebSocket error: {ws.exception()}")

                yield message_iterator()
