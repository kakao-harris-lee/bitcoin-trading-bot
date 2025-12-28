"""
Tests for DataCache integration with AlphaManager and RegimeRouter.
"""

import pytest
from unittest.mock import MagicMock, patch
import pandas as pd
from datetime import datetime


class TestRegimeRouterDataCache:
    """Test RegimeRouter uses DataCache correctly."""

    def _create_sample_df(self, rows: int = 200) -> pd.DataFrame:
        """Create sample daily DataFrame."""
        return pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "open": [100000] * rows,
            "high": [101000] * rows,
            "low": [99000] * rows,
            "close": [100500] * rows,
            "volume": [1000] * rows,
        })

    def test_regime_router_accepts_data_cache(self):
        """RegimeRouter accepts data_cache parameter."""
        from trading.strategy.regime_router import RegimeRouter

        mock_cache = MagicMock()
        router = RegimeRouter(data_cache=mock_cache)

        assert router.data_cache is mock_cache

    def test_regime_router_uses_cache_when_available(self):
        """RegimeRouter.get_recent_daily_df uses cache when available."""
        from trading.strategy.regime_router import RegimeRouter

        # Cache.get() with periods returns tail, so simulate that
        sample_df = self._create_sample_df(180)
        mock_cache = MagicMock()
        mock_cache.get.return_value = sample_df

        router = RegimeRouter(lookback_days=180, data_cache=mock_cache)
        result = router.get_recent_daily_df()

        mock_cache.get.assert_called_once_with('day', periods=180)
        assert len(result) == 180

    def test_regime_router_fallback_without_cache(self):
        """RegimeRouter falls back to DataLoader when cache is None."""
        from trading.strategy.regime_router import RegimeRouter

        router = RegimeRouter(data_cache=None)

        # Mock DataLoader
        sample_df = self._create_sample_df(200)
        with patch('trading.strategy.regime_router.DataLoader') as mock_loader_class:
            mock_loader = MagicMock()
            mock_loader.__enter__ = MagicMock(return_value=mock_loader)
            mock_loader.__exit__ = MagicMock(return_value=False)
            mock_loader.load_timeframe.return_value = sample_df
            mock_loader_class.return_value = mock_loader

            result = router.get_recent_daily_df()

            mock_loader.load_timeframe.assert_called_once()
            assert len(result) == 200

    def test_regime_router_fallback_on_empty_cache(self):
        """RegimeRouter falls back when cache returns empty DataFrame."""
        from trading.strategy.regime_router import RegimeRouter

        mock_cache = MagicMock()
        mock_cache.get.return_value = pd.DataFrame()  # Empty

        router = RegimeRouter(lookback_days=180, data_cache=mock_cache)

        # Mock DataLoader
        sample_df = self._create_sample_df(200)
        with patch('trading.strategy.regime_router.DataLoader') as mock_loader_class:
            mock_loader = MagicMock()
            mock_loader.__enter__ = MagicMock(return_value=mock_loader)
            mock_loader.__exit__ = MagicMock(return_value=False)
            mock_loader.load_timeframe.return_value = sample_df
            mock_loader_class.return_value = mock_loader

            result = router.get_recent_daily_df()

            # Should fallback to DataLoader
            mock_loader.load_timeframe.assert_called_once()


