"""
Trading Engine V2 - Feed Handler
실시간 가격 데이터 수집 및 Redis 발행
"""

import asyncio
import json
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, Callable, List
from datetime import datetime, timedelta
import aiohttp

from ..core.base_module import BaseModule
from ..core.config import Config
from ..core.message_types import (
    PriceMessage, OHLCV, Exchange, EventType, current_timestamp
)

logger = logging.getLogger(__name__)


class WebSocketHandler(ABC):
    """WebSocket 핸들러 추상 클래스"""

    def __init__(self, exchange: Exchange, symbols: List[str]):
        """
        Args:
            exchange: 거래소
            symbols: 구독할 심볼 리스트
        """
        self.exchange = exchange
        self.symbols = symbols
        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._connected = False
        self._reconnect_attempts = 0
        self._max_reconnect_attempts = 10
        self._reconnect_delay = 5  # 초
        self._last_message_time: Optional[datetime] = None
        self._message_callback: Optional[Callable] = None
        self.logger = logging.getLogger(f"ws.{exchange.value}")

    @property
    @abstractmethod
    def ws_url(self) -> str:
        """WebSocket URL"""
        pass

    @abstractmethod
    async def _subscribe(self):
        """심볼 구독"""
        pass

    @abstractmethod
    def _parse_message(self, data: Any) -> Optional[PriceMessage]:
        """메시지 파싱"""
        pass

    def set_callback(self, callback: Callable[[PriceMessage], None]):
        """가격 메시지 콜백 설정"""
        self._message_callback = callback

    async def connect(self) -> bool:
        """WebSocket 연결"""
        try:
            if self._session is None:
                self._session = aiohttp.ClientSession()

            self.logger.info(f"🔌 {self.exchange.value} WebSocket 연결 중...")
            self._ws = await self._session.ws_connect(
                self.ws_url,
                heartbeat=30,
                receive_timeout=60,
            )
            self._connected = True
            self._reconnect_attempts = 0
            self.logger.info(f"✅ {self.exchange.value} WebSocket 연결 성공")

            # 구독 요청
            await self._subscribe()
            return True

        except Exception as e:
            self.logger.error(f"❌ {self.exchange.value} WebSocket 연결 실패: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        """연결 종료"""
        self._connected = False
        if self._ws:
            await self._ws.close()
            self._ws = None
        if self._session:
            await self._session.close()
            self._session = None
        self.logger.info(f"⬛ {self.exchange.value} WebSocket 종료")

    async def reconnect(self) -> bool:
        """재연결"""
        self._reconnect_attempts += 1
        if self._reconnect_attempts > self._max_reconnect_attempts:
            self.logger.error(f"❌ 최대 재연결 시도 횟수 초과")
            return False

        delay = self._reconnect_delay * self._reconnect_attempts
        self.logger.warning(
            f"🔄 {delay}초 후 재연결 시도... ({self._reconnect_attempts}/{self._max_reconnect_attempts})"
        )
        await asyncio.sleep(delay)

        await self.disconnect()
        return await self.connect()

    async def receive(self) -> Optional[PriceMessage]:
        """메시지 수신"""
        if not self._ws or not self._connected:
            return None

        try:
            msg = await self._ws.receive(timeout=30)

            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                self._last_message_time = datetime.now()
                return self._parse_message(data)

            elif msg.type == aiohttp.WSMsgType.BINARY:
                # Binance는 바이너리 메시지 사용
                data = json.loads(msg.data.decode('utf-8'))
                self._last_message_time = datetime.now()
                return self._parse_message(data)

            elif msg.type in (aiohttp.WSMsgType.CLOSED, aiohttp.WSMsgType.ERROR):
                self.logger.warning(f"WebSocket 연결 끊김: {msg.type}")
                self._connected = False
                return None

        except asyncio.TimeoutError:
            # Heartbeat 체크
            if self._last_message_time:
                elapsed = datetime.now() - self._last_message_time
                if elapsed > timedelta(seconds=60):
                    self.logger.warning("60초간 메시지 없음, 재연결 시도")
                    self._connected = False
            return None

        except Exception as e:
            self.logger.error(f"메시지 수신 오류: {e}")
            return None

    @property
    def is_connected(self) -> bool:
        return self._connected and self._ws is not None

    def get_stats(self) -> Dict[str, Any]:
        """상태 통계"""
        return {
            "exchange": self.exchange.value,
            "connected": self._connected,
            "symbols": self.symbols,
            "reconnect_attempts": self._reconnect_attempts,
            "last_message": self._last_message_time.isoformat() if self._last_message_time else None,
        }


class UpbitWebSocket(WebSocketHandler):
    """Upbit WebSocket 핸들러"""

    WS_URL = "wss://api.upbit.com/websocket/v1"

    def __init__(self, symbols: List[str] = None):
        symbols = symbols or ["KRW-BTC"]
        super().__init__(Exchange.UPBIT, symbols)

    @property
    def ws_url(self) -> str:
        return self.WS_URL

    async def _subscribe(self):
        """Upbit ticker 구독"""
        subscribe_msg = [
            {"ticket": f"trading-engine-{current_timestamp()}"},
            {
                "type": "ticker",
                "codes": self.symbols,
                "isOnlyRealtime": True
            },
            {"format": "SIMPLE"}
        ]
        await self._ws.send_json(subscribe_msg)
        self.logger.info(f"📡 구독 요청: {self.symbols}")

    def _parse_message(self, data: Dict) -> Optional[PriceMessage]:
        """Upbit 메시지 파싱"""
        try:
            # SIMPLE 포맷 필드명
            # cd: code, tp: trade_price, tv: trade_volume
            # op: opening_price, hp: high_price, lp: low_price
            # atv: acc_trade_volume

            if "cd" not in data:
                return None

            ohlcv = OHLCV(
                open=float(data.get("op", data.get("tp", 0))),
                high=float(data.get("hp", data.get("tp", 0))),
                low=float(data.get("lp", data.get("tp", 0))),
                close=float(data.get("tp", 0)),
                volume=float(data.get("tv", 0)),
            )

            return PriceMessage(
                timestamp=data.get("tms", current_timestamp()),
                exchange=Exchange.UPBIT,
                symbol=data.get("cd", ""),
                price=float(data.get("tp", 0)),
                volume_24h=float(data.get("atv", 0)),
                ohlcv=ohlcv,
            )

        except Exception as e:
            self.logger.error(f"Upbit 파싱 오류: {e}, data={data}")
            return None


class BinanceWebSocket(WebSocketHandler):
    """Binance WebSocket 핸들러"""

    WS_URL = "wss://fstream.binance.com/ws"

    def __init__(self, symbols: List[str] = None):
        symbols = symbols or ["btcusdt"]
        super().__init__(Exchange.BINANCE, symbols)

    @property
    def ws_url(self) -> str:
        # 멀티 스트림 URL
        streams = [f"{s.lower()}@ticker" for s in self.symbols]
        return f"{self.WS_URL}/{'/'.join(streams)}"

    async def _subscribe(self):
        """Binance는 URL로 구독하므로 별도 요청 불필요"""
        self.logger.info(f"📡 구독 중: {self.symbols}")

    def _parse_message(self, data: Dict) -> Optional[PriceMessage]:
        """Binance 메시지 파싱"""
        try:
            # 24hr ticker 스트림 필드
            # s: symbol, c: close, o: open, h: high, l: low, v: volume
            # q: quote_volume, E: event_time

            if "s" not in data and "data" in data:
                # Combined stream
                data = data["data"]

            if "s" not in data:
                return None

            symbol = data.get("s", "")
            close_price = float(data.get("c", 0))

            ohlcv = OHLCV(
                open=float(data.get("o", close_price)),
                high=float(data.get("h", close_price)),
                low=float(data.get("l", close_price)),
                close=close_price,
                volume=float(data.get("v", 0)),
            )

            return PriceMessage(
                timestamp=data.get("E", current_timestamp()),
                exchange=Exchange.BINANCE,
                symbol=symbol,
                price=close_price,
                volume_24h=float(data.get("q", 0)),
                ohlcv=ohlcv,
            )

        except Exception as e:
            self.logger.error(f"Binance 파싱 오류: {e}, data={data}")
            return None


class FeedHandler(BaseModule):
    """
    Feed Handler - 실시간 데이터 수집기

    Upbit, Binance WebSocket에서 가격 데이터를 수집하여
    Redis Stream(market:prices)에 발행
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        upbit_symbols: List[str] = None,
        binance_symbols: List[str] = None,
    ):
        """
        Args:
            config: 설정
            upbit_symbols: Upbit 구독 심볼 (기본: ["KRW-BTC"])
            binance_symbols: Binance 구독 심볼 (기본: ["btcusdt"])
        """
        super().__init__("feed-handler", config)

        # WebSocket 핸들러
        self._upbit_ws: Optional[UpbitWebSocket] = None
        self._binance_ws: Optional[BinanceWebSocket] = None

        self._upbit_symbols = upbit_symbols or ["KRW-BTC"]
        self._binance_symbols = binance_symbols or ["btcusdt"]

        # 통계
        self._upbit_message_count = 0
        self._binance_message_count = 0
        self._last_prices: Dict[str, PriceMessage] = {}

    async def on_start(self):
        """모듈 시작 - WebSocket 연결"""
        # Upbit 연결
        if self.config.trading.upbit_enabled:
            self._upbit_ws = UpbitWebSocket(self._upbit_symbols)
            if not await self._upbit_ws.connect():
                self.logger.error("Upbit WebSocket 연결 실패")

        # Binance 연결
        if self.config.trading.binance_enabled:
            self._binance_ws = BinanceWebSocket(self._binance_symbols)
            if not await self._binance_ws.connect():
                self.logger.error("Binance WebSocket 연결 실패")

    async def on_stop(self):
        """모듈 정지 - WebSocket 종료"""
        if self._upbit_ws:
            await self._upbit_ws.disconnect()
        if self._binance_ws:
            await self._binance_ws.disconnect()

    async def run_cycle(self):
        """
        메인 사이클 - 각 WebSocket에서 데이터 수집 후 발행
        """
        tasks = []

        # Upbit 수신 태스크
        if self._upbit_ws and self._upbit_ws.is_connected:
            tasks.append(self._receive_and_publish(self._upbit_ws))
        elif self._upbit_ws and not self._upbit_ws.is_connected:
            # 재연결 시도
            tasks.append(self._reconnect(self._upbit_ws))

        # Binance 수신 태스크
        if self._binance_ws and self._binance_ws.is_connected:
            tasks.append(self._receive_and_publish(self._binance_ws))
        elif self._binance_ws and not self._binance_ws.is_connected:
            tasks.append(self._reconnect(self._binance_ws))

        # 동시 실행
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        # 짧은 대기 (CPU 과사용 방지)
        await asyncio.sleep(self.config.trading.feed_interval)

    async def _receive_and_publish(self, ws: WebSocketHandler):
        """WebSocket에서 수신 후 Redis 발행"""
        try:
            price_msg = await ws.receive()
            if price_msg:
                # Redis 발행
                await self.publish(
                    self.config.redis.streams["prices"],
                    price_msg.to_dict()
                )

                # 통계 업데이트
                if ws.exchange == Exchange.UPBIT:
                    self._upbit_message_count += 1
                else:
                    self._binance_message_count += 1

                # 최신 가격 캐시
                key = f"{ws.exchange.value}:{price_msg.symbol}"
                self._last_prices[key] = price_msg

                self.logger.debug(
                    f"📊 {ws.exchange.value} {price_msg.symbol}: {price_msg.price:,.0f}"
                )

        except Exception as e:
            self.logger.error(f"{ws.exchange.value} 수신/발행 오류: {e}")

    async def _reconnect(self, ws: WebSocketHandler):
        """WebSocket 재연결"""
        success = await ws.reconnect()
        if not success:
            # 재연결 실패 시 에러 이벤트 발행
            await self._publish_event(
                EventType.ERROR,
                f"{ws.exchange.value} WebSocket 재연결 실패",
                {"exchange": ws.exchange.value}
            )

    def get_last_price(self, exchange: str, symbol: str) -> Optional[PriceMessage]:
        """최신 가격 조회"""
        key = f"{exchange}:{symbol}"
        return self._last_prices.get(key)

    def get_stats(self) -> Dict[str, Any]:
        """통계"""
        base_stats = super().get_stats()
        base_stats.update({
            "upbit": {
                "enabled": self.config.trading.upbit_enabled,
                "connected": self._upbit_ws.is_connected if self._upbit_ws else False,
                "message_count": self._upbit_message_count,
                "symbols": self._upbit_symbols,
            },
            "binance": {
                "enabled": self.config.trading.binance_enabled,
                "connected": self._binance_ws.is_connected if self._binance_ws else False,
                "message_count": self._binance_message_count,
                "symbols": self._binance_symbols,
            },
            "last_prices": {
                key: {
                    "price": msg.price,
                    "timestamp": msg.timestamp
                }
                for key, msg in self._last_prices.items()
            },
        })
        return base_stats


async def main():
    """테스트 실행"""
    import sys
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)]
    )

    config = Config.from_env()
    handler = FeedHandler(config)

    try:
        await handler.start()
        print("\n📡 Feed Handler 실행 중... (Ctrl+C로 종료)\n")

        # 30초 동안 실행
        for _ in range(30):
            await handler.run_cycle()
            stats = handler.get_stats()
            print(f"\r📊 Upbit: {stats['upbit']['message_count']} | "
                  f"Binance: {stats['binance']['message_count']}", end="", flush=True)

    except KeyboardInterrupt:
        print("\n\n중단됨")
    finally:
        await handler.stop()
        print("\n최종 통계:")
        print(json.dumps(handler.get_stats(), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())
