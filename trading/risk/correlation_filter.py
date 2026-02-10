"""Correlation-based entry filtering.

Prevents entering positions that are highly correlated with existing positions,
avoiding beta exposure doubling (e.g., BTC + ETH move together).

Correlation is calculated using recent returns (default: 240 bars = 4 hours of 1-min data).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Dict, List, Optional, Tuple

import numpy as np

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)


@dataclass
class CorrelationConfig:
    """Configuration for correlation filtering."""

    lookback_bars: int = 240
    """Number of bars for correlation calculation (240 = 4h of 1-min)."""

    threshold: float = 0.75
    """Block/reduce entry if correlation exceeds this."""

    cache_ttl_seconds: int = 300
    """Cache correlation values for this many seconds."""

    min_data_points: int = 60
    """Minimum data points required for valid correlation."""

    @classmethod
    def from_dict(cls, config: Dict) -> "CorrelationConfig":
        """Create from allocation.json config."""
        return cls(
            lookback_bars=config.get("corr_lookback_bars", 240),
            threshold=config.get("corr_threshold", 0.75),
            cache_ttl_seconds=config.get("corr_cache_ttl", 300),
            min_data_points=config.get("corr_min_data", 60),
        )


class CorrelationFilter:
    """Real-time correlation calculation and filtering.

    Calculates rolling correlation between symbol returns to detect
    when entering a new position would just be doubling beta exposure.

    Usage:
        filter = CorrelationFilter(config, redis)

        # Check correlation before entry
        corr = await filter.get_correlation("ETH", "BTC")
        if corr > 0.75:
            # Don't enter ETH if already long BTC

        # Or use the helper
        blocked, reason = await filter.should_block("ETH", ["BTC", "SOL"])
    """

    def __init__(self, config: CorrelationConfig, redis: "RedisStreams"):
        self.config = config
        self.redis = redis

        # Cache: key = "SYMBOL_A_SYMBOL_B" (alphabetical), value = (corr, timestamp)
        self._cache: Dict[str, Tuple[float, float]] = {}

        # Returns cache: symbol -> list of returns
        self._returns_cache: Dict[str, Tuple[List[float], float]] = {}
        self._returns_ttl = 60  # 1 minute cache for returns

    async def get_correlation(self, symbol_a: str, symbol_b: str) -> float:
        """Get correlation between two symbols.

        Args:
            symbol_a: First symbol.
            symbol_b: Second symbol.

        Returns:
            Pearson correlation coefficient (-1 to 1).
            Returns 0 if insufficient data.
        """
        # Normalize cache key (alphabetical order)
        key = f"{min(symbol_a, symbol_b)}_{max(symbol_a, symbol_b)}"

        # Check cache
        now = time.time()
        if key in self._cache:
            corr, ts = self._cache[key]
            if now - ts < self.config.cache_ttl_seconds:
                return corr

        # Calculate correlation
        returns_a = await self._get_returns(symbol_a)
        returns_b = await self._get_returns(symbol_b)

        if len(returns_a) < self.config.min_data_points:
            logger.debug(f"Insufficient data for {symbol_a}: {len(returns_a)} points")
            return 0.0

        if len(returns_b) < self.config.min_data_points:
            logger.debug(f"Insufficient data for {symbol_b}: {len(returns_b)} points")
            return 0.0

        # Align lengths
        min_len = min(len(returns_a), len(returns_b))
        returns_a = returns_a[-min_len:]
        returns_b = returns_b[-min_len:]

        # Calculate Pearson correlation
        try:
            corr = np.corrcoef(returns_a, returns_b)[0, 1]
            if np.isnan(corr):
                corr = 0.0
        except Exception as e:
            logger.warning(f"Correlation calculation failed: {e}")
            corr = 0.0

        # Cache result
        self._cache[key] = (corr, now)

        logger.debug(f"Correlation {symbol_a}-{symbol_b}: {corr:.3f}")

        return corr

    async def should_block(
        self,
        new_symbol: str,
        existing_symbols: List[str],
    ) -> Tuple[bool, str]:
        """Check if new symbol should be blocked due to high correlation.

        Args:
            new_symbol: Symbol to potentially enter.
            existing_symbols: Symbols with open positions.

        Returns:
            Tuple of (should_block, reason_string).
        """
        if not existing_symbols:
            return False, "NO_EXISTING_POSITIONS"

        for existing in existing_symbols:
            corr = await self.get_correlation(new_symbol, existing)
            if corr > self.config.threshold:
                return True, f"HIGH_CORR:{new_symbol}-{existing}={corr:.2f}"

        return False, "CORR_OK"

    async def get_correlation_matrix(
        self,
        symbols: List[str],
    ) -> Dict[str, Dict[str, float]]:
        """Get full correlation matrix for symbols.

        Useful for dashboard display.
        """
        matrix = {}
        for i, sym_a in enumerate(symbols):
            matrix[sym_a] = {}
            for j, sym_b in enumerate(symbols):
                if i == j:
                    matrix[sym_a][sym_b] = 1.0
                elif i < j:
                    corr = await self.get_correlation(sym_a, sym_b)
                    matrix[sym_a][sym_b] = corr
                else:
                    # Use symmetric value
                    matrix[sym_a][sym_b] = matrix[sym_b][sym_a]

        return matrix

    async def _get_returns(self, symbol: str) -> List[float]:
        """Get recent returns for symbol from Redis.

        Returns are calculated as (close[t] - close[t-1]) / close[t-1].
        """
        now = time.time()

        # Check cache
        if symbol in self._returns_cache:
            returns, ts = self._returns_cache[symbol]
            if now - ts < self._returns_ttl:
                return returns

        # Fetch from Redis
        # Assuming prices are stored as a list in Redis
        key = f"prices:{symbol}:minute"

        try:
            # Try to get price history from Redis stream
            prices = await self._fetch_prices_from_stream(symbol)

            if len(prices) < 2:
                return []

            # Calculate returns
            returns = []
            for i in range(1, len(prices)):
                if prices[i - 1] > 0:
                    ret = (prices[i] - prices[i - 1]) / prices[i - 1]
                    returns.append(ret)

            # Cache
            self._returns_cache[symbol] = (returns, now)

            return returns

        except Exception as e:
            logger.warning(f"Failed to get returns for {symbol}: {e}")
            return []

    async def _fetch_prices_from_stream(self, symbol: str) -> List[float]:
        """Fetch price history from Redis stream.

        Falls back to using the market:prices stream data.
        """
        try:
            client = getattr(self.redis, "_client", None)
            if client is None:
                return []

            # Try the dedicated price history first
            history_key = f"price_history:{symbol}"
            raw_data = await client.lrange(history_key, 0, self.config.lookback_bars)

            if raw_data:
                prices = [float(p) for p in raw_data]
                return prices

            # Fallback: read from market:prices stream (more expensive)
            stream_data = await client.xrevrange(
                "market:prices",
                count=self.config.lookback_bars * 3,  # Multiple symbols in stream
            )

            prices = []
            for msg_id, data in stream_data:
                msg_symbol = data.get("symbol", "")
                if msg_symbol == symbol:
                    price = float(data.get("price", 0))
                    if price > 0:
                        prices.append(price)
                        if len(prices) >= self.config.lookback_bars:
                            break

            # Reverse to chronological order
            prices.reverse()
            return prices

        except Exception as e:
            logger.debug(f"Price fetch failed for {symbol}: {e}")
            return []

    def invalidate_cache(self) -> None:
        """Clear all caches. Call when market data is reset."""
        self._cache.clear()
        self._returns_cache.clear()


class CorrelationGroup:
    """Tracks correlated symbol groups for group-level risk caps.

    When using corr_action='group_cap', this class helps manage
    which symbols belong to which correlation group.
    """

    def __init__(self, threshold: float = 0.75):
        self.threshold = threshold
        self.groups: List[set] = []

    def add_symbol(self, symbol: str, correlations: Dict[str, float]) -> int:
        """Add symbol to appropriate group.

        Returns:
            Group index the symbol was added to.
        """
        # Find existing group with high correlation
        for i, group in enumerate(self.groups):
            for member in group:
                corr = correlations.get(member, 0)
                if corr > self.threshold:
                    group.add(symbol)
                    return i

        # No matching group - create new
        self.groups.append({symbol})
        return len(self.groups) - 1

    def get_group(self, symbol: str) -> Optional[set]:
        """Get the group containing symbol."""
        for group in self.groups:
            if symbol in group:
                return group
        return None

    def get_group_members(self, symbol: str) -> List[str]:
        """Get all members of symbol's group."""
        group = self.get_group(symbol)
        return list(group) if group else [symbol]
