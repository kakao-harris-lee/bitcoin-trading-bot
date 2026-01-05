"""Tests for MultiAssetAlphaManager long exposure methods."""

import pytest
from unittest.mock import MagicMock, patch
from pathlib import Path


@pytest.fixture
def mock_portfolio():
    """Create a mock portfolio manager."""
    portfolio = MagicMock()
    portfolio.get_symbols.return_value = ["BTC"]
    return portfolio


@pytest.fixture
def mock_config():
    """Create a basic config for testing."""
    return {"assets": {"BTC": {"enabled": True}}}


class TestGetLongExposureKrw:
    """Tests for get_long_exposure_krw method."""

    def test_returns_active_position_value(self, mock_portfolio, mock_config):
        """Test that get_long_exposure_krw returns correct KRW value."""
        # Patch state file operations
        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'exists', return_value=False):
            from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

            manager = MultiAssetAlphaManager(
                portfolio=mock_portfolio,
                config=mock_config,
            )

            # Set up state with active position
            manager._states["BTC"].active = True
            manager._states["BTC"].quantity = 0.1
            manager._states["BTC"].current_price = 100_000_000  # 100M KRW

            exposure = manager.get_long_exposure_krw("BTC")
            assert exposure == 10_000_000  # 0.1 * 100M = 10M KRW

    def test_returns_zero_when_no_position(self, mock_portfolio, mock_config):
        """Test that get_long_exposure_krw returns 0 when no position."""
        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'exists', return_value=False):
            from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

            manager = MultiAssetAlphaManager(
                portfolio=mock_portfolio,
                config=mock_config,
            )

            exposure = manager.get_long_exposure_krw("BTC")
            assert exposure == 0.0

    def test_returns_zero_when_inactive(self, mock_portfolio, mock_config):
        """Test that get_long_exposure_krw returns 0 when position is inactive."""
        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'exists', return_value=False):
            from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

            manager = MultiAssetAlphaManager(
                portfolio=mock_portfolio,
                config=mock_config,
            )

            # Set up state with inactive position (default)
            manager._states["BTC"].active = False
            manager._states["BTC"].quantity = 0.1  # Has quantity but inactive
            manager._states["BTC"].current_price = 100_000_000

            exposure = manager.get_long_exposure_krw("BTC")
            assert exposure == 0.0

    def test_returns_zero_when_zero_quantity(self, mock_portfolio, mock_config):
        """Test that get_long_exposure_krw returns 0 when quantity is zero."""
        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'exists', return_value=False):
            from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

            manager = MultiAssetAlphaManager(
                portfolio=mock_portfolio,
                config=mock_config,
            )

            # Set up state with zero quantity
            manager._states["BTC"].active = True
            manager._states["BTC"].quantity = 0.0
            manager._states["BTC"].current_price = 100_000_000

            exposure = manager.get_long_exposure_krw("BTC")
            assert exposure == 0.0

    def test_returns_zero_for_unknown_symbol(self, mock_portfolio, mock_config):
        """Test that get_long_exposure_krw returns 0 for unknown symbol."""
        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'exists', return_value=False):
            from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

            manager = MultiAssetAlphaManager(
                portfolio=mock_portfolio,
                config=mock_config,
            )

            exposure = manager.get_long_exposure_krw("UNKNOWN")
            assert exposure == 0.0

    def test_default_symbol_is_btc(self, mock_portfolio, mock_config):
        """Test that default symbol is BTC."""
        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'exists', return_value=False):
            from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

            manager = MultiAssetAlphaManager(
                portfolio=mock_portfolio,
                config=mock_config,
            )

            # Set up BTC position
            manager._states["BTC"].active = True
            manager._states["BTC"].quantity = 0.05
            manager._states["BTC"].current_price = 200_000_000

            # Call without symbol argument
            exposure = manager.get_long_exposure_krw()
            assert exposure == 10_000_000  # 0.05 * 200M = 10M KRW


class TestGetTotalLongExposureKrw:
    """Tests for get_total_long_exposure_krw method."""

    def test_returns_sum_of_all_exposures(self):
        """Test that get_total_long_exposure_krw sums all active positions."""
        # Setup for multi-asset
        mock_portfolio = MagicMock()
        mock_portfolio.get_symbols.return_value = ["BTC", "ETH"]
        config = {
            "assets": {
                "BTC": {"enabled": True},
                "ETH": {"enabled": True},
            }
        }

        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'exists', return_value=False):
            from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

            manager = MultiAssetAlphaManager(
                portfolio=mock_portfolio,
                config=config,
            )

            # Set up BTC position
            manager._states["BTC"].active = True
            manager._states["BTC"].quantity = 0.1
            manager._states["BTC"].current_price = 100_000_000  # 10M KRW

            # Set up ETH position
            manager._states["ETH"].active = True
            manager._states["ETH"].quantity = 2.0
            manager._states["ETH"].current_price = 5_000_000  # 10M KRW

            total_exposure = manager.get_total_long_exposure_krw()
            assert total_exposure == 20_000_000  # 10M + 10M = 20M KRW

    def test_returns_zero_when_no_positions(self, mock_portfolio, mock_config):
        """Test that get_total_long_exposure_krw returns 0 when no positions."""
        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'exists', return_value=False):
            from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

            manager = MultiAssetAlphaManager(
                portfolio=mock_portfolio,
                config=mock_config,
            )

            total_exposure = manager.get_total_long_exposure_krw()
            assert total_exposure == 0.0

    def test_only_includes_active_positions(self):
        """Test that only active positions are included in total."""
        mock_portfolio = MagicMock()
        mock_portfolio.get_symbols.return_value = ["BTC", "ETH"]
        config = {
            "assets": {
                "BTC": {"enabled": True},
                "ETH": {"enabled": True},
            }
        }

        with patch.object(Path, 'mkdir'), \
             patch.object(Path, 'exists', return_value=False):
            from trading.execution.multi_asset_alpha_manager import MultiAssetAlphaManager

            manager = MultiAssetAlphaManager(
                portfolio=mock_portfolio,
                config=config,
            )

            # BTC is active
            manager._states["BTC"].active = True
            manager._states["BTC"].quantity = 0.1
            manager._states["BTC"].current_price = 100_000_000  # 10M KRW

            # ETH is inactive
            manager._states["ETH"].active = False
            manager._states["ETH"].quantity = 2.0
            manager._states["ETH"].current_price = 5_000_000

            total_exposure = manager.get_total_long_exposure_krw()
            assert total_exposure == 10_000_000  # Only BTC counted
