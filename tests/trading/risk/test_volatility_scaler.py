"""Tests for volatility-based position scaling."""

import pytest
from trading.risk.volatility_scaler import compute_volatility_scale


class TestComputeVolatilityScale:
    """Test compute_volatility_scale function."""

    def test_low_vol_clamped_to_max(self):
        """Low volatility (ATR/price = 1%) should scale up but clamp to max_scale."""
        # ATR/price = 1%, target = 2% -> raw scale = 2.0 -> clamped to 1.0
        scale = compute_volatility_scale(atr=1000, price=100_000, target_vol=0.02)
        assert scale == 1.0

    def test_target_vol_returns_one(self):
        """When realized vol matches target, scale should be 1.0."""
        # ATR/price = 2%, target = 2% -> scale = 1.0
        scale = compute_volatility_scale(atr=2000, price=100_000, target_vol=0.02)
        assert scale == pytest.approx(1.0)

    def test_high_vol_reduces_scale(self):
        """High volatility (ATR/price = 4%) should halve the position."""
        # ATR/price = 4%, target = 2% -> scale = 0.5
        scale = compute_volatility_scale(atr=4000, price=100_000, target_vol=0.02)
        assert scale == pytest.approx(0.5)

    def test_very_high_vol_clamped_to_min(self):
        """Very high volatility (ATR/price = 8%) should clamp to min_scale."""
        # ATR/price = 8%, target = 2% -> raw scale = 0.25 -> clamped to 0.25
        scale = compute_volatility_scale(atr=8000, price=100_000, target_vol=0.02)
        assert scale == pytest.approx(0.25)

    def test_extreme_vol_below_min(self):
        """Extreme volatility beyond min_scale should clamp."""
        # ATR/price = 16%, target = 2% -> raw scale = 0.125 -> clamped to 0.25
        scale = compute_volatility_scale(atr=16000, price=100_000, target_vol=0.02)
        assert scale == 0.25

    def test_zero_atr_returns_one(self):
        """ATR=0 should return 1.0 (no scaling)."""
        scale = compute_volatility_scale(atr=0, price=100_000, target_vol=0.02)
        assert scale == 1.0

    def test_zero_price_returns_one(self):
        """Price=0 should return 1.0 (no scaling)."""
        scale = compute_volatility_scale(atr=2000, price=0, target_vol=0.02)
        assert scale == 1.0

    def test_negative_atr_returns_one(self):
        """Negative ATR should return 1.0 (no scaling)."""
        scale = compute_volatility_scale(atr=-1000, price=100_000, target_vol=0.02)
        assert scale == 1.0

    def test_negative_price_returns_one(self):
        """Negative price should return 1.0 (no scaling)."""
        scale = compute_volatility_scale(atr=2000, price=-100_000, target_vol=0.02)
        assert scale == 1.0

    def test_custom_min_max_scale(self):
        """Custom min/max scale parameters should be respected."""
        # ATR/price = 1%, target = 2% -> raw scale = 2.0 -> clamped to max_scale=1.5
        scale = compute_volatility_scale(
            atr=1000, price=100_000, target_vol=0.02,
            min_scale=0.1, max_scale=1.5,
        )
        assert scale == 1.5

        # ATR/price = 20%, target = 2% -> raw scale = 0.1 -> clamped to min_scale=0.1
        scale = compute_volatility_scale(
            atr=20000, price=100_000, target_vol=0.02,
            min_scale=0.1, max_scale=1.5,
        )
        assert scale == 0.1

    def test_custom_target_vol(self):
        """Custom target_vol should change the neutral point."""
        # ATR/price = 4%, target = 4% -> scale = 1.0
        scale = compute_volatility_scale(
            atr=4000, price=100_000, target_vol=0.04,
        )
        assert scale == pytest.approx(1.0)

    def test_eth_typical_values(self):
        """Test with typical ETH values."""
        # ETH at $3000, ATR = $90 (3% vol), target = 2%
        # scale = 0.02 / 0.03 = 0.667
        scale = compute_volatility_scale(atr=90, price=3000, target_vol=0.02)
        assert scale == pytest.approx(0.667, abs=0.01)

    def test_sol_typical_values(self):
        """Test with typical SOL values (higher vol)."""
        # SOL at $150, ATR = $9 (6% vol), target = 2%
        # scale = 0.02 / 0.06 = 0.333
        scale = compute_volatility_scale(atr=9, price=150, target_vol=0.02)
        assert scale == pytest.approx(0.333, abs=0.01)

    def test_monotonically_decreasing_with_vol(self):
        """Scale should decrease as volatility increases."""
        scales = []
        for atr_pct in [0.01, 0.02, 0.03, 0.04, 0.06, 0.08]:
            atr = 100_000 * atr_pct
            scale = compute_volatility_scale(
                atr=atr, price=100_000, target_vol=0.02,
                min_scale=0.0, max_scale=10.0,  # Widen bounds to see full curve
            )
            scales.append(scale)
        # Each successive scale should be <= previous
        for i in range(1, len(scales)):
            assert scales[i] <= scales[i - 1]
