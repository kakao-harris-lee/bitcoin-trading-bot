# tests/trading/strategies/components/test_market_context.py
"""Tests for MarketContext and context-based filtering.

Tests the build_market_context function and verifies that entry strategies
correctly filter based on trend direction and volatility conditions.
"""
import pytest
from trading.strategies.components.models import (
    MarketData,
    MarketContext,
    TradingContext,
    build_market_context,
)


class TestBuildMarketContext:
    """Test build_market_context function."""

    def test_bull_trend_above_threshold(self):
        """MFI > 52 should classify as BULL."""
        ctx = build_market_context(mfi=55.0, adx=20.0, atr=100, close=10000)
        assert ctx.trend == "BULL"

    def test_bull_trend_at_threshold(self):
        """MFI == 52 should classify as BULL."""
        ctx = build_market_context(mfi=52.0, adx=20.0, atr=100, close=10000)
        assert ctx.trend == "BULL"

    def test_bear_trend_below_threshold(self):
        """MFI < 48 should classify as BEAR."""
        ctx = build_market_context(mfi=45.0, adx=20.0, atr=100, close=10000)
        assert ctx.trend == "BEAR"

    def test_bear_trend_at_threshold(self):
        """MFI == 48 should classify as BEAR."""
        ctx = build_market_context(mfi=48.0, adx=20.0, atr=100, close=10000)
        assert ctx.trend == "BEAR"

    def test_neutral_trend_middle(self):
        """48 < MFI < 52 should classify as NEUTRAL."""
        ctx = build_market_context(mfi=50.0, adx=20.0, atr=100, close=10000)
        assert ctx.trend == "NEUTRAL"

    def test_neutral_trend_just_above_bear(self):
        """MFI = 48.1 should classify as NEUTRAL."""
        ctx = build_market_context(mfi=48.1, adx=20.0, atr=100, close=10000)
        assert ctx.trend == "NEUTRAL"

    def test_neutral_trend_just_below_bull(self):
        """MFI = 51.9 should classify as NEUTRAL."""
        ctx = build_market_context(mfi=51.9, adx=20.0, atr=100, close=10000)
        assert ctx.trend == "NEUTRAL"

    def test_volatility_score_calculation(self):
        """Volatility score should be ATR / close."""
        ctx = build_market_context(mfi=50.0, adx=20.0, atr=200, close=10000)
        assert ctx.volatility_score == 0.02

    def test_extreme_volatility_above_threshold(self):
        """Volatility > 3% should be flagged as extreme."""
        ctx = build_market_context(mfi=55.0, adx=20.0, atr=400, close=10000)
        assert ctx.is_extreme_volatility is True
        assert ctx.volatility_score == 0.04

    def test_extreme_volatility_at_boundary(self):
        """Volatility exactly at 3% threshold should NOT be extreme."""
        ctx = build_market_context(mfi=55.0, adx=20.0, atr=300, close=10000)
        assert ctx.is_extreme_volatility is False
        assert ctx.volatility_score == 0.03

    def test_normal_volatility(self):
        """Volatility < 3% should not be extreme."""
        ctx = build_market_context(mfi=55.0, adx=20.0, atr=100, close=10000)
        assert ctx.is_extreme_volatility is False
        assert ctx.volatility_score == 0.01

    def test_zero_close_price(self):
        """Zero close should result in zero volatility score."""
        ctx = build_market_context(mfi=55.0, adx=20.0, atr=100, close=0)
        assert ctx.volatility_score == 0.0
        assert ctx.is_extreme_volatility is False

    def test_adx_passed_through(self):
        """ADX value should be passed through to context."""
        ctx = build_market_context(mfi=50.0, adx=35.0, atr=100, close=10000)
        assert ctx.adx == 35.0

    def test_custom_volatility_threshold(self):
        """Custom volatility threshold should be respected."""
        # 2% volatility with 1.5% threshold should be extreme
        ctx = build_market_context(
            mfi=50.0, adx=20.0, atr=200, close=10000,
            volatility_threshold=0.015
        )
        assert ctx.is_extreme_volatility is True

        # Same volatility with 3% threshold should not be extreme
        ctx = build_market_context(
            mfi=50.0, adx=20.0, atr=200, close=10000,
            volatility_threshold=0.03
        )
        assert ctx.is_extreme_volatility is False


