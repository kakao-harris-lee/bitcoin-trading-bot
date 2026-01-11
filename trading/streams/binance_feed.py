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
        **kwargs,
    ):
        super().__init__(symbol=symbol, redis=redis, **kwargs)
        self.market = market

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
