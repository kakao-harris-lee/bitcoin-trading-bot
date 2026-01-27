"""Tests for regime filters.

Tests BBW, MTF, and Volume filters for enhanced regime detection.
"""

import pytest

from trading.strategies.components.regime_filter import (
    BBWFilter,
    MTFFilter,
    MTFCandle,
    VolumeFilter,
)


class TestBBWFilter:
    """Tests for Bollinger Band Width filter."""

    def test_bbw_calculation(self):
        """BBW = (upper - lower) / middle * 100."""
        f = BBWFilter()
        bbw = f.calculate_bbw(bb_upper=105, bb_lower=95, bb_middle=100)
        assert bbw == 10.0  # (105-95)/100*100 = 10%

    def test_bbw_calculation_narrow_bands(self):
        """Narrow bands produce small BBW."""
        f = BBWFilter()
        bbw = f.calculate_bbw(bb_upper=101, bb_lower=99, bb_middle=100)
        assert bbw == 2.0  # (101-99)/100*100 = 2%

    def test_bbw_calculation_zero_middle(self):
        """Zero middle band returns 0."""
        f = BBWFilter()
        bbw = f.calculate_bbw(bb_upper=105, bb_lower=95, bb_middle=0)
        assert bbw == 0.0

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

    def test_bbw_percentile_insufficient_data(self):
        """Insufficient data returns 50 (middle percentile)."""
        f = BBWFilter()
        assert f.get_percentile() == 50.0  # Default when no data

    def test_needs_confirmation_middle_range(self):
        """BBW between 25-50 percentile needs confirmation."""
        f = BBWFilter(block_threshold=25, confirm_threshold=50)
        # Fill with values so current is around 35th percentile
        for i in range(100):
            f.update_bbw(10.0 + i * 0.1)  # 10.0 to 19.9
        # Current at ~35th percentile (below median, above block)
        f.update_bbw(13.5)
        assert f.needs_confirmation() is True
        assert f.should_block() is False


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
        assert agg.low == 98  # Lowest low
        assert agg.close == 110  # Last close
        assert agg.volume == 4200  # Sum
        assert agg.mfi == pytest.approx(57.25, 0.01)  # Average
        assert agg.adx == pytest.approx(25.5, 0.01)  # Average

    def test_add_candle_returns_aggregated_when_full(self):
        """add_candle returns aggregated after 4 candles."""
        f = MTFFilter(candles_per_period=4)
        for i in range(3):
            result = f.add_candle(MTFCandle(100, 105, 95, 100, 1000, 50, 20))
            assert result is None  # Not full yet
        result = f.add_candle(MTFCandle(100, 110, 90, 105, 1500, 55, 25))
        assert result is not None  # Should return aggregated
        assert result.high == 110
        assert result.low == 90

    def test_direction_aligned_both_bull(self):
        """Both BULL should be aligned."""
        f = MTFFilter()
        assert f.is_direction_aligned("BULL_STRONG", "BULL_MODERATE") is True
        assert f.is_direction_aligned("BULL_MODERATE", "BULL_STRONG") is True
        assert f.is_direction_aligned("SIDEWAYS_UP", "BULL_STRONG") is True

    def test_direction_aligned_both_bear(self):
        """Both BEAR should be aligned."""
        f = MTFFilter()
        assert f.is_direction_aligned("BEAR_STRONG", "BEAR_MODERATE") is True
        assert f.is_direction_aligned("SIDEWAYS_DOWN", "BEAR_STRONG") is True

    def test_direction_conflict_bull_bear(self):
        """BULL vs BEAR should conflict."""
        f = MTFFilter()
        assert f.is_direction_aligned("BULL_STRONG", "BEAR_MODERATE") is False
        assert f.is_direction_aligned("SIDEWAYS_UP", "BEAR_STRONG") is False
        assert f.is_direction_aligned("BEAR_MODERATE", "BULL_STRONG") is False

    def test_neutral_allows_any(self):
        """SIDEWAYS_FLAT (neutral) should allow any lower frame."""
        f = MTFFilter()
        assert f.is_direction_aligned("BULL_STRONG", "SIDEWAYS_FLAT") is True
        assert f.is_direction_aligned("BEAR_STRONG", "SIDEWAYS_FLAT") is True
        assert f.is_direction_aligned("SIDEWAYS_UP", "SIDEWAYS_FLAT") is True

    def test_get_direction(self):
        """Direction grouping should work correctly."""
        f = MTFFilter()
        assert f.get_direction("BULL_STRONG") == "BULL"
        assert f.get_direction("BULL_MODERATE") == "BULL"
        assert f.get_direction("SIDEWAYS_UP") == "BULL"
        assert f.get_direction("SIDEWAYS_FLAT") == "NEUTRAL"
        assert f.get_direction("SIDEWAYS_DOWN") == "BEAR"
        assert f.get_direction("BEAR_MODERATE") == "BEAR"
        assert f.get_direction("BEAR_STRONG") == "BEAR"


class TestVolumeFilter:
    """Tests for Volume confirmation filter."""

    def test_low_volume_blocks(self):
        """Volume ratio < 0.8 should block."""
        f = VolumeFilter(block_ratio=0.8)
        assert f.should_block(volume_ratio=0.5) is True
        assert f.should_block(volume_ratio=0.7) is True
        assert f.should_block(volume_ratio=0.79) is True

    def test_normal_volume_allows(self):
        """Volume ratio >= 0.8 should allow."""
        f = VolumeFilter(block_ratio=0.8)
        assert f.should_block(volume_ratio=0.8) is False
        assert f.should_block(volume_ratio=1.0) is False
        assert f.should_block(volume_ratio=1.5) is False

    def test_bear_regime_bypasses(self):
        """BEAR regimes should bypass volume check."""
        f = VolumeFilter(block_ratio=0.8)
        assert f.should_block(volume_ratio=0.5, target_regime="BEAR_STRONG") is False
        assert f.should_block(volume_ratio=0.5, target_regime="BEAR_MODERATE") is False

    def test_sideways_regime_bypasses(self):
        """SIDEWAYS regimes should bypass volume check."""
        f = VolumeFilter(block_ratio=0.8)
        assert f.should_block(volume_ratio=0.5, target_regime="SIDEWAYS_FLAT") is False
        assert f.should_block(volume_ratio=0.5, target_regime="SIDEWAYS_UP") is False
        assert f.should_block(volume_ratio=0.5, target_regime="SIDEWAYS_DOWN") is False

    def test_bull_regime_not_bypassed(self):
        """BULL regimes should NOT bypass volume check."""
        f = VolumeFilter(block_ratio=0.8)
        assert f.should_block(volume_ratio=0.5, target_regime="BULL_STRONG") is True
        assert f.should_block(volume_ratio=0.5, target_regime="BULL_MODERATE") is True

    def test_high_volume_boosts(self):
        """High volume (>1.2) should signal boost."""
        f = VolumeFilter(boost_ratio=1.2)
        assert f.is_boosted(volume_ratio=1.5) is True
        assert f.is_boosted(volume_ratio=1.3) is True
        assert f.is_boosted(volume_ratio=1.21) is True

    def test_normal_volume_not_boosted(self):
        """Normal volume should not signal boost."""
        f = VolumeFilter(boost_ratio=1.2)
        assert f.is_boosted(volume_ratio=1.0) is False
        assert f.is_boosted(volume_ratio=1.2) is False
        assert f.is_boosted(volume_ratio=0.9) is False
