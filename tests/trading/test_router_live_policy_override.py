import pandas as pd

from trading.modules.regime_router import RegimeDecision
from trading.scripts.backtest_v2_strategies import RegimeRouterLiveAdapter


def _df(n: int = 80) -> pd.DataFrame:
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


def test_sideways_policy_hold_disables_entries(monkeypatch):
    adapter = RegimeRouterLiveAdapter(timeframe="day", sideways_policy="hold")
    df = _df(120)

    # Force market_state to sideways
    monkeypatch.setattr(adapter.router, "classify_from_values", lambda mfi, adx: "SIDEWAYS_NEUTRAL")

    sig = adapter(df, 60, {})
    assert sig["action"] == "hold"


def test_bear_moderate_policy_overrides_upbit_strategy(monkeypatch):
    adapter = RegimeRouterLiveAdapter(timeframe="day", bear_moderate_policy="v35")

    # Force BEAR_MODERATE and ensure default decision is None (hold)
    monkeypatch.setattr(adapter.router, "classify_from_values", lambda mfi, adx: "BEAR_MODERATE")
    monkeypatch.setattr(
        adapter.router,
        "decide_from_market_state",
        lambda market_state: RegimeDecision(
            market_state=market_state,  # type: ignore[arg-type]
            regime="BEAR",  # type: ignore[arg-type]
            upbit_strategy=None,
            binance_strategy="short_v1",
        ),
    )

    assert adapter._pick_strategy("BEAR_MODERATE") == "v35"


def test_bull_policy_hold_long_enters_and_exits(monkeypatch):
    adapter = RegimeRouterLiveAdapter(timeframe="day", bull_policy="hold_long")
    df = _df(120)

    # Enter on BULL
    monkeypatch.setattr(adapter.router, "classify_from_values", lambda mfi, adx: "BULL_STRONG")
    sig1 = adapter(df, 60, {})
    assert sig1["action"] == "buy"
    assert float(sig1.get("fraction", 0.0)) == 1.0

    # Exit when leaving BULL
    monkeypatch.setattr(adapter.router, "classify_from_values", lambda mfi, adx: "BEAR_STRONG")
    sig2 = adapter(df, 61, {})
    assert sig2["action"] == "sell"
    assert float(sig2.get("fraction", 0.0)) == 1.0
