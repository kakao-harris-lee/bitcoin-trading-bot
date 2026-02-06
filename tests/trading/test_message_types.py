"""
Message Types 단위 테스트

테스트 커버리지:
- Pydantic 모델 생성 및 검증
- to_dict / from_dict 변환
- Enum 값 처리
- 헬퍼 함수
"""

import pytest
from datetime import datetime
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from core.types import (
    Exchange, Direction, Action, OrderStatus, MarketState, EventType,
    OHLCV, PriceMessage, SignalMessage, OrderMessage, Position, PositionMessage,
    SystemEvent, create_message_id, current_timestamp,
)


# ========== Enum Tests ==========

class TestEnums:
    """Enum 테스트"""

    def test_exchange_values(self):
        """Exchange enum 값"""
        assert Exchange.BINANCE.value == "binance"

    def test_direction_values(self):
        """Direction enum 값"""
        assert Direction.LONG.value == "long"
        assert Direction.SHORT.value == "short"

    def test_action_values(self):
        """Action enum 값"""
        assert Action.BUY.value == "buy"
        assert Action.SELL.value == "sell"
        assert Action.OPEN_SHORT.value == "open_short"
        assert Action.CLOSE_SHORT.value == "close_short"
        assert Action.HOLD.value == "hold"

    def test_order_status_values(self):
        """OrderStatus enum 값"""
        assert OrderStatus.PENDING.value == "pending"
        assert OrderStatus.FILLED.value == "filled"
        assert OrderStatus.REJECTED.value == "rejected"

    def test_market_state_values(self):
        """MarketState enum 값"""
        assert MarketState.BULL_STRONG.value == "BULL_STRONG"
        assert MarketState.SIDEWAYS_NEUTRAL.value == "SIDEWAYS_NEUTRAL"
        assert MarketState.BEAR_STRONG.value == "BEAR_STRONG"


# ========== OHLCV Tests ==========

class TestOHLCV:
    """OHLCV 모델 테스트"""

    def test_create_ohlcv(self):
        """OHLCV 생성"""
        ohlcv = OHLCV(
            open=100.0,
            high=110.0,
            low=95.0,
            close=105.0,
            volume=1000.0,
        )
        assert ohlcv.open == 100.0
        assert ohlcv.high == 110.0
        assert ohlcv.low == 95.0
        assert ohlcv.close == 105.0
        assert ohlcv.volume == 1000.0

    def test_ohlcv_validation(self):
        """OHLCV 필드 타입 변환"""
        # 문자열로 전달해도 float으로 변환
        ohlcv = OHLCV(
            open="100.5",
            high="110.5",
            low="95.5",
            close="105.5",
            volume="1000.5",
        )
        assert isinstance(ohlcv.open, float)
        assert ohlcv.open == 100.5


# ========== PriceMessage Tests ==========

class TestPriceMessage:
    """PriceMessage 모델 테스트"""

    def test_create_minimal(self):
        """최소 필드로 생성"""
        msg = PriceMessage(
            timestamp=1702345678901,
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            price=134500000,
        )
        assert msg.timestamp == 1702345678901
        assert msg.exchange == Exchange.BINANCE
        assert msg.symbol == "BTCUSDT"
        assert msg.price == 134500000
        assert msg.volume_24h is None
        assert msg.ohlcv is None

    def test_create_full(self):
        """모든 필드로 생성"""
        ohlcv = OHLCV(open=100, high=110, low=90, close=105, volume=1000)
        msg = PriceMessage(
            timestamp=1702345678901,
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            price=43500.50,
            volume_24h=12345.67,
            ohlcv=ohlcv,
        )
        assert msg.ohlcv is not None
        assert msg.ohlcv.close == 105

    def test_to_dict(self):
        """to_dict 변환"""
        msg = PriceMessage(
            timestamp=1702345678901,
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            price=134500000,
        )
        result = msg.to_dict()

        assert isinstance(result, dict)
        assert result["timestamp"] == 1702345678901
        assert result["exchange"] == "binance"  # Enum이 문자열로 변환
        assert result["symbol"] == "BTCUSDT"

    def test_from_dict(self):
        """from_dict 생성"""
        data = {
            "timestamp": 1702345678901,
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "price": 134500000,
        }
        msg = PriceMessage.from_dict(data)

        assert msg.exchange == Exchange.BINANCE
        assert msg.price == 134500000

    def test_from_dict_with_ohlcv(self):
        """OHLCV 포함 from_dict"""
        data = {
            "timestamp": 1702345678901,
            "exchange": "binance",
            "symbol": "BTCUSDT",
            "price": 43500.50,
            "ohlcv": {
                "open": 43000,
                "high": 44000,
                "low": 42500,
                "close": 43500,
                "volume": 12345,
            }
        }
        msg = PriceMessage.from_dict(data)

        assert msg.ohlcv is not None
        assert msg.ohlcv.close == 43500


# ========== SignalMessage Tests ==========