class TestRegimeClassification:
    """Test 7-level regime classification in build_market_context."""

    def test_bull_strong_regime(self):
        """High MFI + strong ADX should classify as BULL_STRONG."""
        ctx = build_market_context(mfi=55.0, adx=26.0, atr=100, close=10000)
        assert ctx.regime == "BULL_STRONG"

    def test_bull_moderate_regime(self):
        """High MFI + moderate ADX should classify as BULL_MODERATE."""
        ctx = build_market_context(mfi=55.0, adx=20.0, atr=100, close=10000)
        assert ctx.regime == "BULL_MODERATE"

    def test_sideways_up_regime(self):
        """Moderate-high MFI (49-54) should classify as SIDEWAYS_UP."""
        ctx = build_market_context(mfi=50.0, adx=15.0, atr=100, close=10000)
        assert ctx.regime == "SIDEWAYS_UP"

    def test_sideways_flat_regime(self):
        """Moderate MFI (41-49) should classify as SIDEWAYS_FLAT."""
        ctx = build_market_context(mfi=45.0, adx=15.0, atr=100, close=10000)
        assert ctx.regime == "SIDEWAYS_FLAT"

    def test_sideways_down_regime(self):
        """Low-moderate MFI (34-41) should classify as SIDEWAYS_DOWN."""
        ctx = build_market_context(mfi=38.0, adx=15.0, atr=100, close=10000)
        assert ctx.regime == "SIDEWAYS_DOWN"

    def test_bear_strong_regime(self):
        """Very low MFI + strong ADX should classify as BEAR_STRONG."""
        ctx = build_market_context(mfi=30.0, adx=26.0, atr=100, close=10000)
        assert ctx.regime == "BEAR_STRONG"

    def test_bear_moderate_regime(self):
        """Very low MFI + weak ADX should classify as BEAR_MODERATE."""
        ctx = build_market_context(mfi=30.0, adx=15.0, atr=100, close=10000)
        assert ctx.regime == "BEAR_MODERATE"

    def test_regime_boundary_bull_strong(self):
        """MFI=54 + ADX=25 should be BULL_STRONG (at thresholds)."""
        ctx = build_market_context(mfi=54.0, adx=25.0, atr=100, close=10000)
        assert ctx.regime == "BULL_STRONG"

    def test_regime_boundary_sideways_up(self):
        """MFI=49 should be SIDEWAYS_UP (at threshold)."""
        ctx = build_market_context(mfi=49.0, adx=15.0, atr=100, close=10000)
        assert ctx.regime == "SIDEWAYS_UP"

    def test_regime_and_trend_consistency(self):
        """Regime should be consistent with trend classification."""
        # BULL trend + BULL_STRONG regime
        ctx = build_market_context(mfi=55.0, adx=26.0, atr=100, close=10000)
        assert ctx.trend == "BULL"
        assert ctx.regime == "BULL_STRONG"

        # BEAR trend + BEAR_STRONG regime
        ctx = build_market_context(mfi=30.0, adx=26.0, atr=100, close=10000)
        assert ctx.trend == "BEAR"
        assert ctx.regime == "BEAR_STRONG"

        # NEUTRAL trend + SIDEWAYS_FLAT regime
        ctx = build_market_context(mfi=50.0, adx=15.0, atr=100, close=10000)
        assert ctx.trend == "NEUTRAL"
        assert ctx.regime == "SIDEWAYS_UP"  # MFI=50 is >= 49


class TestVolumeAnalysis:
    """Test volume analysis in build_market_context."""

    def test_volume_ratio_calculation(self):
        """Volume ratio should be volume / avg_volume."""
        ctx = build_market_context(
            mfi=50.0, adx=20.0, atr=100, close=10000,
            volume=2000, avg_volume=1000
        )
        assert ctx.volume_ratio == 2.0

    def test_high_volume_detection_above_threshold(self):
        """Volume > 1.5x average should be flagged as high."""
        ctx = build_market_context(
            mfi=50.0, adx=20.0, atr=100, close=10000,
            volume=2000, avg_volume=1000  # 2.0x > 1.5x threshold
        )
        assert ctx.is_high_volume is True
        assert ctx.volume_ratio == 2.0

    def test_high_volume_at_boundary(self):
        """Volume exactly at 1.5x threshold should NOT be high volume."""
        ctx = build_market_context(
            mfi=50.0, adx=20.0, atr=100, close=10000,
            volume=1500, avg_volume=1000  # 1.5x exactly
        )
        assert ctx.is_high_volume is False

    def test_normal_volume(self):
        """Volume < 1.5x average should not be high volume."""
        ctx = build_market_context(
            mfi=50.0, adx=20.0, atr=100, close=10000,
            volume=1200, avg_volume=1000  # 1.2x < 1.5x
        )
        assert ctx.is_high_volume is False
        assert ctx.volume_ratio == 1.2

    def test_volume_ratio_with_zero_avg_volume(self):
        """Should default to 1.0 when avg_volume is zero."""
        ctx = build_market_context(
            mfi=50.0, adx=20.0, atr=100, close=10000,
            volume=1000, avg_volume=0
        )
        assert ctx.volume_ratio == 1.0
        assert ctx.is_high_volume is False

    def test_custom_high_volume_threshold(self):
        """Custom high volume threshold should be respected."""
        # 1.3x volume with 1.2x threshold should be high
        ctx = build_market_context(
            mfi=50.0, adx=20.0, atr=100, close=10000,
            volume=1300, avg_volume=1000,
            high_volume_threshold=1.2
        )
        assert ctx.is_high_volume is True

        # Same volume with 1.5x threshold should not be high
        ctx = build_market_context(
            mfi=50.0, adx=20.0, atr=100, close=10000,
            volume=1300, avg_volume=1000,
            high_volume_threshold=1.5
        )
        assert ctx.is_high_volume is False


