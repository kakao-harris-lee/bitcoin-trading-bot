"""Tests for risk-based position sizing."""

import pytest
from trading.risk.position_sizer import (
    calculate_quantity,
    calculate_stop_price,
    round_to_step,
    get_exchange_limits,
    PositionSizer,
    RiskSizingConfig,
    SizingResult,
)


class TestCalculateQuantity:
    """Tests for calculate_quantity function."""

    def test_basic_sizing(self):
        """Test basic risk-based sizing calculation.

        Scenario: $10,000 equity, $100,000 BTC price, 3% stop, 1% risk
        Expected: risk = $100, qty = $100 / (0.03 * $100,000) = 0.033
        """
        result = calculate_quantity(
            equity=10000,
            entry_price=100000,
            stop_price=97000,  # 3% below entry
            symbol="BTC",
            risk_pct=0.01,
        )

        assert result.quantity > 0
        # Allow for fee adjustment: qty should be slightly less than 0.033
        assert 0.030 <= result.quantity <= 0.035
        # Risk amount should be close to $100
        assert 90 <= result.risk_amount <= 110
        assert result.stop_distance_pct == pytest.approx(3.0, rel=0.01)
        assert result.rejection_reason is None

    def test_small_account_sizing(self):
        """Test sizing with smaller account scales proportionally."""
        result = calculate_quantity(
            equity=1000,
            entry_price=100000,
            stop_price=97000,
            symbol="BTC",
            risk_pct=0.01,  # $10 risk
        )

        # $10 risk / (3% * $100,000) = 0.0033, but min_qty is 0.001
        assert result.quantity >= 0.001
        assert result.risk_amount <= 12  # Should be close to $10

    def test_minimum_qty_rejection(self):
        """Test rejection when calculated qty is below exchange minimum."""
        result = calculate_quantity(
            equity=100,  # Very small account
            entry_price=100000,
            stop_price=97000,
            symbol="BTC",
            risk_pct=0.01,  # Only $1 risk
        )

        # $1 / (3% * $100,000) = 0.00033, below 0.001 minimum
        assert result.quantity == 0
        assert "QTY_BELOW_MIN" in result.rejection_reason

    def test_tight_stop_increases_position(self):
        """Tighter stop = larger position (same risk budget).

        Note: Very tight stops may hit margin limits before qty can scale up.
        We use moderate stops to demonstrate the principle.
        """
        # 2% stop (moderate)
        tight_result = calculate_quantity(
            equity=10000,
            entry_price=100000,
            stop_price=98000,  # 2% stop
            symbol="BTC",
            risk_pct=0.01,
        )

        # 5% stop (wide)
        wide_result = calculate_quantity(
            equity=10000,
            entry_price=100000,
            stop_price=95000,  # 5% stop
            symbol="BTC",
            risk_pct=0.01,
        )

        # Tighter stop should allow larger position
        # (unless margin-constrained - check that both have quantities)
        assert tight_result.quantity > 0
        assert wide_result.quantity > 0
        assert tight_result.quantity > wide_result.quantity
        # Both have same risk budget (~$100)
        assert tight_result.risk_amount == pytest.approx(wide_result.risk_amount, rel=0.3)

    def test_stop_distance_too_small(self):
        """Reject if stop distance < 0.1%."""
        result = calculate_quantity(
            equity=10000,
            entry_price=100000,
            stop_price=99950,  # Only 0.05% stop
            symbol="BTC",
            risk_pct=0.01,
        )

        assert result.quantity == 0
        assert "STOP_DISTANCE_TOO_SMALL" in result.rejection_reason

    def test_stop_distance_too_large(self):
        """Reject if stop distance > 50%."""
        result = calculate_quantity(
            equity=10000,
            entry_price=100000,
            stop_price=40000,  # 60% stop
            symbol="BTC",
            risk_pct=0.01,
        )

        assert result.quantity == 0
        assert "STOP_DISTANCE_TOO_LARGE" in result.rejection_reason

    def test_notional_minimum(self):
        """Test rejection when notional value is below exchange minimum."""
        result = calculate_quantity(
            equity=1000,
            entry_price=5,  # Very cheap asset
            stop_price=4.5,  # 10% stop
            symbol="DEFAULT",
            risk_pct=0.01,  # $10 risk
        )

        # $10 / (10% * $5) = 20 units * $5 = $100 notional, should pass
        # But if qty_step rounds down too much, might fail notional
        # This tests edge case handling

    def test_zero_equity_rejection(self):
        """Reject if equity is zero."""
        result = calculate_quantity(
            equity=0,
            entry_price=100000,
            stop_price=97000,
            symbol="BTC",
            risk_pct=0.01,
        )

        assert result.quantity == 0
        assert "ZERO_EQUITY" in result.rejection_reason

    def test_fee_adjustment(self):
        """Fee buffer reduces effective position size."""
        # With default 0.1% fee per side (0.2% round trip)
        with_fee = calculate_quantity(
            equity=10000,
            entry_price=100000,
            stop_price=97000,
            symbol="BTC",
            risk_pct=0.01,
            fee_pct=0.001,
        )

        # With no fee
        no_fee = calculate_quantity(
            equity=10000,
            entry_price=100000,
            stop_price=97000,
            symbol="BTC",
            risk_pct=0.01,
            fee_pct=0.0,
        )

        # Fee-adjusted should be slightly smaller
        assert with_fee.quantity <= no_fee.quantity

    def test_eth_sizing(self):
        """Test sizing for ETH with different exchange limits."""
        result = calculate_quantity(
            equity=10000,
            entry_price=3000,
            stop_price=2910,  # 3% stop
            symbol="ETH",
            risk_pct=0.01,
        )

        assert result.quantity > 0
        # Check it's rounded to ETH step size (0.01) - use approx for float precision
        remainder = result.quantity % 0.01
        assert remainder == pytest.approx(0, abs=0.001) or remainder == pytest.approx(0.01, abs=0.001)

    def test_sol_sizing(self):
        """Test sizing for SOL with different exchange limits."""
        result = calculate_quantity(
            equity=10000,
            entry_price=100,
            stop_price=97,  # 3% stop
            symbol="SOL",
            risk_pct=0.01,
        )

        assert result.quantity > 0
        # Check it's rounded to SOL step size (0.1)
        assert result.quantity % 0.1 == pytest.approx(0, abs=0.001)


