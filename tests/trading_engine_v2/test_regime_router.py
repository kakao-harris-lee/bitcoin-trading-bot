import pandas as pd

from trading_engine_v2.scripts.backtest_v2_strategies import RegimeRouterV1Adapter


def _make_min_df(n: int = 40) -> pd.DataFrame:
    # Minimal OHLCV required by Backtester interface
    ts = pd.date_range("2020-01-01", periods=n, freq="D")
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": [100.0] * n,
            "high": [101.0] * n,
            "low": [99.0] * n,
            "close": [100.0] * n,
            "volume": [1.0] * n,
        }
    )


class _StubStrategy:
    def __init__(self, signals_by_i):
        self.signals_by_i = dict(signals_by_i)
        self.calls = []

    def __call__(self, df, i, params):
        self.calls.append(i)
        return self.signals_by_i.get(i, {"action": "hold"})


def test_router_picks_v35_on_bull_and_sticks_until_full_exit(monkeypatch):
    df = _make_min_df()
    router = RegimeRouterV1Adapter(timeframe="day")

    # Force classifier to always return BULL
    monkeypatch.setattr(router, "_classify_market_state", lambda _df, _i: "BULL_STRONG")

    # v35: buy at i=30, partial sell at 31, full sell at 32
    router.v35 = _StubStrategy(
        {
            30: {"action": "buy", "fraction": 0.5},
            31: {"action": "sell", "fraction": 0.4},
            32: {"action": "sell", "fraction": 1.0},
        }
    )
    # sideways should never be called in this test
    router.sideways_v2 = _StubStrategy({30: {"action": "buy", "fraction": 0.5}})

    # i<30 warmup
    assert router(df, 10, {})["action"] == "hold"

    # entry picks v35
    s30 = router(df, 30, {})
    assert s30["action"] == "buy"
    assert router._active_strategy == "v35"

    # stickiness: keeps delegating to v35
    s31 = router(df, 31, {})
    assert s31["action"] == "sell" and s31["fraction"] == 0.4
    assert router._active_strategy == "v35"

    # full exit clears active
    s32 = router(df, 32, {})
    assert s32["action"] == "sell" and s32["fraction"] == 1.0
    assert router._active_strategy is None

    assert router.sideways_v2.calls == []


def test_router_picks_sideways_on_sideways_regime(monkeypatch):
    df = _make_min_df()
    router = RegimeRouterV1Adapter(timeframe="day")

    monkeypatch.setattr(router, "_classify_market_state", lambda _df, _i: "SIDEWAYS_FLAT")

    router.v35 = _StubStrategy({30: {"action": "buy", "fraction": 0.5}})
    router.sideways_v2 = _StubStrategy({30: {"action": "buy", "fraction": 0.5}})

    s30 = router(df, 30, {})
    assert s30["action"] == "buy"
    assert router._active_strategy == "sideways_v2"
    assert router.v35.calls == []


def test_router_holds_on_bear_regime(monkeypatch):
    df = _make_min_df()
    router = RegimeRouterV1Adapter(timeframe="day")

    monkeypatch.setattr(router, "_classify_market_state", lambda _df, _i: "BEAR_STRONG")

    router.v35 = _StubStrategy({30: {"action": "buy", "fraction": 0.5}})
    router.sideways_v2 = _StubStrategy({30: {"action": "buy", "fraction": 0.5}})

    s30 = router(df, 30, {})
    assert s30["action"] == "hold"
    # ensure neither strategy called
    assert router.v35.calls == []
    assert router.sideways_v2.calls == []
