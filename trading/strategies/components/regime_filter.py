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