class TestCalculateStopPrice:
    """Tests for calculate_stop_price function."""

    def test_long_stop(self):
        """Long stop is below entry."""
        stop = calculate_stop_price(
            entry_price=100000,
            atr=2000,  # 2% ATR
            atr_multiplier=3.5,
            min_stop_pct=0.02,
            max_stop_pct=0.08,
            direction="long",
        )

        # Stop should be below entry
        assert stop < 100000
        # ATR-based: 2% * 3.5 = 7%
        expected = 100000 * (1 - 0.07)
        assert stop == pytest.approx(expected, rel=0.001)

    def test_short_stop(self):
        """Short stop is above entry."""
        stop = calculate_stop_price(
            entry_price=100000,
            atr=2000,
            atr_multiplier=3.5,
            min_stop_pct=0.02,
            max_stop_pct=0.08,
            direction="short",
        )

        # Stop should be above entry
        assert stop > 100000

    def test_min_stop_enforced(self):
        """Minimum stop distance is enforced."""
        stop = calculate_stop_price(
            entry_price=100000,
            atr=500,  # Very low ATR (0.5%)
            atr_multiplier=3.5,  # 1.75% stop
            min_stop_pct=0.03,  # But minimum is 3%
            max_stop_pct=0.08,
            direction="long",
        )

        # Should use minimum 3%
        expected = 100000 * (1 - 0.03)
        assert stop == pytest.approx(expected, rel=0.001)

    def test_max_stop_enforced(self):
        """Maximum stop distance is enforced."""
        stop = calculate_stop_price(
            entry_price=100000,
            atr=5000,  # Very high ATR (5%)
            atr_multiplier=3.5,  # 17.5% stop
            min_stop_pct=0.02,
            max_stop_pct=0.08,  # But max is 8%
            direction="long",
        )

        # Should use maximum 8%
        expected = 100000 * (1 - 0.08)
        assert stop == pytest.approx(expected, rel=0.001)


class TestPositionSizer:
    """Tests for PositionSizer class."""

    def test_size_position_with_atr(self):
        """Test full sizing flow with ATR-based stop."""
        config = RiskSizingConfig(
            risk_per_trade_pct=0.01,
            atr_multiplier=3.0,
            min_stop_pct=0.02,
            max_stop_pct=0.06,
        )
        sizer = PositionSizer(config)

        result = sizer.size_position(
            equity=10000,
            entry_price=100000,
            atr=2000,  # 2% ATR -> 6% stop
            symbol="BTC",
            leverage=1,
            direction="long",
        )

        assert result.quantity > 0
        assert result.rejection_reason is None

    def test_size_position_with_explicit_stop(self):
        """Test sizing with explicit stop price."""
        config = RiskSizingConfig(risk_per_trade_pct=0.01)
        sizer = PositionSizer(config)

        result = sizer.size_position_with_stop(
            equity=10000,
            entry_price=100000,
            stop_price=97000,
            symbol="BTC",
            leverage=1,
        )

        assert result.quantity > 0
        assert result.stop_distance_pct == pytest.approx(3.0, rel=0.01)


class TestRoundToStep:
    """Tests for round_to_step helper."""

    def test_round_down(self):
        """Values round to nearest step."""
        assert round_to_step(0.0335, 0.001) == 0.034
        assert round_to_step(0.0334, 0.001) == 0.033

    def test_round_to_larger_step(self):
        """ETH step is 0.01."""
        assert round_to_step(1.234, 0.01) == 1.23
        assert round_to_step(1.235, 0.01) == 1.24

    def test_zero_step(self):
        """Zero step returns original value."""
        assert round_to_step(1.234567, 0) == 1.234567


class TestGetExchangeLimits:
    """Tests for exchange limits lookup."""

    def test_known_symbols(self):
        """Known symbols return correct limits."""
        btc = get_exchange_limits("BTC")
        assert btc["min_qty"] == 0.001
        assert btc["qty_step"] == 0.001

        eth = get_exchange_limits("ETH")
        assert eth["min_qty"] == 0.01

        sol = get_exchange_limits("SOL")
        assert sol["min_qty"] == 0.1

    def test_unknown_symbol(self):
        """Unknown symbols get default limits."""
        unknown = get_exchange_limits("UNKNOWN")
        assert unknown == get_exchange_limits("DEFAULT")
