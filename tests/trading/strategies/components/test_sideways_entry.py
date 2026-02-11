"""Focused tests for SidewaysEntryStrategy boundary behavior."""

from types import MappingProxyType

from trading.strategies.components.models import (
    MarketContext,
    MarketData,
    Regime,
    TradingContext,
)
from trading.strategies.components.sideways_entry import (
    SidewaysEntryParams,
    SidewaysEntryStrategy,
)


def _make_context(
    regime: Regime = "SIDEWAYS_FLAT",
    rsi: float = 35.0,
    is_high_volume: bool = False,
    volume_ratio: float = 1.0,
    is_extreme_volatility: bool = False,
) -> TradingContext:
    market = MarketData(
        symbol="BTC",
        close=100000.0,
        mfi=50.0,
        adx=15.0,
        rsi=rsi,
        timestamp=1000,
        atr=1000.0,
        volume=100.0,
        avg_volume_20=100.0,
    )
    regime_ctx = MarketContext(
        trend="NEUTRAL",
        regime=regime,
        volatility_score=0.04 if is_extreme_volatility else 0.01,
        is_extreme_volatility=is_extreme_volatility,
        adx=15.0,
        volume_ratio=volume_ratio,
        is_high_volume=is_high_volume,
    )
    return TradingContext(
        symbol="BTC",
        timestamp=1000,
        market=market,
        regime=regime_ctx,
        positions=MappingProxyType({}),
    )


def test_entry_triggers_when_rsi_equals_oversold_threshold():
    strategy = SidewaysEntryStrategy(SidewaysEntryParams(rsi_oversold=35.0))
    ctx = _make_context(rsi=35.0)

    signal = strategy.check_entry(ctx)
    assert signal is not None
    assert signal.side == "buy"


def test_entry_not_triggered_when_rsi_above_oversold_threshold():
    strategy = SidewaysEntryStrategy(SidewaysEntryParams(rsi_oversold=35.0))
    ctx = _make_context(rsi=35.1)

    assert strategy.check_entry(ctx) is None


def test_entry_blocked_by_high_volume_even_if_oversold():
    strategy = SidewaysEntryStrategy()
    ctx = _make_context(rsi=20.0, is_high_volume=True, volume_ratio=1.8)

    assert strategy.check_entry(ctx) is None


def test_entry_blocked_when_non_sideways_regime():
    strategy = SidewaysEntryStrategy()
    ctx = _make_context(regime="BULL_STRONG", rsi=20.0)

    assert strategy.check_entry(ctx) is None


def test_entry_blocked_by_extreme_volatility():
    strategy = SidewaysEntryStrategy()
    ctx = _make_context(rsi=20.0, is_extreme_volatility=True)

    assert strategy.check_entry(ctx) is None


def test_classify_regime_threshold_boundaries():
    strategy = SidewaysEntryStrategy(
        SidewaysEntryParams(mfi_bull=52.0, mfi_bear=48.0, adx_trend=20.0)
    )

    assert strategy._classify_regime(52.0, 20.0) == "BULL_MODERATE"
    assert strategy._classify_regime(52.0, 19.9) == "SIDEWAYS_BULL"
    assert strategy._classify_regime(48.0, 20.0) == "BEAR_MODERATE"
    assert strategy._classify_regime(48.0, 19.9) == "SIDEWAYS_BEAR"
    assert strategy._classify_regime(50.0, 10.0) == "SIDEWAYS_NEUTRAL"
