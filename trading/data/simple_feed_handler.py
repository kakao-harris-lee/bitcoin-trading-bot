"""
SimpleFeedHandler - WebSocket price feed without Redis dependency.

Simplified version of FeedHandler that:
- Connects to Upbit and Binance WebSockets
- Maintains last price cache
- Supports direct callbacks (no Redis)
"""

import asyncio
import json
import logging
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime
from dataclasses import dataclass

import aiohttp

logger = logging.getLogger(__name__)


@dataclass
class OHLCV:
    """OHLCV candle data."""
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass
class PriceMessage:
    """Price message from WebSocket."""
    timestamp: int
    exchange: str
    symbol: str
    price: float
    volume_24h: float
    ohlcv: Optional[OHLCV] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "timestamp": self.timestamp,
            "exchange": self.exchange,
            "symbol": self.symbol,
            "price": self.price,
            "volume_24h": self.volume_24h,
            "ohlcv": {
                "open": self.ohlcv.open,
                "high": self.ohlcv.high,
                "low": self.ohlcv.low,
                "close": self.ohlcv.close,
                "volume": self.ohlcv.volume,
            } if self.ohlcv else None,
        }


class WebSocketClient:
    """Base WebSocket client."""

    def __init__(self, name: str, url: str):
        self.name = name
        self.url = url
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._last_message_time: Optional[datetime] = None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    async def connect(self) -> bool:
        """Connect to WebSocket."""
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            logger.info(f"Connecting to {self.name} WebSocket...")
            self._ws = await self._session.ws_connect(
                self.url,
                heartbeat=30,
                receive_timeout=60,
            )
            self._connected = True
            self._reconnect_attempts = 0
            logger.info(f"Connected to {self.name} WebSocket")

            await self._subscribe()
            return True

        except Exception as e:
            logger.error(f"Failed to connect to {self.name}: {e}")
            self._connected = False
            return False

    async def disconnect(self) -> None:
        """Disconnect from WebSocket."""
        self._connected = False
        # Set to None first, then close (ensures reconnect works even if close fails)
        ws, self._ws = self._ws, None
        session, self._session = self._session, None
        if ws:
            try:
                await ws.close()
            except Exception as e:
                logger.debug(f"Error closing WebSocket for {self.name}: {e}")
        if session:
            try:
                await session.close()
            except Exception as e:
                logger.debug(f"Error closing session for {self.name}: {e}")
        logger.info(f"Disconnected from {self.name}")

    async def reconnect(self) -> bool:
        """Reconnect with backoff."""
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._max_reconnect_attempts:
            logger.error(f"Max reconnect attempts reached for {self.name}")
            return False

        delay = min(5 * self._reconnect_attempts, 60)
        logger.warning(f"Reconnecting to {self.name} in {delay}s...")
        await asyncio.sleep(delay)

        await self.disconnect()
        return await self.connect()

    async def _subscribe(self) -> None:
        """Subscribe to streams (override in subclass)."""
        pass

    async def receive(self) -> Optional[PriceMessage]:
        """Receive and parse message (override in subclass)."""
        pass


class UpbitWebSocketClient(WebSocketClient):
    """Upbit WebSocket client."""

    def __init__(self, symbols: List[str] = None):
        symbols = symbols or ["KRW-BTC"]
        super().__init__("upbit", "wss://api.upbit.com/websocket/v1")
        self.symbols = symbols

    async def _subscribe(self) -> None:
        """Subscribe to Upbit ticker."""
        subscribe_msg = [
            {"ticket": f"async-engine-{int(datetime.now().timestamp())}"},
            {"type": "ticker", "codes": self.symbols, "isOnlyRealtime": True},
            {"format": "SIMPLE"},
        ]
        await self._ws.send_json(subscribe_msg)
        logger.info(f"Subscribed to Upbit: {self.symbols}")

    async def receive(self) -> Optional[PriceMessage]:
        """Receive and parse Upbit message."""
        if not self._ws or not self._connected:
            return None

        try:
            msg = await asyncio.wait_for(self._ws.receive(), timeout=30)

            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                return self._parse(data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                data = json.loads(msg.data.decode("utf-8"))
                return self._parse(data)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                logger.warning(f"Upbit WebSocket closed: {msg.type}")
                self._connected = False

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"Upbit receive error: {e}")

        return None

    def _parse(self, data: Dict) -> Optional[PriceMessage]:
        """Parse Upbit message."""
        if "cd" not in data:
            return None

        try:
            ohlcv = OHLCV(
                open=float(data.get("op", data.get("tp", 0))),
                high=float(data.get("hp", data.get("tp", 0))),
                low=float(data.get("lp", data.get("tp", 0))),
                close=float(data.get("tp", 0)),
                volume=float(data.get("tv", 0)),
            )

            return PriceMessage(
                timestamp=data.get("tms", int(datetime.now().timestamp() * 1000)),
                exchange="upbit",
                symbol=data.get("cd", ""),
                price=float(data.get("tp", 0)),
                volume_24h=float(data.get("atv", 0)),
                ohlcv=ohlcv,
            )
        except Exception as e:
            logger.error(f"Upbit parse error: {e}")
            return None


