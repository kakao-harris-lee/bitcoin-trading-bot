"""Tests for trading constants."""
from trading.config.constants import FeeRates, TimePeriods


class TestFeeRates:
    """Tests for FeeRates constants."""

    def test_spot_fee_rate(self):
        """Spot fee rate is 0.05%."""
        assert FeeRates.SPOT == 0.0005

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
