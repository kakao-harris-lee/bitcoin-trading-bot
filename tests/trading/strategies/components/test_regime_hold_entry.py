"""Tests for RegimeHoldEntryStrategy."""

from types import MappingProxyType

from trading.strategies.components.regime_hold_entry import (
    RegimeHoldEntryParams,
    RegimeHoldEntryStrategy,
)
from trading.strategies.components.models import (
    MarketContext,
    MarketData,
    Regime,
    TradingContext,
)


def _make_context(
    regime: Regime = "BULL_STRONG",
    adx: float = 25.0,
    is_extreme_volatility: bool = False,
) -> TradingContext:
    market = MarketData(
        symbol="BTC",
        close=100000.0,
        mfi=55.0,
        adx=adx,
        rsi=50.0,
        timestamp=1000,
        atr=1500.0,
        volume=100.0,
        avg_volume_20=100.0,
    )
    market_context = MarketContext(
        trend="BULL",
        regime=regime,
        volatility_score=0.01,
        is_extreme_volatility=is_extreme_volatility,
        adx=adx,
        volume_ratio=1.0,
        is_high_volume=False,
    )
    return TradingContext(
        symbol="BTC",
        timestamp=1000,
        market=market,
        regime=market_context,
        positions=MappingProxyType({}),
    )


def test_entry_blocked_by_extreme_volatility():
    strategy = RegimeHoldEntryStrategy()
    ctx = _make_context(is_extreme_volatility=True)

    assert strategy.check_entry(ctx) is None


def test_entry_allowed_when_extreme_volatility_enabled():
    params = RegimeHoldEntryParams(allow_extreme_volatility=True)
    strategy = RegimeHoldEntryStrategy(params=params)
    ctx = _make_context(is_extreme_volatility=True)

    signal = strategy.check_entry(ctx)
    assert signal is not None
    assert signal.side == "buy"


def test_entry_blocked_by_min_adx():
    params = RegimeHoldEntryParams(min_adx=30.0)
    strategy = RegimeHoldEntryStrategy(params=params)
    ctx = _make_context(adx=20.0)

    assert strategy.check_entry(ctx) is None


def test_entry_allowed_when_adx_equals_min_adx():
    params = RegimeHoldEntryParams(min_adx=20.0, allowed_regimes=["BULL_STRONG"])
    strategy = RegimeHoldEntryStrategy(params=params)
    ctx = _make_context(regime="BULL_STRONG", adx=20.0)

    signal = strategy.check_entry(ctx)
    assert signal is not None
    assert signal.side == "buy"


def test_entry_signal_in_allowed_regime():
    params = RegimeHoldEntryParams(
        allowed_regimes=["BEAR_MODERATE"],
        market="spot",
        position_size=0.02,
    )
    strategy = RegimeHoldEntryStrategy(params=params)
    ctx = _make_context(regime="BEAR_MODERATE")

    signal = strategy.check_entry(ctx)
    assert signal is not None
    assert signal.symbol == "BTC"
    assert signal.side == "buy"
    assert signal.market == "spot"
    assert signal.quantity == 0.02
    assert "RegimeHold entry" in signal.reason


def test_entry_none_for_disallowed_regime():
    params = RegimeHoldEntryParams(allowed_regimes=["BEAR_STRONG"])
    strategy = RegimeHoldEntryStrategy(params=params)
    ctx = _make_context(regime="SIDEWAYS_FLAT")

    assert strategy.check_entry(ctx) is None