class BinanceWebSocketClient(WebSocketClient):
    """Binance Futures WebSocket client."""

    def __init__(self, symbols: List[str] = None):
        symbols = symbols or ["btcusdt"]
        streams = [f"{s.lower()}@ticker" for s in symbols]
        url = f"wss://fstream.binance.com/ws/{'/'.join(streams)}"
        super().__init__("binance", url)
        self.symbols = symbols

    async def _subscribe(self) -> None:
        """Binance subscribes via URL, no additional message needed."""
        logger.info(f"Subscribed to Binance: {self.symbols}")

    async def receive(self) -> Optional[PriceMessage]:
        """Receive and parse Binance message."""
        if not self._ws or not self._connected:
            return None

        try:
            msg = await asyncio.wait_for(self._ws.receive(), timeout=30)

            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                return self._parse(data)
            elif msg.type == aiohttp.WSMsgType.BINARY:
                data = json.loads(msg.data.decode("utf-8"))
                return self._parse(data)
            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                logger.warning(f"Binance WebSocket closed: {msg.type}")
                self._connected = False

        except asyncio.TimeoutError:
            pass
        except Exception as e:
            logger.error(f"Binance receive error: {e}")

        return None

    def _parse(self, data: Dict) -> Optional[PriceMessage]:
        """Parse Binance message."""
        # Handle combined stream format
        if "s" not in data and "data" in data:
            data = data["data"]

        if "s" not in data:
            return None

        try:
            close_price = float(data.get("c", 0))
            ohlcv = OHLCV(
                open=float(data.get("o", close_price)),
                high=float(data.get("h", close_price)),
                low=float(data.get("l", close_price)),
                close=close_price,
                volume=float(data.get("v", 0)),
            )

            return PriceMessage(
                timestamp=data.get("E", int(datetime.now().timestamp() * 1000)),
                exchange="binance",
                symbol=data.get("s", ""),
                price=close_price,
                volume_24h=float(data.get("q", 0)),
                ohlcv=ohlcv,
            )
        except Exception as e:
            logger.error(f"Binance parse error: {e}")
            return None


