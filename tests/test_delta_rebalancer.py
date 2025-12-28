"""
Tests for DeltaRebalancer and dynamic rebalancing.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime


class TestDeltaRebalancer:
    """Test DeltaRebalancer component."""

    def _create_mock_rebalancer(
        self,
        long_btc: float = 0.5,
        short_btc: float = 0.5,
        premium_std: float = 0.5,
    ):
        """Create a mock DeltaRebalancer with configurable state."""
        from trading.execution.delta_rebalancer import DeltaRebalancer

        # Mock upbit account
        upbit_account = MagicMock()
        upbit_account.get_balance.return_value = (1_000_000, long_btc)

        # Mock hedge manager with position
        hedge_manager = MagicMock()
        if short_btc > 0:
            hedge_manager.hedge_position = MagicMock()
            hedge_manager.hedge_position.qty = short_btc
        else:
            hedge_manager.hedge_position = None
        hedge_manager.adjust_position = AsyncMock(return_value={
            "direction": "increase" if long_btc > short_btc else "decrease",
            "qty_adjusted": abs(long_btc - short_btc),
            "new_short_qty": long_btc,
            "fees_paid": 10.0,
            "success": True,
        })

        # Mock premium controller
        premium_controller = MagicMock()
        premium_controller.get_stats.return_value = {"std": premium_std}

        rebalancer = DeltaRebalancer(
            upbit_account=upbit_account,
            hedge_manager=hedge_manager,
            premium_controller=premium_controller,
            config={
                "calm_threshold_pct": 3.0,
                "normal_threshold_pct": 5.0,
                "volatile_threshold_pct": 8.0,
                "volatility_calm": 0.5,
                "volatility_high": 1.5,
                "min_rebalance_interval": 30,
            },
        )

        return rebalancer

    def test_dynamic_threshold_calm_market(self):
        """Low volatility (σ < 0.5%) → tight threshold (3%)."""
        rebalancer = self._create_mock_rebalancer(premium_std=0.3)

        threshold = rebalancer.get_dynamic_threshold()
        assert threshold == 3.0

    def test_dynamic_threshold_normal_market(self):
        """Medium volatility (0.5% < σ < 1.5%) → interpolated threshold."""
        rebalancer = self._create_mock_rebalancer(premium_std=1.0)

        threshold = rebalancer.get_dynamic_threshold()
        # Interpolation: 3.0 + (1.0 - 0.5) / (1.5 - 0.5) * (8.0 - 3.0) = 3.0 + 0.5 * 5 = 5.5
        assert 5.0 <= threshold <= 6.0

    def test_dynamic_threshold_volatile_market(self):
        """High volatility (σ > 1.5%) → loose threshold (8%)."""
        rebalancer = self._create_mock_rebalancer(premium_std=2.0)

        threshold = rebalancer.get_dynamic_threshold()
        assert threshold == 8.0

    def test_delta_state_neutral(self):
        """Delta state shows neutral when long == short."""
        rebalancer = self._create_mock_rebalancer(long_btc=0.5, short_btc=0.5)

        state = rebalancer.get_delta_state()

        assert state.long_btc == 0.5
        assert state.short_btc == 0.5
        assert state.net_delta == 0.0
        assert state.drift_pct == 0.0
        assert state.needs_rebalance is False

    def test_delta_state_drift(self):
        """Delta state detects drift when long != short."""
        # long = 0.6, short = 0.5 → drift = 0.1 / 0.6 = 16.7%
        rebalancer = self._create_mock_rebalancer(long_btc=0.6, short_btc=0.5)

        state = rebalancer.get_delta_state()

        assert state.long_btc == 0.6
        assert state.short_btc == 0.5
        assert state.net_delta == pytest.approx(0.1, rel=0.01)
        assert state.drift_pct > 10  # ~16.7%
        assert state.needs_rebalance is True

    def test_delta_state_no_rebalance_within_threshold(self):
        """No rebalance when drift within threshold."""
        # long = 0.51, short = 0.5 → drift = 0.01 / 0.51 = 1.96% < 3%
        rebalancer = self._create_mock_rebalancer(long_btc=0.51, short_btc=0.5, premium_std=0.3)

        state = rebalancer.get_delta_state()

        assert state.drift_pct < 3.0
        assert state.needs_rebalance is False

    def test_on_alpha_trade_buy(self):
        """on_alpha_trade accumulates buy correctly."""
        rebalancer = self._create_mock_rebalancer()

        rebalancer.on_alpha_trade(0.1, "buy")
        assert rebalancer._pending_delta == pytest.approx(0.1, rel=0.01)

        rebalancer.on_alpha_trade(0.05, "buy")
        assert rebalancer._pending_delta == pytest.approx(0.15, rel=0.01)

    def test_on_alpha_trade_sell(self):
        """on_alpha_trade accumulates sell correctly."""
        rebalancer = self._create_mock_rebalancer()

        rebalancer.on_alpha_trade(0.1, "sell")
        assert rebalancer._pending_delta == -0.1

    def test_on_alpha_trade_batching(self):
        """Multiple trades batch into single delta."""
        rebalancer = self._create_mock_rebalancer()

        rebalancer.on_alpha_trade(0.1, "buy")
        rebalancer.on_alpha_trade(0.05, "sell")
        rebalancer.on_alpha_trade(0.02, "buy")

        # Net: +0.1 - 0.05 + 0.02 = +0.07
        assert rebalancer._pending_delta == pytest.approx(0.07, rel=0.01)

    @pytest.mark.asyncio
    async def test_flush_rebalance_triggers_adjustment(self):
        """flush_rebalance triggers HedgeManager.adjust_position."""
        # Large drift to trigger rebalance
        rebalancer = self._create_mock_rebalancer(long_btc=0.6, short_btc=0.4)

        result = await rebalancer.flush_rebalance(binance_price=95000)

        assert result is not None
        assert result["success"] is True
        rebalancer.hedge_manager.adjust_position.assert_called_once()

    @pytest.mark.asyncio
    async def test_flush_rebalance_no_position(self):
        """flush_rebalance returns None if no hedge position."""
        rebalancer = self._create_mock_rebalancer(long_btc=0.5, short_btc=0)
        rebalancer.hedge_manager.hedge_position = None

        result = await rebalancer.flush_rebalance(binance_price=95000)

        assert result is None

    @pytest.mark.asyncio
    async def test_flush_rebalance_within_threshold(self):
        """flush_rebalance returns None if within threshold."""
        # Small drift
        rebalancer = self._create_mock_rebalancer(long_btc=0.51, short_btc=0.5, premium_std=0.3)

        result = await rebalancer.flush_rebalance(binance_price=95000)

        assert result is None
        rebalancer.hedge_manager.adjust_position.assert_not_called()

    def test_get_stats(self):
        """get_stats returns correct structure."""
        rebalancer = self._create_mock_rebalancer(long_btc=0.5, short_btc=0.5)

        stats = rebalancer.get_stats()

        assert "current_state" in stats
        assert "pending_delta" in stats
        assert "rebalance_count" in stats
        assert "total_qty_adjusted" in stats
        assert "total_fees_paid" in stats


class TestHedgeManagerAdjustPosition:
    """Test HedgeManager.adjust_position method."""

    def _create_mock_hedge_manager(self, current_qty: float = 0.5):
        """Create mock HedgeManager with position."""
        from trading.execution.hedge_manager import HedgeManager, HedgePosition

        # Mock components
        binance_account = MagicMock()
        premium_controller = MagicMock()

        hedge_manager = HedgeManager(
            binance_account=binance_account,
            premium_controller=premium_controller,
            config={
                "capital_usdt": 100000,  # Increased to avoid capital capping in tests
                "max_capital_usage_pct": 0.8,
                "fee_pct": 0.04,
                "slippage_pct": 0.02,
            },
            telegram_notifier=None,
            execution_mode="paper",
        )

        if current_qty > 0:
            hedge_manager.hedge_position = HedgePosition(
                qty=current_qty,
                entry_price=95000,
                entry_premium=1.5,
                entry_time=datetime.now(),
            )

        return hedge_manager

    @pytest.mark.asyncio
    async def test_adjust_position_increase(self):
        """adjust_position increases short when target > current."""
        hedge_manager = self._create_mock_hedge_manager(current_qty=0.5)

        result = await hedge_manager.adjust_position(target_qty=0.6, current_price=95000)

        assert result is not None
        assert result["direction"] == "increase"
        assert result["qty_adjusted"] == pytest.approx(0.1, rel=0.01)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_adjust_position_decrease(self):
        """adjust_position decreases short when target < current."""
        hedge_manager = self._create_mock_hedge_manager(current_qty=0.5)

        result = await hedge_manager.adjust_position(target_qty=0.4, current_price=95000)

        assert result is not None
        assert result["direction"] == "decrease"
        assert result["qty_adjusted"] == pytest.approx(0.1, rel=0.01)
        assert result["success"] is True

    @pytest.mark.asyncio
    async def test_adjust_position_no_change(self):
        """adjust_position returns None if no significant change."""
        hedge_manager = self._create_mock_hedge_manager(current_qty=0.5)

        result = await hedge_manager.adjust_position(target_qty=0.5001, current_price=95000)

        assert result is None

    @pytest.mark.asyncio
    async def test_adjust_position_no_position(self):
        """adjust_position returns None if no position exists."""
        hedge_manager = self._create_mock_hedge_manager(current_qty=0)
        hedge_manager.hedge_position = None

        result = await hedge_manager.adjust_position(target_qty=0.5, current_price=95000)

        assert result is None


class TestAlphaManagerRebalancerNotification:
    """Test AlphaManager notifications to DeltaRebalancer."""

    def test_alpha_manager_accepts_rebalancer(self):
        """AlphaManager accepts delta_rebalancer parameter."""
        from trading.execution.alpha_manager import AlphaManager
        from trading.strategy.regime_router import RegimeRouter

        upbit_account = MagicMock()
        upbit_account.get_balance.return_value = (10_000_000, 0)

        router = MagicMock(spec=RegimeRouter)
        rebalancer = MagicMock()

        alpha_manager = AlphaManager(
            upbit_account=upbit_account,
            regime_router=router,
            allocation_config={"upbit": {}},
            delta_rebalancer=rebalancer,
        )

        assert alpha_manager.delta_rebalancer is rebalancer
