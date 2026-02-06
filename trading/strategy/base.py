"""
Trading Engine V2 - Base Strategy
전략 엔진의 기본 클래스
"""

import asyncio
import logging
from abc import abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime
import pandas as pd

from ..core.base_module import BaseModule
from ..core.config import Config
from core.types import (
    PriceMessage, SignalMessage, Exchange, Direction, Action,
    MarketState, create_message_id, current_timestamp
)

logger = logging.getLogger(__name__)


class BaseStrategy(BaseModule):
    """
    전략 엔진의 기본 클래스

    모든 전략은 이 클래스를 상속받아 구현:
    - ShortV1Strategy (Binance Futures Short)
    """

    def __init__(
        self,
        strategy_name: str,
        exchange: Exchange,
        direction: Direction,
        symbol: str,
        config: Optional[Config] = None,
        strategy_config: Optional[Dict] = None,
    ):
        """
        Args:
            strategy_name: 전략 이름 (예: "short-v1")
            exchange: 거래소
            direction: 방향 (LONG/SHORT)
            symbol: 거래 심볼
            config: 시스템 설정
            strategy_config: 전략 하이퍼파라미터
        """
        super().__init__(f"strategy-{strategy_name}", config)

        self.strategy_name = strategy_name
        self.exchange = exchange
        self.direction = direction
        self.symbol = symbol
        self.strategy_config = strategy_config or {}

        # 가격 데이터 버퍼 (지표 계산용)
        self._price_buffer: List[Dict] = []
        self._buffer_size = self.strategy_config.get('buffer_size', 300)

        # 포지션 상태
        self.in_position = False
        self.entry_price = 0.0
        self.entry_time: Optional[datetime] = None
        self.entry_reason = ""

        # 통계
        self._signal_count = 0
        self._last_signal_time: Optional[datetime] = None

    async def on_start(self):
        """전략 시작 - 가격 스트림 구독 준비"""
        self.logger.info(f"📈 {self.strategy_name} 전략 초기화")
        self.logger.info(f"   Exchange: {self.exchange.value}")
        self.logger.info(f"   Direction: {self.direction.value}")
        self.logger.info(f"   Symbol: {self.symbol}")

    async def on_stop(self):
        """전략 정지"""
        self.logger.info(f"📉 {self.strategy_name} 전략 정지")

    async def run_cycle(self):
        """
        메인 사이클 - 가격 데이터 소비 및 신호 생성
        """
        # Redis Stream에서 가격 데이터 소비
        messages = await self.consume(
            self.config.redis.streams["prices"],
            f"strategy-{self.strategy_name.replace('-', '_')}",
            count=10,
            block=1000,
        )

        for msg in messages:
            try:
                price_data = msg["data"]

                # 해당 거래소/심볼만 처리
                if price_data.get("exchange") != self.exchange.value:
                    await self.ack(
                        self.config.redis.streams["prices"],
                        f"strategy-{self.strategy_name.replace('-', '_')}",
                        msg["id"]
                    )
                    continue

                # 가격 버퍼에 추가
                self._add_to_buffer(price_data)

                # 신호 생성 시도
                if len(self._price_buffer) >= self._min_buffer_size():
                    signal = await self._generate_signal()
                    if signal:
                        await self._publish_signal(signal)

                # ACK
                await self.ack(
                    self.config.redis.streams["prices"],
                    f"strategy-{self.strategy_name.replace('-', '_')}",
                    msg["id"]
                )

            except Exception as e:
                self.logger.error(f"가격 처리 오류: {e}")

    def _add_to_buffer(self, price_data: Dict):
        """가격 데이터를 버퍼에 추가"""
        self._price_buffer.append({
            "timestamp": price_data.get("timestamp"),
            "open": float(price_data.get("ohlcv", {}).get("open", price_data.get("price", 0))),
            "high": float(price_data.get("ohlcv", {}).get("high", price_data.get("price", 0))),
            "low": float(price_data.get("ohlcv", {}).get("low", price_data.get("price", 0))),
            "close": float(price_data.get("ohlcv", {}).get("close", price_data.get("price", 0))),
            "volume": float(price_data.get("ohlcv", {}).get("volume", 0)),
        })

        # 버퍼 크기 제한
        if len(self._price_buffer) > self._buffer_size:
            self._price_buffer = self._price_buffer[-self._buffer_size:]

    def _get_dataframe(self) -> pd.DataFrame:
        """버퍼를 DataFrame으로 변환"""
        if not self._price_buffer:
            return pd.DataFrame()

        df = pd.DataFrame(self._price_buffer)
        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        df.set_index('timestamp', inplace=True)
        return df

    async def _generate_signal(self) -> Optional[Dict]:
        """
        신호 생성 (템플릿 메서드)

        Returns:
            신호 딕셔너리 또는 None
        """
        df = self._get_dataframe()
        if df.empty:
            return None

        # 지표 추가
        df = self.add_indicators(df)

        # 현재 인덱스
        i = len(df) - 1
        if i < self._min_buffer_size():
            return None

        # 전략별 신호 생성
        return self.generate_signal(df, i)

    async def _publish_signal(self, signal: Dict):
        """신호를 Redis Stream에 발행"""
        signal_msg = SignalMessage(
            id=create_message_id("sig"),
            timestamp=current_timestamp(),
            strategy=self.strategy_name,
            exchange=self.exchange,
            symbol=self.symbol,
            action=Action(signal["action"]),
            direction=self.direction,
            fraction=signal.get("fraction", 0.5),
            confidence=signal.get("confidence", 0.8),
            reason=signal.get("reason", ""),
            leverage=signal.get("leverage", 1),
            stop_loss_pct=signal.get("stop_loss_pct"),
            take_profit_pct=signal.get("take_profit_pct"),
            metadata=signal.get("metadata"),
        )

        await self.publish(
            self.config.redis.streams["signals"],
            signal_msg.to_dict()
        )

        self._signal_count += 1
        self._last_signal_time = datetime.now()

        self.logger.info(
            f"🎯 신호 발행: {signal_msg.action} | "
            f"reason={signal_msg.reason} | "
            f"fraction={signal_msg.fraction}"
        )

    # ========== 추상 메서드 (서브클래스에서 구현) ==========

    @abstractmethod
    def _min_buffer_size(self) -> int:
        """최소 필요 버퍼 크기"""
        pass

    @abstractmethod
    def add_indicators(self, df: pd.DataFrame) -> pd.DataFrame:
        """지표 추가"""
        pass

    @abstractmethod
    def generate_signal(self, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        신호 생성 로직

        Args:
            df: 지표가 포함된 데이터프레임
            i: 현재 인덱스

        Returns:
            {'action': 'buy'/'sell'/'hold', 'fraction': float, 'reason': str, ...}
        """
        pass

    # ========== 헬퍼 메서드 ==========

    def set_position(self, entry_price: float, reason: str):
        """포지션 설정"""
        self.in_position = True
        self.entry_price = entry_price
        self.entry_time = datetime.now()
        self.entry_reason = reason

    def clear_position(self):
        """포지션 해제"""
        self.in_position = False
        self.entry_price = 0.0
        self.entry_time = None
        self.entry_reason = ""

    def get_stats(self) -> Dict[str, Any]:
        """통계"""
        base_stats = super().get_stats()
        base_stats.update({
            "strategy_name": self.strategy_name,
            "exchange": self.exchange.value,
            "direction": self.direction.value,
            "symbol": self.symbol,
            "in_position": self.in_position,
            "entry_price": self.entry_price,
            "signal_count": self._signal_count,
            "buffer_size": len(self._price_buffer),
            "last_signal": self._last_signal_time.isoformat() if self._last_signal_time else None,
        })
        return base_stats
