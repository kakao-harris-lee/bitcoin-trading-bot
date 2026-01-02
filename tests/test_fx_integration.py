"""
Tests for FX Rate cache component.
"""

import pytest
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


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
