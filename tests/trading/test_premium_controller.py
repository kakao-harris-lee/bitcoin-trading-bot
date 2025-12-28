"""Tests for PremiumController."""

import pytest
from datetime import datetime, timedelta
from unittest.mock import patch
import tempfile
import os

from trading.risk.premium_controller import (
    PremiumController,
    PremiumStats,
    HedgeSignal,
    PremiumReading,
)


@pytest.fixture
def temp_history_file():
    """Create a temporary history file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write('{"readings": []}')
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)


@pytest.fixture
def controller(temp_history_file):
    """Create PremiumController with temp history file."""
    config = {
        "history_file": temp_history_file,
        "entry_threshold_pct": 1.5,
        "entry_sigma": 2.0,
        "min_hold_minutes": 30,
        "negative_funding_exit": -0.05,
    }
    return PremiumController(config)


class TestPremiumStats:
    """Test premium statistics calculation."""

    def test_empty_history_returns_default_stats(self, controller):
        """Empty history should return zero stats."""
        stats = controller.get_stats()
        assert stats.current == 0.0
        assert stats.mean_24h == 0.0
        assert stats.readings_count == 0

    def test_single_reading_returns_current(self, controller):
        """Single reading should set current value."""
        controller.record({
            "premium_pct": 3.5,
            "upbit_usd": 95000,
            "binance_usd": 92000,
            "usd_krw_rate": 1450,
        })

        stats = controller.get_stats()
        assert stats.current == 3.5
        assert stats.readings_count == 1

    def test_multiple_readings_calculate_mean_std(self, controller):
        """Multiple readings should calculate mean and std."""
        premiums = [2.0, 2.5, 3.0, 2.5, 3.5]

        for p in premiums:
            controller.record({
                "premium_pct": p,
                "upbit_usd": 95000,
                "binance_usd": 92000,
                "usd_krw_rate": 1450,
            })

        stats = controller.get_stats()
        assert stats.current == 3.5
        assert 2.5 <= stats.mean_24h <= 2.8  # Mean of [2, 2.5, 3, 2.5, 3.5]
        assert stats.std_24h > 0
        assert stats.readings_count == 5

    def test_volatility_state_classification(self, controller):
        """Test volatility state is correctly classified."""
        # Normal volatility (std < 1%)
        for i in range(10):
            controller.record({
                "premium_pct": 2.0 + (i * 0.05),  # Small variation
                "upbit_usd": 95000,
                "binance_usd": 92000,
                "usd_krw_rate": 1450,
            })

        stats = controller.get_stats()
        assert stats.volatility_state == "normal"

    def test_high_volatility_classification(self, controller):
        """High std should trigger high volatility state."""
        # Large swings
        for p in [1.0, 5.0, 1.0, 6.0, 0.5, 7.0]:
            controller.record({
                "premium_pct": p,
                "upbit_usd": 95000,
                "binance_usd": 92000,
                "usd_krw_rate": 1450,
            })

        stats = controller.get_stats()
        assert stats.volatility_state == "high"


class TestHedgeSignalGeneration:
    """Test hedge signal generation logic."""

    def test_no_signal_below_threshold(self, controller):
        """No entry signal when premium below threshold."""
        # Add baseline readings
        for _ in range(10):
            controller.record({
                "premium_pct": 1.0,  # Below 1.5% threshold
                "upbit_usd": 95000,
                "binance_usd": 94000,
                "usd_krw_rate": 1450,
            })

        signal = controller.generate_signal(
            premium_info={"premium_pct": 1.0},
            upbit_btc_qty=0.5,
        )

        assert signal.action == "hold"

    def test_entry_signal_above_mean_plus_2sigma(self, controller):
        """Entry signal when premium > mean + 2*std AND > threshold."""
        # Build history with mean ~2%, std ~0.5%
        for p in [1.8, 2.0, 2.2, 2.0, 1.8, 2.2, 2.0]:
            controller.record({
                "premium_pct": p,
                "upbit_usd": 95000,
                "binance_usd": 93000,
                "usd_krw_rate": 1450,
            })

        # Current premium: 4.5% (well above mean + 2*std)
        signal = controller.generate_signal(
            premium_info={
                "premium_pct": 4.5,
                "upbit_usd": 95000,
                "binance_usd": 90900,
                "usd_krw_rate": 1450,
            },
            upbit_btc_qty=0.5,
        )

        assert signal.action == "open"
        assert signal.target_btc_qty == 0.5
        assert "entry" in signal.reason

    def test_no_entry_in_high_volatility(self, controller):
        """No entry when volatility is high (slippage guard)."""
        # Create high volatility history
        for p in [1.0, 5.0, 1.0, 6.0, 0.5]:
            controller.record({
                "premium_pct": p,
                "upbit_usd": 95000,
                "binance_usd": 92000,
                "usd_krw_rate": 1450,
            })

        # Even high premium shouldn't trigger entry
        signal = controller.generate_signal(
            premium_info={
                "premium_pct": 8.0,
                "upbit_usd": 95000,
                "binance_usd": 88000,
                "usd_krw_rate": 1450,
            },
            upbit_btc_qty=0.5,
        )

        assert signal.action == "hold"
        assert "volatility" in signal.reason

    def test_exit_on_mean_reversion(self, controller):
        """Exit signal when premium reverts to mean."""
        # Build history
        for p in [3.0, 3.2, 3.0, 2.8, 3.0]:
            controller.record({
                "premium_pct": p,
                "upbit_usd": 95000,
                "binance_usd": 92000,
                "usd_krw_rate": 1450,
            })

        # Simulate open position
        controller.set_position_state(True, datetime.now() - timedelta(hours=1))

        # Current premium at mean
        signal = controller.generate_signal(
            premium_info={
                "premium_pct": 3.0,
                "upbit_usd": 95000,
                "binance_usd": 92233,
                "usd_krw_rate": 1450,
            },
            upbit_btc_qty=0.5,
        )

        assert signal.action == "close"
        assert "mean_reversion" in signal.reason

    def test_exit_on_negative_funding(self, controller):
        """Exit signal when funding rate too negative."""
        # Build history with high premium
        for p in [4.0, 4.5, 4.2, 4.8, 5.0]:
            controller.record({
                "premium_pct": p,
                "upbit_usd": 95000,
                "binance_usd": 91000,
                "usd_krw_rate": 1450,
            })

        # Simulate position and negative funding
        controller.set_position_state(True, datetime.now() - timedelta(hours=1))
        controller.set_funding_rate(-0.08)  # Below -0.05% threshold

        # Current premium ABOVE mean (so mean_reversion doesn't trigger)
        signal = controller.generate_signal(
            premium_info={
                "premium_pct": 5.5,  # Above mean ~4.5%
                "upbit_usd": 95000,
                "binance_usd": 90000,
                "usd_krw_rate": 1450,
            },
            upbit_btc_qty=0.5,
        )

        assert signal.action == "close"
        assert "negative_funding" in signal.reason

    def test_min_hold_time_prevents_early_exit(self, controller):
        """Exit blocked if minimum hold time not reached."""
        # Build history
        for p in [3.0, 3.5, 4.0, 4.5, 5.0]:
            controller.record({
                "premium_pct": p,
                "upbit_usd": 95000,
                "binance_usd": 91000,
                "usd_krw_rate": 1450,
            })

        # Position opened just now (less than 30 min ago)
        controller.set_position_state(True, datetime.now())

        # Premium at mean, but hold time not reached
        signal = controller.generate_signal(
            premium_info={
                "premium_pct": 4.0,  # At mean
                "upbit_usd": 95000,
                "binance_usd": 91346,
                "usd_krw_rate": 1450,
            },
            upbit_btc_qty=0.5,
        )

        assert signal.action == "hold"
        assert "min_hold" in signal.reason


class TestFormatAndAlert:
    """Test formatting and alert functions."""

    def test_format_status(self, controller):
        """Test status formatting."""
        controller.record({
            "premium_pct": 3.5,
            "upbit_usd": 95000,
            "binance_usd": 92000,
            "usd_krw_rate": 1450,
        })

        status = controller.format_status()
        assert "3.5" in status or "+3.5" in status
        assert "Premium" in status

    def test_should_alert_on_entry_opportunity(self, controller):
        """Alert when entry opportunity detected."""
        # Build low premium history
        for _ in range(10):
            controller.record({
                "premium_pct": 1.0,
                "upbit_usd": 95000,
                "binance_usd": 94000,
                "usd_krw_rate": 1450,
            })

        # Add high premium (entry opportunity)
        controller.record({
            "premium_pct": 5.0,
            "upbit_usd": 95000,
            "binance_usd": 90476,
            "usd_krw_rate": 1450,
        })

        alert = controller.should_alert()
        assert alert is not None
        assert "Entry" in alert or "Opportunity" in alert
