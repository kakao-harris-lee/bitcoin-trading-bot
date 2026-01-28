# Enhanced Regime Detection v2 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add BBW, MTF, and Volume filters to reduce regime transition noise by 50%+

**Architecture:** Extend existing `RegimeSmoother` pattern with pluggable filters. Each filter is independent and can be enabled/disabled via config. Filters run sequentially: MTF → BBW → Volume.

**Tech Stack:** Python 3.9+, pytest, existing `MarketData` dataclass

---

## Task 1: BBW Filter - Core Logic

**Files:**
- Create: `trading/strategies/components/regime_filter.py`
- Test: `tests/trading/strategies/components/test_regime_filter.py`

**Step 1: Write the failing test**

Create `tests/trading/strategies/components/test_regime_filter.py`:

```python
"""Tests for regime filters."""

import pytest
from trading.strategies.components.regime_filter import BBWFilter


class TestBBWFilter:
    """Tests for Bollinger Band Width filter."""

    def test_bbw_calculation(self):
        """BBW = (upper - lower) / middle * 100."""
        f = BBWFilter()
        bbw = f.calculate_bbw(bb_upper=105, bb_lower=95, bb_middle=100)
        assert bbw == 10.0  # (105-95)/100*100 = 10%

    def test_bbw_percentile_low_blocks(self):
        """Low BBW percentile (<25) should block transitions."""
        f = BBWFilter(block_threshold=25)
        # Feed 100 values, current is lowest
        for i in range(99):
            f.update_bbw(10.0 + i * 0.1)  # 10.0 to 19.9
        f.update_bbw(5.0)  # Current is very low
        assert f.should_block() is True

    def test_bbw_percentile_high_allows(self):
        """High BBW percentile (>50) should allow transitions."""
        f = BBWFilter(block_threshold=25)
        for i in range(99):
            f.update_bbw(10.0 + i * 0.1)
        f.update_bbw(20.0)  # Current is highest
        assert f.should_block() is False
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/trading/strategies/components/test_regime_filter.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'trading.strategies.components.regime_filter'"

**Step 3: Write minimal implementation**

Create `trading/strategies/components/regime_filter.py`:

```python
"""Regime transition filters to reduce noise.

Filters:
- BBWFilter: Bollinger Band Width filter (blocks in low volatility)
- MTFFilter: Multi-timeframe direction confirmation
- VolumeFilter: Volume confirmation filter
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass


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
    """

    def __init__(
        self,
        block_threshold: int = 25,
        confirm_threshold: int = 50,
        window: int = 100,
    ):
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
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/trading/strategies/components/test_regime_filter.py::TestBBWFilter -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add trading/strategies/components/regime_filter.py tests/trading/strategies/components/test_regime_filter.py
git commit -m "feat(regime): add BBWFilter for volatility-based transition blocking"
```

---

## Task 2: MTF Filter - 4-Hour Aggregation

**Files:**
- Modify: `trading/strategies/components/regime_filter.py`
- Test: `tests/trading/strategies/components/test_regime_filter.py`

**Step 1: Write the failing test**

Add to `tests/trading/strategies/components/test_regime_filter.py`:

```python
from trading.strategies.components.regime_filter import MTFFilter, MTFCandle


class TestMTFFilter:
    """Tests for Multi-Timeframe filter."""

    def test_aggregate_4_candles(self):
        """4 minute60 candles should aggregate to 1 minute240 candle."""
        f = MTFFilter()
        candles = [
            MTFCandle(open=100, high=105, low=98, close=103, volume=1000, mfi=55, adx=25),
            MTFCandle(open=103, high=108, low=101, close=106, volume=1200, mfi=58, adx=26),
            MTFCandle(open=106, high=110, low=104, close=107, volume=900, mfi=56, adx=24),
            MTFCandle(open=107, high=112, low=105, close=110, volume=1100, mfi=60, adx=27),
        ]
        agg = f.aggregate_candles(candles)
        assert agg.open == 100  # First open
        assert agg.high == 112  # Highest high
        assert agg.low == 98    # Lowest low
        assert agg.close == 110  # Last close
        assert agg.volume == 4200  # Sum
        assert agg.mfi == pytest.approx(57.25, 0.01)  # Average
        assert agg.adx == pytest.approx(25.5, 0.01)  # Average

    def test_direction_aligned_both_bull(self):
        """Both BULL should be aligned."""
        f = MTFFilter()
        assert f.is_direction_aligned("BULL_STRONG", "BULL_MODERATE") is True

    def test_direction_conflict_bull_bear(self):
        """BULL vs BEAR should conflict."""
        f = MTFFilter()
        assert f.is_direction_aligned("BULL_STRONG", "BEAR_MODERATE") is False

    def test_neutral_allows_any(self):
        """SIDEWAYS_FLAT (neutral) should allow any lower frame."""
        f = MTFFilter()
        assert f.is_direction_aligned("BULL_STRONG", "SIDEWAYS_FLAT") is True
        assert f.is_direction_aligned("BEAR_STRONG", "SIDEWAYS_FLAT") is True
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/trading/strategies/components/test_regime_filter.py::TestMTFFilter -v`
Expected: FAIL with "ImportError: cannot import name 'MTFFilter'"

**Step 3: Write minimal implementation**

Add to `trading/strategies/components/regime_filter.py`:

```python
from typing import Literal

