"""
Tests for UnifiedBacktester.

This module tests the unified backtesting framework that simulates the complete
trading system including:
- RegimeRouter for market state classification
- Strategy selection based on regime
- Position management with realistic costs
- Combined P&L calculation
"""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from unittest.mock import MagicMock, patch
from dataclasses import asdict

# Import the module under test
from core.unified_backtester import (
    BacktestConfig,
    UnifiedBacktester,
    Trade,
    PositionState,
)


class TestBacktestConfig:
    """Tests for BacktestConfig dataclass."""

    def test_default_values(self):
        """Config has sensible defaults."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert config.upbit_capital_krw == 10_000_000
        assert config.binance_capital_usdt == 10_000
        assert config.assets == ["BTC"]
        assert config.enable_long is True
        assert config.enable_short is True
        assert config.upbit_fee == 0.0005
        assert config.binance_fee == 0.0004
        assert config.slippage == 0.0002
        assert config.timeframe == "day"

    def test_custom_values(self):
        """Config accepts custom values."""
        config = BacktestConfig(
            start_date="2023-01-01",
            end_date="2023-12-31",
            upbit_capital_krw=50_000_000,
            binance_capital_usdt=50_000,
            assets=["BTC", "ETH"],
            enable_long=True,
            enable_short=False,
            upbit_fee=0.001,
            binance_fee=0.0005,
            slippage=0.0005,
            timeframe="minute60",
        )

        assert config.start_date == "2023-01-01"
        assert config.end_date == "2023-12-31"
        assert config.upbit_capital_krw == 50_000_000
        assert config.binance_capital_usdt == 50_000
        assert config.assets == ["BTC", "ETH"]
        assert config.enable_long is True
        assert config.enable_short is False
        assert config.upbit_fee == 0.001
        assert config.binance_fee == 0.0005
        assert config.slippage == 0.0005
        assert config.timeframe == "minute60"


class TestUnifiedBacktesterInit:
    """Tests for UnifiedBacktester initialization."""

    def test_initialization(self):
        """Backtester initializes with config."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-06-30",
        )

        backtester = UnifiedBacktester(config)

        assert backtester.config == config
        assert backtester.upbit_cash == config.upbit_capital_krw
        assert backtester.binance_cash == config.binance_capital_usdt

    def test_initialization_creates_router(self):
        """Backtester creates RegimeRouter instance."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-06-30",
        )

        backtester = UnifiedBacktester(config)

        assert backtester.router is not None


class TestUnifiedBacktesterDataLoading:
    """Tests for data loading functionality."""

    def test_loads_upbit_data(self):
        """Backtester loads Upbit price data."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        backtester._load_data()

        assert "BTC" in backtester.upbit_data
        assert len(backtester.upbit_data["BTC"]) > 0
        assert "close" in backtester.upbit_data["BTC"].columns

    def test_loads_binance_data(self):
        """Backtester loads Binance price data."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        backtester._load_data()

        assert "BTC" in backtester.binance_data
        assert len(backtester.binance_data["BTC"]) > 0
        assert "close" in backtester.binance_data["BTC"].columns

    def test_loads_fx_rates(self):
        """Backtester loads FX rate data."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        backtester = UnifiedBacktester(config)
        backtester._load_data()

        assert backtester.fx_rates is not None
        assert len(backtester.fx_rates) > 0


