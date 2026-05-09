"""Tests for dashboard backtest strategy list generation."""

from types import SimpleNamespace

import pandas as pd

from web.services import backtest_runner


def _mock_spec(market: str = "spot") -> SimpleNamespace:
    return SimpleNamespace(market=market)


def test_get_available_strategies_only_includes_enabled_allocation(monkeypatch):
    monkeypatch.setattr(
        backtest_runner,
        "STRATEGY_REGISTRY",
        {
            "llm_direction": _mock_spec("spot"),
            "regime_long_v2": _mock_spec("spot"),
        },
    )
    monkeypatch.setattr(
        backtest_runner,
        "_load_allocation_strategies",
        lambda: {
            "regime_long_v2": {"enabled": False, "market": "spot"},
            "llm_direction_btc": {"enabled": True, "market": "spot"},
            "llm_direction_eth": {"enabled": False, "market": "spot"},
        },
    )

    strategies = backtest_runner.get_available_strategies()
    ids = [s["id"] for s in strategies]

    assert ids == ["llm_direction_btc"]
    assert "llm_direction" not in ids
    assert "regime_long_v2" not in ids
    assert not any(strategy["id"].startswith("wf_tree60_") for strategy in strategies)


def test_get_available_strategies_keeps_enabled_registry_strategy_once(monkeypatch):
    monkeypatch.setattr(
        backtest_runner,
        "STRATEGY_REGISTRY",
        {
            "regime_long_v2": _mock_spec("spot"),
        },
    )
    monkeypatch.setattr(
        backtest_runner,
        "_load_allocation_strategies",
        lambda: {
            "regime_long_v2": {"enabled": True, "market": "spot"},
            "llm_direction_btc": {"enabled": True, "market": "spot"},
        },
    )

    strategies = backtest_runner.get_available_strategies()
    ids = [s["id"] for s in strategies]

    assert ids == ["regime_long_v2", "llm_direction_btc"]
    assert ids.count("regime_long_v2") == 1
    assert strategies[0]["description"] == "Spot strategy (regime_long_v2)"


def test_core_hold_sleeve_does_not_double_count_initial_capital():
    core_state = backtest_runner._build_core_state(
        {"core_hold_pct": 0.5},
        initial_capital=10_000.0,
        fee_rate=0.0,
        slippage=0.0,
    )
    df = pd.DataFrame(
        [
            {"timestamp": pd.Timestamp("2026-01-01"), "close": 100.0},
            {"timestamp": pd.Timestamp("2026-01-02"), "close": 110.0},
        ]
    )

    backtest_runner._initialize_core_position(df, core_state)
    trade_state = {
        "capital": 10_000.0 - (10_000.0 * core_state["hold_pct"]),
        "position_size": 0.0,
        "position_leverage": 1.0,
    }
    backtest_runner._finalize_generic_trade_state(
        trade_state,
        adapter=SimpleNamespace(current_position=None),
        core_state=core_state,
        df=df,
    )

    assert round(trade_state["capital"], 2) == 10_500.0


def test_core_exit_waits_until_trend_filter_was_confirmed():
    core_state = backtest_runner._build_core_state(
        {
            "core_hold_pct": 0.5,
            "core_exit_on_ema200": True,
            "core_exit_requires_confirmed_trend": True,
        },
        initial_capital=10_000.0,
        fee_rate=0.0,
        slippage=0.0,
    )
    entry_row = pd.Series({"timestamp": pd.Timestamp("2026-01-01"), "close": 100.0})
    below_ema_row = pd.Series(
        {"timestamp": pd.Timestamp("2026-01-02"), "close": 95.0, "ema_200": 100.0}
    )

    backtest_runner._enter_core_position(entry_row, core_state)
    backtest_runner._update_core_position(below_ema_row, core_state)

    assert core_state["active"] is True
    assert core_state["trend_confirmed"] is False


def test_core_exit_after_confirmed_trend_breaks_below_ema200():
    core_state = backtest_runner._build_core_state(
        {
            "core_hold_pct": 0.5,
            "core_exit_on_ema200": True,
            "core_exit_requires_confirmed_trend": True,
        },
        initial_capital=10_000.0,
        fee_rate=0.0,
        slippage=0.0,
    )
    entry_row = pd.Series({"timestamp": pd.Timestamp("2026-01-01"), "close": 100.0})
    above_ema_row = pd.Series(
        {"timestamp": pd.Timestamp("2026-01-02"), "close": 105.0, "ema_200": 100.0}
    )
    below_ema_row = pd.Series(
        {"timestamp": pd.Timestamp("2026-01-03"), "close": 95.0, "ema_200": 100.0}
    )

    backtest_runner._enter_core_position(entry_row, core_state)
    backtest_runner._update_core_position(above_ema_row, core_state)
    backtest_runner._update_core_position(below_ema_row, core_state)

    assert core_state["active"] is False
    assert core_state["qty"] == 0.0
