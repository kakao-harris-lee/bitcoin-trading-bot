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
import math
import time
from collections import deque
from dataclasses import replace
from typing import TYPE_CHECKING, Any

import pandas as pd

from trading.indicators import add_all_indicators
from trading.strategies.components.models import MarketData

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _safe_float(value: Any, default: float = 0.0) -> float:
    """Safely convert value to float, handling NaN and None.

    Args:
        value: Value to convert.
        default: Default value if conversion fails or value is NaN/None.

    Returns:
        Float value or default.
    """
    if value is None:
        return default
    try:
        result = float(value)
        if math.isnan(result):
            return default
        return result
    except (ValueError, TypeError):
        return default


def _safe_int(value: Any, default: int = 0) -> int:
    """Safely convert value to int, handling NaN and None.

    Args:
        value: Value to convert.
        default: Default value if conversion fails or value is NaN/None.

    Returns:
        Int value or default.
    """
    if value is None:
        return default
    try:
        float_val = float(value)
        if math.isnan(float_val):
            return default
        return int(float_val)
    except (ValueError, TypeError):
        return default


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

        # Candle aggregation: build new candles from tick data
        self._building_candle: dict[str, dict] = {}    # symbol -> {open, high, low, close, boundary}
        self._candle_interval: dict[str, int] = {}     # symbol -> interval in seconds
        self._candle_interval_str: dict[str, str] = {} # symbol -> Binance interval string (e.g. "4h")

        # REST candle refresh: flag symbols needing real OHLCV data
        self._pending_refresh: set[str] = set()

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

        # Detect candle interval from timestamp diff of last two candles
        if len(candles) >= 2:
            ts_key = "open_time" if "open_time" in candles[-1] else "timestamp"
            t1 = candles[-2].get(ts_key, 0)
            t2 = candles[-1].get(ts_key, 0)
            if t1 and t2:
                diff = abs(t2 - t1)
                # open_time is in milliseconds from Binance
                if diff > 1_000_000:
                    diff = diff // 1000
                self._candle_interval[symbol] = int(diff)

                # Map seconds to Binance interval string for REST API refresh
                _INTERVAL_MAP = {
                    60: "1m", 300: "5m", 900: "15m",
                    3600: "1h", 14400: "4h", 86400: "1d",
                }
                self._candle_interval_str[symbol] = _INTERVAL_MAP.get(
                    int(diff), "1h"
                )

                logger.info(
                    f"IndicatorService: {symbol} candle interval = {diff}s "
                    f"({diff // 60}m)"
                )

        # Reset building candle for this symbol
        self._building_candle.pop(symbol, None)

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

        # --- Candle aggregation ---
        interval = self._candle_interval.get(symbol)
        if not interval or symbol not in self._history:
            return

        price = float(price_msg.get("price", 0))
        if price <= 0:
            return

        now = time.time()
        boundary = int(now // interval) * interval

        building = self._building_candle.get(symbol)
        if building is None:
            # Start tracking a new candle
            self._building_candle[symbol] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "boundary": boundary,
            }
            return

        if boundary > building["boundary"]:
            # Period boundary crossed — finalize the completed candle
            self._finalize_candle(symbol, building)
            # Start new candle
            self._building_candle[symbol] = {
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "boundary": boundary,
            }
        else:
            # Same period — update running OHLC
            building["high"] = max(building["high"], price)
            building["low"] = min(building["low"], price)
            building["close"] = price

    def _finalize_candle(self, symbol: str, building: dict) -> None:
        """Finalize a completed candle and append it to history.

        Args:
            symbol: Trading symbol.
            building: Dict with open/high/low/close/boundary from tick aggregation.
        """
        history = self._history.get(symbol)
        if not history:
            return

        # Estimate volume from 20-candle historical average (MFI needs volume)
        recent = history[-20:]
        avg_vol = sum(c.get("volume", 0) for c in recent) / max(len(recent), 1)

        candle = {
            "open": building["open"],
            "high": building["high"],
            "low": building["low"],
            "close": building["close"],
            "volume": avg_vol,
            "timestamp": building["boundary"],
            "open_time": building["boundary"] * 1000,  # ms for Binance compat
        }

        history.append(candle)

        # Flag for REST API refresh to replace estimated volume with real data
        self._pending_refresh.add(symbol)

        # Trim to warmup_candles + 50 to prevent unbounded growth
        max_len = self._warmup_candles + 50
        if len(history) > max_len:
            self._history[symbol] = history[-max_len:]

        # Invalidate indicator cache so next get_market_data() recalculates
        self._cache.pop(symbol, None)

        logger.info(
            f"IndicatorService: New candle for {symbol} | "
            f"O={candle['open']:.2f} H={candle['high']:.2f} "
            f"L={candle['low']:.2f} C={candle['close']:.2f} "
            f"(history={len(self._history[symbol])} candles)"
        )

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
                # Update close, high, low with current price for accurate real-time data
                # Note: Indicators (RSI, MFI, etc.) remain from cache - only price fields update
                updated_high = max(cached_data.high, current_price)
                updated_low = min(cached_data.low, current_price)
                return replace(
                    cached_data,
                    close=current_price,
                    high=updated_high,
                    low=updated_low,
                )

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

            # Get timestamp from buffer
            buffer = self._price_buffers.get(symbol, [])
            timestamp = int(buffer[-1].get("timestamp", 0)) if buffer else 0

            # Use values from add_all_indicators() for consistency
            # These are already calculated with rolling windows in precompute.py
            return MarketData(
                symbol=symbol,
                open=_safe_float(last_row.get("open"), current_price),
                close=current_price,
                # Oscillators with neutral defaults
                mfi=_safe_float(last_row.get("mfi"), 50.0),
                adx=_safe_float(last_row.get("adx"), 20.0),
                rsi=_safe_float(last_row.get("rsi"), 50.0),
                timestamp=timestamp,
                # OHLCV
                high=_safe_float(last_row.get("high"), current_price),
                low=_safe_float(last_row.get("low"), current_price),
                volume=_safe_float(last_row.get("volume"), 0.0),
                # MACD
                macd=_safe_float(last_row.get("macd"), 0.0),
                macd_signal=_safe_float(last_row.get("macd_signal"), 0.0),
                # Stochastic with neutral defaults
                stoch_k=_safe_float(last_row.get("stoch_k"), 50.0),
                stoch_d=_safe_float(last_row.get("stoch_d"), 50.0),
                # Bollinger Bands
                bb_upper=_safe_float(last_row.get("bb_upper"), 0.0),
                bb_lower=_safe_float(last_row.get("bb_lower"), 0.0),
                bb_middle=_safe_float(last_row.get("bb_middle"), 0.0),
                # Volatility
                atr=_safe_float(last_row.get("atr"), 0.0),
                # EMAs
                ema_120=_safe_float(last_row.get("ema_120"), 0.0),
                ema_200=_safe_float(last_row.get("ema_200"), 0.0),
                # Historical reference points (from add_all_indicators rolling calculations)
                high_30d=_safe_float(last_row.get("high_30d"), 0.0),
                market_stress=_safe_float(last_row.get("market_stress"), 0.0),
                # Use pre-calculated values from add_all_indicators() for consistency
                prev_high_20=_safe_float(last_row.get("prev_high_20"), 0.0),
                prev_low_20=_safe_float(last_row.get("prev_low_20"), 0.0),
                avg_volume_20=_safe_float(last_row.get("avg_volume_20"), 0.0),
                # Volatility breakout (Larry Williams strategy)
                breakout_signal=_safe_int(last_row.get("breakout_signal"), 0),
                target_price=_safe_float(last_row.get("target_price"), 0.0),
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

    def needs_refresh(self, symbol: str) -> bool:
        """Check if symbol needs REST candle refresh for real OHLCV data.

        Args:
            symbol: Trading symbol.

        Returns:
            True if symbol has pending estimated candles that need real data.
        """
        return symbol in self._pending_refresh

    async def refresh_history(self, symbol: str, market: str = "futures") -> None:
        """Refresh recent candle history with real OHLCV data from Binance REST API.

        Replaces estimated candles (with fake volume) with real data from Binance.
        This ensures volume_ratio calculations are accurate for volume-gated strategies.

        Args:
            symbol: Trading symbol.
            market: Market type ("spot" or "futures").
        """
        from trading.streams.data_warmup import DataWarmup

        history = self._history.get(symbol)
        if not history:
            return

        interval_str = self._candle_interval_str.get(symbol, "1h")

        try:
            warmup = DataWarmup()
            candles = await warmup.fetch_recent_candles(
                symbol=symbol, limit=5, interval=interval_str, market=market,
            )

            if not candles:
                logger.warning(f"IndicatorService: Candle refresh returned no data for {symbol}")
                return

            # Build lookup by open_time (ms) for O(1) matching
            candle_by_ts: dict[int, dict] = {}
            for c in candles:
                # DataWarmup returns timestamp in ms (Binance open_time)
                candle_by_ts[int(c["timestamp"])] = c

            replaced = 0
            for i, h in enumerate(history):
                h_ts = int(h.get("open_time", 0))
                if h_ts in candle_by_ts:
                    real = candle_by_ts[h_ts]
                    history[i]["open"] = real["open"]
                    history[i]["high"] = real["high"]
                    history[i]["low"] = real["low"]
                    history[i]["close"] = real["close"]
                    history[i]["volume"] = real["volume"]
                    replaced += 1

            # Remove from pending set
            self._pending_refresh.discard(symbol)

            # Invalidate indicator cache so next calculation uses real data
            self._cache.pop(symbol, None)

            if replaced > 0:
                logger.info(
                    f"IndicatorService: Candle refresh for {symbol} — "
                    f"replaced {replaced} candle(s) with real OHLCV data"
                )

        except Exception as e:
            logger.warning(f"IndicatorService: Candle refresh failed for {symbol}: {e}")
            # Don't remove from pending — will retry next tick
            return
