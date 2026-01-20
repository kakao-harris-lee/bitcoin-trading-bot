"""Tests for TradingContextBuilder."""

import pytest
from unittest.mock import MagicMock, AsyncMock
from trading.strategies.components.context_builder import TradingContextBuilder
from trading.strategies.components.models import MarketData, Position


@pytest.fixture
def mock_indicator_service():
    """Create mock IndicatorService."""
    service = MagicMock()
    service.get_market_data.return_value = MarketData(
        symbol="BTC",
        close=100000.0,
        mfi=55.0,
        adx=25.0,
        rsi=60.0,
        timestamp=1000,
        atr=1000.0,
        volume=100.0,
        avg_volume_20=80.0,
    )
    return service


@pytest.fixture
def mock_position_manager():
    """Create mock PositionManager."""
    manager = MagicMock()
    manager.get_positions_for_symbol.return_value = {
        "v35_long": Position(
            symbol="BTC",
            entry_price=99000.0,
            quantity=0.01,
            strategy="v35_long",
            market="futures",
            timestamp=900,
        )
    }
    return manager


def test_builder_creates_context(mock_indicator_service, mock_position_manager):
    """TradingContextBuilder creates TradingContext with all components."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    ctx = builder.get_context("BTC", timestamp=1000)

    assert ctx.symbol == "BTC"
    assert ctx.timestamp == 1000
    assert ctx.market.close == 100000.0
    assert ctx.regime.regime == "BULL_STRONG"
    assert ctx.has_position("v35_long")


def test_builder_caches_same_tick(mock_indicator_service, mock_position_manager):
    """TradingContextBuilder caches context for same timestamp."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    ctx1 = builder.get_context("BTC", timestamp=1000)
    ctx2 = builder.get_context("BTC", timestamp=1000)

    assert ctx1 is ctx2  # Same object returned
    assert mock_indicator_service.get_market_data.call_count == 1  # Only called once


def test_builder_invalidates_on_new_tick(mock_indicator_service, mock_position_manager):
    """TradingContextBuilder invalidates cache on new timestamp."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    ctx1 = builder.get_context("BTC", timestamp=1000)
    ctx2 = builder.get_context("BTC", timestamp=2000)

    assert ctx1 is not ctx2  # Different objects
    assert mock_indicator_service.get_market_data.call_count == 2  # Called twice


def test_builder_handles_no_market_data(mock_position_manager):
    """TradingContextBuilder returns None when no market data available."""
    service = MagicMock()
    service.get_market_data.return_value = None

    builder = TradingContextBuilder(
        indicator_service=service,
        position_manager=mock_position_manager,
    )

    ctx = builder.get_context("BTC", timestamp=1000)

    assert ctx is None
