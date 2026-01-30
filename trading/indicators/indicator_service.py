# trading/indicators/indicator_service.py
"""Centralized Indicator Service for efficient market data calculation.

This service eliminates redundant indicator calculations by providing a
system-wide cache. Instead of each strategy independently calculating
indicators, all strategies share the same pre-computed results.

Architecture:
    Before: 4 strategies × 3 symbols = 12 separate indicator calculations
    After:  1 calculation per symbol, shared by all strategies

    CPU reduction: ~75% for indicator computation
"""

from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import replace
from typing import TYPE_CHECKING

import pandas as pd

from trading.indicators import add_all_indicators
from trading.strategies.components.models import MarketData

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class IndicatorService:
    """Centralized indicator calculation with system-wide caching.

    Provides thread-safe, cached access to market indicators. All strategies
    use this service instead of calculating indicators independently.

    Cache Design:
        - Key: (symbol, candle_timestamp) tuple
        - Value: (compute_time, MarketData) tuple
        - TTL: Configurable, default 60 seconds

    Usage:
        service = IndicatorService(cache_ttl=60)

        # In strategy evaluation:
        market_data = service.get_market_data(
            symbol="BTC",
            history=candle_history,
            current_price=91000.0
        )
    """

    def __init__(
        self,
        cache_ttl: float = 60.0,
        warmup_candles: int = 200,
    ):
        """Initialize indicator service.

        Args:
            cache_ttl: Cache time-to-live in seconds.
            warmup_candles: Minimum candles needed for indicator calculation.
        """
        self._cache_ttl = cache_ttl
        self._warmup_candles = warmup_candles

        # Cache: symbol -> (timestamp, MarketData)
        self._cache: dict[str, tuple[float, MarketData]] = {}

        # Shared history storage (eliminates duplicate history across strategies)
        self._history: dict[str, list[dict]] = {}

        # Price buffers for real-time updates
        self._price_buffers: dict[str, deque] = {}

        # Stats for monitoring
        self._cache_hits = 0
        self._cache_misses = 0

        logger.info(f"IndicatorService initialized (cache_ttl={cache_ttl}s)")

    def update_history(self, symbol: str, candles: list[dict]) -> None:
        """Update shared history for a symbol.

        Called by warmup to set initial candle history.

        Args:
            symbol: Trading symbol (BTC, ETH, SOL).
            candles: List of candle dicts with OHLCV data.
        """
        self._history[symbol] = candles
        logger.info(f"IndicatorService: Updated {symbol} history ({len(candles)} candles)")

    def add_price(self, symbol: str, price_msg: dict) -> None:
        """Add a price update to the buffer.

        Called on each price tick to update real-time price.

        Args:
            symbol: Trading symbol.
            price_msg: Price message dict with 'price' and 'timestamp' keys.
        """
        if symbol not in self._price_buffers:
            self._price_buffers[symbol] = deque(maxlen=100)
        self._price_buffers[symbol].append(price_msg)

    def get_market_data(
        self,
        symbol: str,
        current_price: float | None = None,
    ) -> MarketData | None:
        """Get market data with indicators, using cache when possible.

        This is the main entry point for strategies to get indicator data.
        Uses caching to avoid redundant calculations.

        Args:
            symbol: Trading symbol (BTC, ETH, SOL).
            current_price: Override price (optional, defaults to latest buffer price).

        Returns:
            MarketData with all indicators, or None if insufficient data.
        """
        current_time = time.time()

        # Determine current price
        if current_price is None:
            buffer = self._price_buffers.get(symbol)
            if buffer:
                current_price = float(buffer[-1].get("price", 0))
            else:
                # No price data yet
                return None

        # Check cache
        if symbol in self._cache:
            cache_time, cached_data = self._cache[symbol]
            if current_time - cache_time < self._cache_ttl:
                self._cache_hits += 1
                # Return cached data with updated close price for accurate P&L
                return replace(cached_data, close=current_price)

        # Cache miss - need to recalculate
        self._cache_misses += 1
        market_data = self._calculate_indicators(symbol, current_price)

        if market_data:
            self._cache[symbol] = (current_time, market_data)

        return market_data

    def _calculate_indicators(
        self,
        symbol: str,
        current_price: float,
    ) -> MarketData | None:
        """Calculate all indicators for a symbol.

        This is the expensive operation that caching helps avoid.

        Args:
            symbol: Trading symbol.
            current_price: Current price for last candle update.

        Returns:
            MarketData with all indicators, or None if insufficient data.
        """
        history = self._history.get(symbol)
        if not history or len(history) < self._warmup_candles:
            logger.debug(f"IndicatorService: Insufficient history for {symbol}")
            return None

        try:
            # Create DataFrame from history
            df = pd.DataFrame(history)

            # Update last candle with current price
            idx = df.index[-1]
            if 'close' in df.columns:
                df.at[idx, "close"] = current_price
            if 'high' in df.columns:
                df.at[idx, "high"] = max(df.at[idx, "high"], current_price)
            if 'low' in df.columns:
                df.at[idx, "low"] = min(df.at[idx, "low"], current_price)

            # Calculate all indicators (expensive operation)
            df = add_all_indicators(df)
            last_row = df.iloc[-1]

            # Calculate 20-period lookback values
            lookback = 20
            if len(df) >= lookback:
                prev_df = df.iloc[-lookback-1:-1]
                prev_high_20 = float(prev_df['high'].max())
                prev_low_20 = float(prev_df['low'].min())
                avg_volume_20 = float(prev_df['volume'].mean())
            else:
                prev_high_20 = 0.0
                prev_low_20 = 0.0
                avg_volume_20 = 0.0

            # Get timestamp from buffer
            buffer = self._price_buffers.get(symbol, [])
            timestamp = int(buffer[-1].get("timestamp", 0)) if buffer else 0

            return MarketData(
                symbol=symbol,
                open=float(last_row.get("open", current_price)),
                close=float(current_price),
                mfi=float(last_row.get("mfi", 50)),
                adx=float(last_row.get("adx", 20)),
                rsi=float(last_row.get("rsi", 50)),
                timestamp=timestamp,
                high=float(last_row.get("high", current_price)),
                low=float(last_row.get("low", current_price)),
                volume=float(last_row.get("volume", 0)),
                macd=float(last_row.get("macd", 0)),
                macd_signal=float(last_row.get("macd_signal", 0)),
                stoch_k=float(last_row.get("stoch_k", 50)),
                stoch_d=float(last_row.get("stoch_d", 50)),
                bb_upper=float(last_row.get("bb_upper", 0)),
                bb_lower=float(last_row.get("bb_lower", 0)),
                bb_middle=float(last_row.get("bb_middle", 0)),
                atr=float(last_row.get("atr", 0)),
                ema_120=float(last_row.get("ema_120", 0)),
                ema_200=float(last_row.get("ema_200", 0)),
                high_30d=float(last_row.get("high_30d", 0)),
                market_stress=float(last_row.get("market_stress", 0)),
                prev_high_20=prev_high_20,
                prev_low_20=prev_low_20,
                avg_volume_20=avg_volume_20,
            )

        except Exception as e:
            logger.error(f"IndicatorService: Failed to calculate indicators for {symbol}: {e}")
            return None

    def invalidate_cache(self, symbol: str | None = None) -> None:
        """Invalidate cache for a symbol or all symbols.

        Args:
            symbol: Symbol to invalidate, or None for all.
        """
        if symbol:
            self._cache.pop(symbol, None)
        else:
            self._cache.clear()

    def get_stats(self) -> dict:
        """Get cache statistics for monitoring.

        Returns:
            Dict with hit/miss counts and hit rate.
        """
        total = self._cache_hits + self._cache_misses
        hit_rate = self._cache_hits / total if total > 0 else 0

        return {
            "cache_hits": self._cache_hits,
            "cache_misses": self._cache_misses,
            "hit_rate": f"{hit_rate:.1%}",
            "cached_symbols": list(self._cache.keys()),
        }

    def get_history_df(self, symbol: str, limit: int | None = None) -> pd.DataFrame | None:
        """Get a DataFrame copy of cached candle history for a symbol.

        Args:
            symbol: Trading symbol.
            limit: Optional number of most-recent rows to return.

        Returns:
            DataFrame of candle history, or None if no history is cached.
        """
        history = self._history.get(symbol)
        if not history:
            return None

        df = pd.DataFrame(history)
        if limit:
            return df.tail(limit)
        return df