class TestAlphaManagerDataCache:
    """Test AlphaManager uses DataCache correctly."""

    def _create_sample_df(self, rows: int = 500) -> pd.DataFrame:
        """Create sample daily DataFrame."""
        return pd.DataFrame({
            "timestamp": pd.date_range("2024-01-01", periods=rows, freq="D"),
            "open": [100000] * rows,
            "high": [101000] * rows,
            "low": [99000] * rows,
            "close": [100500] * rows,
            "volume": [1000] * rows,
        })

    def _create_mock_alpha_manager(self, data_cache=None):
        """Create AlphaManager with mocked dependencies."""
        from trading.execution.alpha_manager import AlphaManager
        from trading.strategy.regime_router import RegimeRouter

        # Mock account
        mock_account = MagicMock()
        mock_account.get_balance.return_value = (10_000_000, 0)

        # Mock router
        mock_router = MagicMock(spec=RegimeRouter)

        return AlphaManager(
            upbit_account=mock_account,
            regime_router=mock_router,
            allocation_config={"upbit": {}},
            data_cache=data_cache,
        )

    def test_alpha_manager_accepts_data_cache(self):
        """AlphaManager accepts data_cache parameter."""
        mock_cache = MagicMock()
        alpha_manager = self._create_mock_alpha_manager(data_cache=mock_cache)

        assert alpha_manager.data_cache is mock_cache

    def test_alpha_manager_get_daily_df_uses_cache(self):
        """AlphaManager._get_daily_df uses cache when available."""
        sample_df = self._create_sample_df(600)
        mock_cache = MagicMock()
        mock_cache.get.return_value = sample_df

        alpha_manager = self._create_mock_alpha_manager(data_cache=mock_cache)
        result = alpha_manager._get_daily_df()

        mock_cache.get.assert_called_once_with('day')
        assert len(result) == 500  # tail(500)

    def test_alpha_manager_get_daily_df_fallback_without_cache(self):
        """AlphaManager._get_daily_df falls back when cache is None."""
        alpha_manager = self._create_mock_alpha_manager(data_cache=None)

        sample_df = self._create_sample_df(600)
        with patch('trading.execution.alpha_manager.DataLoader') as mock_loader_class:
            mock_loader = MagicMock()
            mock_loader.__enter__ = MagicMock(return_value=mock_loader)
            mock_loader.__exit__ = MagicMock(return_value=False)
            mock_loader.load_timeframe.return_value = sample_df
            mock_loader_class.return_value = mock_loader

            result = alpha_manager._get_daily_df()

            mock_loader.load_timeframe.assert_called_once()
            assert len(result) == 500

    def test_alpha_manager_get_daily_df_fallback_on_empty_cache(self):
        """AlphaManager._get_daily_df falls back when cache returns empty."""
        mock_cache = MagicMock()
        mock_cache.get.return_value = pd.DataFrame()  # Empty

        alpha_manager = self._create_mock_alpha_manager(data_cache=mock_cache)

        sample_df = self._create_sample_df(600)
        with patch('trading.execution.alpha_manager.DataLoader') as mock_loader_class:
            mock_loader = MagicMock()
            mock_loader.__enter__ = MagicMock(return_value=mock_loader)
            mock_loader.__exit__ = MagicMock(return_value=False)
            mock_loader.load_timeframe.return_value = sample_df
            mock_loader_class.return_value = mock_loader

            result = alpha_manager._get_daily_df()

            # Should fallback to DataLoader
            mock_loader.load_timeframe.assert_called_once()


class TestDataCachePreloadAndRefresh:
    """Test DataCache preload and refresh behavior."""

    def test_data_cache_preload_sync(self):
        """DataCache.preload_sync loads specified timeframes."""
        from trading.data.data_cache import DataCache

        with patch('trading.data.data_cache.DataLoader') as mock_loader_class:
            mock_loader = MagicMock()
            mock_loader.__enter__ = MagicMock(return_value=mock_loader)
            mock_loader.__exit__ = MagicMock(return_value=False)
            mock_loader.load_timeframe.return_value = pd.DataFrame({
                "timestamp": [datetime.now()],
                "close": [100000],
            })
            mock_loader_class.return_value = mock_loader

            cache = DataCache()
            cache.preload_sync(['day', 'minute60'])

            # Should have called load_timeframe for both
            assert mock_loader.load_timeframe.call_count == 2

    def test_data_cache_refresh_if_stale_sync(self):
        """DataCache.refresh_if_stale_sync refreshes stale caches."""
        from trading.data.data_cache import DataCache

        with patch('trading.data.data_cache.DataLoader') as mock_loader_class:
            mock_loader = MagicMock()
            mock_loader.__enter__ = MagicMock(return_value=mock_loader)
            mock_loader.__exit__ = MagicMock(return_value=False)
            mock_loader.load_timeframe.return_value = pd.DataFrame({
                "timestamp": [datetime.now()],
                "close": [100000],
            })
            mock_loader_class.return_value = mock_loader

            cache = DataCache()
            # All caches are stale initially
            cache.refresh_if_stale_sync()

            # Should have refreshed all default timeframes (day, minute60, minute15, minute5)
            assert mock_loader.load_timeframe.call_count >= 1

    def test_data_cache_get_returns_copy(self):
        """DataCache.get returns a copy of cached data."""
        from trading.data.data_cache import DataCache

        sample_df = pd.DataFrame({"a": [1, 2, 3]})

        cache = DataCache()
        cache._cache['test'] = sample_df

        result1 = cache.get('test')
        result2 = cache.get('test')

        # Modifying one shouldn't affect the other
        result1['a'] = [10, 20, 30]
        assert list(result2['a']) == [1, 2, 3]
