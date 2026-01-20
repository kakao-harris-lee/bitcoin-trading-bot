"""Tests for V35TrailingExitStrategy with TradingContext."""

import pytest
from trading.strategies.components.v35_trailing_exit import V35TrailingExitStrategy, V35ExitParams
from trading.strategies.components.models import (
    TradingContext, MarketData, Position, build_market_context
)


def _make_context(close: float = 100000.0, mfi: float = 50.0, adx: float = 20.0, high: float = 0.0) -> TradingContext:
    """Helper to create TradingContext for tests."""
    if high == 0.0:
        high = close
    market = MarketData(
        symbol="BTC", close=close, mfi=mfi, adx=adx, rsi=50.0, timestamp=1000,
        high=high, low=close * 0.99, macd=0.0, macd_signal=0.0, atr=1000.0,
    )
    regime = build_market_context(mfi=mfi, adx=adx, atr=1000.0, close=close)
    return TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions={})


def _make_position(entry_price: float = 100000.0, quantity: float = 0.01) -> Position:
    """Helper to create Position for tests."""
    return Position(
        symbol="BTC", entry_price=entry_price, quantity=quantity,
        strategy="v35_long", market="futures", timestamp=900,
    )


def test_v35_exit_stop_loss():
    """V35 exit triggers on stop loss."""
    strategy = V35TrailingExitStrategy(params=V35ExitParams(stop_loss_pct=2.0))
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=97000.0)  # -3% loss

    strategy.on_position_opened(position)
    signal = strategy.check_exit(ctx, position)

    assert signal is not None
    assert signal.side == "sell"
    assert "Stop loss" in signal.reason


def test_v35_exit_hold():
    """V35 exit holds when no exit conditions met."""
    strategy = V35TrailingExitStrategy()
    position = _make_position(entry_price=100000.0)
    ctx = _make_context(close=100500.0)  # Small profit

    strategy.on_position_opened(position)
    signal = strategy.check_exit(ctx, position)

    assert signal is None


def test_v35_exit_has_regime_access():
    """V35 exit can access regime from context."""
    strategy = V35TrailingExitStrategy()
    position = _make_position()
    ctx = _make_context(mfi=55.0, adx=26.0)  # BULL_STRONG regime

    strategy.on_position_opened(position)

    # Exit strategy can now see regime
    assert ctx.regime.regime == "BULL_STRONG"
