"""Tests for PnL calculation utilities."""
import pytest
from trading.utils.pnl import (
    calculate_pnl_pct,
    calculate_hwm_pnl_pct,
    calculate_drawdown_from_hwm,
)


class TestCalculatePnlPct:
    """Tests for calculate_pnl_pct function."""

    def test_long_profit(self):
        """Long position with profit."""
        result = calculate_pnl_pct(105, 100, "long")
        assert result == 5.0

    def test_long_loss(self):
        """Long position with loss."""
        result = calculate_pnl_pct(95, 100, "long")
        assert result == -5.0

    def test_short_profit(self):
        """Short position with profit (price went down)."""
        result = calculate_pnl_pct(95, 100, "short")
        assert result == 5.0

    def test_short_loss(self):
        """Short position with loss (price went up)."""
        result = calculate_pnl_pct(105, 100, "short")
        assert result == -5.0

    def test_zero_entry_price(self):
        """Zero entry price returns 0."""
        result = calculate_pnl_pct(100, 0, "long")
        assert result == 0.0

    def test_negative_entry_price(self):
        """Negative entry price returns 0."""
        result = calculate_pnl_pct(100, -50, "long")
        assert result == 0.0

    def test_default_side_is_long(self):
        """Default side should be long."""
        result = calculate_pnl_pct(110, 100)
        assert result == 10.0

    def test_breakeven(self):
        """Same price returns 0."""
        result = calculate_pnl_pct(100, 100, "long")
        assert result == 0.0


class TestCalculateHwmPnlPct:
    """Tests for calculate_hwm_pnl_pct function."""

    def test_hwm_above_entry(self):
        """HWM above entry price."""
        result = calculate_hwm_pnl_pct(110, 100)
        assert result == 10.0

    def test_hwm_at_entry(self):
        """HWM at entry price (no gain yet)."""
        result = calculate_hwm_pnl_pct(100, 100)
        assert result == 0.0

    def test_zero_entry_price(self):
        """Zero entry price returns 0."""
        result = calculate_hwm_pnl_pct(110, 0)
        assert result == 0.0


class TestCalculateDrawdownFromHwm:
    """Tests for calculate_drawdown_from_hwm function."""

    def test_drawdown_5_percent(self):
        """5% drawdown from HWM."""
        result = calculate_drawdown_from_hwm(95, 100)
        assert result == 5.0

    def test_no_drawdown(self):
        """No drawdown (at HWM)."""
        result = calculate_drawdown_from_hwm(100, 100)
        assert result == 0.0

    def test_zero_hwm(self):
        """Zero HWM returns 0."""
        result = calculate_drawdown_from_hwm(95, 0)
        assert result == 0.0

    def test_large_drawdown(self):
        """Large drawdown calculation."""
        result = calculate_drawdown_from_hwm(80, 100)
        assert result == 20.0
