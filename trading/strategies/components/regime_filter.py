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
