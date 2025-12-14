"""
Trading Engine V2 - Phase 4 Unit Tests
Execution Manager 및 Position Manager 테스트

테스트 대상:
- UpbitAdapter: Upbit 거래소 어댑터
- BinanceAdapter: Binance 거래소 어댑터
- ExecutionManager: 주문 실행 관리
- PositionEntry: 포지션 엔트리
- PositionManager: 포지션 관리
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timedelta
import asyncio
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trading_engine_v2.modules.execution_manager import (
    ExecutionManager, UpbitAdapter, BinanceAdapter,
    OrderTracker, OrderState
)
from trading_engine_v2.modules.position_manager import (
    PositionManager, PositionEntry, ClosedPosition
)
from trading_engine_v2.core.message_types import (
    Exchange, Direction, Action, OrderMessage, OrderStatus
)


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def upbit_adapter():
    """Upbit 어댑터"""
    return UpbitAdapter(api_key="test", secret_key="test")


@pytest.fixture
def binance_adapter():
    """Binance 어댑터"""
    return BinanceAdapter(api_key="test", secret_key="test")


@pytest.fixture
def execution_manager():
    """Execution Manager (Redis 없이)"""
    with patch.object(ExecutionManager, 'redis', new_callable=MagicMock):
        em = ExecutionManager(config=None)
        em.config = MagicMock()
        em.config.redis = MagicMock()
        em.config.redis.streams = {
            'pending_orders': 'orders:pending',
            'executed_orders': 'orders:executed',
        }
        return em


@pytest.fixture
def position_manager():
    """Position Manager (Redis 없이)"""
    with patch.object(PositionManager, 'redis', new_callable=MagicMock):
        pm = PositionManager(config=None, initial_capital=10_000_000)
        pm.config = MagicMock()
        pm.config.redis = MagicMock()
        pm.config.redis.streams = {
            'executed_orders': 'orders:executed',
            'prices': 'market:prices',
            'positions': 'positions:updates',
            'signals': 'strategy:signals',
        }
        return pm


# =============================================================================
# UpbitAdapter Tests
# =============================================================================

class TestUpbitAdapter:
    """UpbitAdapter 단위 테스트"""

    @pytest.mark.asyncio
    async def test_connect(self, upbit_adapter):
        """연결 테스트"""
        result = await upbit_adapter.connect()
        assert result is True
        assert upbit_adapter.connected is True

    @pytest.mark.asyncio
    async def test_disconnect(self, upbit_adapter):
        """연결 종료 테스트"""
        await upbit_adapter.connect()
        await upbit_adapter.disconnect()
        assert upbit_adapter.connected is False

    @pytest.mark.asyncio
    async def test_place_market_buy_order(self, upbit_adapter):
        """시장가 매수 주문 테스트"""
        await upbit_adapter.connect()

        result = await upbit_adapter.place_order(
            symbol="KRW-BTC",
            side="bid",
            quantity=0.001,
            order_type="price"
        )

        assert "uuid" in result
        assert result["side"] == "bid"
        assert result["state"] == "done"
        assert result["market"] == "KRW-BTC"

    @pytest.mark.asyncio
    async def test_place_market_sell_order(self, upbit_adapter):
        """시장가 매도 주문 테스트"""
        await upbit_adapter.connect()

        result = await upbit_adapter.place_order(
            symbol="KRW-BTC",
            side="ask",
            quantity=0.001,
            order_type="market"
        )

        assert "uuid" in result
        assert result["side"] == "ask"
        assert result["state"] == "done"

    @pytest.mark.asyncio
    async def test_cancel_order(self, upbit_adapter):
        """주문 취소 테스트"""
        await upbit_adapter.connect()
        result = await upbit_adapter.cancel_order("test-order-123", "KRW-BTC")
        assert result is True

    @pytest.mark.asyncio
    async def test_get_balance(self, upbit_adapter):
        """잔고 조회 테스트"""
        await upbit_adapter.connect()
        balance = await upbit_adapter.get_balance()
        assert "KRW" in balance
        assert balance["KRW"] > 0


# =============================================================================
# BinanceAdapter Tests
# =============================================================================

class TestBinanceAdapter:
    """BinanceAdapter 단위 테스트"""

    @pytest.mark.asyncio
    async def test_connect(self, binance_adapter):
        """연결 테스트"""
        result = await binance_adapter.connect()
        assert result is True
        assert binance_adapter.connected is True

    @pytest.mark.asyncio
    async def test_place_market_order(self, binance_adapter):
        """시장가 주문 테스트"""
        await binance_adapter.connect()

        result = await binance_adapter.place_order(
            symbol="BTCUSDT",
            side="SELL",
            quantity=0.01,
            order_type="MARKET",
            leverage=3
        )

        assert "orderId" in result
        assert result["status"] == "FILLED"
        assert result["leverage"] == 3

    @pytest.mark.asyncio
    async def test_set_leverage(self, binance_adapter):
        """레버리지 설정 테스트"""
        await binance_adapter.connect()
        result = await binance_adapter.set_leverage("BTCUSDT", 5)
        assert result is True

    @pytest.mark.asyncio
    async def test_get_balance(self, binance_adapter):
        """잔고 조회 테스트"""
        await binance_adapter.connect()
        balance = await binance_adapter.get_balance()
        assert "USDT" in balance


# =============================================================================
# OrderTracker Tests
# =============================================================================

class TestOrderTracker:
    """OrderTracker 단위 테스트"""

    def test_create_tracker(self):
        """트래커 생성 테스트"""
        tracker = OrderTracker(
            order_id="order-001",
            signal_id="sig-001",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            action=Action.BUY,
            direction=Direction.LONG,
            quantity=0.01,
            price=50000000,
        )

        assert tracker.order_id == "order-001"
        assert tracker.state == OrderState.CREATED
        assert tracker.executed_qty == 0.0

    def test_state_transitions(self):
        """상태 전이 테스트"""
        tracker = OrderTracker(
            order_id="order-002",
            signal_id="sig-002",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            action=Action.OPEN_SHORT,
            direction=Direction.SHORT,
            quantity=0.1,
            leverage=3,
        )

        # CREATED → SUBMITTED
        tracker.state = OrderState.SUBMITTED
        tracker.submitted_at = datetime.now()
        assert tracker.state == OrderState.SUBMITTED

        # SUBMITTED → FILLED
        tracker.state = OrderState.FILLED
        tracker.executed_qty = 0.1
        tracker.executed_price = 50000.0
        tracker.filled_at = datetime.now()
        assert tracker.state == OrderState.FILLED


# =============================================================================
# ExecutionManager Tests
# =============================================================================

class TestExecutionManager:
    """ExecutionManager 단위 테스트"""

    def test_init(self, execution_manager):
        """초기화 테스트"""
        assert execution_manager.module_name == "execution-manager"
        assert len(execution_manager.active_orders) == 0
        assert execution_manager._orders_submitted == 0

    @pytest.mark.asyncio
    async def test_on_start(self, execution_manager):
        """시작 테스트"""
        await execution_manager.on_start()
        assert execution_manager.upbit.connected is True
        assert execution_manager.binance.connected is True

    @pytest.mark.asyncio
    async def test_submit_upbit_order(self, execution_manager):
        """Upbit 주문 제출 테스트"""
        await execution_manager.on_start()

        tracker = OrderTracker(
            order_id="order-upbit-001",
            signal_id="sig-001",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            action=Action.BUY,
            direction=Direction.LONG,
            quantity=0.001,
        )

        execution_manager.active_orders[tracker.order_id] = tracker
        await execution_manager._submit_order(tracker)

        # 시장가 즉시 체결
        assert tracker.state == OrderState.FILLED
        assert tracker.executed_qty > 0

    @pytest.mark.asyncio
    async def test_submit_binance_order(self, execution_manager):
        """Binance 주문 제출 테스트"""
        await execution_manager.on_start()

        tracker = OrderTracker(
            order_id="order-binance-001",
            signal_id="sig-001",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            action=Action.OPEN_SHORT,
            direction=Direction.SHORT,
            quantity=0.01,
            leverage=3,
        )

        execution_manager.active_orders[tracker.order_id] = tracker
        await execution_manager._submit_order(tracker)

        assert tracker.state == OrderState.FILLED
        assert tracker.executed_qty > 0

    @pytest.mark.asyncio
    async def test_cancel_order(self, execution_manager):
        """주문 취소 테스트"""
        await execution_manager.on_start()

        tracker = OrderTracker(
            order_id="order-cancel-001",
            signal_id="sig-001",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            action=Action.BUY,
            direction=Direction.LONG,
            quantity=0.001,
        )
        tracker.exchange_order_id = "upbit-order-123"
        tracker.state = OrderState.SUBMITTED

        execution_manager.active_orders[tracker.order_id] = tracker

        result = await execution_manager.cancel_order("order-cancel-001")
        assert result is True
        assert "order-cancel-001" not in execution_manager.active_orders

    def test_get_stats(self, execution_manager):
        """통계 조회 테스트"""
        execution_manager._orders_submitted = 10
        execution_manager._orders_filled = 8
        execution_manager._orders_failed = 2
        execution_manager._total_fees = 5000.0

        stats = execution_manager.get_stats()

        assert stats["orders_submitted"] == 10
        assert stats["orders_filled"] == 8
        assert stats["fill_rate"] == 80.0
        assert stats["total_fees"] == 5000.0


# =============================================================================
# PositionEntry Tests
# =============================================================================

class TestPositionEntry:
    """PositionEntry 단위 테스트"""

    def test_create_long_position(self):
        """Long 포지션 생성"""
        pos = PositionEntry(
            id="pos-001",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
        )

        assert pos.direction == Direction.LONG
        assert pos.unrealized_pnl == 0.0

    def test_update_price_long_profit(self):
        """Long 포지션 이익"""
        pos = PositionEntry(
            id="pos-002",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
        )

        pos.update_price(52000000)  # +4%

        assert pos.current_price == 52000000
        assert pos.unrealized_pnl_pct == pytest.approx(4.0, rel=0.01)
        assert pos.unrealized_pnl > 0

    def test_update_price_long_loss(self):
        """Long 포지션 손실"""
        pos = PositionEntry(
            id="pos-003",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
        )

        pos.update_price(48000000)  # -4%

        assert pos.unrealized_pnl_pct == pytest.approx(-4.0, rel=0.01)
        assert pos.unrealized_pnl < 0

    def test_update_price_short_profit(self):
        """Short 포지션 이익 (가격 하락)"""
        pos = PositionEntry(
            id="pos-004",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            quantity=0.1,
            entry_price=50000,
            leverage=3,
        )

        pos.update_price(48000)  # -4% → +12% (3x 레버리지)

        assert pos.unrealized_pnl_pct == pytest.approx(12.0, rel=0.01)
        assert pos.unrealized_pnl > 0

    def test_update_price_short_loss(self):
        """Short 포지션 손실 (가격 상승)"""
        pos = PositionEntry(
            id="pos-005",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            quantity=0.1,
            entry_price=50000,
            leverage=2,
        )

        pos.update_price(52000)  # +4% → -8% (2x 레버리지)

        assert pos.unrealized_pnl_pct == pytest.approx(-8.0, rel=0.01)
        assert pos.unrealized_pnl < 0

    def test_check_stop_loss_long(self):
        """Long 스탑로스 체크"""
        pos = PositionEntry(
            id="pos-006",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
            stop_loss_price=48000000,  # -4%
        )

        # 가격이 SL 위
        pos.update_price(49000000)
        assert pos.check_stop_loss() is False

        # 가격이 SL 아래
        pos.update_price(47000000)
        assert pos.check_stop_loss() is True

    def test_check_stop_loss_short(self):
        """Short 스탑로스 체크"""
        pos = PositionEntry(
            id="pos-007",
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            quantity=0.1,
            entry_price=50000,
            stop_loss_price=52000,  # +4%
        )

        pos.update_price(51000)
        assert pos.check_stop_loss() is False

        pos.update_price(53000)
        assert pos.check_stop_loss() is True

    def test_check_take_profit_long(self):
        """Long 테이크프로핏 체크"""
        pos = PositionEntry(
            id="pos-008",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
            take_profit_price=55000000,  # +10%
        )

        pos.update_price(54000000)
        assert pos.check_take_profit() is False

        pos.update_price(56000000)
        assert pos.check_take_profit() is True

    def test_trailing_stop_long(self):
        """Long 트레일링 스탑"""
        pos = PositionEntry(
            id="pos-009",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
            trailing_stop_pct=5.0,
        )

        # 가격 상승
        pos.update_price(55000000)
        assert pos.highest_price == 55000000
        assert pos.check_trailing_stop() is False

        # 최고가에서 5% 하락
        pos.update_price(52000000)  # 55M * 0.95 = 52.25M
        assert pos.check_trailing_stop() is True


# =============================================================================
# PositionManager Tests
# =============================================================================

class TestPositionManager:
    """PositionManager 단위 테스트"""

    def test_init(self, position_manager):
        """초기화 테스트"""
        assert position_manager.initial_capital == 10_000_000
        assert position_manager.total_equity == 10_000_000
        assert len(position_manager.positions) == 0

    def test_add_position_long(self, position_manager):
        """Long 포지션 추가"""
        pos = position_manager.add_position(
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
            stop_loss_pct=3.0,
            take_profit_pct=10.0,
        )

        assert pos.id is not None
        assert pos.stop_loss_price == 50000000 * 0.97  # -3%
        assert pos.take_profit_price == 50000000 * 1.10  # +10%
        assert len(position_manager.positions) == 1

    def test_add_position_short(self, position_manager):
        """Short 포지션 추가"""
        pos = position_manager.add_position(
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            quantity=0.1,
            entry_price=50000,
            leverage=3,
            stop_loss_pct=2.0,
            take_profit_pct=5.0,
        )

        assert pos.leverage == 3
        assert pos.stop_loss_price == 50000 * 1.02  # +2% (Short)
        assert pos.take_profit_price == 50000 * 0.95  # -5% (Short)

    def test_close_position_profit(self, position_manager):
        """이익 청산 테스트"""
        position_manager.add_position(
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
        )

        closed = position_manager.close_position(
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            exit_price=55000000,  # +10%
            reason="TAKE_PROFIT"
        )

        assert closed is not None
        assert closed.realized_pnl_pct == pytest.approx(10.0, rel=0.01)
        assert closed.realized_pnl > 0
        assert len(position_manager.positions) == 0
        assert position_manager._winning_trades == 1

    def test_close_position_loss(self, position_manager):
        """손실 청산 테스트"""
        position_manager.add_position(
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
        )

        closed = position_manager.close_position(
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            exit_price=47500000,  # -5%
            reason="STOP_LOSS"
        )

        assert closed.realized_pnl_pct == pytest.approx(-5.0, rel=0.01)
        assert closed.realized_pnl < 0
        assert position_manager._winning_trades == 0

    def test_update_price(self, position_manager):
        """가격 업데이트 테스트"""
        position_manager.add_position(
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
        )

        position_manager.update_price("upbit", "KRW-BTC", 52000000)

        pos = position_manager.get_position(
            Exchange.UPBIT, "KRW-BTC", Direction.LONG
        )
        assert pos.current_price == 52000000
        assert pos.unrealized_pnl_pct == pytest.approx(4.0, rel=0.01)

    def test_get_portfolio_summary(self, position_manager):
        """포트폴리오 요약 테스트"""
        # Long 포지션
        position_manager.add_position(
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=0.1,
            entry_price=50000000,
        )
        position_manager.update_price("upbit", "KRW-BTC", 52000000)

        # Short 포지션
        position_manager.add_position(
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            quantity=0.05,
            entry_price=50000,
        )
        position_manager.update_price("binance", "BTCUSDT", 48000)

        summary = position_manager.get_portfolio_summary()

        assert summary["position_count"] == 2
        assert summary["long_exposure"] > 0
        assert summary["short_exposure"] > 0
        assert summary["unrealized_pnl"] > 0  # 둘 다 이익

    def test_get_stats(self, position_manager):
        """통계 조회 테스트"""
        # 승리 거래
        position_manager.add_position(
            Exchange.UPBIT, "KRW-BTC", Direction.LONG, 0.1, 50000000
        )
        position_manager.close_position(
            Exchange.UPBIT, "KRW-BTC", Direction.LONG, 55000000, "TP"
        )

        # 패배 거래
        position_manager.add_position(
            Exchange.UPBIT, "KRW-BTC", Direction.LONG, 0.1, 50000000
        )
        position_manager.close_position(
            Exchange.UPBIT, "KRW-BTC", Direction.LONG, 48000000, "SL"
        )

        stats = position_manager.get_stats()

        assert stats["total_trades"] == 2
        assert stats["winning_trades"] == 1
        assert stats["win_rate"] == 50.0


# =============================================================================
# Integration Tests
# =============================================================================

class TestPhase4Integration:
    """Phase 4 통합 테스트"""

    @pytest.fixture
    def full_pipeline(self):
        """Execution + Position 파이프라인"""
        with patch.object(ExecutionManager, 'redis', new_callable=MagicMock), \
             patch.object(PositionManager, 'redis', new_callable=MagicMock):

            em = ExecutionManager(config=None)
            pm = PositionManager(config=None, initial_capital=10_000_000)

            # Mock config
            for mgr in [em, pm]:
                mgr.config = MagicMock()
                mgr.config.redis = MagicMock()
                mgr.config.redis.streams = {}

            return {"execution": em, "position": pm}

    @pytest.mark.asyncio
    async def test_order_to_position_flow(self, full_pipeline):
        """주문 → 포지션 흐름"""
        em = full_pipeline["execution"]
        pm = full_pipeline["position"]

        await em.on_start()

        # 1. 주문 실행
        tracker = OrderTracker(
            order_id="flow-order-001",
            signal_id="flow-sig-001",
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            action=Action.BUY,
            direction=Direction.LONG,
            quantity=0.1,
            price=50000000,
        )

        em.active_orders[tracker.order_id] = tracker
        await em._submit_order(tracker)

        assert tracker.state == OrderState.FILLED

        # 2. 포지션 등록
        pm.add_position(
            exchange=tracker.exchange,
            symbol=tracker.symbol,
            direction=tracker.direction,
            quantity=tracker.executed_qty,
            entry_price=tracker.executed_price,
        )

        assert len(pm.positions) == 1

        # 3. 가격 업데이트
        pm.update_price("upbit", "KRW-BTC", 52000000)

        # 4. 포지션 확인
        pos = pm.get_position(Exchange.UPBIT, "KRW-BTC", Direction.LONG)
        assert pos.unrealized_pnl > 0

    @pytest.mark.asyncio
    async def test_hedge_position_management(self, full_pipeline):
        """헤지 포지션 관리"""
        pm = full_pipeline["position"]

        # Long 포지션 (Upbit)
        pm.add_position(
            exchange=Exchange.UPBIT,
            symbol="KRW-BTC",
            direction=Direction.LONG,
            quantity=1.0,
            entry_price=50000000,
        )

        # Short 포지션 (Binance)
        pm.add_position(
            exchange=Exchange.BINANCE,
            symbol="BTCUSDT",
            direction=Direction.SHORT,
            quantity=0.5,
            entry_price=50000,
            leverage=2,
        )

        pm.update_price("upbit", "KRW-BTC", 50000000)
        pm.update_price("binance", "BTCUSDT", 50000)

        summary = pm.get_portfolio_summary()

        # 헤지 비율 확인 (Short / Long)
        # Short: 0.5 * 50000 = 25000 USDT
        # Long: 1.0 * 50000000 = 50M KRW
        assert summary["hedge_ratio"] > 0
        assert summary["position_count"] == 2


# =============================================================================
# Run tests
# =============================================================================

if __name__ == '__main__':
    pytest.main([__file__, '-v', '--tb=short'])
