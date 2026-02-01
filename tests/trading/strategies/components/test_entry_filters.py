"""Tests for entry filters."""
import pytest
from unittest.mock import MagicMock

from trading.strategies.components.entry_filters import EntryFilters, FilterResult


class TestFilterResult:
    """Tests for FilterResult dataclass."""

    def test_passed_result(self):
        """Passed filter result."""
        result = FilterResult(passed=True)
        assert result.passed is True
        assert result.reason is None
        assert bool(result) is True

    def test_failed_result(self):
        """Failed filter result with reason."""
        result = FilterResult(passed=False, reason="test reason")
        assert result.passed is False
        assert result.reason == "test reason"
        assert bool(result) is False


class TestCheckEma200:
    """Tests for EMA200 filter."""

    def test_price_above_ema200(self):
        """Price above EMA200 should pass."""
        market_data = MagicMock()
        market_data.close = 100
        market_data.ema_200 = 95

        result = EntryFilters.check_ema200(market_data, use_filter=True)
        assert result.passed is True

    def test_price_below_ema200(self):
        """Price below EMA200 should fail."""
        market_data = MagicMock()
        market_data.close = 90
        market_data.ema_200 = 95

        result = EntryFilters.check_ema200(market_data, use_filter=True)
        assert result.passed is False
        assert "below EMA200" in result.reason

    def test_filter_disabled(self):
        """Disabled filter should pass."""
        market_data = MagicMock()
        market_data.close = 90
        market_data.ema_200 = 95

        result = EntryFilters.check_ema200(market_data, use_filter=False)
        assert result.passed is True

    def test_ema200_is_zero(self):
        """Zero EMA200 should pass (indicator not ready)."""
        market_data = MagicMock()
        market_data.close = 90
        market_data.ema_200 = 0

        result = EntryFilters.check_ema200(market_data, use_filter=True)
        assert result.passed is True


class TestCheckAdxStrength:
    """Tests for ADX strength filter."""

    def test_adx_above_threshold(self):
        """ADX above threshold should pass."""
        market_data = MagicMock()
        market_data.adx = 25.0

        result = EntryFilters.check_adx_strength(market_data, min_adx=20.0)
        assert result.passed is True

    def test_adx_below_threshold(self):
        """ADX below threshold should fail."""
        market_data = MagicMock()
        market_data.adx = 15.0

        result = EntryFilters.check_adx_strength(market_data, min_adx=20.0)
        assert result.passed is False
        assert "weak trend" in result.reason


class TestCheckNotBearRegime:
    """Tests for bear regime filter."""

    def test_bull_regime_passes(self):
        """Bull regime should pass."""
        result = EntryFilters.check_not_bear_regime("BULL_STRONG")
        assert result.passed is True

    def test_bear_strong_fails(self):
        """BEAR_STRONG should fail."""
        result = EntryFilters.check_not_bear_regime("BEAR_STRONG")
        assert result.passed is False
        assert "BEAR regime" in result.reason

    def test_bear_moderate_fails(self):
        """BEAR_MODERATE should fail."""
        result = EntryFilters.check_not_bear_regime("BEAR_MODERATE")
        assert result.passed is False

    def test_custom_bear_regimes(self):
        """Custom bear regimes set."""
        result = EntryFilters.check_not_bear_regime(
            "SIDEWAYS_DOWN",
            bear_regimes={"SIDEWAYS_DOWN", "BEAR"}
        )
        assert result.passed is False


class TestCheckMfiThreshold:
    """Tests for MFI threshold filter."""

    def test_mfi_above_threshold(self):
        """MFI above threshold should pass."""
        market_data = MagicMock()
        market_data.mfi = 55.0

        result = EntryFilters.check_mfi_threshold(market_data, min_mfi=50.0)
        assert result.passed is True

    def test_mfi_below_threshold(self):
        """MFI below threshold should fail."""
        market_data = MagicMock()
        market_data.mfi = 45.0

        result = EntryFilters.check_mfi_threshold(market_data, min_mfi=50.0)
        assert result.passed is False
        assert "low MFI" in result.reason


class TestCheckMfiRange:
    """Tests for MFI range filter."""

    def test_mfi_in_range(self):
        """MFI in range should pass."""
        market_data = MagicMock()
        market_data.mfi = 50.0

        result = EntryFilters.check_mfi_range(market_data, min_mfi=40.0, max_mfi=60.0)
        assert result.passed is True

    def test_mfi_too_low(self):
        """MFI below range should fail."""
        market_data = MagicMock()
        market_data.mfi = 30.0

        result = EntryFilters.check_mfi_range(market_data, min_mfi=40.0, max_mfi=60.0)
        assert result.passed is False
        assert "too low" in result.reason

    def test_mfi_too_high(self):
        """MFI above range should fail."""
        market_data = MagicMock()
        market_data.mfi = 70.0

        result = EntryFilters.check_mfi_range(market_data, min_mfi=40.0, max_mfi=60.0)
        assert result.passed is False
        assert "too high" in result.reason


class TestCheckVolatility:
    """Tests for volatility filter."""

    def test_volatility_in_range(self):
        """Volatility in range should pass."""
        result = EntryFilters.check_volatility(0.02, min_vol=0.01, max_vol=0.05)
        assert result.passed is True

    def test_volatility_too_low(self):
        """Volatility below minimum should fail."""
        result = EntryFilters.check_volatility(0.005, min_vol=0.01, max_vol=0.05)
        assert result.passed is False
        assert "too low" in result.reason

    def test_volatility_too_high(self):
        """Volatility above maximum should fail."""
        result = EntryFilters.check_volatility(0.10, min_vol=0.01, max_vol=0.05)
        assert result.passed is False
        assert "too high" in result.reason