Regime = Literal[
    "BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP",
    "SIDEWAYS_FLAT", "SIDEWAYS_DOWN",
    "BEAR_MODERATE", "BEAR_STRONG",
]

BULL_DIRECTION = {"BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"}
BEAR_DIRECTION = {"BEAR_STRONG", "BEAR_MODERATE", "SIDEWAYS_DOWN"}
NEUTRAL_DIRECTION = {"SIDEWAYS_FLAT"}


@dataclass
class MTFCandle:
    """Candle data for MTF aggregation."""
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
    """

    def __init__(self, candles_per_period: int = 4):
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
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/trading/strategies/components/test_regime_filter.py::TestMTFFilter -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add trading/strategies/components/regime_filter.py tests/trading/strategies/components/test_regime_filter.py
git commit -m "feat(regime): add MTFFilter for 4-hour direction confirmation"
```

---

## Task 3: Volume Filter

**Files:**
- Modify: `trading/strategies/components/regime_filter.py`
- Test: `tests/trading/strategies/components/test_regime_filter.py`

**Step 1: Write the failing test**

Add to `tests/trading/strategies/components/test_regime_filter.py`:

```python
from trading.strategies.components.regime_filter import VolumeFilter


class TestVolumeFilter:
    """Tests for Volume confirmation filter."""

    def test_low_volume_blocks(self):
        """Volume ratio < 0.8 should block."""
        f = VolumeFilter(block_ratio=0.8)
        assert f.should_block(volume_ratio=0.5) is True

    def test_normal_volume_allows(self):
        """Volume ratio >= 0.8 should allow."""
        f = VolumeFilter(block_ratio=0.8)
        assert f.should_block(volume_ratio=1.0) is False

    def test_bear_regime_bypasses(self):
        """BEAR regimes should bypass volume check."""
        f = VolumeFilter(block_ratio=0.8)
        assert f.should_block(volume_ratio=0.5, target_regime="BEAR_STRONG") is False
        assert f.should_block(volume_ratio=0.5, target_regime="BEAR_MODERATE") is False

    def test_sideways_regime_bypasses(self):
        """SIDEWAYS regimes should bypass volume check."""
        f = VolumeFilter(block_ratio=0.8)
        assert f.should_block(volume_ratio=0.5, target_regime="SIDEWAYS_FLAT") is False

    def test_high_volume_boosts(self):
        """High volume (>1.2) should signal boost."""
        f = VolumeFilter(boost_ratio=1.2)
        assert f.is_boosted(volume_ratio=1.5) is True
        assert f.is_boosted(volume_ratio=1.0) is False
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/trading/strategies/components/test_regime_filter.py::TestVolumeFilter -v`
Expected: FAIL with "ImportError: cannot import name 'VolumeFilter'"

**Step 3: Write minimal implementation**

Add to `trading/strategies/components/regime_filter.py`:

```python
BEAR_REGIMES = {"BEAR_STRONG", "BEAR_MODERATE"}
SIDEWAYS_REGIMES = {"SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN"}


class VolumeFilter:
    """Volume confirmation filter.

    Blocks transitions when volume is below average.
    Exceptions: BEAR and SIDEWAYS transitions (low volume is normal).
    """

    def __init__(
        self,
        block_ratio: float = 0.8,
        boost_ratio: float = 1.2,
    ):
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
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/trading/strategies/components/test_regime_filter.py::TestVolumeFilter -v`
Expected: PASS (5 tests)

**Step 5: Commit**

```bash
git add trading/strategies/components/regime_filter.py tests/trading/strategies/components/test_regime_filter.py
git commit -m "feat(regime): add VolumeFilter with BEAR/SIDEWAYS exceptions"
```

---

## Task 4: EnhancedRegimeRouter - Combined Filter

**Files:**
- Modify: `trading/strategies/components/regime_filter.py`
- Test: `tests/trading/strategies/components/test_regime_filter.py`

**Step 1: Write the failing test**

Add to `tests/trading/strategies/components/test_regime_filter.py`:

```python
from trading.strategies.components.regime_filter import EnhancedRegimeRouter
from trading.strategies.components.models import MarketData


class TestEnhancedRegimeRouter:
    """Tests for combined regime router."""

    def test_no_change_returns_same(self):
        """No regime change should return candidate immediately."""
        router = EnhancedRegimeRouter()
        result = router.get_regime(
            mfi=55, adx=26,
            bb_upper=105, bb_lower=95, bb_middle=100,
            volume_ratio=1.0,
            prev_regime="BULL_STRONG",
        )
        # With high MFI/ADX, should still be BULL_STRONG
        assert result == "BULL_STRONG"

    def test_low_bbw_blocks_transition(self):
        """Low BBW should block regime change."""
        router = EnhancedRegimeRouter()
        # Prime BBW history with high values
        for _ in range(100):
            router._bbw_filter.update_bbw(15.0)

        # Now try transition with very low BBW
        result = router.get_regime(
            mfi=30, adx=26,  # Would be BEAR
            bb_upper=101, bb_lower=99, bb_middle=100,  # BBW = 2% (very low)
            volume_ratio=1.0,
            prev_regime="BULL_STRONG",
        )
        assert result == "BULL_STRONG"  # Blocked, keep previous

    def test_mtf_conflict_blocks_transition(self):
        """MTF direction conflict should block."""
        router = EnhancedRegimeRouter(mtf_enabled=True)
        router.set_mtf_regime("BEAR_STRONG")  # 4h is bearish

        result = router.get_regime(
            mfi=60, adx=26,  # Would be BULL
            bb_upper=110, bb_lower=90, bb_middle=100,  # High BBW
            volume_ratio=1.5,  # High volume
            prev_regime="SIDEWAYS_FLAT",
        )
        assert result == "SIDEWAYS_FLAT"  # Blocked due to MTF conflict

    def test_all_filters_pass_allows_transition(self):
        """All filters passing should allow transition."""
        router = EnhancedRegimeRouter(mtf_enabled=True)
        router.set_mtf_regime("BULL_MODERATE")  # 4h is bullish

        # Prime BBW with low values so current high BBW is high percentile
        for _ in range(100):
            router._bbw_filter.update_bbw(5.0)

        result = router.get_regime(
            mfi=60, adx=28,  # BULL_STRONG
            bb_upper=115, bb_lower=85, bb_middle=100,  # BBW = 30% (high)
            volume_ratio=1.5,  # High volume
            prev_regime="SIDEWAYS_FLAT",
        )
        assert result == "BULL_STRONG"  # All filters pass
```

**Step 2: Run test to verify it fails**

Run: `source .venv/bin/activate && pytest tests/trading/strategies/components/test_regime_filter.py::TestEnhancedRegimeRouter -v`
Expected: FAIL with "ImportError: cannot import name 'EnhancedRegimeRouter'"

**Step 3: Write minimal implementation**

Add to `trading/strategies/components/regime_filter.py`:

```python
from .models import _classify_regime


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
        self._prev_regime: Regime | None = None
        self._pending_regime: Regime | None = None
        self._pending_count: int = 0

    def set_mtf_regime(self, regime: Regime) -> None:
        """Set the 4-hour timeframe regime.

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
        # Calculate candidate regime
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

        # Update BBW
        bbw = self._bbw_filter.calculate_bbw(bb_upper, bb_lower, bb_middle)
        self._bbw_filter.update_bbw(bbw)

        # Filter 1: MTF direction check
        if self._mtf_enabled and self._mtf_regime is not None:
            if not self._mtf_filter.is_direction_aligned(candidate, self._mtf_regime):
                return self._prev_regime  # Block: direction conflict

        # Filter 2: BBW check
        bbw_boosted = self._volume_filter.is_boosted(volume_ratio)
        if not bbw_boosted and self._bbw_filter.should_block():
            return self._prev_regime  # Block: low volatility

        # Filter 3: Volume check
        if self._volume_filter.should_block(volume_ratio, candidate):
            return self._prev_regime  # Block: low volume

        # Check if needs confirmation (BBW between thresholds)
        if self._bbw_filter.needs_confirmation() and not bbw_boosted:
            if candidate == self._pending_regime:
                self._pending_count += 1
                if self._pending_count >= 2:
                    self._prev_regime = candidate
                    self._pending_regime = None
                    self._pending_count = 0
                    return candidate
            else:
                self._pending_regime = candidate
                self._pending_count = 1
            return self._prev_regime  # Needs more confirmation

        # All filters passed
        self._prev_regime = candidate
        self._pending_regime = None
        self._pending_count = 0
        return candidate