class TestRegimeTypeAndCaching:
    """Test Regime type and LRU caching behavior."""

    def test_regime_type_literal(self):
        """Regime should be one of the defined Literal values."""
        from trading.strategies.components.models import Regime, ALL_REGIMES

        # All regimes from build_market_context should be in ALL_REGIMES
        for mfi in [30, 38, 45, 50, 55]:
            for adx in [15, 20, 26]:
                ctx = build_market_context(mfi=float(mfi), adx=float(adx), atr=100, close=10000)
                assert ctx.regime in ALL_REGIMES

    def test_regime_classification_cache_hits(self):
        """LRU cache should provide hits for repeated similar values."""
        from trading.strategies.components.models import _classify_regime_cached

        # Clear cache stats
        _classify_regime_cached.cache_clear()

        # First call - cache miss
        build_market_context(mfi=55.0, adx=25.0, atr=100, close=10000)
        info1 = _classify_regime_cached.cache_info()
        assert info1.misses >= 1

        # Second call with same values - should hit cache
        build_market_context(mfi=55.0, adx=25.0, atr=100, close=10000)
        info2 = _classify_regime_cached.cache_info()
        assert info2.hits >= 1

    def test_regime_rounding_improves_cache_hits(self):
        """Similar values should round to same cache key."""
        from trading.strategies.components.models import _classify_regime_cached

        _classify_regime_cached.cache_clear()

        # First call
        build_market_context(mfi=55.01, adx=25.03, atr=100, close=10000)
        # Second call with slightly different values (rounds to same)
        build_market_context(mfi=55.04, adx=25.01, atr=100, close=10000)

        info = _classify_regime_cached.cache_info()
        # Both should round to 55.0, 25.0 so second call should hit
        assert info.hits >= 1


