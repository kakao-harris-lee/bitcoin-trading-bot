"""Focused tests for ShortEntryStrategy boundary behavior."""

from types import MappingProxyType

from trading.strategies.components.models import (
    MarketContext,
    MarketData,
    Regime,
    TradingContext,
)
from trading.strategies.components.short_entry import (
    ShortEntryParams,
    ShortEntryStrategy,
)


def _make_context(
    regime: Regime = "BEAR_STRONG",
    rsi: float = 75.0,
    mfi: float = 30.0,
    adx: float = 30.0,
    is_extreme_volatility: bool = True,
    indicators: dict[str, float] | None = None,
) -> TradingContext:
    market = MarketData(
        symbol="BTC",
        close=100000.0,
        mfi=mfi,
        adx=adx,
        rsi=rsi,
        timestamp=1000,
        atr=2000.0,
        volume=100.0,
        avg_volume_20=80.0,
        indicators=indicators,
    )
    regime_ctx = MarketContext(
        trend="BEAR",
        regime=regime,
        volatility_score=0.04 if is_extreme_volatility else 0.01,
        is_extreme_volatility=is_extreme_volatility,
        adx=adx,
    )
    return TradingContext(
        symbol="BTC",
        timestamp=1000,
        market=market,
        regime=regime_ctx,
        positions=MappingProxyType({}),
    )


def test_no_entry_when_rsi_equals_overbought_threshold():
    params = ShortEntryParams(rsi_overbought=70.0)
    strategy = ShortEntryStrategy(params=params)
    ctx = _make_context(rsi=70.0)

    assert strategy.check_entry(ctx) is None


def test_entry_when_rsi_above_overbought_threshold():
    params = ShortEntryParams(rsi_overbought=70.0)
    strategy = ShortEntryStrategy(params=params)
    ctx = _make_context(rsi=70.1)

    signal = strategy.check_entry(ctx)
    assert signal is not None
    assert signal.side == "sell"


def test_sideways_without_extreme_volatility_is_blocked():
    strategy = ShortEntryStrategy()
    ctx = _make_context(regime="SIDEWAYS_FLAT", is_extreme_volatility=False)

    assert strategy.check_entry(ctx) is None


def test_sideways_with_extreme_volatility_allows_entry():
    strategy = ShortEntryStrategy()
    ctx = _make_context(regime="SIDEWAYS_DOWN", rsi=75.0, is_extreme_volatility=True)

    signal = strategy.check_entry(ctx)
    assert signal is not None
    assert signal.side == "sell"


def test_use_param_regime_bear_threshold_is_inclusive():
    params = ShortEntryParams(
        use_param_regime=True,
        mfi_bear=48.0,
        adx_trend=20.0,
        rsi_overbought=70.0,
    )
    strategy = ShortEntryStrategy(params=params)
    # Context regime is bullish, but use_param_regime should reclassify from MFI/ADX.
    ctx = _make_context(
        regime="BULL_STRONG",
        mfi=48.0,
        adx=20.0,
        rsi=71.0,
        is_extreme_volatility=False,
    )

    signal = strategy.check_entry(ctx)
    assert signal is not None
    assert "BEAR_STRONG" in signal.reason


def test_death_cross_can_enter_even_in_bull_regime_when_enabled():
    params = ShortEntryParams(
        require_death_cross=True,
        adx_min=25.0,
        di_negative_dominant=True,
        require_adx_not_declining=True,
    )
    strategy = ShortEntryStrategy(params=params)
    ctx = _make_context(
        regime="BULL_MODERATE",
        rsi=40.0,
        is_extreme_volatility=False,
        indicators={
            "ema_fast": 99.0,
            "ema_slow": 100.0,
            "plus_di": 20.0,
            "minus_di": 25.0,
            "adx_slope": -1.0,
        },
    )

    signal = strategy.check_entry(ctx)
    assert signal is not None
    assert "EMA Dead Cross" in signal.reason


def test_death_cross_blocked_when_di_filter_enabled_and_not_bearish():
    params = ShortEntryParams(
        require_death_cross=True,
        adx_min=25.0,
        di_negative_dominant=True,
    )
    strategy = ShortEntryStrategy(params=params)
    ctx = _make_context(
        regime="BEAR_STRONG",
        rsi=50.0,
        indicators={
            "ema_fast": 99.0,
            "ema_slow": 100.0,
            "plus_di": 25.0,
            "minus_di": 25.0,
        },
    )

    assert strategy.check_entry(ctx) is None
