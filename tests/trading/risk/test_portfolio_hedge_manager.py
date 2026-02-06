"""Tests for PortfolioHedgeManager."""

import pytest
from trading.risk.portfolio_hedge_manager import PortfolioHedgeManager, HedgeState


class TestPortfolioHedgeManager:
    """Test state machine transitions, hysteresis, and budget calculation."""

    def _make_manager(self, **kwargs):
        defaults = dict(
            initial_capital=10_000,
            activate_drawdown_pct=10.0,
            deactivate_drawdown_pct=5.0,
            hedge_budget_pct=0.20,
        )
        defaults.update(kwargs)
        return PortfolioHedgeManager(**defaults)

    # --- Basic state transitions ---

    def test_starts_in_normal_mode(self):
        mgr = self._make_manager()
        assert mgr.mode == "normal"
        assert not mgr.hedge_active

    def test_normal_to_hedge_at_threshold(self):
        mgr = self._make_manager()
        mgr.update(10_000)  # set peak
        state = mgr.update(9_000)  # exactly 10% drawdown
        assert state.mode == "hedge"
        assert mgr.hedge_active
        assert state.activation_count == 1

    def test_no_transition_below_threshold(self):
        mgr = self._make_manager()
        mgr.update(10_000)
        state = mgr.update(9_100)  # 9% drawdown, below 10%
        assert state.mode == "normal"
        assert not mgr.hedge_active

    def test_hedge_to_normal_with_hysteresis(self):
        mgr = self._make_manager()
        mgr.update(10_000)
        mgr.update(9_000)  # activate at 10%
        assert mgr.hedge_active

        # At 6% drawdown (still above 5% deactivate) → stays hedge
        state = mgr.update(9_400)
        assert state.mode == "hedge"

        # At 4.9% drawdown (below 5%) → deactivates
        state = mgr.update(9_510)
        assert state.mode == "normal"
        assert not mgr.hedge_active

    def test_no_oscillation_in_hysteresis_band(self):
        """Drawdown between 5-10% after activation should stay in hedge."""
        mgr = self._make_manager()
        mgr.update(10_000)
        mgr.update(8_900)  # 11% → activate
        assert mgr.hedge_active

        # Bounce around in the hysteresis band (5-10%)
        for equity in [9_200, 9_100, 9_300, 9_050, 9_400]:
            state = mgr.update(equity)
            assert state.mode == "hedge", f"Should stay hedge at equity={equity}"

        # Only deactivate below 5%
        state = mgr.update(9_600)  # 4% drawdown (peak still 10000)
        assert state.mode == "normal"

    # --- Peak equity tracking ---

    def test_peak_equity_tracks_new_highs(self):
        mgr = self._make_manager()
        mgr.update(10_000)
        assert mgr.peak_equity == 10_000

        mgr.update(11_000)
        assert mgr.peak_equity == 11_000

        mgr.update(10_500)
        assert mgr.peak_equity == 11_000  # unchanged after decline

    def test_peak_resets_after_recovery(self):
        """After recovering past peak, new peak is established."""
        mgr = self._make_manager()
        mgr.update(10_000)
        mgr.update(8_500)  # 15% drawdown → hedge
        assert mgr.hedge_active

        # Recover past peak
        mgr.update(10_500)  # new peak, 0% drawdown
        assert mgr.peak_equity == 10_500
        assert not mgr.hedge_active  # below 5% dd (0%)

    # --- Multiple activation cycles ---

    def test_multiple_activation_cycles(self):
        mgr = self._make_manager()

        # Cycle 1
        mgr.update(10_000)
        mgr.update(9_000)  # activate
        assert mgr.activation_count == 1
        mgr.update(10_000)  # recover → deactivate (0% dd)
        assert not mgr.hedge_active

        # Cycle 2
        mgr.update(10_000)
        mgr.update(8_900)  # activate again (11%)
        assert mgr.activation_count == 2
        assert mgr.hedge_active

    # --- Hedge budget ---

    def test_hedge_budget_calculation(self):
        mgr = self._make_manager(initial_capital=10_000, hedge_budget_pct=0.20)
        assert mgr.hedge_budget == 2_000

    def test_hedge_budget_different_pcts(self):
        mgr = self._make_manager(initial_capital=50_000, hedge_budget_pct=0.30)
        assert mgr.hedge_budget == 15_000

    # --- HedgeState dataclass ---

    def test_state_fields(self):
        mgr = self._make_manager()
        mgr.update(10_000)
        state = mgr.update(8_800)  # 12% drawdown
        assert state.mode == "hedge"
        assert abs(state.drawdown_pct - 12.0) < 0.01
        assert state.peak_equity == 10_000
        assert state.current_equity == 8_800
        assert state.hedge_activated_at == pytest.approx(12.0, abs=0.01)
        assert state.activation_count == 1

    def test_state_holds_last_activation_drawdown(self):
        mgr = self._make_manager()
        mgr.update(10_000)
        state = mgr.update(8_800)  # activate at 12%
        assert state.hedge_activated_at == pytest.approx(12.0, abs=0.01)

        # Drawdown deepens but hedge_activated_at doesn't change
        state = mgr.update(8_000)  # 20% dd
        assert state.hedge_activated_at == pytest.approx(12.0, abs=0.01)

    # --- Reset ---

    def test_reset(self):
        mgr = self._make_manager()
        mgr.update(10_000)
        mgr.update(8_500)
        assert mgr.hedge_active

        mgr.reset()
        assert mgr.mode == "normal"
        assert mgr.peak_equity == 0.0
        assert mgr.activation_count == 0

    # --- Validation ---

    def test_invalid_thresholds_raises(self):
        with pytest.raises(ValueError, match="deactivate_drawdown_pct"):
            PortfolioHedgeManager(
                activate_drawdown_pct=10.0,
                deactivate_drawdown_pct=10.0,  # must be less than activate
            )

        with pytest.raises(ValueError, match="deactivate_drawdown_pct"):
            PortfolioHedgeManager(
                activate_drawdown_pct=5.0,
                deactivate_drawdown_pct=10.0,  # greater than activate
            )

    # --- Edge cases ---

    def test_zero_equity(self):
        mgr = self._make_manager()
        mgr.update(10_000)
        state = mgr.update(0)  # 100% drawdown
        assert state.mode == "hedge"
        assert state.drawdown_pct == 100.0

    def test_first_update_sets_peak(self):
        mgr = self._make_manager()
        state = mgr.update(5_000)
        assert state.peak_equity == 5_000
        assert state.drawdown_pct == 0.0
        assert state.mode == "normal"

    def test_drawdown_pct_property(self):
        mgr = self._make_manager()
        mgr.update(10_000)
        mgr.update(9_500)
        assert mgr.drawdown_pct == pytest.approx(5.0, abs=0.01)

    def test_exact_deactivate_threshold_stays_hedge(self):
        """At exactly the deactivate threshold, should stay in hedge (< is strict)."""
        mgr = self._make_manager()
        mgr.update(10_000)
        mgr.update(8_000)  # activate at 20%
        assert mgr.hedge_active

        # Exactly 5% drawdown → stays in hedge (deactivate requires < 5%)
        state = mgr.update(9_500)
        assert state.mode == "hedge"
