# trading/streams/redis_streams.py
"""Redis Streams wrapper for async publish/consume."""
from __future__ import annotations

import json
import os
import redis.asyncio as redis
from datetime import datetime
from typing import Any


class RedisStreams:
    """Async Redis Streams client.

    Provides a simple interface for:
    - Publishing messages to streams
    - Consuming messages via consumer groups
    - Hash operations for state storage

    Usage:
        streams = RedisStreams(url="redis://localhost:6379")
        await streams.connect()

        # Publish
        msg_id = await streams.publish("prices", {"symbol": "BTC", "price": "43000"})

        # Consume
        await streams.create_consumer_group("prices", "strategy-group")
        messages = await streams.consume("prices", "strategy-group", "consumer-1")

        await streams.disconnect()
    """

    def __init__(self, url: str = "redis://localhost:6379"):
        """Initialize RedisStreams client.

        Args:
            url: Redis connection URL (e.g., redis://localhost:6379/0)
        """
        self.url = url
        self._client: redis.Redis | None = None
        self._state_event_maxlen = int(os.getenv("REDIS_STATE_EVENT_MAXLEN", "50000"))
        self._regime_snapshot_maxlen = int(os.getenv("REDIS_REGIME_SNAPSHOT_MAXLEN", "200000"))
        self._regime_snapshot_ttl_sec = int(os.getenv("REGIME_SNAPSHOT_TTL_SEC", "172800"))
        self._selector_snapshot_ttl_sec = int(os.getenv("SELECTOR_SNAPSHOT_TTL_SEC", "1209600"))
        self._default_stream_maxlen = self._load_default_stream_maxlen()

    @staticmethod
    def _load_default_stream_maxlen() -> dict[str, int]:
        defaults = {
            "alerts": 20000,
            "orders": 10000,
            "trades": 20000,
            "exit_signals": 10000,
            "market:prices": 50000,
            "strategy:decisions": 10000,
            "strategy:selector:events": 5000,
            "strategy:entry:funnel": 10000,
            "observability:system:state": 2000,
            # Legacy streams that can otherwise accumulate for months.
            "system:universe": 5000,
            "system:universe_updates": 2000,
            "market:quotes": 50000,
            "market:ticks": 100000,
            "signals:detected": 10000,
        }
        loaded: dict[str, int] = {}
        for stream, default in defaults.items():
            env_key = f"REDIS_STREAM_MAXLEN_{stream.upper().replace(':', '_')}"
            try:
                loaded[stream] = int(os.getenv(env_key, str(default)))
            except ValueError:
                loaded[stream] = default
        return loaded

    def _resolve_stream_maxlen(self, stream: str, maxlen: int | None = None) -> int | None:
        if maxlen is not None:
            return maxlen
        return self._default_stream_maxlen.get(stream)

    @staticmethod
    def _stringify_mapping(mapping: dict[str, Any]) -> dict[str, str]:
        flat: dict[str, str] = {}
        for key, value in mapping.items():
            if isinstance(value, (dict, list)):
                flat[str(key)] = json.dumps(value, ensure_ascii=False)
            else:
                flat[str(key)] = str(value)
        return flat

    async def _safe_publish_state_event(
        self,
        stream: str,
        event: dict[str, Any],
        maxlen: int | None = None,
    ) -> None:
        try:
            await self.publish_event(
                stream,
                self._stringify_mapping(event),
                maxlen=maxlen if maxlen is not None else self._state_event_maxlen,
            )
        except Exception:
            # Never fail critical state writes because event mirror failed.
            return

    async def connect(self) -> None:
        """Connect to Redis."""
        connect_timeout = float(os.getenv("REDIS_CONNECT_TIMEOUT_SEC", "3"))
        socket_timeout = float(os.getenv("REDIS_SOCKET_TIMEOUT_SEC", "3"))
        self._client = redis.from_url(
            self.url,
            decode_responses=True,
            socket_connect_timeout=connect_timeout,
            socket_timeout=socket_timeout,
        )
        try:
            await self._client.ping()
        except Exception as exc:
            await self.disconnect()
            raise RuntimeError(f"Failed to connect to Redis ({self.url}): {exc}") from exc

    async def disconnect(self) -> None:
        """Disconnect from Redis."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def create_consumer_group(
        self, stream: str, group: str, start_id: str = "0"
    ) -> None:
        """Create consumer group, ignore if exists.

        Args:
            stream: Stream name
            group: Consumer group name
            start_id: Start reading from this ID ("0" = beginning, "$" = new only)
        """
        try:
            await self._client.xgroup_create(stream, group, id=start_id, mkstream=True)
        except redis.ResponseError as e:
            if "BUSYGROUP" not in str(e):
                raise

    async def reclaim_and_ack_stale_messages(
        self,
        stream: str,
        group: str,
        consumer: str,
        min_idle_ms: int = 30_000,
        count: int = 200,
        max_passes: int = 20,
    ) -> int:
        """Reclaim stale pending messages and ack them.

        This is intended for ephemeral streams such as market data where old
        pending entries should not block group health after restarts.

        Args:
            stream: Stream name.
            group: Consumer group name.
            consumer: Active consumer that reclaims stale entries.
            min_idle_ms: Minimum idle time before reclaiming.
            count: Maximum entries per reclaim pass.
            max_passes: Maximum reclaim passes to avoid long startup stalls.

        Returns:
            Number of reclaimed+acked messages.
        """
        reclaimed = 0
        start_id = "0-0"

        for _ in range(max_passes):
            try:
                result = await self._client.xautoclaim(
                    stream,
                    group,
                    consumer,
                    min_idle_ms,
                    start_id=start_id,
                    count=count,
                )
            except redis.ResponseError as e:
                if "NOGROUP" in str(e):
                    return reclaimed
                raise

            if not result:
                break

            next_start = result[0] if len(result) > 0 else start_id
            claimed_raw = result[1] if len(result) > 1 else []
            claimed_ids: list[str] = []

            for item in claimed_raw:
                if isinstance(item, (tuple, list)) and item:
                    claimed_ids.append(item[0])
                elif isinstance(item, str):
                    claimed_ids.append(item)

            if claimed_ids:
                await self._client.xack(stream, group, *claimed_ids)
                reclaimed += len(claimed_ids)

            if len(claimed_ids) < count or next_start == start_id:
                break
            start_id = next_start

        return reclaimed

    async def prune_idle_consumers(
        self,
        stream: str,
        group: str,
        active_consumers: set[str] | None = None,
        min_idle_ms: int = 300_000,
    ) -> int:
        """Remove stale idle consumers from a group.

        Args:
            stream: Stream name.
            group: Consumer group name.
            active_consumers: Consumers to keep even if idle.
            min_idle_ms: Minimum idle time before deletion.

        Returns:
            Number of consumers removed.
        """
        keep = active_consumers or set()
        removed = 0

        try:
            consumers = await self._client.xinfo_consumers(stream, group)
        except redis.ResponseError as e:
            if "NOGROUP" in str(e):
                return 0
            raise

        for info in consumers:
            name = info.get("name")
            if isinstance(name, bytes):
                name = name.decode("utf-8", errors="ignore")
            if not name or name in keep:
                continue

            idle_ms = int(info.get("idle", 0))
            if idle_ms < min_idle_ms:
                continue

            await self._client.xgroup_delconsumer(stream, group, name)
            removed += 1

        return removed

    async def ensure_ephemeral_consumer_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        reclaim_idle_ms: int = 30_000,
        prune_idle_ms: int = 300_000,
    ) -> dict[str, int]:
        """Create + clean an ephemeral group used for realtime feeds."""
        await self.create_consumer_group(stream, group, start_id="$")
        reclaimed = await self.reclaim_and_ack_stale_messages(
            stream=stream,
            group=group,
            consumer=consumer,
            min_idle_ms=reclaim_idle_ms,
        )
        pruned = await self.prune_idle_consumers(
            stream=stream,
            group=group,
            active_consumers={consumer},
            min_idle_ms=prune_idle_ms,
        )
        return {"reclaimed": reclaimed, "pruned_consumers": pruned}

    async def publish(
        self,
        stream: str,
        data: dict[str, Any],
        maxlen: int | None = None,
    ) -> str:
        """Publish message to stream.

        Args:
            stream: Stream name
            data: Message data (flat dict with string values)

        Args:
            maxlen: Optional stream max length for auto-trimming.

        Returns:
            Message ID assigned by Redis
        """
        resolved_maxlen = self._resolve_stream_maxlen(stream, maxlen=maxlen)
        if resolved_maxlen is not None:
            return await self._client.xadd(stream, data, maxlen=resolved_maxlen)
        return await self._client.xadd(stream, data)

    async def publish_event(
        self, stream: str, data: dict[str, str], maxlen: int | None = None
    ) -> str:
        """Publish event to stream with optional auto-trimming.

        Args:
            stream: Stream name
            data: Event data (flat dict with string values)
            maxlen: Maximum stream length for auto-trimming (None = no limit)

        Returns:
            Message ID assigned by Redis
        """
        resolved_maxlen = self._resolve_stream_maxlen(stream, maxlen=maxlen)
        return await self._client.xadd(stream, data, maxlen=resolved_maxlen)

    async def read_latest(self, stream: str, count: int = 100) -> list[dict[str, Any]]:
        """Read latest stream entries in reverse-chronological order."""
        entries = await self._client.xrevrange(stream, count=count)
        messages: list[dict[str, Any]] = []
        for msg_id, payload in entries:
            item = dict(payload)
            item["_id"] = msg_id
            messages.append(item)
        return messages

    async def consume(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 1000,
    ) -> list[dict[str, Any]]:
        """Consume messages from stream via consumer group.

        Args:
            stream: Stream name
            group: Consumer group name
            consumer: Consumer name (unique within group)
            count: Maximum messages to return
            block_ms: Block timeout in milliseconds (0 = no block)

        Returns:
            List of message dicts with _id field added
        """
        result = await self._client.xreadgroup(
            groupname=group,
            consumername=consumer,
            streams={stream: ">"},
            count=count,
            block=block_ms,
        )

        if not result:
            return []

        messages = []
        for _stream_name, stream_messages in result:
            for msg_id, msg_data in stream_messages:
                msg_data["_id"] = msg_id
                messages.append(msg_data)

        return messages

    async def ack(self, stream: str, group: str, msg_id: str) -> None:
        """Acknowledge message processing.

        Args:
            stream: Stream name
            group: Consumer group name
            msg_id: Message ID to acknowledge
        """
        await self._client.xack(stream, group, msg_id)

    async def hset(self, key: str, mapping: dict[str, Any]) -> None:
        """Set hash fields.

        Args:
            key: Hash key
            mapping: Field-value pairs to set
        """
        await self._client.hset(key, mapping=mapping)

    async def set_account(self, key: str, data: dict[str, Any]) -> None:
        """Set account hash and mirror change as stream event."""
        payload = self._stringify_mapping(data)
        await self._client.hset(key, mapping=payload)
        await self._safe_publish_state_event(
            "account:events",
            {
                "event": "account_update",
                "key": key,
                "timestamp": datetime.now().isoformat(),
                "timestamp_ms": int(datetime.now().timestamp() * 1000),
                "fields": json.dumps(payload, ensure_ascii=False),
            },
        )

    async def hgetall(self, key: str) -> dict[str, str]:
        """Get all hash fields.

        Args:
            key: Hash key

        Returns:
            Dict of field-value pairs
        """
        return await self._client.hgetall(key)

    async def hexists(self, key: str, field: str) -> bool:
        """Check if hash field exists.

        Args:
            key: Hash key
            field: Field name

        Returns:
            True if field exists
        """
        return await self._client.hexists(key, field)

    # Position helpers
    async def set_position(self, symbol: str, market: str, data: dict[str, Any]) -> None:
        """Set position data.

        Args:
            symbol: Trading symbol (e.g., "BTC")
            market: Market type (spot-only runtime uses "spot")
            data: Position data (flat dict with string values)
        """
        key = f"positions:{symbol}:{market}"
        payload = self._stringify_mapping(data)
        await self._client.hset(key, mapping=payload)
        await self._safe_publish_state_event(
            "positions:events",
            {
                "event": "position_upsert",
                "key": key,
                "symbol": symbol,
                "market": market,
                "timestamp": datetime.now().isoformat(),
                "timestamp_ms": int(datetime.now().timestamp() * 1000),
                "fields": json.dumps(payload, ensure_ascii=False),
            },
        )

    async def patch_position(self, symbol: str, market: str, data: dict[str, Any]) -> None:
        """Patch existing position hash fields and mirror as a state event."""
        key = f"positions:{symbol}:{market}"
        payload = self._stringify_mapping(data)
        await self._client.hset(key, mapping=payload)
        await self._safe_publish_state_event(
            "positions:events",
            {
                "event": "position_patch",
                "key": key,
                "symbol": symbol,
                "market": market,
                "timestamp": datetime.now().isoformat(),
                "timestamp_ms": int(datetime.now().timestamp() * 1000),
                "fields": json.dumps(payload, ensure_ascii=False),
            },
        )

    async def get_position(self, symbol: str, market: str) -> dict[str, str]:
        """Get position data.

        Args:
            symbol: Trading symbol (e.g., "BTC")
            market: Market type (spot-only runtime uses "spot")

        Returns:
            Dict of position data including symbol and market
        """
        key = f"positions:{symbol}:{market}"
        data = await self._client.hgetall(key)
        if data:
            # Include symbol and market in returned data for convenience
            data["symbol"] = symbol
            data["market"] = market
        return data

    async def has_position(self, symbol: str, market: str) -> bool:
        """Check if position exists.

        Args:
            symbol: Trading symbol (e.g., "BTC")
            market: Market type (spot-only runtime uses "spot")

        Returns:
            True if position exists
        """
        key = f"positions:{symbol}:{market}"
        return await self._client.exists(key) > 0

    async def clear_position(self, symbol: str, market: str) -> None:
        """Clear position.

        Args:
            symbol: Trading symbol (e.g., "BTC")
            market: Market type (spot-only runtime uses "spot")
        """
        key = f"positions:{symbol}:{market}"
        await self._client.delete(key)
        await self._safe_publish_state_event(
            "positions:events",
            {
                "event": "position_clear",
                "key": key,
                "symbol": symbol,
                "market": market,
                "timestamp": datetime.now().isoformat(),
                "timestamp_ms": int(datetime.now().timestamp() * 1000),
            },
        )

    # Risk helpers
    async def set_risk(self, data: dict[str, Any]) -> None:
        """Set risk data.

        Args:
            data: Risk data (flat dict with string values)
        """
        payload = self._stringify_mapping(data)
        await self._client.hset("risk", mapping=payload)
        await self._safe_publish_state_event(
            "risk:events",
            {
                "event": "risk_update",
                "key": "risk",
                "timestamp": datetime.now().isoformat(),
                "timestamp_ms": int(datetime.now().timestamp() * 1000),
                "fields": json.dumps(payload, ensure_ascii=False),
            },
        )

    async def set_regime_snapshot(self, symbol: str, payload: dict[str, Any]) -> None:
        """Persist latest regime snapshot and mirror it to stream."""
        serialized = self._stringify_mapping(payload)
        await self._client.hset("regime:latest", symbol, json.dumps(serialized, ensure_ascii=False))
        if self._regime_snapshot_ttl_sec > 0:
            await self._client.expire("regime:latest", self._regime_snapshot_ttl_sec)
        await self._safe_publish_state_event(
            "regime:snapshots",
            {
                "event": "regime_snapshot",
                "symbol": symbol,
                "market": serialized.get("market", ""),
                "strategy": serialized.get("strategy", ""),
                "regime": serialized.get("regime", ""),
                "trend": serialized.get("trend", ""),
                "price": serialized.get("price", ""),
                "timestamp": serialized.get("timestamp", datetime.now().isoformat()),
                "timestamp_ms": serialized.get("timestamp_ms", int(datetime.now().timestamp() * 1000)),
            },
            maxlen=self._regime_snapshot_maxlen,
        )

    async def set_selector_snapshot(self, strategy: str, payload: dict[str, Any]) -> None:
        """Persist latest selector snapshot and mirror it to stream."""
        serialized = self._stringify_mapping(payload)
        key = f"strategy:selector:latest:{strategy}"
        await self._client.hset(key, mapping=serialized)
        if self._selector_snapshot_ttl_sec > 0:
            await self._client.expire(key, self._selector_snapshot_ttl_sec)
        await self._safe_publish_state_event(
            "strategy:selector:snapshots",
            {
                "event": "selector_snapshot",
                "strategy": strategy,
                "key": key,
                "timestamp": serialized.get("timestamp", datetime.now().isoformat()),
                "timestamp_ms": int(datetime.now().timestamp() * 1000),
                "fields": json.dumps(serialized, ensure_ascii=False),
            },
        )

    async def get_risk(self) -> dict[str, str]:
        """Get risk data.

        Returns:
            Dict of risk data
        """
        return await self._client.hgetall("risk")

    async def is_blocked(self) -> bool:
        """Check if trading is blocked.

        Returns:
            True if trading is blocked
        """
        risk = await self.get_risk()
        return risk.get("blocked") == "true"

    async def is_kill_switch_on(self) -> bool:
        """Check if kill switch is on.

        Returns:
            True if kill switch is enabled
        """
        risk = await self.get_risk()
        return risk.get("kill_switch") == "true"
