#!/usr/bin/env python3
"""Tests for spot-only backtester."""

import pytest
import pandas as pd
from datetime import datetime, timedelta

from core.backtester import Backtester


@pytest.fixture
def sample_data():
    start = datetime.now()
    timestamps = [start + timedelta(hours=i) for i in range(100)]
    return pd.DataFrame(
        {
            "timestamp": timestamps,
            "open": [50000 + i * 10 for i in range(100)],
            "high": [50100 + i * 10 for i in range(100)],
            "low": [49900 + i * 10 for i in range(100)],
            "close": [50000 + i * 10 for i in range(100)],
            "volume": [100 + i for i in range(100)],
        }
    )


def test_backtester_uses_spot_defaults():
    backtester = Backtester()
    assert backtester.market == "spot"
    assert backtester.fee_rate == 0.001
    assert backtester.leverage == 1


def test_backtester_rejects_non_spot_market():
    with pytest.raises(ValueError):
        Backtester(market="margin")


def test_custom_fee_rate_overrides_default():
    backtester = Backtester(market="spot", fee_rate=0.002)
    assert backtester.fee_rate == 0.002


def test_spot_backtester_run(sample_data):
    backtester = Backtester(initial_capital=10000, market="spot")

    def simple_strategy(df, i, params):
        if i == 10:
            return {"action": "buy", "fraction": 0.5}
        if i == 50:
            return {"action": "sell", "fraction": 1.0}
        return {"action": "hold"}

    results = backtester.run(sample_data, simple_strategy)

    assert "total_return" in results
    assert "total_trades" in results
    assert "sharpe_ratio" in results
    assert "max_drawdown_pct" in results


def test_final_capital_after_auto_liquidation_not_double_counted(sample_data):
    backtester = Backtester(initial_capital=10000, market="spot", fee_rate=0.0, slippage=0.0)

    def buy_once_hold(df, i, params):
        if i == 0:
            return {"action": "buy", "fraction": 1.0}
        return {"action": "hold"}

    results = backtester.run(sample_data, buy_once_hold)

    entry_price = sample_data.iloc[0]["close"]
    exit_price = sample_data.iloc[-1]["close"]
    expected_final = 10000 * (exit_price / entry_price)
    expected_return = (expected_final - 10000) / 10000 * 100

    assert results["total_trades"] == 1
    assert results["final_capital"] == pytest.approx(expected_final, rel=1e-9)
    assert results["total_return"] == pytest.approx(expected_return, rel=1e-9)


def test_signal_price_override_is_used_for_execution(sample_data):
    backtester = Backtester(initial_capital=10000, market="spot", fee_rate=0.0, slippage=0.0)

    def strategy_with_trigger_price(df, i, params):
        if i == 0:
            return {"action": "buy", "fraction": 1.0}
        if i == 1:
            close_price = float(df.iloc[i]["close"])
            return {"action": "sell", "fraction": 1.0, "price": close_price * 0.9}
        return {"action": "hold"}

    results = backtester.run(sample_data, strategy_with_trigger_price)

    entry_price = float(sample_data.iloc[0]["close"])
    forced_exit_price = float(sample_data.iloc[1]["close"]) * 0.9
    expected_final = 10000 * (forced_exit_price / entry_price)

    assert results["total_trades"] == 1
    assert results["final_capital"] == pytest.approx(expected_final, rel=1e-9)


def test_partial_sell_tracks_fifo_quantities_correctly(sample_data):
    backtester = Backtester(initial_capital=10000, market="spot", fee_rate=0.0, slippage=0.0)

    def partial_exit_strategy(df, i, params):
        if i == 0:
            return {"action": "buy", "fraction": 1.0}
        if i == 1:
            return {"action": "sell", "fraction": 0.5}
        if i == 2:
            return {"action": "sell", "fraction": 1.0}
        return {"action": "hold"}

    results = backtester.run(sample_data, partial_exit_strategy)
    closed = results.get("trades", [])

    assert results["total_trades"] == 2
    assert len(closed) == 2

    bought_qty = 10000 / float(sample_data.iloc[0]["close"])
    closed_qty = sum(float(t.quantity) for t in closed)
    assert closed_qty == pytest.approx(bought_qty, rel=1e-9)
