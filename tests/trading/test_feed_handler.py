"""
Feed Handler 단위 테스트

테스트 커버리지:
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

from trading.data.feed_handler import (
    FeedHandler,
    BinanceWebSocket,
    WebSocketHandler,
)
from core.types import (
    PriceMessage, OHLCV, Exchange
)
from trading.core.config import Config, TradingConfig


# ========== Fixtures ==========

@pytest.fixture
def config():
    """테스트용 Config"""
    cfg = Config()
    cfg.trading = TradingConfig(
        binance_enabled=True,
        feed_interval=0.1,  # 빠른 테스트
    )
    return cfg


@pytest.fixture
def binance_ws():
    """Binance WebSocket 인스턴스"""
    return BinanceWebSocket(symbols=["btcusdt"])


@pytest.fixture
def feed_handler(config):
    """FeedHandler 인스턴스"""
    return FeedHandler(
        config=config,
        binance_symbols=["btcusdt"],
    )


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
        assert feed_handler._binance_symbols == ["btcusdt"]
        assert feed_handler._running is False

    def test_get_stats_initial(self, feed_handler):
        """초기 통계"""
        stats = feed_handler.get_stats()

        assert stats["module"] == "feed-handler"
        assert stats["running"] is False
        assert stats["message_count"] == 0
        assert stats["binance"]["message_count"] == 0

    def test_get_last_price_empty(self, feed_handler):
        """가격 조회 - 데이터 없음"""
        result = feed_handler.get_last_price("binance", "BTCUSDT")
        assert result is None

    @pytest.mark.asyncio
    async def test_on_start_creates_websockets(self, feed_handler):
        """시작 시 WebSocket 생성"""
        with patch.object(BinanceWebSocket, 'connect', new_callable=AsyncMock) as binance_mock:
            binance_mock.return_value = True

            await feed_handler.on_start()

            assert feed_handler._binance_ws is not None
            binance_mock.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_stop_disconnects_websockets(self, feed_handler):
        """정지 시 WebSocket 종료"""
        # Mock WebSocket 설정
        feed_handler._binance_ws = Mock()
        feed_handler._binance_ws.disconnect = AsyncMock()

        await feed_handler.on_stop()

        feed_handler._binance_ws.disconnect.assert_called_once()

    @pytest.mark.asyncio
    async def test_receive_and_publish(self, feed_handler):
        """메시지 수신 및 발행"""
        # Mock 설정
        mock_price = PriceMessage(
            timestamp=1702345678901,
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            price=43500.50,
            volume_24h=536789012.34,
        )

        mock_ws = Mock(spec=BinanceWebSocket)
        mock_ws.exchange = Exchange.BINANCE
        mock_ws.receive = AsyncMock(return_value=mock_price)
        mock_ws.is_connected = True

        feed_handler.publish = AsyncMock(return_value="test-id")

        await feed_handler._receive_and_publish(mock_ws)

        # 발행 확인
        feed_handler.publish.assert_called_once()
        assert feed_handler._binance_message_count == 1

        # 가격 캐시 확인
        cached = feed_handler.get_last_price("binance", "BTCUSDT")
        assert cached is not None
        assert cached.price == 43500.50


# ========== WebSocket Connection Tests ==========

class TestWebSocketConnection:
    """WebSocket 연결 테스트"""

    @pytest.mark.asyncio
    async def test_reconnect_increments_attempts(self, binance_ws):
        """재연결 시도 횟수 증가"""
        binance_ws._reconnect_delay = 0.01  # 빠른 테스트

        with patch.object(binance_ws, 'disconnect', new_callable=AsyncMock), \
             patch.object(binance_ws, 'connect', new_callable=AsyncMock) as mock_connect:

            mock_connect.return_value = False

            await binance_ws.reconnect()

            assert binance_ws._reconnect_attempts == 1

    @pytest.mark.asyncio
    async def test_reconnect_max_attempts(self, binance_ws):
        """최대 재연결 시도 횟수"""
        binance_ws._reconnect_delay = 0.01
        binance_ws._reconnect_attempts = 10
        binance_ws._max_reconnect_attempts = 10

        result = await binance_ws.reconnect()

        assert result is False


# ========== PriceMessage Tests ==========

class TestPriceMessage:
    """PriceMessage 테스트"""

    def test_to_dict(self):
        """딕셔너리 변환"""
        msg = PriceMessage(
            timestamp=1702345678901,
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            price=43500.50,
            volume_24h=536789012.34,
            ohlcv=OHLCV(
                open=43000.00,
                high=44000.00,
                low=42500.00,
                close=43500.50,
                volume=12345.67,
            ),
        )

        result = msg.to_dict()

        assert result["timestamp"] == 1702345678901
        assert result["exchange"] == "binance"
        assert result["symbol"] == "BTCUSDT"
        assert result["price"] == 43500.50
        assert result["ohlcv"]["close"] == 43500.50

    def test_from_dict(self):
        """딕셔너리에서 생성"""
        data = {
            "timestamp": 1702345678901,
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "price": 43500.50,
            "volume_24h": 536789012.34,
        }

        msg = PriceMessage.from_dict(data)

        assert msg.timestamp == 1702345678901
        assert msg.exchange == Exchange.BINANCE
        assert msg.price == 43500.50


# ========== Integration Tests (Markers) ==========

@pytest.mark.integration
class TestFeedHandlerIntegration:
    """통합 테스트 (실제 연결)"""

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
