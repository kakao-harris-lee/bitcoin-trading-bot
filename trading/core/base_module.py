"""
Trading Engine V2 - Base Module
모든 모듈의 기본 클래스
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List
from datetime import datetime

from .config import Config
from .redis_client import RedisClient
from core.types import SystemEvent, EventType, current_timestamp

logger = logging.getLogger(__name__)


class BaseModule(ABC):
    """
    모든 트레이딩 모듈의 기본 클래스

    각 모듈은 이 클래스를 상속받아 구현:
    - Feed Handler
    - Strategy Engine
    - Risk Manager
    - Position Manager
    - Execution Manager
    - Notifier
    """

    def __init__(
        self,
        module_name: str,
        config: Optional[Config] = None,
        redis_client: Optional[RedisClient] = None
    ):
        """
        Args:
            module_name: 모듈 이름 (예: "feed-handler", "strategy-short")
            config: 설정 객체
            redis_client: Redis 클라이언트 (공유 가능)
        """
        self.module_name = module_name
        self.config = config or Config.from_env()
        self._redis = redis_client
        self._own_redis = redis_client is None  # 자체 생성 여부

        self._running = False
        self._started_at: Optional[datetime] = None
        self._message_count = 0

        # 로깅 설정
        self.logger = logging.getLogger(f"trading.{module_name}")

    @property
    def redis(self) -> RedisClient:
        """Redis 클라이언트 반환"""
        if self._redis is None:
            self._redis = RedisClient(self.config.redis)
        return self._redis

    async def start(self) -> "BaseModule":
        """
        모듈 시작

        Returns:
            self (체이닝용)
        """
        self.logger.info(f"🚀 {self.module_name} 시작 중...")

        # Redis 연결 (자체 생성인 경우)
        if self._own_redis:
            if not await self.redis.connect():
                raise ConnectionError(f"{self.module_name}: Redis 연결 실패")

        # 모듈별 초기화
        await self.on_start()

        self._running = True
        self._started_at = datetime.now()

        # 시작 이벤트 발행
        await self._publish_event(EventType.STARTUP, f"{self.module_name} 시작됨")

        self.logger.info(f"✅ {self.module_name} 시작 완료")
        return self

    async def stop(self):
        """모듈 정지"""
        self.logger.info(f"🛑 {self.module_name} 정지 중...")

        self._running = False

        # 모듈별 정리
        await self.on_stop()

        # 종료 이벤트 발행
        await self._publish_event(EventType.SHUTDOWN, f"{self.module_name} 정지됨")

        # Redis 연결 종료 (자체 생성인 경우)
        if self._own_redis and self._redis:
            await self._redis.disconnect()

        self.logger.info(f"⬛ {self.module_name} 정지 완료")

    async def run_forever(self):
        """
        무한 루프 실행
        각 모듈은 이 메서드를 통해 지속적으로 실행
        """
        try:
            while self._running:
                await self.run_cycle()
        except asyncio.CancelledError:
            self.logger.info(f"{self.module_name} 취소됨")
        except Exception as e:
            self.logger.error(f"{self.module_name} 오류: {e}")
            await self._publish_event(EventType.ERROR, str(e))
            raise

    # ========== 추상 메서드 (서브클래스에서 구현) ==========

    @abstractmethod
    async def on_start(self):
        """모듈 시작 시 초기화 (서브클래스 구현)"""
        pass

    @abstractmethod
    async def on_stop(self):
        """모듈 정지 시 정리 (서브클래스 구현)"""
        pass

    @abstractmethod
    async def run_cycle(self):
        """
        메인 실행 사이클 (서브클래스 구현)

        예시:
        - Feed Handler: 가격 데이터 수집 및 발행
        - Strategy: 신호 생성
        - Risk Manager: 신호 검증
        """
        pass

    # ========== 헬퍼 메서드 ==========

    async def publish(self, stream_name: str, data: Dict[str, Any]) -> str:
        """
        메시지 발행 (래퍼)

        Args:
            stream_name: 스트림 이름
            data: 메시지 데이터

        Returns:
            메시지 ID
        """
        self._message_count += 1
        return await self.redis.publish(stream_name, data)

    async def consume(
        self,
        stream_name: str,
        group_name: str,
        count: int = 10,
        block: int = 1000,
    ) -> List[Dict]:
        """
        메시지 소비 (래퍼)

        Args:
            stream_name: 스트림 이름
            group_name: Consumer Group 이름
            count: 가져올 메시지 수
            block: 블로킹 시간 (ms)

        Returns:
            메시지 리스트
        """
        return await self.redis.consume(
            stream_name,
            group_name,
            consumer_name=self.module_name,
            count=count,
            block=block,
        )

    async def ack(self, stream_name: str, group_name: str, message_id: str):
        """메시지 ACK (래퍼)"""
        await self.redis.ack(stream_name, group_name, message_id)

    async def _publish_event(self, event_type: EventType, message: str, data: Dict = None):
        """시스템 이벤트 발행"""
        event = SystemEvent(
            timestamp=current_timestamp(),
            event_type=event_type,
            module=self.module_name,
            message=message,
            data=data,
        )
        await self.publish(
            self.config.redis.streams["events"],
            event.to_dict()
        )

    def get_stats(self) -> Dict[str, Any]:
        """모듈 통계 반환"""
        uptime = None
        if self._started_at:
            uptime = (datetime.now() - self._started_at).total_seconds()

        return {
            "module": self.module_name,
            "running": self._running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "uptime_seconds": uptime,
            "message_count": self._message_count,
        }