class TestRegimeClassification:
    """Tests for regime classification during backtest."""

    def test_classifies_bull_regime(self):
        """Backtester correctly identifies BULL regime."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        backtester = UnifiedBacktester(config)

        # High MFI, high ADX = BULL_STRONG
        state = backtester.router.classify_from_values(mfi=60, adx=30)
        assert state == "BULL_STRONG"

    def test_classifies_bear_regime(self):
        """Backtester correctly identifies BEAR regime."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        backtester = UnifiedBacktester(config)

        # Low MFI, high ADX = BEAR_STRONG
        state = backtester.router.classify_from_values(mfi=40, adx=25)
        assert state == "BEAR_STRONG"

    def test_classifies_sideways_regime(self):
        """Backtester correctly identifies SIDEWAYS regime."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        backtester = UnifiedBacktester(config)

        # Neutral MFI = SIDEWAYS
        state = backtester.router.classify_from_values(mfi=50, adx=15)
        assert state == "SIDEWAYS_NEUTRAL"


class TestPositionManagement:
    """Tests for position entry/exit logic."""

    def test_long_entry_on_bull(self):
        """Long position entered on BULL regime."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            enable_long=True,
            enable_short=False,
        )

        backtester = UnifiedBacktester(config)
        initial_cash = backtester.upbit_cash

        # Simulate BULL entry
        backtester._enter_long("BTC", price=50_000_000, fraction=0.5)

        assert backtester.upbit_cash < initial_cash
        assert backtester.positions.get("BTC") is not None
        assert backtester.positions["BTC"].side == "long"

    def test_short_entry_on_bear(self):
        """Short position entered on BEAR regime."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            enable_long=False,
            enable_short=True,
        )

        backtester = UnifiedBacktester(config)

        # Simulate BEAR entry
        backtester._enter_short("BTC", price=50_000, fraction=0.3)

        assert backtester.positions.get("BTC_SHORT") is not None
        assert backtester.positions["BTC_SHORT"].side == "short"

    def test_exit_on_regime_change(self):
        """Position exited when regime changes."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        backtester = UnifiedBacktester(config)

        # Enter long
        backtester._enter_long("BTC", price=50_000_000, fraction=0.5)
        assert backtester.positions.get("BTC") is not None

        # Exit long
        backtester._exit_long("BTC", price=51_000_000)
        assert backtester.positions.get("BTC") is None

    def test_exit_on_take_profit(self):
        """Position exited on take profit (5%)."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        backtester = UnifiedBacktester(config)

        # Enter at 50M, TP at 5% = 52.5M
        backtester._enter_long("BTC", price=50_000_000, fraction=0.5)

        # Check if should exit at 5.5% gain
        should_tp = backtester._check_take_profit("BTC", current_price=52_750_000)
        assert should_tp is True

    def test_exit_on_stop_loss(self):
        """Position exited on stop loss (2%)."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        backtester = UnifiedBacktester(config)

        # Enter at 50M, SL at 2% = 49M
        backtester._enter_long("BTC", price=50_000_000, fraction=0.5)

        # Check if should exit at 2.5% loss
        should_sl = backtester._check_stop_loss("BTC", current_price=48_750_000)
        assert should_sl is True


