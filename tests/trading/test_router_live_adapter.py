import pandas as pd

from trading.scripts.backtest_v2_strategies import RegimeRouterLiveAdapter


def _df(n: int = 80) -> pd.DataFrame:
    # simple monotonic series with volume; indicators should be computable
    ts = pd.date_range("2020-01-01", periods=n, freq="D")
    close = pd.Series(range(10_000, 10_000 + n), dtype=float)
    return pd.DataFrame(
        {
            "timestamp": ts,
            "open": close,
            "high": close + 1,
            "low": close - 1,
            "close": close,
            "volume": 1_000.0,
        }
    )


def test_router_live_stickiness_clears_on_full_exit(monkeypatch):
    adapter = RegimeRouterLiveAdapter(timeframe="day")
    df = _df(120)

    # force regime pick to v35
    monkeypatch.setattr(adapter.router, "classify_from_values", lambda mfi, adx: "BULL_MODERATE")

    # make v35 emit buy then full sell
    calls = {"n": 0}

    def fake_v35(_df, _i, _params):
        calls["n"] += 1
        if calls["n"] == 1:
            return {"action": "buy", "fraction": 0.3, "reason": "TEST_BUY"}
        if calls["n"] == 2:
            return {"action": "sell", "fraction": 1.0, "reason": "TEST_SELL"}
        return {"action": "hold"}

    monkeypatch.setattr(adapter, "_delegate", lambda key, d, i, p: fake_v35(d, i, p))

    s1 = adapter(df, 60, {})
    assert s1["action"] == "buy"
    assert adapter._active_strategy == "v35"

    s2 = adapter(df, 61, {})
    assert s2["action"] == "sell"
    assert adapter._active_strategy is None
