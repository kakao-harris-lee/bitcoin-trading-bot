"""Tests for trading constants."""
import pytest
from trading.config.constants import (
    FeeRates,
    TimePeriods,
    LeverageDefaults,
    DrawdownThresholds,
)


class TestFeeRates:
    """Tests for FeeRates constants."""

    def test_futures_fee_rate(self):
        """Futures fee rate is 0.04%."""
        assert FeeRates.FUTURES == 0.0004

    def test_spot_fee_rate(self):
        """Spot fee rate is 0.05%."""
        assert FeeRates.SPOT == 0.0005

    def test_futures_slippage(self):
        """Futures slippage is 0.02%."""
        assert FeeRates.FUTURES_SLIPPAGE == 0.0002

    def test_spot_slippage(self):
        """Spot slippage is 0."""
        assert FeeRates.SPOT_SLIPPAGE == 0.0


class TestTimePeriods:
    """Tests for TimePeriods constants."""

    def test_rf_history_window(self):
        """RF history window is 720 candles (30 days hourly)."""
        assert TimePeriods.RF_HISTORY_WINDOW == 720

    def test_min_history_required(self):
        """Minimum history for LSTM is 60 candles."""
        assert TimePeriods.MIN_HISTORY_REQUIRED == 60

    def test_backtest_warmup(self):
        """Backtest warmup is 200 candles."""
        assert TimePeriods.BACKTEST_WARMUP == 200

    def test_stop_loss_cooldown(self):
        """Stop loss cooldown is 24 candles (1 day)."""
        assert TimePeriods.STOP_LOSS_COOLDOWN == 24

    def test_trading_days_per_year(self):
        """Trading days per year for Sharpe ratio."""
        assert TimePeriods.TRADING_DAYS_PER_YEAR == 252


class TestLeverageDefaults:
    """Tests for LeverageDefaults constants."""

    def test_max_leverage(self):
        """Maximum leverage is 3x."""
        assert LeverageDefaults.MAX == 3.0

    def test_bull_strong_leverage(self):
        """Bull strong leverage is 3x."""
        assert LeverageDefaults.BULL_STRONG == 3.0

    def test_bull_moderate_leverage(self):
        """Bull moderate leverage is 2x."""
        assert LeverageDefaults.BULL_MODERATE == 2.0

    def test_sideways_leverage(self):
        """Sideways leverage is 1x."""
        assert LeverageDefaults.SIDEWAYS == 1.0

    def test_bear_leverage(self):
        """Bear leverage is 0 (cash)."""
        assert LeverageDefaults.BEAR == 0.0


class TestDrawdownThresholds:
    """Tests for DrawdownThresholds constants."""

    def test_warning_threshold(self):
        """Warning threshold is 8%."""
        assert DrawdownThresholds.WARNING == 8.0

    def test_reduce_threshold(self):
        """Reduce threshold is 10%."""
        assert DrawdownThresholds.REDUCE == 10.0

    def test_exit_threshold(self):
        """Exit threshold is 12%."""
        assert DrawdownThresholds.EXIT == 12.0

    def test_thresholds_are_ordered(self):
        """Thresholds are in correct order."""
        assert DrawdownThresholds.WARNING < DrawdownThresholds.REDUCE
        assert DrawdownThresholds.REDUCE < DrawdownThresholds.EXIT