class TestSignalMessage:
    """SignalMessage 모델 테스트"""

    def test_create_signal(self):
        """신호 메시지 생성"""
        signal = SignalMessage(
            id="sig-123",
            timestamp=1702345678901,
            strategy="short-v1",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            action=Action.BUY,
            direction=Direction.LONG,
            fraction=0.5,
            confidence=0.85,
            reason="BULL_STRONG 진입",
        )
        assert signal.id == "sig-123"
        assert signal.action == Action.BUY
        assert signal.fraction == 0.5
        assert signal.confidence == 0.85
        assert signal.leverage == 1  # 기본값

    def test_signal_fraction_validation(self):
        """fraction 범위 검증"""
        # 유효 범위 (0.0 ~ 1.0)
        signal = SignalMessage(
            id="sig-123",
            timestamp=1702345678901,
            strategy="test",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            action=Action.BUY,
            direction=Direction.LONG,
            fraction=0.0,
            confidence=1.0,
            reason="test",
        )
        assert signal.fraction == 0.0
        assert signal.confidence == 1.0

    def test_signal_to_dict(self):
        """to_dict 변환"""
        signal = SignalMessage(
            id="sig-123",
            timestamp=1702345678901,
            strategy="short-v1",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            action=Action.BUY,
            direction=Direction.LONG,
            fraction=0.5,
            confidence=0.85,
            reason="test",
        )
        result = signal.to_dict()

        assert result["action"] == "buy"
        assert result["direction"] == "long"
        assert result["exchange"] == "binance"


# ========== OrderMessage Tests ==========

class TestOrderMessage:
    """OrderMessage 모델 테스트"""

    def test_create_order(self):
        """주문 메시지 생성"""
        order = OrderMessage(
            id="ord-456",
            timestamp=1702345678901,
            signal_id="sig-123",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            action=Action.BUY,
            direction=Direction.LONG,
            quantity=0.01,
        )
        assert order.status == OrderStatus.PENDING
        assert order.leverage == 1
        assert order.executed_qty is None

    def test_order_with_execution(self):
        """체결 정보 포함 주문"""
        order = OrderMessage(
            id="ord-456",
            timestamp=1702345678901,
            signal_id="sig-123",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            action=Action.BUY,
            direction=Direction.LONG,
            quantity=0.01,
            price=134500000,
            status=OrderStatus.FILLED,
            executed_qty=0.01,
            executed_price=134500000,
            fee=6725,
        )
        assert order.status == OrderStatus.FILLED
        assert order.executed_price == 134500000


# ========== PositionMessage Tests ==========

class TestPositionMessage:
    """PositionMessage 모델 테스트"""

    def test_create_position_message(self):
        """포지션 메시지 생성"""
        binance_pos = Position(
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            side=Direction.LONG,
            quantity=0.05,
            entry_price=130000000,
            current_price=134500000,
            unrealized_pnl=225000,
            unrealized_pnl_pct=3.46,
        )

        msg = PositionMessage(
            timestamp=1702345678901,
            total_equity_krw=15000000,
            positions={"binance": binance_pos},
            total_pnl_pct=5.0,
        )

        assert msg.total_equity_krw == 15000000
        assert "binance" in msg.positions
        assert msg.total_pnl_pct == 5.0


# ========== SystemEvent Tests ==========

class TestSystemEvent:
    """SystemEvent 모델 테스트"""

    def test_create_event(self):
        """시스템 이벤트 생성"""
        event = SystemEvent(
            timestamp=1702345678901,
            event_type=EventType.STARTUP,
            module="feed-handler",
            message="시작됨",
        )
        assert event.event_type == EventType.STARTUP
        assert event.module == "feed-handler"

    def test_event_with_data(self):
        """데이터 포함 이벤트"""
        event = SystemEvent(
            timestamp=1702345678901,
            event_type=EventType.ERROR,
            module="strategy-short",
            message="연결 실패",
            data={"error_code": 500, "retry_count": 3},
        )
        assert event.data is not None
        assert event.data["error_code"] == 500


# ========== Helper Functions Tests ==========

class TestHelperFunctions:
    """헬퍼 함수 테스트"""

    def test_create_message_id_format(self):
        """메시지 ID 포맷"""
        msg_id = create_message_id("sig")
        parts = msg_id.split("-")

        assert len(parts) == 3
        assert parts[0] == "sig"
        assert parts[1].isdigit()  # timestamp
        assert len(parts[2]) == 8  # uuid

    def test_create_message_id_unique(self):
        """메시지 ID 고유성"""
        ids = [create_message_id() for _ in range(100)]
        assert len(ids) == len(set(ids))  # 모두 고유

    def test_current_timestamp(self):
        """현재 타임스탬프"""
        ts = current_timestamp()

        assert isinstance(ts, int)
        assert ts > 0
        # 밀리초 단위 (13자리)
        assert len(str(ts)) == 13

    def test_current_timestamp_increasing(self):
        """타임스탬프 증가"""
        ts1 = current_timestamp()
        ts2 = current_timestamp()
        assert ts2 >= ts1


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
