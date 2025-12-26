"""
Trading Engine V2 - Execution Manager
주문 실행 및 체결 관리

기능:
- Redis Stream에서 대기 주문 수신
- 거래소별 어댑터를 통한 주문 실행
- 주문 상태 추적 및 업데이트
- 체결 결과 발행
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List, Protocol
from datetime import datetime
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum

from ..core.base_module import BaseModule
from ..core.config import Config
from core.types import (
    OrderMessage, Exchange, Direction, Action, OrderStatus,
    EventType, create_message_id, current_timestamp
)

logger = logging.getLogger(__name__)


# =============================================================================
# Exchange Adapter Protocol
# =============================================================================

class ExchangeAdapter(Protocol):
    """거래소 어댑터 프로토콜"""

    async def connect(self) -> bool:
        """거래소 API 연결"""
        ...

    async def disconnect(self) -> None:
        """연결 종료"""
        ...

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: str = "market"
    ) -> Dict[str, Any]:
        """주문 실행"""
        ...

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """주문 취소"""
        ...

    async def get_order_status(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """주문 상태 조회"""
        ...

    async def get_balance(self) -> Dict[str, float]:
        """잔고 조회"""
        ...


# =============================================================================
# Upbit Adapter
# =============================================================================

class UpbitAdapter:
    """Upbit 거래소 어댑터"""

    def __init__(self, api_key: str = "", secret_key: str = ""):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://api.upbit.com"
        self.connected = False
        self.logger = logging.getLogger("trading.upbit-adapter")

    async def connect(self) -> bool:
        """Upbit API 연결 확인"""
        try:
            # 실제로는 API 키 검증
            self.connected = True
            self.logger.info("Upbit 연결 성공")
            return True
        except Exception as e:
            self.logger.error(f"Upbit 연결 실패: {e}")
            return False

    async def disconnect(self) -> None:
        """연결 종료"""
        self.connected = False
        self.logger.info("Upbit 연결 종료")

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: str = "market"
    ) -> Dict[str, Any]:
        """
        Upbit 주문 실행

        Args:
            symbol: 심볼 (예: KRW-BTC)
            side: bid(매수) / ask(매도)
            quantity: 수량
            price: 지정가 (시장가 시 None)
            order_type: limit / price(시장가 매수) / market(시장가 매도)

        Returns:
            주문 결과
        """
        try:
            # 시뮬레이션 모드
            order_id = create_message_id("upbit-order")

            # 시장가 주문 시 즉시 체결 가정
            if order_type in ["price", "market"]:
                executed_price = price or 50000000  # 임시
                result = {
                    "uuid": order_id,
                    "side": side,
                    "ord_type": order_type,
                    "state": "done",
                    "market": symbol,
                    "volume": str(quantity),
                    "executed_volume": str(quantity),
                    "price": str(executed_price),
                    "avg_price": str(executed_price),
                    "fee": str(executed_price * quantity * 0.0005),
                }
            else:
                # 지정가 주문
                result = {
                    "uuid": order_id,
                    "side": side,
                    "ord_type": order_type,
                    "state": "wait",
                    "market": symbol,
                    "volume": str(quantity),
                    "executed_volume": "0",
                    "price": str(price),
                    "avg_price": None,
                    "fee": "0",
                }

            self.logger.info(f"Upbit 주문 실행: {symbol} {side} {quantity}")
            return result

        except Exception as e:
            self.logger.error(f"Upbit 주문 실패: {e}")
            return {"error": str(e), "state": "failed"}

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """주문 취소"""
        try:
            self.logger.info(f"Upbit 주문 취소: {order_id}")
            return True
        except Exception as e:
            self.logger.error(f"Upbit 주문 취소 실패: {e}")
            return False

    async def get_order_status(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """주문 상태 조회"""
        return {
            "uuid": order_id,
            "state": "done",
            "market": symbol,
        }

    async def get_balance(self) -> Dict[str, float]:
        """잔고 조회"""
        return {
            "KRW": 10000000.0,
            "BTC": 0.0,
        }


# =============================================================================
# Binance Adapter
# =============================================================================

class BinanceAdapter:
    """Binance Futures 거래소 어댑터"""

    def __init__(self, api_key: str = "", secret_key: str = ""):
        self.api_key = api_key
        self.secret_key = secret_key
        self.base_url = "https://fapi.binance.com"
        self.connected = False
        self.logger = logging.getLogger("trading.binance-adapter")

    async def connect(self) -> bool:
        """Binance API 연결 확인"""
        try:
            self.connected = True
            self.logger.info("Binance 연결 성공")
            return True
        except Exception as e:
            self.logger.error(f"Binance 연결 실패: {e}")
            return False

    async def disconnect(self) -> None:
        """연결 종료"""
        self.connected = False
        self.logger.info("Binance 연결 종료")

    async def place_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: Optional[float] = None,
        order_type: str = "MARKET",
        leverage: int = 1,
        position_side: str = "BOTH"
    ) -> Dict[str, Any]:
        """
        Binance Futures 주문 실행

        Args:
            symbol: 심볼 (예: BTCUSDT)
            side: BUY / SELL
            quantity: 수량
            price: 지정가
            order_type: MARKET / LIMIT
            leverage: 레버리지
            position_side: BOTH / LONG / SHORT

        Returns:
            주문 결과
        """
        try:
            order_id = create_message_id("binance-order")

            if order_type == "MARKET":
                executed_price = price or 50000.0  # 임시 USD
                result = {
                    "orderId": order_id,
                    "symbol": symbol,
                    "side": side,
                    "type": order_type,
                    "status": "FILLED",
                    "origQty": str(quantity),
                    "executedQty": str(quantity),
                    "price": str(executed_price),
                    "avgPrice": str(executed_price),
                    "commission": str(executed_price * quantity * 0.0004),
                    "leverage": leverage,
                }
            else:
                result = {
                    "orderId": order_id,
                    "symbol": symbol,
                    "side": side,
                    "type": order_type,
                    "status": "NEW",
                    "origQty": str(quantity),
                    "executedQty": "0",
                    "price": str(price),
                    "avgPrice": None,
                    "commission": "0",
                    "leverage": leverage,
                }

            self.logger.info(f"Binance 주문 실행: {symbol} {side} {quantity} x{leverage}")
            return result

        except Exception as e:
            self.logger.error(f"Binance 주문 실패: {e}")
            return {"error": str(e), "status": "FAILED"}

    async def cancel_order(self, order_id: str, symbol: str) -> bool:
        """주문 취소"""
        try:
            self.logger.info(f"Binance 주문 취소: {order_id}")
            return True
        except Exception as e:
            self.logger.error(f"Binance 주문 취소 실패: {e}")
            return False

    async def get_order_status(self, order_id: str, symbol: str) -> Dict[str, Any]:
        """주문 상태 조회"""
        return {
            "orderId": order_id,
            "status": "FILLED",
            "symbol": symbol,
        }

    async def get_balance(self) -> Dict[str, float]:
        """잔고 조회"""
        return {
            "USDT": 10000.0,
        }

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """레버리지 설정"""
        try:
            self.logger.info(f"Binance 레버리지 설정: {symbol} x{leverage}")
            return True
        except Exception as e:
            self.logger.error(f"레버리지 설정 실패: {e}")
            return False


# =============================================================================
# Order State Machine
# =============================================================================

class OrderState(str, Enum):
    """주문 상태"""
    CREATED = "created"
    VALIDATING = "validating"
    PENDING = "pending"
    SUBMITTED = "submitted"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"
    FAILED = "failed"


@dataclass
class OrderTracker:
    """주문 추적"""
    order_id: str
    signal_id: str
    exchange: Exchange
    symbol: str
    action: Action
    direction: Direction
    quantity: float
    price: Optional[float] = None
    leverage: int = 1

    # 상태
    state: OrderState = OrderState.CREATED
    exchange_order_id: Optional[str] = None
    executed_qty: float = 0.0
    executed_price: float = 0.0
    fee: float = 0.0

    # 타임스탬프
    created_at: datetime = field(default_factory=datetime.now)
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None

    # 오류
    error_message: Optional[str] = None
    retry_count: int = 0


# =============================================================================
# Execution Manager
# =============================================================================

class ExecutionManager(BaseModule):
    """
    Execution Manager - 주문 실행 관리

    기능:
    - Redis Stream에서 주문 수신
    - 거래소별 어댑터 관리
    - 주문 상태 추적
    - 체결 결과 발행
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        upbit_adapter: Optional[UpbitAdapter] = None,
        binance_adapter: Optional[BinanceAdapter] = None,
    ):
        super().__init__("execution-manager", config)

        # 거래소 어댑터
        self.upbit = upbit_adapter or UpbitAdapter()
        self.binance = binance_adapter or BinanceAdapter()

        # 주문 추적
        self.active_orders: Dict[str, OrderTracker] = {}
        self.completed_orders: List[OrderTracker] = []

        # 설정
        self.max_retry = 3
        self.retry_delay = 1.0  # 초

        # 통계
        self._orders_submitted = 0
        self._orders_filled = 0
        self._orders_failed = 0
        self._total_fees = 0.0

    async def on_start(self):
        """시작 시 초기화"""
        # 거래소 연결
        await self.upbit.connect()
        await self.binance.connect()
        self.logger.info("거래소 어댑터 연결 완료")

    async def on_stop(self):
        """종료 시 정리"""
        # 미체결 주문 처리
        if self.active_orders:
            self.logger.warning(f"미체결 주문 {len(self.active_orders)}건 존재")

        # 연결 종료
        await self.upbit.disconnect()
        await self.binance.disconnect()

    async def run_cycle(self):
        """실행 주기"""
        try:
            # 대기 주문 수신
            orders = await self._receive_pending_orders()

            for order_data in orders:
                await self._process_order(order_data)

            # 활성 주문 상태 확인
            await self._check_active_orders()

            await asyncio.sleep(0.1)

        except Exception as e:
            self.logger.error(f"실행 주기 오류: {e}")

    async def _receive_pending_orders(self) -> List[Dict]:
        """대기 주문 수신"""
        try:
            stream = self.config.redis.streams.get("pending_orders", "orders:pending")
            messages = await self.redis.read_stream(
                stream,
                group="execution-manager",
                consumer=f"exec-{self.module_name}",
                count=10
            )
            return messages
        except Exception as e:
            self.logger.debug(f"주문 수신 중: {e}")
            return []

    async def _process_order(self, order_data: Dict):
        """주문 처리"""
        try:
            # OrderTracker 생성
            tracker = OrderTracker(
                order_id=order_data.get("id", create_message_id("order")),
                signal_id=order_data.get("signal_id", ""),
                exchange=Exchange(order_data.get("exchange", "upbit")),
                symbol=order_data.get("symbol", ""),
                action=Action(order_data.get("action", "hold")),
                direction=Direction(order_data.get("direction", "long")),
                quantity=float(order_data.get("quantity", 0)),
                price=order_data.get("price"),
                leverage=int(order_data.get("leverage", 1)),
            )

            self.active_orders[tracker.order_id] = tracker
            self.logger.info(f"주문 수신: {tracker.order_id} {tracker.action.value}")

            # 거래소로 제출
            await self._submit_order(tracker)

        except Exception as e:
            self.logger.error(f"주문 처리 실패: {e}")

    async def _submit_order(self, tracker: OrderTracker):
        """거래소에 주문 제출"""
        tracker.state = OrderState.SUBMITTED
        tracker.submitted_at = datetime.now()

        try:
            if tracker.exchange == Exchange.UPBIT:
                result = await self._submit_upbit_order(tracker)
            else:
                result = await self._submit_binance_order(tracker)

            # 결과 처리
            if result.get("error"):
                tracker.state = OrderState.FAILED
                tracker.error_message = result.get("error")
                self._orders_failed += 1
            else:
                tracker.exchange_order_id = result.get("uuid") or result.get("orderId")
                self._orders_submitted += 1

                # 체결 확인
                await self._check_fill_status(tracker, result)

        except Exception as e:
            tracker.state = OrderState.FAILED
            tracker.error_message = str(e)
            self._orders_failed += 1
            self.logger.error(f"주문 제출 실패: {e}")

    async def _submit_upbit_order(self, tracker: OrderTracker) -> Dict:
        """Upbit 주문 제출"""
        # side 변환
        if tracker.action == Action.BUY:
            side = "bid"
            order_type = "price"  # 시장가 매수
        else:
            side = "ask"
            order_type = "market"  # 시장가 매도

        return await self.upbit.place_order(
            symbol=tracker.symbol,
            side=side,
            quantity=tracker.quantity,
            price=tracker.price,
            order_type=order_type
        )

    async def _submit_binance_order(self, tracker: OrderTracker) -> Dict:
        """Binance 주문 제출"""
        # 레버리지 설정
        if tracker.leverage > 1:
            await self.binance.set_leverage(tracker.symbol, tracker.leverage)

        # side 변환
        if tracker.action in [Action.BUY, Action.CLOSE_SHORT]:
            side = "BUY"
        else:
            side = "SELL"

        return await self.binance.place_order(
            symbol=tracker.symbol,
            side=side,
            quantity=tracker.quantity,
            price=tracker.price,
            order_type="MARKET",
            leverage=tracker.leverage
        )

    async def _check_fill_status(self, tracker: OrderTracker, result: Dict):
        """체결 상태 확인"""
        state = result.get("state") or result.get("status")

        if state in ["done", "FILLED"]:
            tracker.state = OrderState.FILLED
            tracker.filled_at = datetime.now()
            tracker.executed_qty = float(result.get("executed_volume") or result.get("executedQty", 0))
            tracker.executed_price = float(result.get("avg_price") or result.get("avgPrice", 0))
            tracker.fee = float(result.get("fee") or result.get("commission", 0))

            self._orders_filled += 1
            self._total_fees += tracker.fee

            # 완료 목록으로 이동
            self.completed_orders.append(tracker)
            del self.active_orders[tracker.order_id]

            # 체결 결과 발행
            await self._publish_execution(tracker)

            self.logger.info(
                f"✅ 주문 체결: {tracker.symbol} {tracker.action.value} "
                f"{tracker.executed_qty}@{tracker.executed_price}"
            )

        elif state in ["wait", "NEW", "PARTIALLY_FILLED"]:
            if state == "PARTIALLY_FILLED":
                tracker.state = OrderState.PARTIAL
                tracker.executed_qty = float(result.get("executedQty", 0))

    async def _check_active_orders(self):
        """활성 주문 상태 확인"""
        for order_id, tracker in list(self.active_orders.items()):
            if tracker.state in [OrderState.SUBMITTED, OrderState.PARTIAL]:
                try:
                    if tracker.exchange == Exchange.UPBIT:
                        result = await self.upbit.get_order_status(
                            tracker.exchange_order_id, tracker.symbol
                        )
                    else:
                        result = await self.binance.get_order_status(
                            tracker.exchange_order_id, tracker.symbol
                        )

                    await self._check_fill_status(tracker, result)

                except Exception as e:
                    self.logger.error(f"주문 상태 확인 실패: {e}")

    async def _publish_execution(self, tracker: OrderTracker):
        """체결 결과 발행"""
        try:
            execution_data = {
                "order_id": tracker.order_id,
                "signal_id": tracker.signal_id,
                "exchange": tracker.exchange.value,
                "symbol": tracker.symbol,
                "action": tracker.action.value,
                "direction": tracker.direction.value,
                "quantity": tracker.executed_qty,
                "price": tracker.executed_price,
                "fee": tracker.fee,
                "leverage": tracker.leverage,
                "filled_at": tracker.filled_at.isoformat() if tracker.filled_at else None,
            }

            stream = self.config.redis.streams.get("executed_orders", "orders:executed")
            await self.redis.publish(stream, execution_data)

        except Exception as e:
            self.logger.error(f"체결 결과 발행 실패: {e}")

    # =========================================================================
    # 직접 주문 API
    # =========================================================================

    async def execute_order(self, order: OrderMessage) -> OrderTracker:
        """직접 주문 실행"""
        tracker = OrderTracker(
            order_id=order.id,
            signal_id=order.signal_id,
            exchange=Exchange(order.exchange),
            symbol=order.symbol,
            action=Action(order.action),
            direction=Direction(order.direction),
            quantity=order.quantity,
            price=order.price,
            leverage=order.leverage,
        )

        self.active_orders[tracker.order_id] = tracker
        await self._submit_order(tracker)

        return tracker

    async def cancel_order(self, order_id: str) -> bool:
        """주문 취소"""
        tracker = self.active_orders.get(order_id)
        if not tracker:
            return False

        try:
            if tracker.exchange == Exchange.UPBIT:
                success = await self.upbit.cancel_order(
                    tracker.exchange_order_id, tracker.symbol
                )
            else:
                success = await self.binance.cancel_order(
                    tracker.exchange_order_id, tracker.symbol
                )

            if success:
                tracker.state = OrderState.CANCELLED
                del self.active_orders[order_id]

            return success

        except Exception as e:
            self.logger.error(f"주문 취소 실패: {e}")
            return False

    # =========================================================================
    # 상태 조회
    # =========================================================================

    def get_active_orders(self) -> List[Dict]:
        """활성 주문 목록"""
        return [
            {
                "order_id": t.order_id,
                "exchange": t.exchange.value,
                "symbol": t.symbol,
                "action": t.action.value,
                "quantity": t.quantity,
                "state": t.state.value,
            }
            for t in self.active_orders.values()
        ]

    def get_stats(self) -> Dict[str, Any]:
        """통계"""
        return {
            "orders_submitted": self._orders_submitted,
            "orders_filled": self._orders_filled,
            "orders_failed": self._orders_failed,
            "active_orders": len(self.active_orders),
            "total_fees": self._total_fees,
            "fill_rate": (
                self._orders_filled / self._orders_submitted * 100
                if self._orders_submitted > 0 else 0
            ),
        }
