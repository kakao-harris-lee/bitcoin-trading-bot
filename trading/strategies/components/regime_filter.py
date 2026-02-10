"""Regime transition filters to reduce noise.

Filters applied sequentially when a regime change is detected:
1. MTFFilter: Multi-timeframe direction confirmation (4h)
2. BBWFilter: Bollinger Band Width filter (blocks in low volatility)
3. VolumeFilter: Volume confirmation filter

Design doc: docs/plans/2026-01-27-enhanced-regime-detection-design.md
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Literal

from .models import _classify_regime

# 7-level regime classification (matches models.py)
Regime = Literal[
    "BULL_STRONG",
    "BULL_MODERATE",
    "SIDEWAYS_UP",
    "SIDEWAYS_FLAT",
    "SIDEWAYS_DOWN",
    "BEAR_MODERATE",
    "BEAR_STRONG",
]

# Direction groupings for MTF alignment
BULL_DIRECTION = {"BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"}
BEAR_DIRECTION = {"BEAR_STRONG", "BEAR_MODERATE", "SIDEWAYS_DOWN"}
NEUTRAL_DIRECTION = {"SIDEWAYS_FLAT"}

# Regime groups for volume filter exceptions
BEAR_REGIMES = {"BEAR_STRONG", "BEAR_MODERATE"}
SIDEWAYS_REGIMES = {"SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN"}


@dataclass
class BBWFilterConfig:
    """Configuration for BBW filter."""

    block_threshold: int = 25  # Percentile below which to block
    confirm_threshold: int = 50  # Percentile requiring 2-candle confirm
    window: int = 100  # Rolling window for percentile calculation


class BBWFilter:
    """Bollinger Band Width filter.

    Blocks regime transitions when BBW percentile is low (consolidation).
    Low volatility periods produce noisy regime signals.

    BBW = (bb_upper - bb_lower) / bb_middle * 100

    Rules:
    - BBW percentile < 25: Block transition (keep previous regime)
    - BBW percentile 25-50: Allow with 2-candle confirmation
    - BBW percentile > 50: Allow immediate transition
    """

    def __init__(
        self,
        block_threshold: int = 25,
        confirm_threshold: int = 50,
        window: int = 100,
    ):
        """Initialize BBW filter.

        Args:
            block_threshold: Percentile below which to block transitions
            confirm_threshold: Percentile requiring confirmation
            window: Rolling window for percentile calculation
        """
        self.block_threshold = block_threshold
        self.confirm_threshold = confirm_threshold
        self.window = window
        self._bbw_history: deque[float] = deque(maxlen=window)
        self._current_bbw: float = 0.0

    def calculate_bbw(
        self,
        bb_upper: float,
        bb_lower: float,
        bb_middle: float,
    ) -> float:
        """Calculate Bollinger Band Width percentage.

        Args:
            bb_upper: Upper Bollinger Band
            bb_lower: Lower Bollinger Band
            bb_middle: Middle Bollinger Band (SMA)

        Returns:
            BBW as percentage (e.g., 10.0 for 10%)
        """
        if bb_middle <= 0:
            return 0.0
        return (bb_upper - bb_lower) / bb_middle * 100

    def update_bbw(self, bbw: float) -> None:
        """Update BBW history with new value.

        Args:
            bbw: Current BBW value
        """
        self._bbw_history.append(bbw)
        self._current_bbw = bbw

    def get_percentile(self) -> float:
        """Get current BBW percentile rank (0-100).

        Returns:
            Percentile rank of current BBW in history
        """
        if len(self._bbw_history) < 2:
            return 50.0  # Default to middle when insufficient data

        current = self._current_bbw
        below_count = sum(1 for v in self._bbw_history if v < current)
        return (below_count / len(self._bbw_history)) * 100

    def should_block(self) -> bool:
        """Check if transition should be blocked.

        Returns:
            True if BBW percentile is below block threshold
        """
        return self.get_percentile() < self.block_threshold

    def needs_confirmation(self) -> bool:
        """Check if transition needs 2-candle confirmation.

        Returns:
            True if BBW percentile is between block and confirm thresholds
        """
        pct = self.get_percentile()
        return self.block_threshold <= pct < self.confirm_threshold


@dataclass
class MTFCandle:
    """Candle data for MTF aggregation.

    Holds OHLCV plus MFI/ADX for regime calculation at higher timeframes.
    """

    open: float
    high: float
    low: float
    close: float
    volume: float
    mfi: float
    adx: float


class MTFFilter:
    """Multi-Timeframe direction filter.

    Aggregates minute60 candles into minute240 (4h) and checks
    if regime direction is aligned between timeframes.

    Direction Groups:
    - BULL: BULL_STRONG, BULL_MODERATE, SIDEWAYS_UP
    - BEAR: BEAR_STRONG, BEAR_MODERATE, SIDEWAYS_DOWN
    - NEUTRAL: SIDEWAYS_FLAT

    Rules:
    - Same direction: aligned (allow transition)
    - Upper is NEUTRAL: aligned (follow lower)
    - Different direction: not aligned (block transition)
    """

    def __init__(self, candles_per_period: int = 4):
        """Initialize MTF filter.

        Args:
            candles_per_period: Number of candles to aggregate (4 for 4h from 1h)
        """
        self.candles_per_period = candles_per_period
        self._candle_buffer: deque[MTFCandle] = deque(maxlen=candles_per_period)

    def aggregate_candles(self, candles: list[MTFCandle]) -> MTFCandle:
        """Aggregate multiple candles into one higher timeframe candle.

        Args:
            candles: List of candles to aggregate (oldest first)

        Returns:
            Aggregated candle with OHLCV and averaged MFI/ADX
        """
        if not candles:
            raise ValueError("Cannot aggregate empty candle list")

        return MTFCandle(
            open=candles[0].open,
            high=max(c.high for c in candles),
            low=min(c.low for c in candles),
            close=candles[-1].close,
            volume=sum(c.volume for c in candles),
            mfi=sum(c.mfi for c in candles) / len(candles),
            adx=sum(c.adx for c in candles) / len(candles),
        )

    def add_candle(self, candle: MTFCandle) -> MTFCandle | None:
        """Add a candle and return aggregated if buffer full.

        Args:
            candle: New minute60 candle

        Returns:
            Aggregated minute240 candle if buffer full, else None
        """
        self._candle_buffer.append(candle)
        if len(self._candle_buffer) == self.candles_per_period:
            return self.aggregate_candles(list(self._candle_buffer))
        return None

    def get_direction(self, regime: Regime) -> str:
        """Get direction group for a regime.

        Args:
            regime: Regime classification

        Returns:
            "BULL", "BEAR", or "NEUTRAL"
        """
        if regime in BULL_DIRECTION:
            return "BULL"
        elif regime in BEAR_DIRECTION:
            return "BEAR"
        else:
            return "NEUTRAL"

    def is_direction_aligned(
        self,
        lower_regime: Regime,
        upper_regime: Regime,
    ) -> bool:
        """Check if lower and upper timeframe directions are aligned.

        Rules:
        - Same direction: aligned
        - Upper is NEUTRAL: aligned (follow lower)
        - Different direction: not aligned

        Args:
            lower_regime: minute60 regime
            upper_regime: minute240 regime

        Returns:
            True if directions are aligned
        """
        upper_dir = self.get_direction(upper_regime)

        # Neutral upper allows any lower
        if upper_dir == "NEUTRAL":
            return True

        lower_dir = self.get_direction(lower_regime)
        return lower_dir == upper_dir


class VolumeFilter:
    """Volume confirmation filter.

    Blocks transitions when volume is below average.
    Price movement without volume is "unconvinced movement."

    volume_ratio = current_volume / SMA(volume, 20)

    Rules:
    - volume_ratio < 0.8: Block transition
    - volume_ratio 0.8-1.2: Normal, combine with BBW filter
    - volume_ratio > 1.2: High volume boosts confidence

    Exceptions (bypass volume check):
    - BEAR transitions: Panic sells can have low volume
    - SIDEWAYS transitions: Low volume is normal
    """

    def __init__(
        self,
        block_ratio: float = 0.8,
        boost_ratio: float = 1.2,
    ):
        """Initialize Volume filter.

        Args:
            block_ratio: Volume ratio below which to block transitions
            boost_ratio: Volume ratio above which to boost confidence
        """
        self.block_ratio = block_ratio
        self.boost_ratio = boost_ratio

    def should_block(
        self,
        volume_ratio: float,
        target_regime: Regime | None = None,
    ) -> bool:
        """Check if transition should be blocked due to low volume.

        Args:
            volume_ratio: current_volume / avg_volume_20
            target_regime: The regime we're transitioning TO (for exceptions)

        Returns:
            True if volume is too low (and no exception applies)
        """
        # BEAR transitions: panic sells can have low volume
        if target_regime in BEAR_REGIMES:
            return False

        # SIDEWAYS transitions: low volume is normal
        if target_regime in SIDEWAYS_REGIMES:
            return False

        return volume_ratio < self.block_ratio

    def is_boosted(self, volume_ratio: float) -> bool:
        """Check if volume is high enough to boost confidence.

        High volume can relax BBW threshold.

        Args:
            volume_ratio: current_volume / avg_volume_20

        Returns:
            True if volume is above boost threshold
        """
        return volume_ratio > self.boost_ratio


@dataclass
class EnhancedRegimeConfig:
    """Configuration for EnhancedRegimeRouter."""

    bbw_block_threshold: int = 25
    bbw_confirm_threshold: int = 50
    bbw_window: int = 100
    volume_block_ratio: float = 0.8
    volume_boost_ratio: float = 1.2
    mtf_enabled: bool = True


class EnhancedRegimeRouter:
    """Enhanced regime router with BBW, MTF, and Volume filters.

    Applies filters sequentially to reduce noisy regime transitions:
    1. MTF direction check (if enabled)
    2. BBW percentile check
    3. Volume confirmation check

    All filters must pass for a transition to occur.

    Configuration parameters:
    - bbw_block_threshold: BBW percentile below which to block (default 25)
    - bbw_confirm_threshold: BBW percentile requiring confirmation (default 50)
    - volume_block_ratio: Volume ratio below which to block (default 0.8)
    - volume_boost_ratio: Volume ratio above which to relax BBW (default 1.2)
    - mtf_enabled: Whether to check 4-hour direction alignment (default True)
    """

    def __init__(
        self,
        bbw_block_threshold: int = 25,
        bbw_confirm_threshold: int = 50,
        bbw_window: int = 100,
        volume_block_ratio: float = 0.8,
        volume_boost_ratio: float = 1.2,
        mtf_enabled: bool = True,
    ):
        """Initialize EnhancedRegimeRouter.

        Args:
            bbw_block_threshold: BBW percentile below which to block
            bbw_confirm_threshold: BBW percentile requiring 2-candle confirm
            bbw_window: Rolling window for BBW percentile calculation
            volume_block_ratio: Volume ratio below which to block
            volume_boost_ratio: Volume ratio above which to boost confidence
            mtf_enabled: Whether to check MTF direction alignment
        """
        self._bbw_filter = BBWFilter(
            block_threshold=bbw_block_threshold,
            confirm_threshold=bbw_confirm_threshold,
            window=bbw_window,
        )
        self._volume_filter = VolumeFilter(
            block_ratio=volume_block_ratio,
            boost_ratio=volume_boost_ratio,
        )
        self._mtf_filter = MTFFilter()
        self._mtf_enabled = mtf_enabled
        self._mtf_regime: Regime | None = None
        self._last_lower_candle_ts: int | None = None
        self._prev_regime: Regime | None = None
        self._pending_regime: Regime | None = None
        self._pending_count: int = 0

    def update_from_lower_candle(
        self,
        candle: MTFCandle,
        candle_ts: int | None = None,
    ) -> None:
        """Update internal MTF regime from incoming lower-timeframe candle.

        Args:
            candle: Lower-timeframe candle (e.g., 1h).
            candle_ts: Candle timestamp for deduplication (optional).
        """
        if not self._mtf_enabled:
            return

        if candle_ts is not None and candle_ts == self._last_lower_candle_ts:
            return

        if candle_ts is not None:
            self._last_lower_candle_ts = candle_ts

        aggregated = self._mtf_filter.add_candle(candle)
        if aggregated is None:
            return

        self._mtf_regime = _classify_regime(aggregated.mfi, aggregated.adx)

    def set_mtf_regime(self, regime: Regime) -> None:
        """Set the 4-hour timeframe regime.

        Call this when a new 4h candle completes.

        Args:
            regime: Current 4h regime classification
        """
        self._mtf_regime = regime

    def get_regime(
        self,
        mfi: float,
        adx: float,
        bb_upper: float,
        bb_lower: float,
        bb_middle: float,
        volume_ratio: float,
        prev_regime: Regime | None = None,
    ) -> Regime:
        """Get filtered regime classification.

        Applies filters sequentially:
        1. Calculate candidate regime from MFI/ADX
        2. If no change from prev_regime, return immediately
        3. MTF direction check (if enabled and MTF regime set)
        4. BBW percentile check (bypassed if high volume)
        5. Volume confirmation check (bypassed for BEAR/SIDEWAYS)

        Args:
            mfi: Money Flow Index (0-100)
            adx: Average Directional Index
            bb_upper: Upper Bollinger Band
            bb_lower: Lower Bollinger Band
            bb_middle: Middle Bollinger Band
            volume_ratio: current_volume / avg_volume_20
            prev_regime: Previous regime (uses internal state if None)

        Returns:
            Filtered regime classification
        """
        # Calculate candidate regime using standard classification
        candidate = _classify_regime(mfi, adx)

        # Use provided prev_regime or internal state
        if prev_regime is not None:
            self._prev_regime = prev_regime

        # Initialize if first call
        if self._prev_regime is None:
            self._prev_regime = candidate
            return candidate

        # No change, no filtering needed
        if candidate == self._prev_regime:
            self._pending_regime = None
            self._pending_count = 0
            return candidate

        # Update BBW for history
        bbw = self._bbw_filter.calculate_bbw(bb_upper, bb_lower, bb_middle)
        self._bbw_filter.update_bbw(bbw)

        # Check if volume boosts confidence (relaxes BBW)
        bbw_boosted = self._volume_filter.is_boosted(volume_ratio)

        # Filter 1: MTF direction check
        if self._mtf_enabled and self._mtf_regime is not None:
            if not self._mtf_filter.is_direction_aligned(candidate, self._mtf_regime):
                return self._prev_regime  # Block: direction conflict

        # Filter 2: BBW check (bypassed if high volume)
        if not bbw_boosted and self._bbw_filter.should_block():
            return self._prev_regime  # Block: low volatility

        # Filter 3: Volume check (with BEAR/SIDEWAYS exceptions)
        if self._volume_filter.should_block(volume_ratio, candidate):
            return self._prev_regime  # Block: low volume

        # Check if needs confirmation (BBW between thresholds)
        if self._bbw_filter.needs_confirmation() and not bbw_boosted:
            if candidate == self._pending_regime:
                self._pending_count += 1
                if self._pending_count >= 2:
                    # Confirmed after 2 candles
                    self._prev_regime = candidate
                    self._pending_regime = None
                    self._pending_count = 0
                    return candidate
            else:
                # New pending regime
                self._pending_regime = candidate
                self._pending_count = 1
            return self._prev_regime  # Needs more confirmation

        # All filters passed - allow transition
        self._prev_regime = candidate
        self._pending_regime = None
        self._pending_count = 0
        return candidate

    def reset(self) -> None:
        """Reset router state.

        Call when starting a new trading session or after long gaps.
        """
        self._prev_regime = None
        self._mtf_regime = None
        self._last_lower_candle_ts = None
        self._pending_regime = None
        self._pending_count = 0
        self._bbw_filter._bbw_history.clear()
        self._bbw_filter._current_bbw = 0.0
