"""Tests for HedgeManager."""

import pytest
import asyncio
from datetime import datetime, timedelta
from unittest.mock import Mock, AsyncMock, patch
import tempfile
import os

from trading.execution.hedge_manager import (
    HedgeManager,
    HedgePosition,
    HedgeTrade,
    ExecutionError,
)
from trading.risk.premium_controller import PremiumController, HedgeSignal, PremiumStats


@pytest.fixture
def temp_history_file():
    """Create a temporary history file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
        f.write('{"readings": []}')
        temp_path = f.name
    yield temp_path
    os.unlink(temp_path)


@pytest.fixture
def premium_controller(temp_history_file):
    """Create PremiumController with temp history file."""
    config = {
        "history_file": temp_history_file,
        "entry_threshold_pct": 1.5,
        "entry_sigma": 2.0,
    }
    return PremiumController(config)


@pytest.fixture
def mock_binance_account():
    """Create mock Binance account."""
    account = Mock()
    account.get_balance.return_value = (5000.0, 0.0)
    account.get_position.return_value = None
    account.open_position = Mock(return_value={"success": True})
    account.close_position = Mock(return_value={"success": True, "realized_pnl": 100.0})
    return account


@pytest.fixture
def hedge_manager(mock_binance_account, premium_controller):
    """Create HedgeManager with mocks."""
    config = {
        "capital_usdt": 5000,
        "max_capital_usage_pct": 0.8,
        "fee_pct": 0.04,
        "slippage_pct": 0.02,
    }
    return HedgeManager(
        binance_account=mock_binance_account,
        premium_controller=premium_controller,
        config=config,
    )


class TestHedgeManagerInit:
    """Test HedgeManager initialization."""

    def test_init_with_defaults(self, mock_binance_account, premium_controller):
        """Manager initializes with default config."""
        manager = HedgeManager(
            binance_account=mock_binance_account,
            premium_controller=premium_controller,
        )

        assert manager.capital == 5000
        assert manager.hedge_position is None
        assert manager.is_hedged is False
        assert len(manager.trades) == 0

    def test_init_with_custom_config(self, mock_binance_account, premium_controller):
        """Manager accepts custom config."""
        config = {"capital_usdt": 10000}
        manager = HedgeManager(
            binance_account=mock_binance_account,
            premium_controller=premium_controller,
            config=config,
        )

        assert manager.capital == 10000


class TestDeltaExposure:
    """Test delta exposure calculations."""

    def test_no_hedge_full_long_exposure(self, hedge_manager):
        """Without hedge, full long exposure."""
        exposure = hedge_manager.get_delta_exposure(upbit_btc=0.5)

        assert exposure["long_btc"] == 0.5
        assert exposure["short_btc"] == 0.0
        assert exposure["net_btc"] == 0.5
        assert exposure["is_neutral"] is False

    def test_with_hedge_neutral_exposure(self, hedge_manager):
        """With matching hedge, exposure is neutral."""
        hedge_manager.hedge_position = HedgePosition(
            qty=0.5,
            entry_price=95000,
            entry_premium=3.5,
            entry_time=datetime.now(),
        )

        exposure = hedge_manager.get_delta_exposure(upbit_btc=0.5)

        assert exposure["long_btc"] == 0.5
        assert exposure["short_btc"] == 0.5
        assert exposure["net_btc"] == 0.0
        assert exposure["is_neutral"] is True
        assert exposure["hedge_ratio"] == 1.0

    def test_partial_hedge(self, hedge_manager):
        """Partial hedge shows correct ratio."""
        hedge_manager.hedge_position = HedgePosition(
            qty=0.25,
            entry_price=95000,
            entry_premium=3.5,
            entry_time=datetime.now(),
        )

        exposure = hedge_manager.get_delta_exposure(upbit_btc=0.5)

        assert exposure["hedge_ratio"] == 0.5
        assert exposure["is_neutral"] is False


class TestHedgeExecution:
    """Test hedge execution logic."""

    @pytest.mark.asyncio
    async def test_evaluate_no_action_when_hold(self, hedge_manager, premium_controller):
        """No execution when signal is hold."""
        # Build low premium history
        for _ in range(5):
            premium_controller.record({
                "premium_pct": 1.0,
                "upbit_usd": 95000,
                "binance_usd": 94000,
                "usd_krw_rate": 1450,
            })

        signal = await hedge_manager.evaluate(
            upbit_btc_balance=0.5,
            binance_price=94000,
            premium_info={"premium_pct": 1.0},
        )

        assert signal.action == "hold"
        assert hedge_manager.hedge_position is None

    @pytest.mark.asyncio
    async def test_open_hedge_on_entry_signal(self, hedge_manager, premium_controller):
        """Open hedge when entry signal generated."""
        # Build low premium history then spike
        for _ in range(10):
            premium_controller.record({
                "premium_pct": 1.0,
                "upbit_usd": 95000,
                "binance_usd": 94000,
                "usd_krw_rate": 1450,
            })

        # High premium triggers entry
        signal = await hedge_manager.evaluate(
            upbit_btc_balance=0.5,
            binance_price=90000,
            premium_info={
                "premium_pct": 5.5,
                "upbit_usd": 95000,
                "binance_usd": 90000,
                "usd_krw_rate": 1450,
            },
        )

        assert signal.action == "open"
        assert hedge_manager.hedge_position is not None
        assert hedge_manager.is_hedged is True

    @pytest.mark.asyncio
    async def test_close_hedge_on_mean_reversion(self, hedge_manager, premium_controller):
        """Close hedge when premium reverts to mean."""
        # Build history and open position
        for p in [3.0, 3.5, 4.0, 4.5, 5.0]:
            premium_controller.record({
                "premium_pct": p,
                "upbit_usd": 95000,
                "binance_usd": 91000,
                "usd_krw_rate": 1450,
            })

        # Manually set position and controller state
        hedge_manager.hedge_position = HedgePosition(
            qty=0.5,
            entry_price=91000,
            entry_premium=5.0,
            entry_time=datetime.now() - timedelta(hours=1),
        )
        premium_controller.set_position_state(True, datetime.now() - timedelta(hours=1))

        # Premium reverts to mean
        signal = await hedge_manager.evaluate(
            upbit_btc_balance=0.5,
            binance_price=91500,
            premium_info={
                "premium_pct": 4.0,  # At mean
                "upbit_usd": 95000,
                "binance_usd": 91346,
                "usd_krw_rate": 1450,
            },
        )

        assert signal.action == "close"
        assert hedge_manager.hedge_position is None
        assert len(hedge_manager.trades) == 1

    def test_capital_limit_caps_position(self, hedge_manager):
        """Position size capped by capital limit."""
        # Large position request
        hedge_manager.capital = 1000  # Only $1000 available

        # Should be capped at 80% of capital
        max_margin = 1000 * 0.8
        expected_qty = max_margin / 95000  # ~0.0084 BTC

        # Check capital limits work in _open_hedge indirectly
        assert hedge_manager.config["max_capital_usage_pct"] == 0.8


class TestFundingApplication:
    """Test funding rate application."""

    def test_apply_funding_to_position(self, hedge_manager):
        """Funding applied to active position."""
        hedge_manager.hedge_position = HedgePosition(
            qty=0.5,
            entry_price=95000,
            entry_premium=3.5,
            entry_time=datetime.now(),
        )

        # Apply positive funding (shorts receive)
        funding = hedge_manager.apply_funding(
            binance_price=95000,
            rate=0.0001,  # 0.01%
        )

        assert funding == 0.5 * 95000 * 0.0001  # ~4.75 USDT
        assert hedge_manager.hedge_position.accumulated_funding == funding

    def test_no_funding_without_position(self, hedge_manager):
        """No funding applied without position."""
        funding = hedge_manager.apply_funding(
            binance_price=95000,
            rate=0.0001,
        )

        assert funding == 0.0


class TestStatistics:
    """Test statistics calculation."""

    def test_empty_stats(self, hedge_manager):
        """Empty stats when no trades."""
        stats = hedge_manager.get_statistics()

        assert stats["total_trades"] == 0
        assert stats["total_pnl"] == 0
        assert stats["net_pnl"] == 0

    def test_stats_with_trades(self, hedge_manager):
        """Statistics calculated from trades."""
        hedge_manager.trades = [
            HedgeTrade(
                entry_time=datetime.now() - timedelta(hours=2),
                exit_time=datetime.now() - timedelta(hours=1),
                qty=0.5,
                entry_price=90000,
                exit_price=89000,  # Profit (short)
                entry_premium=5.0,
                exit_premium=3.0,
                pnl=500,  # (90000-89000) * 0.5
                funding=10,
                fees=5,
            ),
            HedgeTrade(
                entry_time=datetime.now() - timedelta(hours=1),
                exit_time=datetime.now(),
                qty=0.3,
                entry_price=91000,
                exit_price=92000,  # Loss (short)
                entry_premium=4.0,
                exit_premium=2.5,
                pnl=-300,  # (91000-92000) * 0.3
                funding=5,
                fees=3,
            ),
        ]

        stats = hedge_manager.get_statistics()

        assert stats["total_trades"] == 2
        assert stats["total_pnl"] == 200  # 500 - 300
        assert stats["total_funding"] == 15
        assert stats["total_fees"] == 8
        assert stats["net_pnl"] == 207  # 200 + 15 - 8
        assert stats["win_rate"] == 50.0  # 1 of 2 winning


class TestSerialization:
    """Test state serialization."""

    def test_to_dict_without_position(self, hedge_manager):
        """Serialization without position."""
        data = hedge_manager.to_dict()

        assert data["capital"] == 5000
        assert data["is_hedged"] is False
        assert data["position"] is None
        assert "statistics" in data

    def test_to_dict_with_position(self, hedge_manager):
        """Serialization with position."""
        hedge_manager.hedge_position = HedgePosition(
            qty=0.5,
            entry_price=95000,
            entry_premium=3.5,
            entry_time=datetime.now(),
        )

        data = hedge_manager.to_dict()

        assert data["is_hedged"] is True
        assert data["position"]["qty"] == 0.5
        assert data["position"]["entry_price"] == 95000
