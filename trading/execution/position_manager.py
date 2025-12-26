"""
Trading Engine V2 - Position Manager
포지션 관리 및 PnL 계산

기능:
- 체결 결과 수신 및 포지션 업데이트
- 실시간 PnL 계산
- Stop Loss / Take Profit 모니터링
- 포지션 상태 발행
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field
from enum import Enum

from ..core.base_module import BaseModule
from ..core.config import Config
from ..core.message_types import (
    Exchange, Direction, Action, Position, PositionMessage,
    EventType, create_message_id, current_timestamp
)

logger = logging.getLogger(__name__)


# =============================================================================
# Position Data Structures
# =============================================================================

@dataclass
class PositionEntry:
    """개별 포지션 엔트리"""
    id: str
    exchange: Exchange
    symbol: str
    direction: Direction
    quantity: float
    entry_price: float
    leverage: int = 1

    # 현재 상태
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0

    # 리스크 관리
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    trailing_stop_pct: Optional[float] = None
    highest_price: float = 0.0  # 트레일링 스탑용

    # 메타데이터
    signal_id: Optional[str] = None
    order_id: Optional[str] = None
    strategy: str = ""
    opened_at: datetime = field(default_factory=datetime.now)
    closed_at: Optional[datetime] = None

    def update_price(self, price: float):
        """현재가 업데이트 및 PnL 계산"""
        self.current_price = price

        if self.direction == Direction.LONG:
            pnl_ratio = (price - self.entry_price) / self.entry_price
        else:  # SHORT
            pnl_ratio = (self.entry_price - price) / self.entry_price

        self.unrealized_pnl_pct = pnl_ratio * 100 * self.leverage
        self.unrealized_pnl = self.quantity * self.entry_price * pnl_ratio * self.leverage

        # 트레일링 스탑용 최고가 업데이트
        if self.direction == Direction.LONG:
            self.highest_price = max(self.highest_price, price)
        else:
            if self.highest_price == 0:
                self.highest_price = price
            else:
                self.highest_price = min(self.highest_price, price)

    def check_stop_loss(self) -> bool:
        """스탑로스 확인"""
        if self.stop_loss_price is None:
            return False

        if self.direction == Direction.LONG:
            return self.current_price <= self.stop_loss_price
        else:
            return self.current_price >= self.stop_loss_price

    def check_take_profit(self) -> bool:
        """테이크프로핏 확인"""
        if self.take_profit_price is None:
            return False

        if self.direction == Direction.LONG:
            return self.current_price >= self.take_profit_price
        else:
            return self.current_price <= self.take_profit_price

    def check_trailing_stop(self) -> bool:
        """트레일링 스탑 확인"""
        if self.trailing_stop_pct is None or self.highest_price == 0:
            return False

        if self.direction == Direction.LONG:
            trailing_price = self.highest_price * (1 - self.trailing_stop_pct / 100)
            return self.current_price <= trailing_price
        else:
            trailing_price = self.highest_price * (1 + self.trailing_stop_pct / 100)
            return self.current_price >= trailing_price

    def to_dict(self) -> Dict[str, Any]:
        """딕셔너리 변환"""
        return {
            "id": self.id,
            "exchange": self.exchange.value,
            "symbol": self.symbol,
            "direction": self.direction.value,
            "quantity": self.quantity,
            "entry_price": self.entry_price,
            "current_price": self.current_price,
            "leverage": self.leverage,
            "unrealized_pnl": self.unrealized_pnl,
            "unrealized_pnl_pct": self.unrealized_pnl_pct,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "strategy": self.strategy,
            "opened_at": self.opened_at.isoformat(),
        }


@dataclass
class ClosedPosition:
    """청산된 포지션"""
    id: str
    exchange: Exchange
    symbol: str
    direction: Direction
    quantity: float
    entry_price: float
    exit_price: float
    leverage: int = 1

    # 결과
    realized_pnl: float = 0.0
    realized_pnl_pct: float = 0.0
    exit_reason: str = ""

    # 시간
    opened_at: datetime = field(default_factory=datetime.now)
    closed_at: datetime = field(default_factory=datetime.now)
    holding_time: timedelta = field(default_factory=timedelta)


# =============================================================================
# Position Manager
# =============================================================================

class PositionManager(BaseModule):
    """
    Position Manager - 포지션 관리

    기능:
    - 체결 결과 수신 및 포지션 생성/업데이트
    - 실시간 가격으로 PnL 계산
    - SL/TP/트레일링 스탑 모니터링
    - 포지션 상태 발행
    """

    def __init__(
        self,
        config: Optional[Config] = None,
        initial_capital: float = 10_000_000,
    ):
        super().__init__("position-manager", config)

        # 자본
        self.initial_capital = initial_capital
        self.total_equity = initial_capital
        self.available_balance = initial_capital

        # 포지션
        self.positions: Dict[str, PositionEntry] = {}
        self.closed_positions: List[ClosedPosition] = []

        # 가격 캐시
        self.price_cache: Dict[str, float] = {}

        # 통계
        self._total_trades = 0
        self._winning_trades = 0
        self._total_pnl = 0.0
        self._max_drawdown = 0.0
        self._peak_equity = initial_capital

    async def on_start(self):
        """시작 시 초기화"""
        self.logger.info(f"초기 자본: {self.initial_capital:,.0f} KRW")

    async def on_stop(self):
        """종료 시 정리"""
        # 포지션 상태 저장
        self.logger.info(f"활성 포지션 {len(self.positions)}개, 총 자산 {self.total_equity:,.0f} KRW")

    async def run_cycle(self):
        """실행 주기"""
        try:
            # 체결 결과 수신
            executions = await self._receive_executions()
            for exec_data in executions:
                await self._process_execution(exec_data)

            # 가격 업데이트 수신
            prices = await self._receive_prices()
            for price_data in prices:
                await self._update_price(price_data)

            # SL/TP 모니터링
            await self._monitor_positions()

            # 상태 발행 (10초마다)
            if hasattr(self, '_last_publish'):
                if (datetime.now() - self._last_publish).seconds >= 10:
                    await self._publish_position_update()
                    self._last_publish = datetime.now()
            else:
                self._last_publish = datetime.now()

            await asyncio.sleep(0.1)

        except Exception as e:
            self.logger.error(f"실행 주기 오류: {e}")

    async def _receive_executions(self) -> List[Dict]:
        """체결 결과 수신"""
        try:
            stream = self.config.redis.streams.get("executed_orders", "orders:executed")
            messages = await self.redis.read_stream(
                stream,
                group="position-manager",
                consumer=f"pos-{self.module_name}",
                count=10
            )
            return messages
        except Exception as e:
            self.logger.debug(f"체결 수신 중: {e}")
            return []

    async def _receive_prices(self) -> List[Dict]:
        """가격 데이터 수신"""
        try:
            stream = self.config.redis.streams.get("prices", "market:prices")
            messages = await self.redis.read_stream(
                stream,
                group="position-manager",
                consumer=f"pos-{self.module_name}",
                count=100
            )
            return messages
        except Exception as e:
            self.logger.debug(f"가격 수신 중: {e}")
            return []

    async def _process_execution(self, exec_data: Dict):
        """체결 결과 처리"""
        try:
            order_id = exec_data.get("order_id")
            exchange = Exchange(exec_data.get("exchange", "upbit"))
            symbol = exec_data.get("symbol", "")
            action = Action(exec_data.get("action", "hold"))
            direction = Direction(exec_data.get("direction", "long"))
            quantity = float(exec_data.get("quantity", 0))
            price = float(exec_data.get("price", 0))
            leverage = int(exec_data.get("leverage", 1))

            # 포지션 키
            pos_key = f"{exchange.value}:{symbol}:{direction.value}"

            if action in [Action.BUY, Action.OPEN_SHORT]:
                # 신규 포지션 또는 추가
                await self._open_position(
                    pos_key, order_id, exchange, symbol, direction,
                    quantity, price, leverage, exec_data
                )
            elif action in [Action.SELL, Action.CLOSE_SHORT]:
                # 포지션 청산
                await self._close_position(pos_key, quantity, price, "MANUAL")

        except Exception as e:
            self.logger.error(f"체결 처리 실패: {e}")

    async def _open_position(
        self,
        pos_key: str,
        order_id: str,
        exchange: Exchange,
        symbol: str,
        direction: Direction,
        quantity: float,
        price: float,
        leverage: int,
        exec_data: Dict
    ):
        """포지션 오픈"""
        if pos_key in self.positions:
            # 기존 포지션에 추가 (평균 단가 계산)
            pos = self.positions[pos_key]
            total_value = pos.quantity * pos.entry_price + quantity * price
            total_qty = pos.quantity + quantity
            pos.quantity = total_qty
            pos.entry_price = total_value / total_qty
        else:
            # 신규 포지션
            pos = PositionEntry(
                id=create_message_id("pos"),
                exchange=exchange,
                symbol=symbol,
                direction=direction,
                quantity=quantity,
                entry_price=price,
                leverage=leverage,
                current_price=price,
                signal_id=exec_data.get("signal_id"),
                order_id=order_id,
                strategy=exec_data.get("strategy", ""),
            )
            self.positions[pos_key] = pos

        # 잔고 업데이트
        cost = quantity * price / leverage
        self.available_balance -= cost

        self.logger.info(
            f"📈 포지션 오픈: {symbol} {direction.value} "
            f"{quantity}@{price:,.0f} x{leverage}"
        )

    async def _close_position(
        self,
        pos_key: str,
        quantity: float,
        exit_price: float,
        reason: str
    ):
        """포지션 청산"""
        if pos_key not in self.positions:
            self.logger.warning(f"포지션 없음: {pos_key}")
            return

        pos = self.positions[pos_key]

        # 청산 수량 결정
        close_qty = min(quantity, pos.quantity)

        # PnL 계산
        if pos.direction == Direction.LONG:
            pnl_ratio = (exit_price - pos.entry_price) / pos.entry_price
        else:
            pnl_ratio = (pos.entry_price - exit_price) / pos.entry_price

        realized_pnl = close_qty * pos.entry_price * pnl_ratio * pos.leverage
        realized_pnl_pct = pnl_ratio * 100 * pos.leverage

        # 청산된 포지션 기록
        closed = ClosedPosition(
            id=pos.id,
            exchange=pos.exchange,
            symbol=pos.symbol,
            direction=pos.direction,
            quantity=close_qty,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            leverage=pos.leverage,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            exit_reason=reason,
            opened_at=pos.opened_at,
            closed_at=datetime.now(),
            holding_time=datetime.now() - pos.opened_at,
        )
        self.closed_positions.append(closed)

        # 통계 업데이트
        self._total_trades += 1
        self._total_pnl += realized_pnl
        if realized_pnl > 0:
            self._winning_trades += 1

        # 잔고 업데이트
        original_cost = close_qty * pos.entry_price / pos.leverage
        self.available_balance += original_cost + realized_pnl
        self.total_equity += realized_pnl

        # 최대 낙폭 업데이트
        self._peak_equity = max(self._peak_equity, self.total_equity)
        current_dd = (self._peak_equity - self.total_equity) / self._peak_equity * 100
        self._max_drawdown = max(self._max_drawdown, current_dd)

        # 부분 청산 vs 완전 청산
        if close_qty >= pos.quantity:
            del self.positions[pos_key]
            emoji = "🔴" if realized_pnl < 0 else "🟢"
        else:
            pos.quantity -= close_qty
            emoji = "🟡"

        self.logger.info(
            f"{emoji} 포지션 청산: {pos.symbol} {pos.direction.value} "
            f"{close_qty}@{exit_price:,.0f} | PnL: {realized_pnl:+,.0f} ({realized_pnl_pct:+.2f}%) | {reason}"
        )

    async def _update_price(self, price_data: Dict):
        """가격 업데이트"""
        exchange = price_data.get("exchange", "")
        symbol = price_data.get("symbol", "")
        price = float(price_data.get("price", 0))

        if not price:
            return

        # 캐시 업데이트
        cache_key = f"{exchange}:{symbol}"
        self.price_cache[cache_key] = price

        # 관련 포지션 업데이트
        for pos_key, pos in self.positions.items():
            if pos.exchange.value == exchange and pos.symbol == symbol:
                pos.update_price(price)

    async def _monitor_positions(self):
        """SL/TP 모니터링"""
        for pos_key, pos in list(self.positions.items()):
            exit_reason = None

            if pos.check_stop_loss():
                exit_reason = "STOP_LOSS"
            elif pos.check_take_profit():
                exit_reason = "TAKE_PROFIT"
            elif pos.check_trailing_stop():
                exit_reason = "TRAILING_STOP"

            if exit_reason:
                await self._trigger_close_signal(pos, exit_reason)

    async def _trigger_close_signal(self, pos: PositionEntry, reason: str):
        """청산 신호 발행"""
        try:
            # 청산 신호 생성
            if pos.direction == Direction.LONG:
                action = Action.SELL
            else:
                action = Action.CLOSE_SHORT

            signal_data = {
                "id": create_message_id("close"),
                "timestamp": current_timestamp(),
                "strategy": pos.strategy,
                "exchange": pos.exchange.value,
                "symbol": pos.symbol,
                "action": action.value,
                "direction": pos.direction.value,
                "fraction": 1.0,
                "confidence": 1.0,
                "reason": reason,
                "position_id": pos.id,
            }

            stream = self.config.redis.streams.get("signals", "strategy:signals")
            await self.redis.publish(stream, signal_data)

            self.logger.info(f"⚠️ 청산 신호 발행: {pos.symbol} | {reason}")

        except Exception as e:
            self.logger.error(f"청산 신호 발행 실패: {e}")

    async def _publish_position_update(self):
        """포지션 상태 발행"""
        try:
            # 총 미실현 PnL 계산
            total_unrealized_pnl = sum(p.unrealized_pnl for p in self.positions.values())

            # Long/Short 노출도
            long_exposure = sum(
                p.quantity * p.current_price
                for p in self.positions.values()
                if p.direction == Direction.LONG
            )
            short_exposure = sum(
                p.quantity * p.current_price
                for p in self.positions.values()
                if p.direction == Direction.SHORT
            )

            # 헤지 비율
            hedge_ratio = short_exposure / long_exposure if long_exposure > 0 else 0

            position_data = {
                "timestamp": current_timestamp(),
                "total_equity": self.total_equity + total_unrealized_pnl,
                "available_balance": self.available_balance,
                "unrealized_pnl": total_unrealized_pnl,
                "realized_pnl": self._total_pnl,
                "long_exposure": long_exposure,
                "short_exposure": short_exposure,
                "hedge_ratio": hedge_ratio,
                "positions": [p.to_dict() for p in self.positions.values()],
                "position_count": len(self.positions),
            }

            stream = self.config.redis.streams.get("positions", "positions:updates")
            await self.redis.publish(stream, position_data)

        except Exception as e:
            self.logger.error(f"포지션 상태 발행 실패: {e}")

    # =========================================================================
    # 직접 API
    # =========================================================================

    def add_position(
        self,
        exchange: Exchange,
        symbol: str,
        direction: Direction,
        quantity: float,
        entry_price: float,
        leverage: int = 1,
        stop_loss_pct: Optional[float] = None,
        take_profit_pct: Optional[float] = None,
        trailing_stop_pct: Optional[float] = None,
    ) -> PositionEntry:
        """포지션 추가"""
        pos_key = f"{exchange.value}:{symbol}:{direction.value}"

        pos = PositionEntry(
            id=create_message_id("pos"),
            exchange=exchange,
            symbol=symbol,
            direction=direction,
            quantity=quantity,
            entry_price=entry_price,
            leverage=leverage,
            current_price=entry_price,
            highest_price=entry_price,
        )

        # SL/TP 설정
        if stop_loss_pct:
            if direction == Direction.LONG:
                pos.stop_loss_price = entry_price * (1 - stop_loss_pct / 100)
            else:
                pos.stop_loss_price = entry_price * (1 + stop_loss_pct / 100)

        if take_profit_pct:
            if direction == Direction.LONG:
                pos.take_profit_price = entry_price * (1 + take_profit_pct / 100)
            else:
                pos.take_profit_price = entry_price * (1 - take_profit_pct / 100)

        if trailing_stop_pct:
            pos.trailing_stop_pct = trailing_stop_pct

        self.positions[pos_key] = pos
        return pos

    def close_position(
        self,
        exchange: Exchange,
        symbol: str,
        direction: Direction,
        exit_price: float,
        reason: str = "MANUAL"
    ) -> Optional[ClosedPosition]:
        """포지션 청산 (동기)"""
        pos_key = f"{exchange.value}:{symbol}:{direction.value}"

        if pos_key not in self.positions:
            return None

        pos = self.positions[pos_key]

        # PnL 계산
        if direction == Direction.LONG:
            pnl_ratio = (exit_price - pos.entry_price) / pos.entry_price
        else:
            pnl_ratio = (pos.entry_price - exit_price) / pos.entry_price

        realized_pnl = pos.quantity * pos.entry_price * pnl_ratio * pos.leverage
        realized_pnl_pct = pnl_ratio * 100 * pos.leverage

        closed = ClosedPosition(
            id=pos.id,
            exchange=pos.exchange,
            symbol=pos.symbol,
            direction=pos.direction,
            quantity=pos.quantity,
            entry_price=pos.entry_price,
            exit_price=exit_price,
            leverage=pos.leverage,
            realized_pnl=realized_pnl,
            realized_pnl_pct=realized_pnl_pct,
            exit_reason=reason,
            opened_at=pos.opened_at,
            closed_at=datetime.now(),
            holding_time=datetime.now() - pos.opened_at,
        )

        self.closed_positions.append(closed)
        self._total_trades += 1
        self._total_pnl += realized_pnl
        if realized_pnl > 0:
            self._winning_trades += 1

        del self.positions[pos_key]

        return closed

    def update_price(self, exchange: str, symbol: str, price: float):
        """가격 업데이트 (동기)"""
        for pos in self.positions.values():
            if pos.exchange.value == exchange and pos.symbol == symbol:
                pos.update_price(price)

    def get_position(self, exchange: Exchange, symbol: str, direction: Direction) -> Optional[PositionEntry]:
        """포지션 조회"""
        pos_key = f"{exchange.value}:{symbol}:{direction.value}"
        return self.positions.get(pos_key)

    def get_all_positions(self) -> List[Dict]:
        """모든 포지션 목록"""
        return [p.to_dict() for p in self.positions.values()]

    def get_portfolio_summary(self) -> Dict[str, Any]:
        """포트폴리오 요약"""
        total_unrealized = sum(p.unrealized_pnl for p in self.positions.values())

        long_exposure = sum(
            p.quantity * p.current_price
            for p in self.positions.values()
            if p.direction == Direction.LONG
        )
        short_exposure = sum(
            p.quantity * p.current_price
            for p in self.positions.values()
            if p.direction == Direction.SHORT
        )

        return {
            "initial_capital": self.initial_capital,
            "total_equity": self.total_equity + total_unrealized,
            "available_balance": self.available_balance,
            "unrealized_pnl": total_unrealized,
            "realized_pnl": self._total_pnl,
            "total_return_pct": (self.total_equity + total_unrealized - self.initial_capital) / self.initial_capital * 100,
            "long_exposure": long_exposure,
            "short_exposure": short_exposure,
            "hedge_ratio": short_exposure / long_exposure if long_exposure > 0 else 0,
            "position_count": len(self.positions),
        }

    def get_stats(self) -> Dict[str, Any]:
        """거래 통계"""
        win_rate = self._winning_trades / self._total_trades * 100 if self._total_trades > 0 else 0

        return {
            "total_trades": self._total_trades,
            "winning_trades": self._winning_trades,
            "losing_trades": self._total_trades - self._winning_trades,
            "win_rate": win_rate,
            "total_pnl": self._total_pnl,
            "max_drawdown": self._max_drawdown,
            "peak_equity": self._peak_equity,
        }
