"""Tests for regime filters.

Tests BBW, MTF, and Volume filters for enhanced regime detection.
"""

import pytest

from trading.strategies.components.regime_filter import BBWFilter


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
