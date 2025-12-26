#!/usr/bin/env python3
"""
Trading Engine V2 - Redis Setup Script (Server Version)
서버에서 localhost로 Redis 연결
"""

import asyncio
import sys
import os

# Redis 연결 설정 (서버 내부용)
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "@1tidh6ls6ls")

# Streams 정의
STREAMS = {
    "prices": "market:prices",
    "orderbook": "market:orderbook",
    "signals": "strategy:signals",
    "pending_orders": "orders:pending",
    "executed_orders": "orders:executed",
    "positions": "positions:updates",
    "events": "system:events",
}

# Consumer Groups 정의
CONSUMER_GROUPS = {
    "market:prices": [
        "strategy-v35",
        "strategy-short-v1",
        "risk-manager",
        "position-manager",
        "dashboard",
    ],
    "market:orderbook": [
        "execution-manager",
    ],
    "strategy:signals": [
        "risk-manager",
    ],
    "orders:pending": [
        "executor-upbit",
        "executor-binance",
    ],
    "orders:executed": [
        "position-manager",
        "notifier",
    ],
    "positions:updates": [
        "risk-manager",
        "dashboard",
        "notifier",
    ],
    "system:events": [
        "all-modules",
    ],
}


async def main():
    import redis.asyncio as redis
    from redis.exceptions import ResponseError

    print("\n" + "=" * 70)
    print("  Trading Engine V2 - Redis Setup (Server)")
    print("=" * 70)

    print(f"\n📡 Redis 연결 정보:")
    print(f"   Host: {REDIS_HOST}")
    print(f"   Port: {REDIS_PORT}")

    # Redis 연결
    try:
        client = redis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            password=REDIS_PASSWORD,
            decode_responses=True,
        )
        await client.ping()
        print(f"   ✅ 연결 성공!")
    except Exception as e:
        print(f"   ❌ 연결 실패: {e}")
        return False

    try:
        # 서버 정보
        info = await client.info("server")
        print(f"\n📍 Redis Server Info:")
        print(f"   Version: {info.get('redis_version', 'N/A')}")
        print(f"   Uptime: {info.get('uptime_in_days', 0)} days")

        # Streams 생성
        print(f"\n📊 Streams 생성:")
        streams_created = 0
        for name, stream_key in STREAMS.items():
            try:
                # 존재 여부 확인
                try:
                    await client.xinfo_stream(stream_key)
                    print(f"   ⏭️  {stream_key:<25} (이미 존재)")
                except ResponseError:
                    # 생성
                    await client.xadd(stream_key, {"event": "stream_created"}, maxlen=10000)
                    print(f"   ✅ {stream_key:<25} (생성됨)")
                streams_created += 1
            except Exception as e:
                print(f"   ❌ {stream_key:<25} - 오류: {e}")

        # Consumer Groups 생성
        print(f"\n👥 Consumer Groups 생성:")
        groups_created = 0
        for stream_name, groups in CONSUMER_GROUPS.items():
            print(f"\n   📌 {stream_name}:")
            for group_name in groups:
                try:
                    await client.xgroup_create(
                        stream_name,
                        group_name,
                        id="$",  # 새 메시지부터
                        mkstream=True
                    )
                    print(f"      ✅ {group_name}")
                    groups_created += 1
                except ResponseError as e:
                    if "BUSYGROUP" in str(e):
                        print(f"      ⏭️  {group_name} (이미 존재)")
                        groups_created += 1
                    else:
                        print(f"      ❌ {group_name} - {e}")

        # 테스트 메시지
        print(f"\n🧪 테스트 메시지 발행:")
        test_id = await client.xadd("system:events", {
            "event": "setup_complete",
            "message": "Trading Engine V2 Redis 설정 완료",
            "timestamp": str(asyncio.get_event_loop().time())
        })
        print(f"   ✅ 발행됨: {test_id}")

        # 결과 요약
        print("\n" + "=" * 70)
        print("  설정 완료!")
        print("=" * 70)
        print(f"\n   📊 Streams: {streams_created}")
        print(f"   👥 Consumer Groups: {groups_created}")
        print(f"\n   ✅ Redis 인프라 준비 완료!\n")

        return True

    finally:
        await client.close()


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