class SimpleFeedHandler:
    """
    Simple feed handler without Redis dependency.

    Connects to Upbit and Binance WebSockets,
    maintains price cache, and supports callbacks.
    """

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        on_price: Optional[Callable[["PriceMessage"], None]] = None,
    ) -> "SimpleFeedHandler":
        """
        Create SimpleFeedHandler from allocation config.

        Args:
            config: Allocation config with "assets" section
            on_price: Callback for price updates

        Returns:
            Configured SimpleFeedHandler
        """
        assets = config.get("assets", {})
        upbit_symbols = []
        binance_symbols = []

        for symbol, asset_config in assets.items():
            if asset_config.get("enabled", False):
                upbit_symbols.append(asset_config.get("upbit_symbol", f"KRW-{symbol}"))
                binance_symbols.append(asset_config.get("binance_symbol", f"{symbol}USDT"))

        return cls(
            upbit_symbols=upbit_symbols,
            binance_symbols=binance_symbols,
            on_price=on_price,
        )

    def __init__(
        self,
        upbit_symbols: List[str] = None,
        binance_symbols: List[str] = None,
        on_price: Optional[Callable[["PriceMessage"], None]] = None,
    ):
        """
        Args:
            upbit_symbols: Upbit symbols to subscribe
            binance_symbols: Binance symbols to subscribe
            on_price: Callback for new prices
        """
        self._upbit_symbols = upbit_symbols or ["KRW-BTC"]
        self._binance_symbols = binance_symbols or ["btcusdt"]
        self._upbit_ws = UpbitWebSocketClient(self._upbit_symbols)
        self._binance_ws = BinanceWebSocketClient(self._binance_symbols)
        self._on_price = on_price
        self._last_prices: Dict[str, PriceMessage] = {}
        self._started = False
        self._tasks: List[asyncio.Task] = []

        # Symbol mapping (exchange symbol -> canonical symbol)
        self._symbol_map: Dict[str, str] = {}
        self._build_symbol_map()

        # Statistics
        self._upbit_count = 0
        self._binance_count = 0

    def _build_symbol_map(self) -> None:
        """Build mapping from exchange symbols to canonical symbols."""
        # Upbit: KRW-BTC -> BTC
        for sym in self._upbit_symbols:
            canonical = sym.replace("KRW-", "")
            self._symbol_map[sym] = canonical
            self._symbol_map[sym.upper()] = canonical

        # Binance: btcusdt/BTCUSDT -> BTC
        for sym in self._binance_symbols:
            canonical = sym.upper().replace("USDT", "")
            self._symbol_map[sym] = canonical
            self._symbol_map[sym.upper()] = canonical
            self._symbol_map[sym.lower()] = canonical

    def get_canonical_symbol(self, exchange_symbol: str) -> Optional[str]:
        """Get canonical symbol from exchange symbol."""
        return self._symbol_map.get(exchange_symbol) or self._symbol_map.get(exchange_symbol.upper())

    async def start(self) -> None:
        """Start feed handler."""
        if self._started:
            return

        # Connect WebSockets
        await self._upbit_ws.connect()
        await self._binance_ws.connect()

        # Start receive loops
        self._tasks = [
            asyncio.create_task(self._receive_loop(self._upbit_ws, "upbit")),
            asyncio.create_task(self._receive_loop(self._binance_ws, "binance")),
        ]

        self._started = True
        logger.info("SimpleFeedHandler started")

    async def stop(self) -> None:
        """Stop feed handler."""
        for task in self._tasks:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

        await self._upbit_ws.disconnect()
        await self._binance_ws.disconnect()

        self._started = False
        logger.info("SimpleFeedHandler stopped")

    async def _receive_loop(self, ws: WebSocketClient, exchange: str) -> None:
        """Receive loop for a WebSocket."""
        while True:
            try:
                if not ws.is_connected:
                    if not await ws.reconnect():
                        await asyncio.sleep(60)
                        continue

                msg = await ws.receive()
                if msg:
                    # Update cache
                    key = f"{exchange}:{msg.symbol}"
                    self._last_prices[key] = msg

                    # Update stats
                    if exchange == "upbit":
                        self._upbit_count += 1
                    else:
                        self._binance_count += 1

                    # Callback
                    if self._on_price:
                        try:
                            self._on_price(msg)
                        except Exception as e:
                            logger.error(f"Price callback error: {e}")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"{exchange} receive loop error: {e}")
                await asyncio.sleep(1)

    def get_last_price(self, exchange: str, symbol: str) -> Optional[PriceMessage]:
        """Get last price for exchange and symbol."""
        # Try exact match first, then uppercase (Binance returns uppercase)
        key = f"{exchange}:{symbol}"
        result = self._last_prices.get(key)
        if result is None:
            key_upper = f"{exchange}:{symbol.upper()}"
            result = self._last_prices.get(key_upper)
        return result

    def get_stats(self) -> Dict[str, Any]:
        """Get feed handler statistics."""
        return {
            "started": self._started,
            "upbit": {
                "connected": self._upbit_ws.is_connected,
                "message_count": self._upbit_count,
            },
            "binance": {
                "connected": self._binance_ws.is_connected,
                "message_count": self._binance_count,
            },
            "last_prices": {
                key: {"price": msg.price, "timestamp": msg.timestamp}
                for key, msg in self._last_prices.items()
            },
        }


async def main():
    """Test SimpleFeedHandler."""
    logging.basicConfig(level=logging.INFO)

    def on_price(msg: PriceMessage):
        print(f"{msg.exchange}: {msg.price:,.0f}")

    handler = SimpleFeedHandler(on_price=on_price)

    try:
        await handler.start()
        print("Feed handler running... (Ctrl+C to stop)")

        for _ in range(60):  # Run for 60 seconds
            await asyncio.sleep(1)
            print(f"Stats: {handler.get_stats()}")

    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        await handler.stop()


if __name__ == "__main__":
    asyncio.run(main())