```

**Step 4: Run test to verify it passes**

Run: `source .venv/bin/activate && pytest tests/trading/strategies/components/test_regime_filter.py::TestEnhancedRegimeRouter -v`
Expected: PASS (4 tests)

**Step 5: Commit**

```bash
git add trading/strategies/components/regime_filter.py tests/trading/strategies/components/test_regime_filter.py
git commit -m "feat(regime): add EnhancedRegimeRouter combining all filters"
```

---

## Task 5: Integration with CompositeStrategyTask

**Files:**
- Modify: `trading/strategies/components/composite_task.py`
- Test: Manual verification via paper trading

**Step 1: Add regime_version parameter**

Find the `__init__` method in `composite_task.py` and add:

```python
# In __init__ parameters
regime_version: str = "v1",  # "v1" = current, "v2" = enhanced

# In __init__ body
self.regime_version = regime_version
if regime_version == "v2":
    from .regime_filter import EnhancedRegimeRouter
    self._enhanced_router = EnhancedRegimeRouter()
else:
    self._enhanced_router = None
```

**Step 2: Use enhanced router when enabled**

Find where regime is classified in `_process_market_data` or similar and add:

```python
# After getting market_data
if self._enhanced_router is not None:
    regime = self._enhanced_router.get_regime(
        mfi=market_data.mfi,
        adx=market_data.adx,
        bb_upper=market_data.bb_upper,
        bb_lower=market_data.bb_lower,
        bb_middle=market_data.bb_middle,
        volume_ratio=market_data.volume / market_data.avg_volume_20 if market_data.avg_volume_20 > 0 else 1.0,
    )
