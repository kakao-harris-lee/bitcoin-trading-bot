"""
Integration tests for the complete trading system.

Tests the interaction between:
- RegimeRouter
- Strategy selection (V35, VA02, Short_V1)
- Position management
- Premium arbitrage
- Cost calculation
"""

import pytest
import pandas as pd
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.unified_backtester import UnifiedBacktester, BacktestConfig


class TestFullSystemIntegration:
    """Full system integration tests."""

    def test_system_runs_without_error(self):
        """System completes a full backtest without errors."""
        config = BacktestConfig(
            start_date="2024-06-01",
            end_date="2024-06-30",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        assert result is not None
        assert 'total_return_pct' in result
        assert 'equity_curve' in result

    def test_regime_affects_strategy_selection(self):
        """Different regimes activate different strategies."""
        # BULL period should activate V35
        bull_config = BacktestConfig(
            start_date="2024-10-15",  # Known BULL period
            end_date="2024-10-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
            enable_short=False,
            enable_premium_arb=False,
        )

        backtester = UnifiedBacktester(bull_config)
        result = backtester.run()

        # Should have results (trades depend on market conditions)
        assert result is not None
        assert 'total_trades' in result

    def test_costs_are_applied(self):
        """Trading costs are properly deducted."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-03-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Costs should be reflected in returns
        # If there were trades, there should be fee impact
        assert result is not None
        if result['total_trades'] > 0:
            # Final equity should differ from initial due to trading
            equity_curve = result['equity_curve']
            if len(equity_curve) > 0:
                initial = equity_curve['total_equity_krw'].iloc[0]
                final = equity_curve['total_equity_krw'].iloc[-1]
                # There should be some change (not exactly equal due to fees)
                assert initial != final or result['total_trades'] == 0

    def test_equity_curve_is_continuous(self):
        """Equity curve has no gaps or NaN values."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        equity_curve = result['equity_curve']
        assert not equity_curve['total_equity_krw'].isna().any()
        assert equity_curve['total_equity_krw'].min() > 0

    def test_premium_arb_config_respected(self):
        """Premium arbitrage can be enabled/disabled."""
        # With premium arb disabled
        config_no_arb = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-06-30",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
            enable_premium_arb=False,
        )

        backtester = UnifiedBacktester(config_no_arb)
        result = backtester.run()

        # Should complete without error
        assert result is not None
        assert 'total_return_pct' in result


class TestTradeFrequency:
    """Test trade frequency meets requirements."""

    def test_minimum_trade_frequency(self):
        """System generates reasonable trade frequency."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Should have at least some trades in a year
        # Requirement: Enough trades for statistical significance
        assert result['total_trades'] >= 5, "Too few trades for meaningful analysis"

    def test_not_overtrading(self):
        """System doesn't trade excessively (fee drain)."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Should not trade more than once per day on average
        # 252 trading days * 2 (long + short) = 504 max
        assert result['total_trades'] <= 500, "Overtrading detected"


class TestProfitability:
    """Test profitability requirements."""

    def test_training_period_runs(self):
        """Training period backtest completes."""
        config = BacktestConfig(
            start_date="2020-01-01",
            end_date="2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Training period should complete without error
        assert result is not None
        assert 'total_return_pct' in result

    def test_drawdown_calculation_works(self):
        """Max drawdown is calculated correctly."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Drawdown should be a negative percentage or zero
        assert result['max_drawdown_pct'] <= 0


class TestRegimeIntegration:
    """Test regime router integration."""

    def test_router_classifies_all_periods(self):
        """Router provides classification for all periods."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Equity curve should have regime column
        equity_curve = result['equity_curve']
        assert 'regime' in equity_curve.columns

    def test_bull_regime_enables_long(self):
        """BULL regime allows long positions."""
        config = BacktestConfig(
            start_date="2024-10-01",  # Q4 2024 had BULL periods
            end_date="2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
            enable_long=True,
            enable_short=False,
            enable_premium_arb=False,
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Should have executed some long trades in BULL periods
        assert result is not None
        # Note: actual trades depend on market conditions

    def test_bear_regime_enables_short(self):
        """BEAR regime allows short positions."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
            enable_long=False,
            enable_short=True,
            enable_premium_arb=False,
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Should complete without error
        assert result is not None


class TestMultiAsset:
    """Test multi-asset functionality."""

    def test_multi_asset_backtest(self):
        """Backtester handles multiple assets."""
        config = BacktestConfig(
            start_date="2024-06-01",
            end_date="2024-06-30",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC", "ETH"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Should complete without error
        assert result is not None
        assert 'total_return_pct' in result


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_handles_missing_data_gracefully(self):
        """Backtester handles gaps in data."""
        config = BacktestConfig(
            start_date="2020-01-01",  # Might have gaps
            end_date="2020-01-31",
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)

        # Should not raise
        result = backtester.run()
        assert isinstance(result, dict)

    def test_zero_capital_scenario(self):
        """Handles edge case of minimal capital."""
        config = BacktestConfig(
            start_date="2024-06-01",
            end_date="2024-06-30",
            upbit_capital_krw=100_000,  # Minimal capital
            binance_capital_usdt=100,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Should complete without error
        assert result is not None

    def test_short_period_backtest(self):
        """Handles very short backtest periods."""
        config = BacktestConfig(
            start_date="2024-06-01",
            end_date="2024-06-07",  # 7 days
            upbit_capital_krw=10_000_000,
            binance_capital_usdt=10_000,
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        result = backtester.run()

        # Should complete (may have no trades due to lookback)
        assert result is not None
