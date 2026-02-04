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
        "v35_classic_wide": Position(
            symbol="BTC",
            entry_price=99000.0,
            quantity=0.01,
            strategy="v35_classic_wide",
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
    assert ctx.has_position("v35_classic_wide")


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


def test_update_position_adds_new_position(mock_indicator_service):
    """update_position() adds a new position to cached context."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=None,
    )

    # First get context (no positions initially)
    ctx1 = builder.get_context("BTC", timestamp=1000)
    assert not ctx1.has_position("v35_classic_wide")

    # Add a position
    new_pos = Position(
        symbol="BTC",
        entry_price=99000.0,
        quantity=0.01,
        strategy="v35_classic_wide",
        market="futures",
        timestamp=1000,
    )
    builder.update_position("BTC", "v35_classic_wide", new_pos)

    # Check position is now visible
    ctx2 = builder.get_context("BTC", timestamp=1000)
    assert ctx2.has_position("v35_classic_wide")
    assert ctx2.positions["v35_classic_wide"].entry_price == 99000.0


def test_update_position_removes_position(mock_indicator_service, mock_position_manager):
    """update_position() with None removes position from cached context."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    # Get context with position
    ctx1 = builder.get_context("BTC", timestamp=1000)
    assert ctx1.has_position("v35_classic_wide")

    # Remove the position
    builder.update_position("BTC", "v35_classic_wide", None)

    # Check position is removed
    ctx2 = builder.get_context("BTC", timestamp=1000)
    assert not ctx2.has_position("v35_classic_wide")


def test_update_position_no_op_when_not_cached(mock_indicator_service):
    """update_position() does nothing when symbol not in cache."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=None,
    )

    # Don't get context first - symbol not cached
    new_pos = Position(
        symbol="BTC",
        entry_price=99000.0,
        quantity=0.01,
        strategy="v35_classic_wide",
        market="futures",
        timestamp=1000,
    )

    # This should not raise
    builder.update_position("BTC", "v35_classic_wide", new_pos)

    # Now get context - position manager is None so no positions
    ctx = builder.get_context("BTC", timestamp=1000)
    assert not ctx.has_position("v35_classic_wide")


def test_invalidate_single_symbol(mock_indicator_service, mock_position_manager):
    """invalidate(symbol) clears only that symbol's cache."""
    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    # Cache BTC context
    ctx1 = builder.get_context("BTC", timestamp=1000)

    # Invalidate BTC
    builder.invalidate("BTC")

    # Should rebuild on next call
    ctx2 = builder.get_context("BTC", timestamp=1000)
    assert ctx1 is not ctx2
    assert mock_indicator_service.get_market_data.call_count == 2


def test_invalidate_all_symbols(mock_indicator_service, mock_position_manager):
    """invalidate() without args clears entire cache."""
    # Setup mock to return different data per symbol
    def mock_market_data(symbol):
        return MarketData(
            symbol=symbol,
            close=100000.0 if symbol == "BTC" else 3000.0,
            mfi=55.0,
            adx=25.0,
            rsi=60.0,
            timestamp=1000,
            atr=1000.0,
            volume=100.0,
            avg_volume_20=80.0,
        )

    mock_indicator_service.get_market_data.side_effect = mock_market_data

    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    # Cache both symbols
    ctx_btc1 = builder.get_context("BTC", timestamp=1000)
    ctx_eth1 = builder.get_context("ETH", timestamp=1000)

    # Invalidate all
    builder.invalidate()

    # Both should rebuild
    ctx_btc2 = builder.get_context("BTC", timestamp=1000)
    ctx_eth2 = builder.get_context("ETH", timestamp=1000)

    assert ctx_btc1 is not ctx_btc2
    assert ctx_eth1 is not ctx_eth2
    assert mock_indicator_service.get_market_data.call_count == 4


def test_multi_symbol_cache_isolation(mock_indicator_service, mock_position_manager):
    """Different symbols have isolated cache entries."""
    # Setup mock to return different data per symbol
    def mock_market_data(symbol):
        prices = {"BTC": 100000.0, "ETH": 3000.0, "SOL": 150.0}
        return MarketData(
            symbol=symbol,
            close=prices.get(symbol, 100.0),
            mfi=55.0,
            adx=25.0,
            rsi=60.0,
            timestamp=1000,
            atr=1000.0,
            volume=100.0,
            avg_volume_20=80.0,
        )

    mock_indicator_service.get_market_data.side_effect = mock_market_data

    builder = TradingContextBuilder(
        indicator_service=mock_indicator_service,
        position_manager=mock_position_manager,
    )

    # Get context for all three symbols
    ctx_btc = builder.get_context("BTC", timestamp=1000)
    ctx_eth = builder.get_context("ETH", timestamp=1000)
    ctx_sol = builder.get_context("SOL", timestamp=1000)

    # Verify each has correct isolated data
    assert ctx_btc.market.close == 100000.0
    assert ctx_eth.market.close == 3000.0
    assert ctx_sol.market.close == 150.0

    # Verify each is cached independently
    assert builder.get_context("BTC", timestamp=1000) is ctx_btc
    assert builder.get_context("ETH", timestamp=1000) is ctx_eth
    assert builder.get_context("SOL", timestamp=1000) is ctx_sol

    # Invalidate only ETH
    builder.invalidate("ETH")

    # BTC and SOL should still be cached, ETH should rebuild
    assert builder.get_context("BTC", timestamp=1000) is ctx_btc
    assert builder.get_context("SOL", timestamp=1000) is ctx_sol
    assert builder.get_context("ETH", timestamp=1000) is not ctx_eth
