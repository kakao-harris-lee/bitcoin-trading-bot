"""Tests for TradingContext dataclass."""

import pytest
from trading.strategies.components.models import (
    TradingContext,
    MarketData,
    MarketContext,
    Position,
    build_market_context,
)


def test_trading_context_creation():
    """TradingContext can be created with all required fields."""
    market = MarketData(
        symbol="BTC",
        close=100000.0,
        mfi=55.0,
        adx=25.0,
        rsi=60.0,
        timestamp=1000,
    )
    regime = build_market_context(mfi=55.0, adx=25.0, atr=1000.0, close=100000.0)
    positions = {
        "v35_long": Position(
            symbol="BTC",
            entry_price=99000.0,
            quantity=0.01,
            strategy="v35_long",
            market="futures",
            timestamp=900,
        )
    }

    ctx = TradingContext(
        symbol="BTC",
        timestamp=1000,
        market=market,
        regime=regime,
        positions=positions,
    )

    assert ctx.symbol == "BTC"
    assert ctx.market.close == 100000.0
    assert ctx.regime.regime == "BULL_STRONG"
    assert "v35_long" in ctx.positions


def test_trading_context_has_position():
    """TradingContext.has_position returns correct boolean."""
    market = MarketData(symbol="BTC", close=100000.0, mfi=50.0, adx=20.0, rsi=50.0, timestamp=1000)
    regime = build_market_context(mfi=50.0, adx=20.0, atr=1000.0, close=100000.0)
    positions = {"v35_long": Position(symbol="BTC", entry_price=99000.0, quantity=0.01, strategy="v35_long", market="futures", timestamp=900)}

    ctx = TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions=positions)

    assert ctx.has_position("v35_long") is True
    assert ctx.has_position("short_v1") is False


def test_trading_context_get_position():
    """TradingContext.get_position returns position or None."""
    market = MarketData(symbol="BTC", close=100000.0, mfi=50.0, adx=20.0, rsi=50.0, timestamp=1000)
    regime = build_market_context(mfi=50.0, adx=20.0, atr=1000.0, close=100000.0)
    pos = Position(symbol="BTC", entry_price=99000.0, quantity=0.01, strategy="v35_long", market="futures", timestamp=900)
    positions = {"v35_long": pos}

    ctx = TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions=positions)

    assert ctx.get_position("v35_long") == pos
    assert ctx.get_position("nonexistent") is None


def test_trading_context_other_strategies_positioned():
    """TradingContext.other_strategies_positioned excludes specified strategy."""
    market = MarketData(symbol="BTC", close=100000.0, mfi=50.0, adx=20.0, rsi=50.0, timestamp=1000)
    regime = build_market_context(mfi=50.0, adx=20.0, atr=1000.0, close=100000.0)
    positions = {
        "v35_long": Position(symbol="BTC", entry_price=99000.0, quantity=0.01, strategy="v35_long", market="futures", timestamp=900),
        "sideways": Position(symbol="BTC", entry_price=98000.0, quantity=0.02, strategy="sideways", market="futures", timestamp=800),
    }

    ctx = TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions=positions)

    others = ctx.other_strategies_positioned("v35_long")
    assert "sideways" in others
    assert "v35_long" not in others


def test_trading_context_immutable():
    """TradingContext is immutable (frozen dataclass)."""
    market = MarketData(symbol="BTC", close=100000.0, mfi=50.0, adx=20.0, rsi=50.0, timestamp=1000)
    regime = build_market_context(mfi=50.0, adx=20.0, atr=1000.0, close=100000.0)

    ctx = TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions={})

    with pytest.raises(Exception):  # FrozenInstanceError or dataclasses.FrozenInstanceError
        ctx.symbol = "ETH"
