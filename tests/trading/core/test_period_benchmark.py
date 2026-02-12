from __future__ import annotations

import pandas as pd
import pytest

from trading.core.period_benchmark import (
    alpha_by_market_direction,
    build_period_comparison,
    build_portfolio_comparison,
    compound_return,
    compute_period_returns_from_equity,
    compute_period_returns_from_prices,
)


def test_compute_period_returns_from_equity_monthly() -> None:
    equity = pd.DataFrame(
        {
            "timestamp": [
                "2026-01-01",
                "2026-01-31",
                "2026-02-28",
            ],
            "total_equity": [100.0, 120.0, 132.0],
        }
    )

    monthly = compute_period_returns_from_equity(equity, "M")
    assert len(monthly) == 2
    assert monthly.iloc[0] == pytest.approx(0.20)
    assert monthly.iloc[1] == pytest.approx(0.10)


def test_compute_period_returns_from_prices_monthly() -> None:
    prices = pd.DataFrame(
        {
            "timestamp": [
                "2026-01-01",
                "2026-01-31",
                "2026-02-28",
            ],
            "close": [100.0, 110.0, 99.0],
        }
    )

    monthly = compute_period_returns_from_prices(prices, "M")
    assert len(monthly) == 2
    assert monthly.iloc[0] == pytest.approx(0.10)
    assert monthly.iloc[1] == pytest.approx(-0.10)


def test_build_period_and_portfolio_comparison() -> None:
    idx = pd.to_datetime(["2026-01-31", "2026-02-28"])
    btc_strategy = pd.Series([0.20, 0.10], index=idx, name="strategy_return")
    btc_bnh = pd.Series([0.10, -0.10], index=idx, name="bnh_return")
    eth_strategy = pd.Series([0.05, 0.00], index=idx, name="strategy_return")
    eth_bnh = pd.Series([0.02, -0.02], index=idx, name="bnh_return")

    btc = build_period_comparison(
        strategy_returns=btc_strategy,
        benchmark_returns=btc_bnh,
        symbol="BTC",
        freq="M",
    )
    eth = build_period_comparison(
        strategy_returns=eth_strategy,
        benchmark_returns=eth_bnh,
        symbol="ETH",
        freq="M",
    )
    combined = pd.concat([btc, eth], ignore_index=True)
    portfolio = build_portfolio_comparison(combined)

    assert set(portfolio["symbol"]) == {"PORTFOLIO"}
    jan = portfolio.loc[portfolio["period"] == "2026-01"].iloc[0]
    feb = portfolio.loc[portfolio["period"] == "2026-02"].iloc[0]
    assert jan["strategy_return"] == pytest.approx(0.125)
    assert jan["bnh_return"] == pytest.approx(0.06)
    assert jan["alpha"] == pytest.approx(0.065)
    assert feb["strategy_return"] == pytest.approx(0.05)
    assert feb["bnh_return"] == pytest.approx(-0.06)
    assert feb["alpha"] == pytest.approx(0.11)


def test_alpha_split_and_compound() -> None:
    periods = pd.DataFrame(
        {
            "bnh_return": [0.10, -0.05, 0.03, -0.02],
            "alpha": [-0.02, 0.04, -0.01, 0.03],
        }
    )
    split = alpha_by_market_direction(periods)
    assert split["up_mean_alpha"] == pytest.approx((-0.02 - 0.01) / 2)
    assert split["down_mean_alpha"] == pytest.approx((0.04 + 0.03) / 2)

    total = compound_return(pd.Series([0.10, -0.05, 0.02]))
    assert round(total, 6) == round((1.10 * 0.95 * 1.02) - 1.0, 6)
