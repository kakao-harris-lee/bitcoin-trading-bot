"""
Redis Client 단위 테스트

테스트 커버리지:
- RedisClient 초기화
- Stream 생성/관리
- Consumer Group 생성
- 메시지 발행/소비
- 상태 저장/조회

Note: 실제 Redis 연결이 필요한 테스트는 @pytest.mark.integration 마커 사용
"""

import pytest
import asyncio
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import json
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trading.core.redis_client import RedisClient, setup_streams_and_groups
from trading.core.config import RedisConfig, Config


# ========== Fixtures ==========

@pytest.fixture
def redis_config():
    """테스트용 Redis 설정"""
    return RedisConfig(
        host="localhost",
        port=6379,
        username="",
        password="",
        db=15,  # 테스트용 DB
    )


@pytest.fixture
def redis_client(redis_config):
    """RedisClient 인스턴스"""
    return RedisClient(redis_config)


# ========== RedisClient Init Tests ==========

class TestRedisClientInit:
    """RedisClient 초기화 테스트"""

    def test_init_default_config(self):
        """기본 설정으로 초기화"""
        client = RedisClient()
        assert client.config is not None
        assert client._client is None
        assert client.is_connected is False

    def test_init_custom_config(self, redis_config):
        """커스텀 설정으로 초기화"""
        client = RedisClient(redis_config)
        assert client.config.host == "localhost"
        assert client.config.port == 6379
        assert client.config.db == 15


# ========== Connection Tests ==========

class TestRedisConnection:
    """Redis 연결 테스트"""

    @pytest.mark.asyncio
    async def test_connect_success(self, redis_client):
        """연결 성공"""
        with patch('redis.asyncio.Redis') as mock_redis:
            mock_instance = MagicMock()
            mock_instance.ping = AsyncMock(return_value=True)
            mock_redis.return_value = mock_instance

            result = await redis_client.connect()

            assert result is True
            assert redis_client.is_connected is True

    @pytest.mark.asyncio
    async def test_connect_failure(self, redis_client):
        """연결 실패"""
        with patch('redis.asyncio.Redis') as mock_redis:
            mock_redis.side_effect = ConnectionError("연결 실패")

            result = await redis_client.connect()

            assert result is False
            assert redis_client.is_connected is False

    @pytest.mark.asyncio
    async def test_disconnect(self, redis_client):
        """연결 종료"""
        mock_client = MagicMock()
        mock_client.close = AsyncMock()
        redis_client._client = mock_client
        redis_client._connected = True

        await redis_client.disconnect()

        assert redis_client.is_connected is False
        mock_client.close.assert_called_once()


# ========== Stream Operations Tests ==========

class TestStreamOperations:
    """Stream 연산 테스트"""

    @pytest.mark.asyncio
    async def test_create_stream_exists(self, redis_client):
        """이미 존재하는 Stream"""
        mock_client = MagicMock()
        mock_client.xinfo_stream = AsyncMock(return_value={"length": 100})
        redis_client._client = mock_client

        result = await redis_client.create_stream("test:stream")

        assert result is True
        mock_client.xinfo_stream.assert_called_once_with("test:stream")

    @pytest.mark.asyncio
    async def test_create_stream_new(self, redis_client):
        """새 Stream 생성"""
        from redis.exceptions import ResponseError

        mock_client = MagicMock()
        mock_client.xinfo_stream = AsyncMock(side_effect=ResponseError("no such key"))
        mock_client.xadd = AsyncMock(return_value="1702345678901-0")
        redis_client._client = mock_client

        result = await redis_client.create_stream("test:stream")

        assert result is True
        mock_client.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_create_consumer_group_success(self, redis_client):
        """Consumer Group 생성 성공"""
        mock_client = MagicMock()
        mock_client.xgroup_create = AsyncMock(return_value=True)
        redis_client._client = mock_client

        result = await redis_client.create_consumer_group(
            "test:stream", "test-group", "0"
        )

        assert result is True

    @pytest.mark.asyncio
    async def test_create_consumer_group_already_exists(self, redis_client):
        """이미 존재하는 Consumer Group"""
        from redis.exceptions import ResponseError

        mock_client = MagicMock()
        mock_client.xgroup_create = AsyncMock(
            side_effect=ResponseError("BUSYGROUP Consumer Group name already exists")
        )
        redis_client._client = mock_client

        result = await redis_client.create_consumer_group(
            "test:stream", "test-group", "0"
        )

        assert result is True  # 이미 존재해도 성공


# ========== Publish Tests ==========

class TestPublish:
    """메시지 발행 테스트"""

    @pytest.mark.asyncio
    async def test_publish_simple_data(self, redis_client):
        """단순 데이터 발행"""
        mock_client = MagicMock()
        mock_client.xadd = AsyncMock(return_value="1702345678901-0")
        redis_client._client = mock_client

        data = {"key": "value", "number": 123}
        result = await redis_client.publish("test:stream", data)

        assert result == "1702345678901-0"
        mock_client.xadd.assert_called_once()

    @pytest.mark.asyncio
    async def test_publish_nested_data(self, redis_client):
        """중첩 데이터 발행 (JSON 변환)"""
        mock_client = MagicMock()
        mock_client.xadd = AsyncMock(return_value="1702345678901-0")
        redis_client._client = mock_client

        data = {
            "simple": "value",
            "nested": {"inner": "data"},
            "list": [1, 2, 3],
        }
        await redis_client.publish("test:stream", data)

        # xadd 호출 인자 확인
        call_args = mock_client.xadd.call_args
        flat_data = call_args[0][1]

        assert flat_data["simple"] == "value"
        assert json.loads(flat_data["nested"]) == {"inner": "data"}
        assert json.loads(flat_data["list"]) == [1, 2, 3]


