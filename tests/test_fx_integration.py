"""
Tests for FX Rate integration in trading engine.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


class TestFXRateIntegration:
    """Test FX rate integration in calculate_kimchi_premium."""

    def _create_mock_engine(self, fx_rate=None, fx_stale=False):
        """Create a mock engine with optional FX cache."""
        engine = MagicMock()
        engine._allocation_config = {
            "premium_tracking": {"usd_krw_rate": 1450}
        }

        if fx_rate is not None:
            engine.fx_cache = MagicMock()
            engine.fx_cache.rate = fx_rate
            engine.fx_cache.is_stale = fx_stale
        else:
            engine.fx_cache = None

        # Import and bind the actual method
        from trading.engine import DualPaperTradingEngine
        engine.calculate_kimchi_premium = lambda prices: DualPaperTradingEngine.calculate_kimchi_premium(engine, prices)

        return engine

    def test_premium_uses_live_fx_rate(self):
        """Premium calculation uses FXRateCache.rate when available."""
        engine = self._create_mock_engine(fx_rate=1380)

        prices = {"upbit": 100_000_000, "binance": 68_000}
        result = engine.calculate_kimchi_premium(prices)

        # With 1380: 100M / 1380 = 72,463.77 USD
        # Premium: (72463.77 - 68000) / 68000 * 100 = 6.56%
        assert result["usd_krw_rate"] == 1380
        assert 6.5 <= result["premium_pct"] <= 6.6
        assert result["fx_stale"] is False

    def test_fallback_when_no_cache(self):
        """Uses config default when fx_cache not available."""
        engine = self._create_mock_engine(fx_rate=None)

        prices = {"upbit": 100_000_000, "binance": 68_000}
        result = engine.calculate_kimchi_premium(prices)

        assert result["usd_krw_rate"] == 1450  # Config default
        assert result["fx_stale"] is False

    def test_rejects_out_of_bounds_rate_low(self):
        """Sanity check rejects invalid FX rates (too low)."""
        engine = self._create_mock_engine(fx_rate=500)

        prices = {"upbit": 100_000_000, "binance": 68_000}
        result = engine.calculate_kimchi_premium(prices)

        assert result["usd_krw_rate"] == 1450  # Fallback

    def test_rejects_out_of_bounds_rate_high(self):
        """Sanity check rejects invalid FX rates (too high)."""
        engine = self._create_mock_engine(fx_rate=2000)

        prices = {"upbit": 100_000_000, "binance": 68_000}
        result = engine.calculate_kimchi_premium(prices)

        assert result["usd_krw_rate"] == 1450  # Fallback

    def test_stale_rate_still_used(self):
        """Stale rate is still used but marked as stale."""
        engine = self._create_mock_engine(fx_rate=1400, fx_stale=True)

        prices = {"upbit": 100_000_000, "binance": 68_000}
        result = engine.calculate_kimchi_premium(prices)

        assert result["usd_krw_rate"] == 1400  # Still uses it
        assert result["fx_stale"] is True

    def test_zero_binance_price(self):
        """Handles zero binance price gracefully."""
        engine = self._create_mock_engine(fx_rate=1400)

        prices = {"upbit": 100_000_000, "binance": 0}
        result = engine.calculate_kimchi_premium(prices)

        assert result["premium_pct"] == 0.0
        assert result["binance_usd"] == 0.0

    def test_premium_calculation_accuracy(self):
        """Verify premium calculation formula."""
        engine = self._create_mock_engine(fx_rate=1450)

        # Known values for easy calculation
        # Upbit: 145,000,000 KRW / 1450 = 100,000 USD
        # Binance: 95,000 USD
        # Premium: (100000 - 95000) / 95000 * 100 = 5.26%
        prices = {"upbit": 145_000_000, "binance": 95_000}
        result = engine.calculate_kimchi_premium(prices)

        assert result["upbit_usd"] == 100_000.0
        assert result["binance_usd"] == 95_000.0
        assert result["premium_pct"] == 5.26


class TestFXRateCache:
    """Test FXRateCache component directly."""

    @pytest.mark.asyncio
    async def test_fx_cache_start_stop(self):
        """FXRateCache can start and stop."""
        from trading.core.fx_cache import FXRateCache

        cache = FXRateCache(default_rate=1450, refresh_interval=60)
        assert cache.rate == 1450

        # Mock aiohttp to avoid actual API calls
        with patch('aiohttp.ClientSession') as mock_session:
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.json = AsyncMock(return_value={"rates": {"KRW": 1380}})
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=None)

            mock_session_instance = MagicMock()
            mock_session_instance.get = MagicMock(return_value=mock_response)
            mock_session_instance.close = AsyncMock()
            mock_session.return_value = mock_session_instance

            await cache.start()
            assert cache._started is True

            await cache.stop()
            assert cache._started is False

    def test_is_stale_detection(self):
        """Test stale detection logic."""
        from trading.core.fx_cache import FXRateCache

        cache = FXRateCache(default_rate=1450, refresh_interval=300)

        # No update yet - should be stale
        assert cache.is_stale is True

        # Simulate recent update
        cache._updated_at = datetime.now()
        assert cache.is_stale is False

    def test_rate_bounds(self):
        """Test rate property returns correct value."""
        from trading.core.fx_cache import FXRateCache

        cache = FXRateCache(default_rate=1450)
        assert cache.rate == 1450

        cache._rate = 1380
        assert cache.rate == 1380
