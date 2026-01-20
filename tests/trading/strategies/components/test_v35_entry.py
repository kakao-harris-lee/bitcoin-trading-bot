"""Tests for V35EntryStrategy with TradingContext."""

import pytest
from trading.strategies.components.v35_entry import V35EntryStrategy, V35EntryParams
from trading.strategies.components.models import (
    TradingContext, MarketData, MarketContext, Position, build_market_context
)


def _make_context(
    mfi: float = 55.0,
    adx: float = 25.0,
    rsi: float = 60.0,
    macd: float = 10.0,
    macd_signal: float = 5.0,
    close: float = 100000.0,
) -> TradingContext:
    """Helper to create TradingContext for tests."""
    market = MarketData(
        symbol="BTC",
        close=close,
        mfi=mfi,
        adx=adx,
        rsi=rsi,
        timestamp=1000,
        macd=macd,
        macd_signal=macd_signal,
        atr=1000.0,
        volume=100.0,
        avg_volume_20=80.0,
    )
    regime = build_market_context(mfi=mfi, adx=adx, atr=1000.0, close=close)
    return TradingContext(symbol="BTC", timestamp=1000, market=market, regime=regime, positions={})


def test_v35_entry_bull_strong_signal():
    """V35 entry generates signal in BULL_STRONG with MACD crossover."""
    strategy = V35EntryStrategy()
    ctx = _make_context(mfi=55.0, adx=26.0, rsi=58.0, macd=10.0, macd_signal=5.0)

    signal = strategy.check_entry(ctx)

    assert signal is not None
    assert signal.side == "buy"
    assert "MOMENTUM" in signal.reason


def test_v35_entry_no_signal_bear_regime():
    """V35 entry returns None in BEAR regime."""
    strategy = V35EntryStrategy()
    ctx = _make_context(mfi=30.0, adx=26.0)  # BEAR_STRONG

    signal = strategy.check_entry(ctx)

    assert signal is None


def test_v35_entry_no_signal_weak_adx():
    """V35 entry returns None when ADX is weak."""
    strategy = V35EntryStrategy()
    ctx = _make_context(mfi=55.0, adx=15.0)  # Weak ADX

    signal = strategy.check_entry(ctx)

    assert signal is None