# ========== Consume Tests ==========

class TestConsume:
    """메시지 소비 테스트"""

    @pytest.mark.asyncio
    async def test_consume_messages(self, redis_client):
        """메시지 소비"""
        mock_client = MagicMock()
        mock_client.xreadgroup = AsyncMock(return_value=[
            ("test:stream", [
                ("1702345678901-0", {"key": "value", "number": "123"}),
                ("1702345678902-0", {"key": "value2"}),
            ])
        ])
        redis_client._client = mock_client

        messages = await redis_client.consume(
            "test:stream",
            "test-group",
            "consumer-1",
            count=10,
            block=1000,
        )

        assert len(messages) == 2
        assert messages[0]["id"] == "1702345678901-0"
        assert messages[0]["data"]["key"] == "value"

    @pytest.mark.asyncio
    async def test_consume_no_messages(self, redis_client):
        """메시지 없음"""
        mock_client = MagicMock()
        mock_client.xreadgroup = AsyncMock(return_value=None)
        redis_client._client = mock_client

        messages = await redis_client.consume(
            "test:stream",
            "test-group",
            "consumer-1",
        )

        assert messages == []

    @pytest.mark.asyncio
    async def test_consume_json_parsing(self, redis_client):
        """JSON 필드 파싱"""
        mock_client = MagicMock()
        mock_client.xreadgroup = AsyncMock(return_value=[
            ("test:stream", [
                ("1702345678901-0", {
                    "simple": "value",
                    "nested": '{"inner": "data"}',
                }),
            ])
        ])
        redis_client._client = mock_client

        messages = await redis_client.consume(
            "test:stream", "test-group", "consumer-1"
        )

        assert messages[0]["data"]["nested"] == {"inner": "data"}


# ========== ACK Tests ==========

class TestAck:
    """메시지 ACK 테스트"""

    @pytest.mark.asyncio
    async def test_ack_message(self, redis_client):
        """메시지 ACK"""
        mock_client = MagicMock()
        mock_client.xack = AsyncMock(return_value=1)
        redis_client._client = mock_client

        await redis_client.ack("test:stream", "test-group", "1702345678901-0")

        mock_client.xack.assert_called_once_with(
            "test:stream", "test-group", "1702345678901-0"
        )


# ========== State Operations Tests ==========

class TestStateOperations:
    """상태 저장/조회 테스트"""

    @pytest.mark.asyncio
    async def test_set_state(self, redis_client):
        """상태 저장"""
        mock_client = MagicMock()
        mock_client.hset = AsyncMock()
        mock_client.expire = AsyncMock()
        redis_client._client = mock_client

        data = {"key": "value", "nested": {"inner": "data"}}
        await redis_client.set_state("state:test", data, expire=3600)

        mock_client.hset.assert_called_once()
        mock_client.expire.assert_called_once_with("state:test", 3600)

    @pytest.mark.asyncio
    async def test_get_state(self, redis_client):
        """상태 조회"""
        mock_client = MagicMock()
        mock_client.hgetall = AsyncMock(return_value={
            "key": "value",
            "nested": '{"inner": "data"}',
        })
        redis_client._client = mock_client

        result = await redis_client.get_state("state:test")

        assert result["key"] == "value"
        assert result["nested"] == {"inner": "data"}

    @pytest.mark.asyncio
    async def test_delete_state(self, redis_client):
        """상태 삭제"""
        mock_client = MagicMock()
        mock_client.delete = AsyncMock(return_value=1)
        redis_client._client = mock_client

        await redis_client.delete_state("state:test")

        mock_client.delete.assert_called_once_with("state:test")


# ========== Integration Tests ==========

@pytest.mark.integration
class TestRedisIntegration:
    """실제 Redis 연결 통합 테스트"""

    @pytest.mark.asyncio
    @pytest.mark.skip(reason="실제 Redis 서버 필요")
    async def test_full_workflow(self):
        """전체 워크플로우 테스트"""
        config = RedisConfig(host="localhost", port=6379, db=15)
        client = RedisClient(config)

        try:
            # 연결
            assert await client.connect() is True

            # Stream 생성
            await client.create_stream("test:integration")

            # Consumer Group 생성
            await client.create_consumer_group(
                "test:integration", "test-group"
            )

            # 메시지 발행
            msg_id = await client.publish(
                "test:integration",
                {"test": "data", "timestamp": 12345}
            )
            assert msg_id is not None

            # 메시지 소비
            messages = await client.consume(
                "test:integration",
                "test-group",
                "test-consumer",
                count=1,
                block=1000,
            )
            assert len(messages) == 1

            # ACK
            await client.ack(
                "test:integration",
                "test-group",
                messages[0]["id"]
            )

        finally:
            await client.disconnect()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