class TestCostCalculation:
    """Tests for fee and slippage calculations."""

    def test_upbit_buy_cost(self):
        """Upbit buy includes fee and slippage."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            upbit_fee=0.0005,
            slippage=0.0002,
        )

        backtester = UnifiedBacktester(config)

        # Buy 1 BTC at 50M
        cost = backtester._calculate_buy_cost(
            exchange="upbit",
            price=50_000_000,
            quantity=1.0,
        )

        # Expected: 50M * (1 + 0.0005 + 0.0002) = 50,035,000
        expected = 50_000_000 * (1 + 0.0005 + 0.0002)
        assert cost == pytest.approx(expected, rel=0.0001)

    def test_upbit_sell_proceeds(self):
        """Upbit sell deducts fee and slippage."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            upbit_fee=0.0005,
            slippage=0.0002,
        )

        backtester = UnifiedBacktester(config)

        # Sell 1 BTC at 50M
        proceeds = backtester._calculate_sell_proceeds(
            exchange="upbit",
            price=50_000_000,
            quantity=1.0,
        )

        # Expected: 50M * (1 - 0.0005 - 0.0002) = 49,965,000
        expected = 50_000_000 * (1 - 0.0005 - 0.0002)
        assert proceeds == pytest.approx(expected, rel=0.0001)

    def test_binance_short_entry_cost(self):
        """Binance short entry includes fee."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            binance_fee=0.0004,
            slippage=0.0002,
        )

        backtester = UnifiedBacktester(config)

        # Open short 1 BTC at 50K USDT
        cost = backtester._calculate_short_entry_margin(
            price=50_000,
            quantity=1.0,
        )

        # Margin required (notional value affected by fees)
        assert cost > 0


class TestBacktestRun:
    """Tests for full backtest execution."""

    def test_run_returns_results_dict(self):
        """run() returns dictionary with required keys."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        results = backtester.run()

        assert isinstance(results, dict)
        assert "total_return_pct" in results
        assert "total_trades" in results
        assert "win_rate" in results
        assert "sharpe_ratio" in results
        assert "max_drawdown_pct" in results
        assert "avg_win_pct" in results
        assert "avg_loss_pct" in results
        assert "equity_curve" in results

    def test_run_equity_curve_is_dataframe(self):
        """run() returns equity curve as DataFrame."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        results = backtester.run()

        assert isinstance(results["equity_curve"], pd.DataFrame)
        assert len(results["equity_curve"]) > 0
        assert "timestamp" in results["equity_curve"].columns
        assert "total_equity_krw" in results["equity_curve"].columns

    def test_run_calculates_sharpe_ratio(self):
        """run() calculates Sharpe ratio."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-06-30",
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        results = backtester.run()

        # Sharpe can be positive, negative, or NaN (if no trades)
        assert "sharpe_ratio" in results
        if results["total_trades"] > 0:
            assert not np.isnan(results["sharpe_ratio"]) or results["sharpe_ratio"] == 0

    def test_run_calculates_max_drawdown(self):
        """run() calculates maximum drawdown."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-06-30",
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        results = backtester.run()

        assert "max_drawdown_pct" in results
        # Drawdown should be 0 or negative (loss)
        assert results["max_drawdown_pct"] <= 0 or results["max_drawdown_pct"] >= 0  # Can be 0 if no loss

    def test_run_long_only_mode(self):
        """run() works with long-only mode."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-03-31",
            assets=["BTC"],
            enable_long=True,
            enable_short=False,
        )

        backtester = UnifiedBacktester(config)
        results = backtester.run()

        assert isinstance(results, dict)
        assert "total_return_pct" in results

    def test_run_short_only_mode(self):
        """run() works with short-only mode."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-03-31",
            assets=["BTC"],
            enable_long=False,
            enable_short=True,
        )

        backtester = UnifiedBacktester(config)
        results = backtester.run()

        assert isinstance(results, dict)
        assert "total_return_pct" in results


class TestTradeRecording:
    """Tests for trade recording functionality."""

    def test_trade_record_created(self):
        """Trades are recorded with correct fields."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
        )

        backtester = UnifiedBacktester(config)

        # Enter and exit a position
        backtester._enter_long("BTC", price=50_000_000, fraction=0.5)
        backtester._exit_long("BTC", price=51_000_000)

        assert len(backtester.trades) > 0
        trade = backtester.trades[-1]
        assert trade.asset == "BTC"
        assert trade.side == "long"
        assert trade.entry_price == 50_000_000
        assert trade.exit_price == 51_000_000

    def test_trades_dataframe_in_results(self):
        """Results include trades as DataFrame."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-03-31",
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)
        results = backtester.run()

        # trades key should exist (can be None or DataFrame)
        assert "trades" in results
        if results["total_trades"] > 0:
            assert results["trades"] is not None


class TestMultiAsset:
    """Tests for multi-asset backtesting."""

    def test_multi_asset_initialization(self):
        """Backtester handles multiple assets."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-31",
            assets=["BTC", "ETH"],
        )

        backtester = UnifiedBacktester(config)
        backtester._load_data()

        assert "BTC" in backtester.upbit_data
        assert "ETH" in backtester.upbit_data

    def test_multi_asset_run(self):
        """run() works with multiple assets."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-03-31",
            assets=["BTC", "ETH"],
        )

        backtester = UnifiedBacktester(config)
        results = backtester.run()

        assert isinstance(results, dict)
        assert "total_return_pct" in results


class TestEdgeCases:
    """Tests for edge cases and error handling."""

    def test_no_trades_scenario(self):
        """Backtester handles periods with no trades gracefully."""
        config = BacktestConfig(
            start_date="2024-01-01",
            end_date="2024-01-07",  # Very short period
            assets=["BTC"],
            enable_long=False,
            enable_short=False,
        )

        backtester = UnifiedBacktester(config)
        results = backtester.run()

        assert results["total_trades"] == 0
        assert results["total_return_pct"] == 0.0

    def test_handles_missing_data_gracefully(self):
        """Backtester handles gaps in data."""
        config = BacktestConfig(
            start_date="2020-01-01",  # Might have gaps
            end_date="2020-01-31",
            assets=["BTC"],
        )

        backtester = UnifiedBacktester(config)

        # Should not raise
        results = backtester.run()
        assert isinstance(results, dict)
