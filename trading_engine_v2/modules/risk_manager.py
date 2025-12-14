"""
Trading Engine V2 - Risk Manager
신호 검증 및 위험 관리
"""

import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
from dataclasses import dataclass, field

from ..core.base_module import BaseModule
from ..core.config import Config
from ..core.message_types import (
    SignalMessage, OrderMessage, Exchange, Direction, Action,
    OrderStatus, EventType, create_message_id, current_timestamp
)

logger = logging.getLogger(__name__)


@dataclass
class PositionState:
    """포지션 상태"""
    exchange: Exchange
    symbol: str
    direction: Direction
    quantity: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    unrealized_pnl: float = 0.0
    unrealized_pnl_pct: float = 0.0
    leverage: int = 1


@dataclass
class RiskState:
    """리스크 상태"""
    total_equity: float = 0.0
    daily_pnl: float = 0.0
    daily_pnl_pct: float = 0.0
    max_drawdown: float = 0.0
    current_drawdown: float = 0.0
    peak_equity: float = 0.0
    long_exposure: float = 0.0
    short_exposure: float = 0.0
    hedge_ratio: float = 0.5
    positions: Dict[str, PositionState] = field(default_factory=dict)
    daily_trades: int = 0
    last_reset: datetime = field(default_factory=datetime.now)


