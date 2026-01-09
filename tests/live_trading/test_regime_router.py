import pytest

from trading.strategy.regime_router import RegimeRouter


@pytest.mark.parametrize(
    "mfi,adx,expected",
    [
        (60.0, 30.0, "BULL_STRONG"),
        (60.0, 22.0, "BULL_MODERATE"),
        (60.0, 10.0, "SIDEWAYS_BULL"),
        (40.0, 25.0, "BEAR_STRONG"),
        (40.0, 16.0, "BEAR_MODERATE"),
        (40.0, 10.0, "SIDEWAYS_BEAR"),
        (50.0, 30.0, "SIDEWAYS_NEUTRAL"),
    ],
)
def test_classify_from_values_thresholds(mfi, adx, expected):
    router = RegimeRouter(
        mfi_bull=52.0,
        mfi_bear=48.0,
        adx_strong=25.0,
        adx_trend=20.0,
        adx_weak=15.0,
    )
    assert router.classify_from_values(mfi=mfi, adx=adx) == expected


def test_market_state_to_regime():
    """Test that market_state_to_regime correctly maps states to regimes."""
    router = RegimeRouter()

    assert router.market_state_to_regime("BULL_STRONG") == "BULL"
    assert router.market_state_to_regime("BULL_MODERATE") == "BULL"
    assert router.market_state_to_regime("SIDEWAYS_BULL") == "SIDEWAYS"
    assert router.market_state_to_regime("SIDEWAYS_NEUTRAL") == "SIDEWAYS"
    assert router.market_state_to_regime("SIDEWAYS_BEAR") == "SIDEWAYS"
    assert router.market_state_to_regime("BEAR_MODERATE") == "BEAR"
    assert router.market_state_to_regime("BEAR_STRONG") == "BEAR"


def test_deprecated_params_ignored():
    """Test that deprecated policy parameters are silently ignored."""
    # Should not raise, deprecated params absorbed by **kwargs
    router = RegimeRouter(
        bull_policy="hold_long",
        sideways_policy="v35",
        binance_gate_mode="bear_strong_only",
    )
    # Router should still work for classification
    assert router.classify_from_values(mfi=60.0, adx=30.0) == "BULL_STRONG"
