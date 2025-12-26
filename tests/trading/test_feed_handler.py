"""
Feed Handler 단위 테스트

테스트 커버리지:
- UpbitWebSocket 메시지 파싱
- BinanceWebSocket 메시지 파싱
- FeedHandler 초기화 및 상태 관리
- WebSocket 연결/재연결 로직
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
from datetime import datetime
import json

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trading.modules.feed_handler import (
    FeedHandler,
    UpbitWebSocket,
    BinanceWebSocket,
    WebSocketHandler,
)
from trading.core.message_types import (
    PriceMessage, OHLCV, Exchange
)
from trading.core.config import Config, TradingConfig


# ========== Fixtures ==========

@pytest.fixture
def config():
    """테스트용 Config"""
    cfg = Config()
    cfg.trading = TradingConfig(
        upbit_enabled=True,
        binance_enabled=True,
        feed_interval=0.1,  # 빠른 테스트
    )
    return cfg


@pytest.fixture
def upbit_ws():
    """Upbit WebSocket 인스턴스"""
    return UpbitWebSocket(symbols=["KRW-BTC"])


@pytest.fixture
def binance_ws():
    """Binance WebSocket 인스턴스"""
    return BinanceWebSocket(symbols=["btcusdt"])


@pytest.fixture
def feed_handler(config):
    """FeedHandler 인스턴스"""
    return FeedHandler(
        config=config,
        upbit_symbols=["KRW-BTC"],
        binance_symbols=["btcusdt"],
    )


# ========== Upbit WebSocket Tests ==========

class TestUpbitWebSocket:
    """Upbit WebSocket 테스트"""

    def test_init(self, upbit_ws):
        """초기화 테스트"""
        assert upbit_ws.exchange == Exchange.UPBIT
        assert upbit_ws.symbols == ["KRW-BTC"]
        assert upbit_ws.is_connected is False
        assert upbit_ws.ws_url == "wss://api.upbit.com/websocket/v1"

    def test_parse_message_valid(self, upbit_ws):
        """유효한 메시지 파싱"""
        # Upbit SIMPLE 포맷 메시지
        data = {
            "ty": "ticker",
            "cd": "KRW-BTC",
            "tp": 134500000,        # trade_price
            "op": 134000000,        # opening_price
            "hp": 135000000,        # high_price
            "lp": 133500000,        # low_price
            "tv": 0.5,              # trade_volume
            "atv": 1234.56,         # acc_trade_volume
            "tms": 1702345678901,   # timestamp
        }

        result = upbit_ws._parse_message(data)

        assert result is not None
        assert isinstance(result, PriceMessage)
        assert result.exchange == Exchange.UPBIT
        assert result.symbol == "KRW-BTC"
        assert result.price == 134500000
        assert result.volume_24h == 1234.56
        assert result.ohlcv.open == 134000000
        assert result.ohlcv.high == 135000000
        assert result.ohlcv.low == 133500000
        assert result.ohlcv.close == 134500000
        assert result.ohlcv.volume == 0.5

    def test_parse_message_minimal(self, upbit_ws):
        """최소 필드만 있는 메시지"""
        data = {
            "cd": "KRW-BTC",
            "tp": 134500000,
        }

        result = upbit_ws._parse_message(data)

        assert result is not None
        assert result.price == 134500000
        assert result.symbol == "KRW-BTC"

    def test_parse_message_invalid(self, upbit_ws):
        """유효하지 않은 메시지"""
        # cd (code) 필드 없음
        data = {"tp": 134500000}

        result = upbit_ws._parse_message(data)

        assert result is None

    def test_parse_message_empty(self, upbit_ws):
        """빈 메시지"""
        result = upbit_ws._parse_message({})
        assert result is None

    def test_get_stats(self, upbit_ws):
        """통계 조회"""
        stats = upbit_ws.get_stats()

        assert stats["exchange"] == "upbit"
        assert stats["connected"] is False
        assert stats["symbols"] == ["KRW-BTC"]
        assert stats["reconnect_attempts"] == 0


# ========== Binance WebSocket Tests ==========

class TestBinanceWebSocket:
    """Binance WebSocket 테스트"""

    def test_init(self, binance_ws):
        """초기화 테스트"""
        assert binance_ws.exchange == Exchange.BINANCE
        assert binance_ws.symbols == ["btcusdt"]
        assert binance_ws.is_connected is False

    def test_ws_url_single_symbol(self, binance_ws):
        """단일 심볼 URL"""
        assert "btcusdt@ticker" in binance_ws.ws_url

    def test_ws_url_multiple_symbols(self):
        """다중 심볼 URL"""
        ws = BinanceWebSocket(symbols=["btcusdt", "ethusdt"])
        assert "btcusdt@ticker" in ws.ws_url
        assert "ethusdt@ticker" in ws.ws_url

    def test_parse_message_valid(self, binance_ws):
        """유효한 메시지 파싱"""
        # Binance 24hr ticker 메시지
        data = {
            "e": "24hrTicker",
            "E": 1702345678901,     # event_time
            "s": "BTCUSDT",         # symbol
            "c": "43500.50",        # close
            "o": "43000.00",        # open
            "h": "44000.00",        # high
            "l": "42500.00",        # low
            "v": "12345.67",        # volume
            "q": "536789012.34",    # quote_volume
        }

        result = binance_ws._parse_message(data)

        assert result is not None
        assert isinstance(result, PriceMessage)
        assert result.exchange == Exchange.BINANCE
        assert result.symbol == "BTCUSDT"
        assert result.price == 43500.50
        assert result.ohlcv.open == 43000.00
        assert result.ohlcv.high == 44000.00
        assert result.ohlcv.low == 42500.00
        assert result.ohlcv.close == 43500.50
        assert result.ohlcv.volume == 12345.67

    def test_parse_message_combined_stream(self, binance_ws):
        """Combined stream 포맷"""
        data = {
            "stream": "btcusdt@ticker",
            "data": {
                "e": "24hrTicker",
                "E": 1702345678901,
                "s": "BTCUSDT",
                "c": "43500.50",
                "o": "43000.00",
                "h": "44000.00",
                "l": "42500.00",
                "v": "12345.67",
                "q": "536789012.34",
            }
        }

        result = binance_ws._parse_message(data)

        assert result is not None
        assert result.symbol == "BTCUSDT"
        assert result.price == 43500.50

    def test_parse_message_invalid(self, binance_ws):
        """유효하지 않은 메시지"""
        data = {"v": "12345"}
        result = binance_ws._parse_message(data)
        assert result is None


# ========== FeedHandler Tests ==========

class TestFeedHandler:
    """FeedHandler 테스트"""

    def test_init(self, feed_handler, config):
        """초기화 테스트"""
        assert feed_handler.module_name == "feed-handler"
        assert feed_handler._upbit_symbols == ["KRW-BTC"]
        assert feed_handler._binance_symbols == ["btcusdt"]
        assert feed_handler._running is False

    def test_get_stats_initial(self, feed_handler):
        """초기 통계"""
        stats = feed_handler.get_stats()

        assert stats["module"] == "feed-handler"
        assert stats["running"] is False
        assert stats["message_count"] == 0
        assert stats["upbit"]["message_count"] == 0
        assert stats["binance"]["message_count"] == 0

    def test_get_last_price_empty(self, feed_handler):
        """가격 조회 - 데이터 없음"""
        result = feed_handler.get_last_price("upbit", "KRW-BTC")
        assert result is None

    @pytest.mark.asyncio
    async def test_on_start_creates_websockets(self, feed_handler):
        """시작 시 WebSocket 생성"""
        with patch.object(UpbitWebSocket, 'connect', new_callable=AsyncMock) as upbit_mock, \
             patch.object(BinanceWebSocket, 'connect', new_callable=AsyncMock) as binance_mock:

            upbit_mock.return_value = True
            binance_mock.return_value = True

            await feed_handler.on_start()

            assert feed_handler._upbit_ws is not None
            assert feed_handler._binance_ws is not None
            upbit_mock.assert_called_once()
            binance_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_stop_disconnects_websockets(self, feed_handler):
        """정지 시 WebSocket 종료"""
        # Mock WebSocket 설정
        feed_handler._upbit_ws = Mock()
        feed_handler._upbit_ws.disconnect = AsyncMock()
        feed_handler._binance_ws = Mock()
        feed_handler._binance_ws.disconnect = AsyncMock()

        await feed_handler.on_stop()

        feed_handler._upbit_ws.disconnect.assert_called_once()
        feed_handler._binance_ws.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_and_publish(self, feed_handler):
        """메시지 수신 및 발행"""
        # Mock 설정
        mock_price = PriceMessage(
            timestamp=1702345678901,
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            price=134500000,
            volume_24h=1234.56,
        )

        mock_ws = Mock(spec=UpbitWebSocket)
        mock_ws.exchange = Exchange.UPBIT
        mock_ws.receive = AsyncMock(return_value=mock_price)
        mock_ws.is_connected = True

        feed_handler.publish = AsyncMock(return_value="test-id")

        await feed_handler._receive_and_publish(mock_ws)

        # 발행 확인
        feed_handler.publish.assert_called_once()
        assert feed_handler._upbit_message_count == 1

        # 가격 캐시 확인
        cached = feed_handler.get_last_price("upbit", "KRW-BTC")
        assert cached is not None
        assert cached.price == 134500000


# ========== WebSocket Connection Tests ==========

class TestWebSocketConnection:
    """WebSocket 연결 테스트"""

    @pytest.mark.asyncio
    async def test_reconnect_increments_attempts(self, upbit_ws):
        """재연결 시도 횟수 증가"""
        upbit_ws._reconnect_delay = 0.01  # 빠른 테스트

        with patch.object(upbit_ws, 'disconnect', new_callable=AsyncMock), \
             patch.object(upbit_ws, 'connect', new_callable=AsyncMock) as mock_connect:

            mock_connect.return_value = False

            await upbit_ws.reconnect()

            assert upbit_ws._reconnect_attempts == 1

    @pytest.mark.asyncio
    async def test_reconnect_max_attempts(self, upbit_ws):
        """최대 재연결 시도 횟수"""
        upbit_ws._reconnect_delay = 0.01
        upbit_ws._reconnect_attempts = 10
        upbit_ws._max_reconnect_attempts = 10

        result = await upbit_ws.reconnect()

        assert result is False


# ========== PriceMessage Tests ==========

class TestPriceMessage:
    """PriceMessage 테스트"""

    def test_to_dict(self):
        """딕셔너리 변환"""
        msg = PriceMessage(
            timestamp=1702345678901,
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            price=134500000,
            volume_24h=1234.56,
            ohlcv=OHLCV(
                open=134000000,
                high=135000000,
                low=133500000,
                close=134500000,
                volume=100.5,
            ),
        )

        result = msg.to_dict()

        assert result["timestamp"] == 1702345678901
        assert result["exchange"] == "upbit"
        assert result["symbol"] == "KRW-BTC"
        assert result["price"] == 134500000
        assert result["ohlcv"]["close"] == 134500000

    def test_from_dict(self):
        """딕셔너리에서 생성"""
        data = {
            "timestamp": 1702345678901,
            "exchange": "upbit",
            "symbol": "KRW-BTC",
            "price": 134500000,
            "volume_24h": 1234.56,
        }

        msg = PriceMessage.from_dict(data)

        assert msg.timestamp == 1702345678901
        assert msg.exchange == Exchange.UPBIT
        assert msg.price == 134500000


# ========== Integration Tests (Markers) ==========

@pytest.mark.integration
class TestFeedHandlerIntegration:
    """통합 테스트 (실제 연결)"""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="실제 WebSocket 연결 필요")
    async def test_upbit_real_connection(self):
        """Upbit 실제 연결 테스트"""
        ws = UpbitWebSocket(["KRW-BTC"])
        try:
            connected = await ws.connect()
            assert connected is True

            # 메시지 수신 대기
            msg = await asyncio.wait_for(ws.receive(), timeout=30)
            assert msg is not None
            assert msg.exchange == Exchange.UPBIT

        finally:
            await ws.disconnect()

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="실제 WebSocket 연결 필요")
    async def test_binance_real_connection(self):
        """Binance 실제 연결 테스트"""
        ws = BinanceWebSocket(["btcusdt"])
        try:
            connected = await ws.connect()
            assert connected is True

            msg = await asyncio.wait_for(ws.receive(), timeout=30)
            assert msg is not None
            assert msg.exchange == Exchange.BINANCE

        finally:
            await ws.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
