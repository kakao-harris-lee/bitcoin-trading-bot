#!/usr/bin/env python3
"""
Trading Engine V2 - Redis Setup Script
Redis Streams 및 Consumer Groups 초기 설정
"""

import asyncio
import sys
import os

# 프로젝트 루트 추가
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from trading_engine_v2.core.config import Config
from trading_engine_v2.core.redis_client import RedisClient


async def verify_connection(client: RedisClient) -> bool:
    """Redis 연결 확인 및 기본 정보 출력"""
    try:
        info = await client._client.info("server")
        print(f"\n📍 Redis Server Info:")
        print(f"   Version: {info.get('redis_version', 'N/A')}")
        print(f"   OS: {info.get('os', 'N/A')}")
        print(f"   Uptime: {info.get('uptime_in_days', 0)} days")
        return True
    except Exception as e:
        print(f"❌ 연결 정보 조회 실패: {e}")
        return False


async def create_streams(client: RedisClient, config: Config) -> int:
    """모든 Stream 생성"""
    created = 0
    print(f"\n📊 Streams 생성:")

    for name, stream_key in config.redis.streams.items():
        try:
            await client.create_stream(stream_key)
            print(f"   ✅ {stream_key:<25} ({name})")
            created += 1
        except Exception as e:
            print(f"   ❌ {stream_key:<25} - 오류: {e}")

    return created


async def create_consumer_groups(client: RedisClient, config: Config) -> int:
    """모든 Consumer Group 생성"""
    created = 0
    print(f"\n👥 Consumer Groups 생성:")

    for stream_name, groups in config.redis.consumer_groups.items():
        print(f"\n   📌 {stream_name}:")
        for group_name in groups:
            try:
                success = await client.create_consumer_group(
                    stream_name,
                    group_name,
                    start_id="$"  # 새 메시지부터 소비
                )
                if success:
                    print(f"      ✅ {group_name}")
                    created += 1
            except Exception as e:
                print(f"      ❌ {group_name} - 오류: {e}")

    return created


async def verify_streams(client: RedisClient, config: Config):
    """생성된 Stream 확인"""
    print(f"\n🔍 Stream 상태 확인:")

    for name, stream_key in config.redis.streams.items():
        try:
            info = await client.get_stream_info(stream_key)
            if info:
                length = info.get("length", 0)
                groups = info.get("groups", 0)
                print(f"   ✅ {stream_key:<25} - 메시지: {length}, 그룹: {groups}")
            else:
                print(f"   ⚠️  {stream_key:<25} - 정보 없음")
        except Exception as e:
            print(f"   ❌ {stream_key:<25} - 오류: {e}")


async def test_publish_consume(client: RedisClient, config: Config):
    """Publish/Consume 테스트"""
    print(f"\n🧪 Publish/Consume 테스트:")

    test_stream = config.redis.streams["events"]
    test_group = "all-modules"
    test_consumer = "test-consumer"

    # Publish
    test_data = {
        "event": "test",
        "message": "Hello from setup script!",
        "timestamp": "2025-12-12T00:00:00"
    }

    msg_id = await client.publish(test_stream, test_data)
    print(f"   📤 Published: {msg_id}")

    # Consume (방금 발행한 메시지는 $ 이후이므로 바로 소비 가능)
    # 새로 발행된 메시지 확인을 위해 잠시 대기
    await asyncio.sleep(0.1)

    messages = await client.consume(
        test_stream,
        test_group,
        test_consumer,
        count=1,
        block=100
    )

    if messages:
        print(f"   📥 Consumed: {messages[0]['id']}")
        await client.ack(test_stream, test_group, messages[0]['id'])
        print(f"   ✅ ACK 완료")
    else:
        print(f"   ⚠️  소비할 메시지 없음 (정상 - 새 메시지 대기 중)")

    print(f"\n   ✅ Publish/Consume 테스트 완료")


async def main():
    """메인 설정 함수"""
    print("\n" + "=" * 70)
    print("  Trading Engine V2 - Redis Setup")
    print("=" * 70)

    # 설정 로드
    config = Config.from_env()

    print(f"\n📡 Redis 연결 정보:")
    print(f"   Host: {config.redis.host}")
    print(f"   Port: {config.redis.port}")
    print(f"   Username: {config.redis.username}")

    # Redis 연결
    client = RedisClient(config.redis)

    if not await client.connect():
        print("\n❌ Redis 연결 실패! 설정을 확인하세요.")
        return False

    try:
        # 1. 연결 확인
        await verify_connection(client)

        # 2. Streams 생성
        streams_created = await create_streams(client, config)

        # 3. Consumer Groups 생성
        groups_created = await create_consumer_groups(client, config)

        # 4. 생성 결과 확인
        await verify_streams(client, config)

        # 5. Publish/Consume 테스트
        await test_publish_consume(client, config)

        # 결과 요약
        print("\n" + "=" * 70)
        print("  설정 완료!")
        print("=" * 70)
        print(f"\n   📊 생성된 Streams: {streams_created}")
        print(f"   👥 생성된 Consumer Groups: {groups_created}")
        print(f"\n   ✅ Redis 인프라 준비 완료!\n")

        return True

    finally:
        await client.disconnect()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