class TestRegimeThresholdExternalization:
    """Test that custom regime thresholds change classification."""

    def test_custom_mfi_bull_strong_raises_bar(self):
        """Higher mfi_bull_strong should make BULL_STRONG harder to reach."""
        # Default: MFI=55 + ADX=26 → BULL_STRONG
        ctx_default = build_market_context(mfi=55.0, adx=26.0, atr=100, close=10000)
        assert ctx_default.regime == "BULL_STRONG"

        # Custom: raise threshold to 58 → same MFI now only reaches BULL_MODERATE
        ctx_custom = build_market_context(
            mfi=55.0, adx=26.0, atr=100, close=10000,
            mfi_bull_strong=58.0, mfi_bull_moderate=58.0,
        )
        assert ctx_custom.regime == "SIDEWAYS_UP"

    def test_custom_mfi_bull_strong_lowers_bar(self):
        """Lower mfi_bull_strong should make BULL_STRONG easier to reach."""
        # Default: MFI=52 + ADX=26 → SIDEWAYS_UP (52 < 54)
        ctx_default = build_market_context(mfi=52.0, adx=26.0, atr=100, close=10000)
        assert ctx_default.regime == "SIDEWAYS_UP"

        # Custom: lower threshold to 50 → now qualifies as BULL_STRONG
        ctx_custom = build_market_context(
            mfi=52.0, adx=26.0, atr=100, close=10000,
            mfi_bull_strong=50.0, mfi_bull_moderate=50.0,
        )
        assert ctx_custom.regime == "BULL_STRONG"

    def test_custom_adx_strong_trend_threshold(self):
        """Custom ADX threshold changes trend strength classification."""
        # Default: ADX=22 is NOT strong (< 25) → BULL_MODERATE
        ctx_default = build_market_context(mfi=55.0, adx=22.0, atr=100, close=10000)
        assert ctx_default.regime == "BULL_MODERATE"

        # Custom: lower ADX threshold to 20 → now strong trend → BULL_STRONG
        ctx_custom = build_market_context(
            mfi=55.0, adx=22.0, atr=100, close=10000,
            adx_strong_trend=20.0,
        )
        assert ctx_custom.regime == "BULL_STRONG"

    def test_custom_mfi_bear_strong_threshold(self):
        """Custom MFI bear threshold changes bear/sideways boundary."""
        # Default: MFI=36 → SIDEWAYS_DOWN (>= 34)
        ctx_default = build_market_context(mfi=36.0, adx=15.0, atr=100, close=10000)
        assert ctx_default.regime == "SIDEWAYS_DOWN"

        # Custom: raise bear_strong to 38 → MFI=36 now below threshold → BEAR_MODERATE
        ctx_custom = build_market_context(
            mfi=36.0, adx=15.0, atr=100, close=10000,
            mfi_bear_strong=38.0,
        )
        assert ctx_custom.regime == "BEAR_MODERATE"

    def test_custom_sideways_up_threshold(self):
        """Custom sideways_up threshold changes sideways boundaries."""
        # Default: MFI=50 → SIDEWAYS_UP (>= 49)
        ctx_default = build_market_context(mfi=50.0, adx=15.0, atr=100, close=10000)
        assert ctx_default.regime == "SIDEWAYS_UP"

        # Custom: raise sideways_up to 52 → MFI=50 now SIDEWAYS_FLAT
        ctx_custom = build_market_context(
            mfi=50.0, adx=15.0, atr=100, close=10000,
            mfi_sideways_up=52.0,
        )
        assert ctx_custom.regime == "SIDEWAYS_FLAT"

    def test_default_thresholds_match_hardcoded(self):
        """Passing default threshold values explicitly gives same result as no args."""
        for mfi in [30.0, 38.0, 45.0, 50.0, 55.0]:
            for adx in [15.0, 20.0, 26.0]:
                ctx_implicit = build_market_context(mfi=mfi, adx=adx, atr=100, close=10000)
                ctx_explicit = build_market_context(
                    mfi=mfi, adx=adx, atr=100, close=10000,
                    mfi_bull_strong=54.0,
                    mfi_bull_moderate=54.0,
                    mfi_sideways_up=49.0,
                    mfi_bear_moderate=41.0,
                    mfi_bear_strong=34.0,
                    adx_strong_trend=25.0,
                    adx_moderate_trend=18.0,
                )
                assert ctx_implicit.regime == ctx_explicit.regime, (
                    f"Mismatch at MFI={mfi}, ADX={adx}: "
                    f"{ctx_implicit.regime} != {ctx_explicit.regime}"
                )

    def test_drawdown_bear_override_uses_custom_adx(self):
        """Drawdown BEAR override should use custom adx_strong_trend threshold."""
        # Drawdown BEAR with ADX=22: default ADX threshold=25 → BEAR_MODERATE
        ctx_default = build_market_context(
            mfi=55.0, adx=22.0, atr=100, close=8500,
            recent_high=10000, drawdown_bear_threshold=0.10,
        )
        assert ctx_default.is_drawdown_bear
        assert ctx_default.regime == "BEAR_MODERATE"

        # Custom: lower ADX threshold to 20 → ADX=22 now strong → BEAR_STRONG
        ctx_custom = build_market_context(
            mfi=55.0, adx=22.0, atr=100, close=8500,
            recent_high=10000, drawdown_bear_threshold=0.10,
            adx_strong_trend=20.0,
        )
        assert ctx_custom.is_drawdown_bear
        assert ctx_custom.regime == "BEAR_STRONG"

    def test_partial_threshold_override(self):
        """Passing only some thresholds uses defaults for the rest."""
        # Only override mfi_bull_strong, rest should use defaults
        ctx = build_market_context(
            mfi=55.0, adx=26.0, atr=100, close=10000,
            mfi_bull_strong=60.0,  # Raised — MFI=55 won't qualify
        )
        # mfi_bull_moderate default is 54.0, ADX=26 >= adx_moderate_trend=18 → BULL_MODERATE
        assert ctx.regime == "BULL_MODERATE"


class TestMarketContextImmutability:
    """Test that MarketContext is immutable."""

    def test_frozen_dataclass(self):
        """MarketContext should be immutable (frozen)."""
        ctx = build_market_context(mfi=50.0, adx=20.0, atr=100, close=10000)

        with pytest.raises(AttributeError):
            ctx.trend = "BULL"

        with pytest.raises(AttributeError):
            ctx.volatility_score = 0.5

        with pytest.raises(AttributeError):
            ctx.is_extreme_volatility = True
