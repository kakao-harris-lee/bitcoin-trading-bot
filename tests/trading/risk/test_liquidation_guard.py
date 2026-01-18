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
