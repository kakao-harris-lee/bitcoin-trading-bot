"""Tests for dashboard backtest strategy list generation."""

from types import SimpleNamespace

from web.services import backtest_runner


def _mock_spec(market: str = "spot") -> SimpleNamespace:
    return SimpleNamespace(market=market)


def test_get_available_strategies_only_includes_enabled_allocation_and_wf(monkeypatch):
    monkeypatch.setattr(
        backtest_runner,
        "STRATEGY_REGISTRY",
        {
            "mlp_direction": _mock_spec("spot"),
            "regime_long_v2": _mock_spec("spot"),
            "hybrid_long_v2": _mock_spec("spot"),
        },
    )
    monkeypatch.setattr(
        backtest_runner,
        "BACKTEST_ONLY_STRATEGIES",
        (
            {
                "id": "wf_tree60_btc",
                "name": "Walk-Forward Tree60 BTC",
                "description": "Backtest-only walk-forward XGB+LGB ensemble (BTC spot)",
            },
        ),
    )
    monkeypatch.setattr(
        backtest_runner,
        "_load_allocation_strategies",
        lambda: {
            "regime_long_v2": {"enabled": False, "market": "spot"},
            "mlp_direction_btc": {"enabled": True, "market": "spot"},
            "mlp_direction_eth": {"enabled": False, "market": "spot"},
        },
    )

    strategies = backtest_runner.get_available_strategies()
    ids = [s["id"] for s in strategies]

    assert ids == ["mlp_direction_btc", "wf_tree60_btc"]
    assert "mlp_direction" not in ids
    assert "regime_long_v2" not in ids


def test_get_available_strategies_keeps_enabled_registry_strategy_once(monkeypatch):
    monkeypatch.setattr(
        backtest_runner,
        "STRATEGY_REGISTRY",
        {
            "hybrid_long_v2": _mock_spec("spot"),
        },
    )
    monkeypatch.setattr(
        backtest_runner,
        "BACKTEST_ONLY_STRATEGIES",
        (
            {
                "id": "wf_tree60_eth",
                "name": "Walk-Forward Tree60 ETH",
                "description": "Backtest-only walk-forward XGB+LGB ensemble (ETH spot)",
            },
        ),
    )
    monkeypatch.setattr(
        backtest_runner,
        "_load_allocation_strategies",
        lambda: {
            "hybrid_long_v2": {"enabled": True, "market": "spot"},
            "mlp_direction_btc": {"enabled": True, "market": "spot"},
        },
    )

    strategies = backtest_runner.get_available_strategies()
    ids = [s["id"] for s in strategies]

    assert ids == ["hybrid_long_v2", "mlp_direction_btc", "wf_tree60_eth"]
    assert ids.count("hybrid_long_v2") == 1
    assert strategies[0]["description"] == "Spot strategy (hybrid_long_v2)"
