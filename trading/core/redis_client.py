"""
Trading Engine V2 - Redis Client
Redis Streams 연결 및 관리
"""

import asyncio
import json
import logging
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime

import redis.asyncio as redis
from redis.asyncio import Redis
from redis.exceptions import ResponseError

from .config import Config, RedisConfig

logger = logging.getLogger(__name__)


class RedisClient:
    """Redis Streams 클라이언트"""

    def __init__(self, config: Optional[RedisConfig] = None):
        """
        Args:
            config: Redis 설정 (없으면 기본값 사용)
        """
        self.config = config or RedisConfig()
        self._client: Optional[Redis] = None
        self._pubsub = None
        self._connected = False

    async def connect(self) -> bool:
        """Redis 연결"""
        try:
            self._client = redis.Redis(
                host=self.config.host,
                port=self.config.port,
                username=self.config.username,
                password=self.config.password,
                db=self.config.db,
                decode_responses=True,
            )

            # 연결 테스트
            await self._client.ping()
            self._connected = True
            logger.info(f"✅ Redis 연결 성공: {self.config.host}:{self.config.port}")
            return True

        except Exception as e:
            logger.error(f"❌ Redis 연결 실패: {e}")
            self._connected = False
            return False

    async def disconnect(self):
        """연결 종료"""
        if self._client:
            await self._client.close()
            self._connected = False
            logger.info("Redis 연결 종료")

    @property
    def is_connected(self) -> bool:
        return self._connected

    # ========== Stream Operations ==========

    async def create_stream(self, stream_name: str) -> bool:
        """
        Stream 생성 (존재하지 않으면)

        Args:
            stream_name: 스트림 이름
        """
        try:
            # XINFO로 존재 여부 확인
            await self._client.xinfo_stream(stream_name)
            logger.debug(f"Stream already exists: {stream_name}")
            return True
        except ResponseError:
            # 존재하지 않으면 초기 메시지로 생성
            await self._client.xadd(
                stream_name,
                {"event": "stream_created", "timestamp": datetime.now().isoformat()},
                maxlen=1000,
            )
            logger.info(f"✅ Stream 생성: {stream_name}")
            return True

    async def create_consumer_group(
        self,
        stream_name: str,
        group_name: str,
        start_id: str = "0"
    ) -> bool:
        """
        Consumer Group 생성

        Args:
            stream_name: 스트림 이름
            group_name: 그룹 이름
            start_id: 시작 ID ("0" = 처음부터, "$" = 새 메시지부터)
        """
        try:
            await self._client.xgroup_create(
                stream_name,
                group_name,
                id=start_id,
                mkstream=True
            )
            logger.info(f"✅ Consumer Group 생성: {stream_name} -> {group_name}")
            return True
        except ResponseError as e:
            if "BUSYGROUP" in str(e):
                logger.debug(f"Consumer Group already exists: {group_name}")
                return True
            logger.error(f"Consumer Group 생성 실패: {e}")
            return False

    async def publish(
        self,
        stream_name: str,
        data: Dict[str, Any],
        maxlen: int = 10000
    ) -> str:
        """
        Stream에 메시지 발행

        Args:
            stream_name: 스트림 이름
            data: 메시지 데이터
            maxlen: 최대 메시지 수 (오래된 메시지 자동 삭제)

        Returns:
            메시지 ID
        """
        # 중첩 객체는 JSON 문자열로 변환
        flat_data = {}
        for key, value in data.items():
            if isinstance(value, (dict, list)):
                flat_data[key] = json.dumps(value, ensure_ascii=False)
            else:
                flat_data[key] = str(value)

        message_id = await self._client.xadd(
            stream_name,
            flat_data,
            maxlen=maxlen,
            approximate=True
        )
        logger.debug(f"Published to {stream_name}: {message_id}")
        return message_id

    async def consume(
        self,
        stream_name: str,
        group_name: str,
        consumer_name: str,
        count: int = 10,
        block: int = 1000,
    ) -> List[Dict]:
        """
        Consumer Group으로 메시지 소비

        Args:
            stream_name: 스트림 이름
            group_name: 그룹 이름
            consumer_name: 소비자 이름
            count: 한 번에 가져올 메시지 수
            block: 블로킹 시간 (ms), 0이면 즉시 반환

        Returns:
            메시지 리스트 [{"id": "...", "data": {...}}, ...]
        """
        try:
            response = await self._client.xreadgroup(
                groupname=group_name,
                consumername=consumer_name,
                streams={stream_name: ">"},  # ">" = 새 메시지만
                count=count,
                block=block,
            )

            messages = []
            if response:
                for stream, stream_messages in response:
                    for msg_id, msg_data in stream_messages:
                        # JSON 문자열 파싱
                        parsed_data = {}
                        for key, value in msg_data.items():
                            try:
                                parsed_data[key] = json.loads(value)
                            except (json.JSONDecodeError, TypeError):
                                parsed_data[key] = value

                        messages.append({
                            "id": msg_id,
                            "stream": stream,
                            "data": parsed_data
                        })

            return messages

        except Exception as e:
            logger.error(f"Consume error: {e}")
            return []

    async def ack(self, stream_name: str, group_name: str, message_id: str):
        """
        메시지 처리 완료 확인 (ACK)

        Args:
            stream_name: 스트림 이름
            group_name: 그룹 이름
            message_id: 메시지 ID
        """
        await self._client.xack(stream_name, group_name, message_id)

    async def get_stream_info(self, stream_name: str) -> Dict:
        """Stream 정보 조회"""
        try:
            info = await self._client.xinfo_stream(stream_name)
            return info
        except ResponseError:
            return {}

    async def get_pending_messages(
        self,
        stream_name: str,
        group_name: str
    ) -> List[Dict]:
        """미처리 메시지 조회"""
        try:
            pending = await self._client.xpending(stream_name, group_name)
            return pending
        except Exception as e:
            logger.error(f"Pending 조회 실패: {e}")
            return []

    # ========== Key-Value Operations (상태 저장용) ==========

    async def set_state(self, key: str, data: Dict, expire: int = None):
        """상태 저장 (Hash)"""
        flat_data = {}
        for k, v in data.items():
            if isinstance(v, (dict, list)):
                flat_data[k] = json.dumps(v, ensure_ascii=False)
            else:
                flat_data[k] = str(v)

        await self._client.hset(key, mapping=flat_data)
        if expire:
            await self._client.expire(key, expire)

    async def get_state(self, key: str) -> Dict:
        """상태 조회"""
        data = await self._client.hgetall(key)
        parsed = {}
        for k, v in data.items():
            try:
                parsed[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                parsed[k] = v
        return parsed

    async def delete_state(self, key: str):
        """상태 삭제"""
        await self._client.delete(key)


async def setup_streams_and_groups(config: Optional[Config] = None) -> bool:
    """
    모든 Stream과 Consumer Group 초기 설정

    Args:
        config: 전체 설정

    Returns:
        성공 여부
    """
    config = config or Config()
    client = RedisClient(config.redis)

    if not await client.connect():
        return False

    try:
        print("\n" + "=" * 60)
        print("  Redis Streams & Consumer Groups 설정")
        print("=" * 60 + "\n")

        # 1. Streams 생성
        print("📊 Streams 생성:")
        for name, stream_key in config.redis.streams.items():
            await client.create_stream(stream_key)
            print(f"   ✅ {stream_key}")

        print()

        # 2. Consumer Groups 생성
        print("👥 Consumer Groups 생성:")
        for stream_name, groups in config.redis.consumer_groups.items():
            for group_name in groups:
                await client.create_consumer_group(stream_name, group_name, start_id="$")
                print(f"   ✅ {stream_name} -> {group_name}")

        print("\n" + "=" * 60)
        print("  설정 완료!")
        print("=" * 60 + "\n")

        return True

    finally:
        await client.disconnect()


# 테스트 및 초기화 스크립트
if __name__ == "__main__":
    asyncio.run(setup_streams_and_groups())