class RiskManager(BaseModule):
    """
    Risk Manager - 신호 검증 및 위험 관리

    기능:
    - 모든 전략 신호 검증
    - 포지션 크기 조정
    - Long/Short 헤지 비율 관리
    - 최대 손실 한도 체크
    - 승인된 주문만 실행기로 전달
    """

    # 기본 리스크 파라미터
    DEFAULT_PARAMS = {
        'max_drawdown_pct': 20.0,
        'max_position_pct': 50.0,
        'daily_loss_limit_pct': 5.0,
        'min_hedge_ratio': 0.3,
        'max_hedge_ratio': 0.7,
        'max_leverage': 3,
        'volatility_threshold': 0.05,
        'max_daily_trades': 10,
        'cooldown_seconds': 300,  # 5분
    }

    def __init__(
        self,
        config: Optional[Config] = None,
        risk_params: Optional[Dict] = None,
        initial_capital: float = 10_000_000,
    ):
        super().__init__("risk-manager", config)

        self.risk_params = {**self.DEFAULT_PARAMS, **(risk_params or {})}
        self.initial_capital = initial_capital

        # 리스크 상태
        self.state = RiskState(
            total_equity=initial_capital,
            peak_equity=initial_capital,
        )

        # 마지막 신호 시간 (쿨다운용)
        self._last_signal_times: Dict[str, datetime] = {}

        # 통계
        self._signals_received = 0
        self._signals_approved = 0
        self._signals_rejected = 0

    async def on_start(self):
        """시작"""
        self.logger.info("⚠️ Risk Manager 시작")
        self.logger.info(f"   초기 자본: {self.initial_capital:,.0f}")
        self.logger.info(f"   최대 낙폭: {self.risk_params['max_drawdown_pct']}%")
        self.logger.info(f"   헤지 범위: {self.risk_params['min_hedge_ratio']:.1%} ~ "
                        f"{self.risk_params['max_hedge_ratio']:.1%}")

    async def on_stop(self):
        """정지"""
        self.logger.info("⚠️ Risk Manager 정지")
        self.logger.info(f"   처리 신호: {self._signals_received}")
        self.logger.info(f"   승인: {self._signals_approved}, 거부: {self._signals_rejected}")

    async def run_cycle(self):
        """메인 사이클 - 신호 소비 및 검증"""
        # Redis Stream에서 전략 신호 소비
        messages = await self.consume(
            self.config.redis.streams["signals"],
            "risk-manager",
            count=10,
            block=1000,
        )

        for msg in messages:
            try:
                signal_data = msg["data"]
                self._signals_received += 1

                # 신호 검증
                validation = self._validate_signal(signal_data)

                if validation['approved']:
                    # 주문 생성 및 발행
                    order = self._create_order(signal_data, validation)
                    await self._publish_order(order)
                    self._signals_approved += 1

                    self.logger.info(
                        f"✅ 신호 승인: {signal_data.get('strategy')} | "
                        f"{signal_data.get('action')} | "
                        f"조정 fraction: {validation['adjusted_fraction']:.2f}"
                    )
                else:
                    self._signals_rejected += 1
                    self.logger.warning(
                        f"❌ 신호 거부: {signal_data.get('strategy')} | "
                        f"사유: {validation['reason']}"
                    )

                # ACK
                await self.ack(
                    self.config.redis.streams["signals"],
                    "risk-manager",
                    msg["id"]
                )

            except Exception as e:
                self.logger.error(f"신호 처리 오류: {e}")

        # 일일 리셋 체크
        self._check_daily_reset()

    def _validate_signal(self, signal: Dict) -> Dict:
        """
        신호 검증

        Returns:
            {'approved': bool, 'reason': str, 'adjusted_fraction': float}
        """
        strategy = signal.get('strategy', '')
        exchange = signal.get('exchange', '')
        action = signal.get('action', '')
        fraction = float(signal.get('fraction', 0.5))

        # 1. 일일 손실 한도 체크
        if self.state.daily_pnl_pct <= -self.risk_params['daily_loss_limit_pct']:
            return {
                'approved': False,
                'reason': f'DAILY_LOSS_LIMIT_EXCEEDED_{self.state.daily_pnl_pct:.2f}%',
                'adjusted_fraction': 0,
            }

        # 2. 최대 낙폭 체크
        if self.state.current_drawdown >= self.risk_params['max_drawdown_pct']:
            return {
                'approved': False,
                'reason': f'MAX_DRAWDOWN_EXCEEDED_{self.state.current_drawdown:.2f}%',
                'adjusted_fraction': 0,
            }

        # 3. 일일 거래 횟수 체크
        if self.state.daily_trades >= self.risk_params['max_daily_trades']:
            return {
                'approved': False,
                'reason': f'MAX_DAILY_TRADES_EXCEEDED_{self.state.daily_trades}',
                'adjusted_fraction': 0,
            }

        # 4. 쿨다운 체크
        cooldown = self.risk_params['cooldown_seconds']
        last_time = self._last_signal_times.get(strategy)
        if last_time:
            elapsed = (datetime.now() - last_time).total_seconds()
            if elapsed < cooldown:
                return {
                    'approved': False,
                    'reason': f'COOLDOWN_{int(cooldown - elapsed)}s_REMAINING',
                    'adjusted_fraction': 0,
                }

        # 5. 헤지 비율 조정
        adjusted_fraction = self._adjust_for_hedge_ratio(
            exchange=exchange,
            action=action,
            fraction=fraction
        )

        if adjusted_fraction <= 0:
            return {
                'approved': False,
                'reason': 'HEDGE_RATIO_LIMIT',
                'adjusted_fraction': 0,
            }

        # 6. 포지션 크기 제한
        max_position_pct = self.risk_params['max_position_pct']
        if adjusted_fraction > max_position_pct / 100:
            adjusted_fraction = max_position_pct / 100

        # 승인
        self._last_signal_times[strategy] = datetime.now()
        self.state.daily_trades += 1

        return {
            'approved': True,
            'reason': 'APPROVED',
            'adjusted_fraction': adjusted_fraction,
        }

    def _adjust_for_hedge_ratio(
        self,
        exchange: str,
        action: str,
        fraction: float
    ) -> float:
        """
        헤지 비율에 따른 포지션 조정

        상승장: Long 비중 ↑, Short 비중 ↓
        하락장: Long 비중 ↓, Short 비중 ↑
        횡보장: 50:50
        """
        current_long = self.state.long_exposure
        current_short = self.state.short_exposure
        total_exposure = current_long + current_short

        # 신규 포지션인 경우
        if total_exposure == 0:
            return fraction

        # 현재 헤지 비율
        if current_long > 0:
            current_hedge = current_short / current_long
        else:
            current_hedge = 1.0

        min_hedge = self.risk_params['min_hedge_ratio']
        max_hedge = self.risk_params['max_hedge_ratio']

        # Long 진입 시
        if exchange == 'upbit' and action in ['buy']:
            # 헤지 비율이 너무 낮으면 Long 제한
            if current_hedge < min_hedge and current_short > 0:
                return fraction * 0.5
            return fraction

        # Short 진입 시
        elif exchange == 'binance' and action in ['open_short']:
            # 헤지 비율이 너무 높으면 Short 제한
            if current_hedge > max_hedge and current_long > 0:
                return fraction * 0.5
            return fraction

        return fraction

    def _create_order(self, signal: Dict, validation: Dict) -> Dict:
        """승인된 신호로 주문 생성"""
        return {
            'id': create_message_id('ord'),
            'timestamp': current_timestamp(),
            'signal_id': signal.get('id', ''),
            'exchange': signal.get('exchange'),
            'symbol': signal.get('symbol'),
            'action': signal.get('action'),
            'direction': signal.get('direction'),
            'quantity': validation['adjusted_fraction'],
            'price': None,  # 시장가
            'leverage': signal.get('leverage', 1),
            'status': 'pending',
            'stop_loss_pct': signal.get('stop_loss_pct'),
            'take_profit_pct': signal.get('take_profit_pct'),
            'metadata': signal.get('metadata'),
        }

    async def _publish_order(self, order: Dict):
        """주문 발행"""
        await self.publish(
            self.config.redis.streams["pending_orders"],
            order
        )

    def _check_daily_reset(self):
        """일일 리셋 체크"""
        now = datetime.now()
        if now.date() > self.state.last_reset.date():
            self.logger.info("📅 일일 리셋 수행")
            self.state.daily_pnl = 0.0
            self.state.daily_pnl_pct = 0.0
            self.state.daily_trades = 0
            self.state.last_reset = now

    def update_position(
        self,
        exchange: str,
        symbol: str,
        quantity: float,
        entry_price: float,
        current_price: float,
        direction: str = 'long',
        leverage: int = 1
    ):
        """포지션 업데이트 (외부에서 호출)"""
        key = f"{exchange}:{symbol}"

        if quantity > 0:
            pnl = (current_price - entry_price) / entry_price
            if direction == 'short':
                pnl = -pnl
            pnl *= leverage

            self.state.positions[key] = PositionState(
                exchange=Exchange(exchange),
                symbol=symbol,
                direction=Direction(direction),
                quantity=quantity,
                entry_price=entry_price,
                current_price=current_price,
                unrealized_pnl=pnl * entry_price * quantity,
                unrealized_pnl_pct=pnl * 100,
                leverage=leverage,
            )
        else:
            self.state.positions.pop(key, None)

        # 노출도 재계산
        self._recalculate_exposure()

    def _recalculate_exposure(self):
        """Long/Short 노출도 재계산"""
        long_total = 0.0
        short_total = 0.0

        for pos in self.state.positions.values():
            value = pos.quantity * pos.current_price
            if pos.direction == Direction.LONG:
                long_total += value
            else:
                short_total += value

        self.state.long_exposure = long_total
        self.state.short_exposure = short_total

        if long_total > 0:
            self.state.hedge_ratio = short_total / long_total
        else:
            self.state.hedge_ratio = 0.0

    def update_equity(self, total_equity: float):
        """자산 업데이트"""
        self.state.total_equity = total_equity

        # 피크 갱신
        if total_equity > self.state.peak_equity:
            self.state.peak_equity = total_equity

        # 낙폭 계산
        if self.state.peak_equity > 0:
            self.state.current_drawdown = (
                (self.state.peak_equity - total_equity) / self.state.peak_equity * 100
            )
            self.state.max_drawdown = max(
                self.state.max_drawdown,
                self.state.current_drawdown
            )

        # 일일 손익
        self.state.daily_pnl = total_equity - self.initial_capital
        self.state.daily_pnl_pct = self.state.daily_pnl / self.initial_capital * 100

    def get_risk_state(self) -> Dict:
        """현재 리스크 상태 반환"""
        return {
            'total_equity': self.state.total_equity,
            'daily_pnl': self.state.daily_pnl,
            'daily_pnl_pct': self.state.daily_pnl_pct,
            'current_drawdown': self.state.current_drawdown,
            'max_drawdown': self.state.max_drawdown,
            'long_exposure': self.state.long_exposure,
            'short_exposure': self.state.short_exposure,
            'hedge_ratio': self.state.hedge_ratio,
            'daily_trades': self.state.daily_trades,
            'positions': len(self.state.positions),
        }

    def get_stats(self) -> Dict[str, Any]:
        """통계"""
        base_stats = super().get_stats()
        base_stats.update({
            'signals_received': self._signals_received,
            'signals_approved': self._signals_approved,
            'signals_rejected': self._signals_rejected,
            'approval_rate': (
                self._signals_approved / self._signals_received * 100
                if self._signals_received > 0 else 0
            ),
            'risk_state': self.get_risk_state(),
        })
        return base_stats
