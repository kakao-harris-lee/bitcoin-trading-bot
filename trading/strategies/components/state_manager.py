"""Redis-backed State Manager for strategy persistence.

Solves the problem of state loss on restart (e.g., high_water_mark, entry_count).
All stateful variables in strategies should use this manager.

Key schema: state:{strategy_name}:{symbol}:{variable_name}

Usage:
    state = StateManager(redis_client, strategy_name="mlp_direction_btc_exit")

    # Load existing state on init
    await state.load(symbol="BTC", variable="high_water_mark", default=0.0)

    # Get current value
    hwm = await state.get("BTC", "high_water_mark")

    # Update (writes to Redis immediately)
    await state.set("BTC", "high_water_mark", 51000.0)

    # Delete on position close
    await state.delete("BTC", "high_water_mark")
"""
# pylint: disable=broad-exception-caught

from __future__ import annotations

import json
import logging
import os
import inspect
from datetime import datetime
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


class StateManager:
    """Redis-backed state persistence for strategies.

    Provides automatic persistence of strategy state variables to Redis.
    State is loaded on initialization and written immediately on updates.

    Thread-safe for async operations within a single strategy instance.
    """

    def __init__(
        self,
        redis: Redis,
        strategy_name: str,
        key_prefix: str = "state",
    ):
        """Initialize StateManager.

        Args:
            redis: Async Redis client instance.
            strategy_name: Name of the strategy (e.g., "mlp_direction_btc_exit").
            key_prefix: Prefix for Redis keys (default: "state").
        """
        self._redis = redis
        self._strategy_name = strategy_name
        self._key_prefix = key_prefix
        # Local cache for fast reads
        self._cache: dict[str, Any] = {}
        try:
            self._event_maxlen = max(1000, int(os.getenv("STATE_EVENT_MAXLEN", "200000")))
        except ValueError:
            self._event_maxlen = 200000
        try:
            self._state_ttl_sec = max(0, int(os.getenv("STATE_KEY_TTL_SEC", str(90 * 24 * 3600))))
        except ValueError:
            self._state_ttl_sec = 90 * 24 * 3600

    def _make_key(self, symbol: str, variable: str) -> str:
        """Generate Redis key for a state variable.

        Key schema: {prefix}:{strategy_name}:{symbol}:{variable}

        Args:
            symbol: Trading symbol (e.g., "BTC").
            variable: Variable name (e.g., "high_water_mark").

        Returns:
            Full Redis key string.
        """
        return f"{self._key_prefix}:{self._strategy_name}:{symbol}:{variable}"

    def _cache_key(self, symbol: str, variable: str) -> str:
        """Generate local cache key."""
        return f"{symbol}:{variable}"

    def _index_key(self, symbol: str) -> str:
        """Generate Redis key for state variable index."""
        return f"{self._key_prefix}:index:{self._strategy_name}:{symbol}"

    async def _safe_record_event(
        self,
        symbol: str,
        variable: str,
        event_type: str,
        value: Any = None,
    ) -> None:
        """Best-effort state event emission (never fails main state write)."""
        try:
            payload = {
                "event": event_type,
                "strategy": self._strategy_name,
                "symbol": symbol,
                "variable": variable,
                "timestamp": datetime.now().isoformat(),
                "timestamp_ms": str(int(datetime.now().timestamp() * 1000)),
            }
            if value is not None:
                payload["value"] = json.dumps(value)
            await self._redis.xadd("state:events", payload, maxlen=self._event_maxlen)
        except Exception:
            return

    async def _safe_index_add(self, symbol: str, variable: str) -> None:
        """Best-effort add variable to per-symbol state index."""
        try:
            result = self._redis.sadd(self._index_key(symbol), variable)
            if inspect.isawaitable(result):
                await result
            await self._safe_refresh_index_ttl(symbol)
        except Exception:
            return

    async def _safe_index_remove(self, symbol: str, variable: str) -> None:
        """Best-effort remove variable from per-symbol state index."""
        try:
            result = self._redis.srem(self._index_key(symbol), variable)
            if inspect.isawaitable(result):
                await result
            await self._safe_refresh_index_ttl(symbol)
        except Exception:
            return

    async def _safe_refresh_index_ttl(self, symbol: str) -> None:
        if self._state_ttl_sec <= 0:
            return
        try:
            result = self._redis.expire(self._index_key(symbol), self._state_ttl_sec)
            if inspect.isawaitable(result):
                await result
        except Exception:
            return

    async def load(
        self,
        symbol: str,
        variable: str,
        default: Any = None,
    ) -> Any:
        """Load state from Redis into local cache.

        Should be called on strategy initialization for each state variable.

        Args:
            symbol: Trading symbol.
            variable: Variable name.
            default: Default value if not found in Redis.

        Returns:
            Loaded value or default.
        """
        key = self._make_key(symbol, variable)
        cache_key = self._cache_key(symbol, variable)

        try:
            value = await self._redis.get(key)
            if value is not None:
                # Decode and parse JSON
                parsed = json.loads(value)
                self._cache[cache_key] = parsed
                logger.debug(
                    "StateManager: Loaded %s = %s", key, parsed
                )
                return parsed
            else:
                self._cache[cache_key] = default
                logger.debug(
                    "StateManager: No existing state for %s, using default=%s",
                    key,
                    default,
                )
                return default
        except Exception as e:
            logger.warning("StateManager: Failed to load %s: %s", key, e)
            self._cache[cache_key] = default
            return default

    async def get(
        self,
        symbol: str,
        variable: str,
        default: Any = None,
    ) -> Any:
        """Get state value (from cache, or load from Redis if not cached).

        Args:
            symbol: Trading symbol.
            variable: Variable name.
            default: Default value if not found.

        Returns:
            Current value or default.
        """
        cache_key = self._cache_key(symbol, variable)

        if cache_key in self._cache:
            return self._cache[cache_key]

        # Not in cache, load from Redis
        return await self.load(symbol, variable, default)

    async def set(
        self,
        symbol: str,
        variable: str,
        value: Any,
    ) -> None:
        """Set state value (writes to Redis first, then updates cache).

        Args:
            symbol: Trading symbol.
            variable: Variable name.
            value: New value to store.
        """
        key = self._make_key(symbol, variable)
        cache_key = self._cache_key(symbol, variable)

        old_value = self._cache.get(cache_key)

        try:
            # Write to Redis first to ensure persistence
            serialized = json.dumps(value)
            if self._state_ttl_sec > 0:
                await self._redis.set(key, serialized, ex=self._state_ttl_sec)
            else:
                await self._redis.set(key, serialized)
            await self._safe_index_add(symbol, variable)
            await self._safe_record_event(symbol, variable, "state_set", value)

            # Only update cache after successful Redis write
            self._cache[cache_key] = value

            if old_value != value:
                logger.info(
                    "StateManager: Updated %s: %s -> %s",
                    key,
                    old_value,
                    value,
                )
        except Exception as e:
            logger.error("StateManager: Failed to persist %s: %s", key, e)
            # Do NOT update cache if Redis fails - maintains consistency
            # On restart, we'll load the last known good value from Redis

    async def delete(
        self,
        symbol: str,
        variable: str,
    ) -> None:
        """Delete state value from cache and Redis.

        Should be called when position is closed.

        Args:
            symbol: Trading symbol.
            variable: Variable name.
        """
        key = self._make_key(symbol, variable)
        cache_key = self._cache_key(symbol, variable)

        self._cache.pop(cache_key, None)

        try:
            await self._redis.delete(key)
            await self._safe_index_remove(symbol, variable)
            await self._safe_record_event(symbol, variable, "state_delete")
            logger.debug("StateManager: Deleted %s", key)
        except Exception as e:
            logger.warning("StateManager: Failed to delete %s: %s", key, e)

    async def load_all_for_symbol(
        self,
        symbol: str,
        variables: list[str],
        defaults: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Load multiple state variables for a symbol.

        Convenience method for loading all state on position open.

        Args:
            symbol: Trading symbol.
            variables: List of variable names to load.
            defaults: Dict of variable -> default value.

        Returns:
            Dict of variable -> value.
        """
        defaults = defaults or {}
        result = {}

        for var in variables:
            default = defaults.get(var)
            result[var] = await self.load(symbol, var, default)

        return result

    async def delete_all_for_symbol(
        self,
        symbol: str,
        variables: list[str],
    ) -> None:
        """Delete multiple state variables for a symbol.

        Convenience method for clearing all state on position close.

        Args:
            symbol: Trading symbol.
            variables: List of variable names to delete.
        """
        for var in variables:
            await self.delete(symbol, var)

    def get_cached(self, symbol: str, variable: str, default: Any = None) -> Any:
        """Get value from local cache only (synchronous, no Redis).

        Use when you know the value was already loaded.

        Args:
            symbol: Trading symbol.
            variable: Variable name.
            default: Default if not in cache.

        Returns:
            Cached value or default.
        """
        cache_key = self._cache_key(symbol, variable)
        return self._cache.get(cache_key, default)

    def set_cached(self, symbol: str, variable: str, value: Any) -> None:
        """Set value in local cache only (synchronous, no Redis write).

        Use for temporary values that will be persisted later via set().

        Args:
            symbol: Trading symbol.
            variable: Variable name.
            value: Value to cache.
        """
        cache_key = self._cache_key(symbol, variable)
        self._cache[cache_key] = value

    @property
    def strategy_name(self) -> str:
        """Get the strategy name."""
        return self._strategy_name

    def list_cached_symbols(self, variable: str) -> list[str]:
        """List all symbols that have a cached value for a variable.

        Args:
            variable: Variable name.

        Returns:
            List of symbols with cached values.
        """
        suffix = f":{variable}"
        return [
            key.split(":")[0]
            for key in self._cache.keys()
            if key.endswith(suffix)
        ]
