# trading/streams/binance_feed.py
"""Binance-specific price feed implementation."""
# pylint: disable=broad-exception-caught
from __future__ import annotations
import asyncio
import json
import logging
import os
import time
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
BINANCE_SPOT_REST = "https://api.binance.com/api/v3/ticker/price"
BINANCE_FUTURES_REST = "https://fapi.binance.com/fapi/v1/ticker/price"


class BinanceFeedTask(SymbolFeedTask):
    """Feed task for Binance spot or futures."""

    def __init__(
        self,
        symbol: str,
        redis: RedisStreams,
        market: str = "futures",
        stream_type: str | None = None,
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
        self._stream_type = self._resolve_stream_type(stream_type)
        self._heartbeat_enabled = os.getenv("BINANCE_HEARTBEAT_ENABLED", "1") == "1"
        self._heartbeat_idle_seconds = max(
            5.0,
            float(os.getenv("BINANCE_HEARTBEAT_IDLE_SEC", "20") or 20.0),
        )
        self._heartbeat_rest_poll_seconds = max(
            5.0,
            float(os.getenv("BINANCE_HEARTBEAT_REST_POLL_SEC", "30") or 30.0),
        )

    @staticmethod
    def _resolve_stream_type(stream_type: str | None) -> str:
        raw = (stream_type or os.getenv("BINANCE_STREAM_TYPE", "miniTicker")).strip().lower()
        if raw in {"bookticker", "book_ticker"}:
            return "bookTicker"
        if raw in {"miniticker", "mini_ticker"}:
            return "miniTicker"
        logger.warning("Unknown BINANCE stream type '%s', fallback to miniTicker", raw)
        return "miniTicker"

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

        Supports per-symbol `miniTicker` (trade-driven) and `bookTicker`
        (best bid/ask updates) streams.
        """
        pair = f"{self.symbol.lower()}usdt"
        stream = f"{pair}@{self._stream_type}"

        if self.market == "futures":
            return f"{BINANCE_FUTURES_WS}/{stream}"
        return f"{BINANCE_SPOT_WS}/{stream}"

    def _parse_ticker_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        """Parse Binance ticker payload according to configured stream type."""
        price: str | None = None
        exchange_ts = msg.get("E") or msg.get("T")

        if self._stream_type == "bookTicker":
            bid_raw = msg.get("b")
            ask_raw = msg.get("a")
            try:
                bid = float(bid_raw) if bid_raw is not None else 0.0
                ask = float(ask_raw) if ask_raw is not None else 0.0
                if bid > 0 and ask > 0:
                    price = str((bid + ask) / 2.0)
                elif bid > 0:
                    price = str(bid)
                elif ask > 0:
                    price = str(ask)
            except (TypeError, ValueError):
                price = None

        if price is None:
            # miniTicker close price or fallback for malformed bookTicker payload.
            price = str(msg["c"])

        return {
            "price": price,
            "market": self.market,
            "exchange_ts": exchange_ts,
            "source": "binance",
        }

    def _is_live_ticker_message(self, data: dict[str, Any]) -> bool:
        if self._stream_type == "miniTicker":
            return data.get("e") == "24hrMiniTicker"

        # bookTicker payload often has no explicit `e` in raw stream mode.
        event_type = str(data.get("e", "")).strip()
        if event_type and event_type != "bookTicker":
            return False
        return ("b" in data) or ("a" in data)

    def _rest_ticker_url(self) -> str:
        return BINANCE_FUTURES_REST if self.market == "futures" else BINANCE_SPOT_REST

    def _rest_ticker_symbol(self) -> str:
        return f"{self.symbol.upper()}USDT"

    async def _fetch_rest_heartbeat(self, session: aiohttp.ClientSession) -> dict[str, Any] | None:
        """Fallback heartbeat using REST ticker when WS is idle."""
        try:
            async with session.get(
                self._rest_ticker_url(),
                params={"symbol": self._rest_ticker_symbol()},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as response:
                if response.status != 200:
                    logger.debug(
                        "REST heartbeat %s failed for %s: status=%s",
                        self.market,
                        self.symbol,
                        response.status,
                    )
                    return None
                payload = await response.json()
        except Exception as e:
            logger.debug("REST heartbeat fetch failed for %s: %s", self.symbol, e)
            return None

        price = payload.get("price")
        if price is None:
            return None

        return {
            "price": str(price),
            "market": self.market,
            "exchange_ts": int(time.time() * 1000),
            "source": "binance_rest",
            "heartbeat": "true",
        }

    @asynccontextmanager
    async def _connect_websocket(self) -> AsyncIterator[AsyncIterator[dict]]:
        """Connect to Binance WebSocket."""
        url = self._build_ws_url()
        logger.info("Connecting to %s", url)

        async with aiohttp.ClientSession() as session:
            async with session.ws_connect(url) as ws:
                async def message_iterator():
                    last_live_tick = time.monotonic()
                    last_rest_poll = 0.0

                    while True:
                        try:
                            msg = await ws.receive(timeout=self._heartbeat_idle_seconds)
                        except asyncio.TimeoutError:
                            if not self._heartbeat_enabled:
                                continue
                            now = time.monotonic()
                            should_poll = (
                                (now - last_live_tick) >= self._heartbeat_idle_seconds
                                and (now - last_rest_poll) >= self._heartbeat_rest_poll_seconds
                            )
                            if not should_poll:
                                continue
                            heartbeat_msg = await self._fetch_rest_heartbeat(session)
                            last_rest_poll = now
                            if heartbeat_msg is not None:
                                yield heartbeat_msg
                            continue

                        if msg.type == aiohttp.WSMsgType.TEXT:
                            data = json.loads(msg.data)
                            if self._is_live_ticker_message(data):
                                last_live_tick = time.monotonic()
                                yield self._parse_ticker_message(data)
                        elif msg.type == aiohttp.WSMsgType.ERROR:
                            raise ConnectionError(f"WebSocket error: {ws.exception()}")
                        elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.CLOSING):
                            break

                yield message_iterator()
