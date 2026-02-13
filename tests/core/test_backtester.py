#!/usr/bin/env python3
"""
Tests for Backtester with spot/futures market support.
"""
import pytest
import pandas as pd
from datetime import datetime, timedelta
from core.backtester import Backtester


@pytest.fixture
def sample_data():
    """Generate sample OHLCV data."""
    start = datetime.now()
    timestamps = [start + timedelta(hours=i) for i in range(100)]

    df = pd.DataFrame({
        'timestamp': timestamps,
        'open': [50000 + i * 10 for i in range(100)],
        'high': [50100 + i * 10 for i in range(100)],
        'low': [49900 + i * 10 for i in range(100)],
        'close': [50000 + i * 10 for i in range(100)],
        'volume': [100 + i for i in range(100)],
    })

    return df


class TestBacktesterSpotSupport:
    """Test backtester spot market support."""

    def test_spot_backtester_uses_spot_fee_rate(self):
        """Spot backtester should use 0.1% fee rate by default."""
        backtester = Backtester(market="spot")

        assert backtester.market == "spot"
        assert backtester.fee_rate == 0.001  # 0.1%

    def test_futures_backtester_uses_futures_fee_rate(self):
        """Futures backtester should use 0.05% fee rate by default."""
        backtester = Backtester(market="futures")

        assert backtester.market == "futures"
        assert backtester.fee_rate == 0.0005  # 0.05%

    def test_spot_backtester_uses_leverage_1(self):
        """Spot backtester should use leverage=1."""
        backtester = Backtester(market="spot")

        assert backtester.leverage == 1

    def test_futures_backtester_uses_leverage_3(self):
        """Futures backtester should use leverage=3."""
        backtester = Backtester(market="futures")

        assert backtester.leverage == 3

    def test_custom_fee_rate_overrides_default(self):
        """Custom fee rate should override auto-detection."""
        backtester = Backtester(market="spot", fee_rate=0.002)

        assert backtester.fee_rate == 0.002

    def test_default_market_is_futures(self):
        """Default market should be futures for backward compatibility."""
        backtester = Backtester()

        assert backtester.market == "futures"
        assert backtester.fee_rate == 0.0005

    def test_spot_backtester_run(self, sample_data):
        """Spot backtester should run without errors."""
        backtester = Backtester(
            initial_capital=10000,
            market="spot",
        )

        def simple_strategy(df, i, params):
            """Buy at 10, sell at 50."""
            if i == 10:
                return {'action': 'buy', 'fraction': 0.5}
            elif i == 50:
                return {'action': 'sell', 'fraction': 1.0}
            return {'action': 'hold'}

        results = backtester.run(sample_data, simple_strategy)

        assert 'total_return' in results
        assert 'total_trades' in results
        assert 'sharpe_ratio' in results
        assert 'max_drawdown_pct' in results


class TestBacktesterFeeDifference:
    """Test that spot and futures fees are applied correctly."""

    def test_spot_fees_higher_than_futures(self, sample_data):
        """Spot fees (0.1%) should reduce returns compared to futures (0.05%)."""
        # Same strategy for both
        def buy_and_hold(df, i, params):
            if i == 10:
                return {'action': 'buy', 'fraction': 1.0}
            elif i == 90:
                return {'action': 'sell', 'fraction': 1.0}
            return {'action': 'hold'}

        # Run spot
        spot_backtester = Backtester(
            initial_capital=10000,
            market="spot",
        )
        spot_results = spot_backtester.run(sample_data, buy_and_hold)

        # Run futures
        futures_backtester = Backtester(
            initial_capital=10000,
            market="futures",
        )
        futures_results = futures_backtester.run(sample_data, buy_and_hold)

        # Futures should have higher final capital due to lower fees
        # (assuming same price movement)
        assert futures_results['final_capital'] > spot_results['final_capital']

    def test_final_capital_after_auto_liquidation_not_double_counted(self, sample_data):
        """Final capital should not include stale position value after forced liquidation."""
        backtester = Backtester(
            initial_capital=10000,
            market="spot",
            fee_rate=0.0,
            slippage=0.0,
        )

        def buy_once_hold(df, i, params):
            if i == 0:
                return {'action': 'buy', 'fraction': 1.0}
            return {'action': 'hold'}

        results = backtester.run(sample_data, buy_once_hold)

        entry_price = sample_data.iloc[0]["close"]
        exit_price = sample_data.iloc[-1]["close"]
        expected_final = 10000 * (exit_price / entry_price)
        expected_return = (expected_final - 10000) / 10000 * 100

        assert results["total_trades"] == 1
        assert results["final_capital"] == pytest.approx(expected_final, rel=1e-9)
        assert results["total_return"] == pytest.approx(expected_return, rel=1e-9)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