else:
    regime = self.entry_strategy._classify_regime(market_data.mfi, market_data.adx)
```

**Step 3: Update allocation.json schema**

Add to strategy config:

```json
{
  "v35_long_v2": {
    "entry": "v35",
    "exit": "v35_trailing",
    "market": "futures",
    "regime_version": "v2"
  }
}
```

**Step 4: Commit**

```bash
git add trading/strategies/components/composite_task.py
git commit -m "feat(regime): integrate EnhancedRegimeRouter with CompositeStrategyTask"
```

---

## Task 6: A/B Test Configuration

**Files:**
- Modify: `config/strategies/allocation.json`

**Step 1: Add v2 strategy variants**

```json
{
  "strategies": {
    "v35_long": {
      "entry": "v35",
      "exit": "v35_trailing",
      "market": "futures",
      "regime_version": "v1"
    },
    "v35_long_v2": {
      "entry": "v35",
      "exit": "v35_trailing",
      "market": "futures",
      "regime_version": "v2",
      "position_pct": 0.15
    }
  }
}
```

**Step 2: Commit**

```bash
git add config/strategies/allocation.json
git commit -m "feat(regime): add v35_long_v2 for A/B testing"
```

---

## Summary

| Task | Description | Tests |
|------|-------------|-------|
| 1 | BBWFilter - volatility blocking | 3 |
| 2 | MTFFilter - 4h direction check | 4 |
| 3 | VolumeFilter - volume confirmation | 5 |
| 4 | EnhancedRegimeRouter - combined | 4 |
| 5 | CompositeStrategyTask integration | manual |
| 6 | A/B test configuration | manual |

**Total new tests:** 16
**Total commits:** 6
