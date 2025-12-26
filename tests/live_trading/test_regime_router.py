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


def test_decide_from_market_state_routes_correct_strategies():
    router = RegimeRouter()

    bull = router.decide_from_market_state("BULL_MODERATE")
    assert bull.regime == "BULL"
    assert bull.upbit_strategy == "v35"
    assert bull.binance_strategy is None

    sideways = router.decide_from_market_state("SIDEWAYS_NEUTRAL")
    assert sideways.regime == "SIDEWAYS"
    assert sideways.upbit_strategy == "sideways_v2"
    assert sideways.binance_strategy is None

    bear = router.decide_from_market_state("BEAR_STRONG")
    assert bear.regime == "BEAR"
    assert bear.upbit_strategy is None
    assert bear.binance_strategy == "short_v1"


def test_decide_from_market_state_supports_hold_long_policy_and_binance_gate_modes():
    router = RegimeRouter(
        bull_policy="hold_long",
        sideways_policy="v35",
        sideways_bear_policy="sideways_v2",
        bear_moderate_policy="hold",
        bear_strong_policy="hold",
        binance_gate_mode="bear_strong_only",
    )

    bull = router.decide_from_market_state("BULL_STRONG")
    assert bull.upbit_strategy == "bull_hold"
    assert bull.binance_strategy is None

    # SIDEWAYS_BEAR uses override (sideways_v2)
    swb = router.decide_from_market_state("SIDEWAYS_BEAR")
    assert swb.upbit_strategy == "sideways_v2"
    # gate is bear_strong_only -> no Binance
    assert swb.binance_strategy is None

    # BEAR_MODERATE: Binance gate requires BEAR_STRONG
    bm = router.decide_from_market_state("BEAR_MODERATE")
    assert bm.upbit_strategy is None
    assert bm.binance_strategy is None

    bs = router.decide_from_market_state("BEAR_STRONG")
    assert bs.upbit_strategy is None
    assert bs.binance_strategy == "short_v1"
