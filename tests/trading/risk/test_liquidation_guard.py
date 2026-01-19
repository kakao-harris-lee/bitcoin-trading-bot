import pytest
from trading.risk.liquidation_guard import LiquidationGuard, LiquidationInfo


class TestLiquidationPriceCalculation:
    """Test liquidation price calculations for isolated margin."""

    def test_long_liquidation_price_5x(self):
        """Long 5x: liquidation when price drops ~20%."""
        guard = LiquidationGuard()

        liq_price = guard.calculate_liquidation_price(
            entry_price=100000,
            leverage=5,
            side="buy",
            position_value=10000,
        )

        # Formula: entry * (1 - 1/leverage + mmr)
        # 100000 * (1 - 0.20 + 0.004) = 80400
        assert liq_price == pytest.approx(80400, rel=0.01)

    def test_short_liquidation_price_5x(self):
        """Short 5x: liquidation when price rises ~20%."""
        guard = LiquidationGuard()

        liq_price = guard.calculate_liquidation_price(
            entry_price=100000,
            leverage=5,
            side="sell",
            position_value=10000,
        )

        # Formula: entry * (1 + 1/leverage - mmr)
        # 100000 * (1 + 0.20 - 0.004) = 119600
        assert liq_price == pytest.approx(119600, rel=0.01)

    def test_long_liquidation_price_10x(self):
        """Long 10x: liquidation when price drops ~10%."""
        guard = LiquidationGuard()

        liq_price = guard.calculate_liquidation_price(
            entry_price=100000,
            leverage=10,
            side="buy",
            position_value=10000,
        )

        # 100000 * (1 - 0.10 + 0.004) = 90400
        assert liq_price == pytest.approx(90400, rel=0.01)


class TestLiquidationDistanceCheck:
    """Test position safety checks."""

    def test_safe_long_position(self):
        """Position far from liquidation should be safe."""
        guard = LiquidationGuard()

        info = guard.check_position_safety(
            entry_price=100000,
            current_price=95000,
            liquidation_price=80400,
            side="buy",
        )

        assert info.should_exit is False
        assert info.distance_pct > 20  # Far from liquidation

    def test_dangerous_long_position(self):
        """Position close to liquidation should trigger exit."""
        guard = LiquidationGuard()

        info = guard.check_position_safety(
            entry_price=100000,
            current_price=82000,  # Very close to 80400 liquidation
            liquidation_price=80400,
            side="buy",
        )

        assert info.should_exit is True
        assert info.distance_pct < 20  # Within danger zone

    def test_safe_short_position(self):
        """Short position far from liquidation should be safe."""
        guard = LiquidationGuard()

        info = guard.check_position_safety(
            entry_price=100000,
            current_price=105000,  # Price rose but still safe
            liquidation_price=119600,  # Short liquidation at ~20% above
            side="sell",
        )

        assert info.should_exit is False
        assert info.distance_pct > 20  # Far from liquidation

    def test_dangerous_short_position(self):
        """Short position close to liquidation should trigger exit."""
        guard = LiquidationGuard()

        info = guard.check_position_safety(
            entry_price=100000,
            current_price=117000,  # Very close to 119600 liquidation
            liquidation_price=119600,
            side="sell",
        )

        assert info.should_exit is True
        assert info.distance_pct < 20  # Within danger zone


class TestMaintenanceMarginRates:
    """Test maintenance margin rate tier selection."""

    def test_small_position_rate(self):
        """Small positions get lowest rate."""
        guard = LiquidationGuard()
        rate = guard.get_maintenance_margin_rate(10000)  # $10k position
        assert rate == 0.004  # 0.4%

    def test_medium_position_rate(self):
        """Medium positions get higher rate."""
        guard = LiquidationGuard()
        rate = guard.get_maintenance_margin_rate(100000)  # $100k position
        assert rate == 0.005  # 0.5%

    def test_large_position_rate(self):
        """Large positions get highest rate tier."""
        guard = LiquidationGuard()
        rate = guard.get_maintenance_margin_rate(10_000_000)  # $10M position
        assert rate == 0.05  # 5.0%

    def test_custom_margin_rates(self):
        """Custom margin rates can be provided."""
        custom_rates = [
            (100_000, 0.01),
            (float('inf'), 0.02),
        ]
        guard = LiquidationGuard(maintenance_margin_rates=custom_rates)

        assert guard.get_maintenance_margin_rate(50000) == 0.01
        assert guard.get_maintenance_margin_rate(200000) == 0.02


class TestInputValidation:
    """Test input validation."""

    def test_negative_position_value_raises(self):
        """Negative position value should raise."""
        guard = LiquidationGuard()
        with pytest.raises(ValueError):
            guard.get_maintenance_margin_rate(-1000)

    def test_negative_entry_price_raises(self):
        """Negative entry price should raise."""
        guard = LiquidationGuard()
        with pytest.raises(ValueError):
            guard.calculate_liquidation_price(
                entry_price=-100,
                leverage=5,
                side="buy",
                position_value=10000,
            )

    def test_zero_leverage_raises(self):
        """Zero leverage should raise."""
        guard = LiquidationGuard()
        with pytest.raises(ValueError):
            guard.calculate_liquidation_price(
                entry_price=100000,
                leverage=0,
                side="buy",
                position_value=10000,
            )

    def test_invalid_side_raises(self):
        """Invalid side should raise."""
        guard = LiquidationGuard()
        with pytest.raises(ValueError):
            guard.calculate_liquidation_price(
                entry_price=100000,
                leverage=5,
                side="invalid",
                position_value=10000,
            )
