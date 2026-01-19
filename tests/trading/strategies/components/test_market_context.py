# tests/trading/strategies/components/test_market_context.py
"""Tests for MarketContext and context-based filtering.

Tests the build_market_context function and verifies that entry strategies
correctly filter based on trend direction and volatility conditions.
"""
import pytest
from trading.strategies.components.models import (
    MarketData,
    MarketContext,
    build_market_context,
)
from trading.strategies.components.v35_entry import V35EntryStrategy
from trading.strategies.components.short_entry import ShortEntryStrategy
from trading.strategies.components.sideways_entry import SidewaysEntryStrategy


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
    """Test V35-style regime classification in build_market_context."""

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


class TestV35ContextFiltering:
    """Test V35 entry context-based filtering."""

    @pytest.fixture
    def entry(self):
        """Create V35 entry strategy."""
        return V35EntryStrategy()

    @pytest.fixture
    def bullish_market_data(self):
        """Market data with bullish indicators for momentum entry."""
        return MarketData(
            symbol="BTC",
            close=95000.0,
            mfi=55.0,
            adx=25.0,
            rsi=58.0,  # Above momentum_rsi_bull_strong (57.0)
            timestamp=1000000,
            macd=1.5,  # MACD crossover (above signal)
            macd_signal=1.0,
        )

    def test_allows_bull_trend(self, entry, bullish_market_data):
        """V35 should allow entry when trend is BULL."""
        context = MarketContext(
            trend="BULL",
            regime="BULL_STRONG",  # MFI=55, ADX=25 -> BULL_STRONG
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(bullish_market_data, context)
        assert signal is not None
        assert signal.side == "buy"

    def test_skips_bear_trend(self, entry, bullish_market_data):
        """V35 should skip long entry when trend is BEAR."""
        context = MarketContext(
            trend="BEAR",
            regime="BEAR_STRONG",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(bullish_market_data, context)
        assert signal is None

    def test_allows_neutral_trend(self, entry, bullish_market_data):
        """V35 should allow entry when trend is NEUTRAL."""
        context = MarketContext(
            trend="NEUTRAL",
            regime="BULL_STRONG",  # High MFI/ADX in market_data
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(bullish_market_data, context)
        assert signal is not None

    def test_skips_extreme_volatility(self, entry, bullish_market_data):
        """V35 should skip entry during extreme volatility."""
        context = MarketContext(
            trend="BULL",
            regime="BULL_STRONG",
            volatility_score=0.04,
            is_extreme_volatility=True,
            adx=25.0,
        )
        signal = entry.check_entry(bullish_market_data, context)
        assert signal is None

    def test_skips_bear_and_extreme_volatility(self, entry, bullish_market_data):
        """V35 should skip when both BEAR trend and extreme volatility."""
        context = MarketContext(
            trend="BEAR",
            regime="BEAR_STRONG",
            volatility_score=0.05,
            is_extreme_volatility=True,
            adx=25.0,
        )
        signal = entry.check_entry(bullish_market_data, context)
        assert signal is None

    def test_allows_high_but_not_extreme_volatility(self, entry, bullish_market_data):
        """V35 should allow entry when volatility is high but not extreme."""
        context = MarketContext(
            trend="BULL",
            regime="BULL_STRONG",
            volatility_score=0.029,  # Just under 3%
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(bullish_market_data, context)
        assert signal is not None


class TestShortContextFiltering:
    """Test Short entry context-based filtering."""

    @pytest.fixture
    def entry(self):
        """Create Short entry strategy."""
        return ShortEntryStrategy()

    @pytest.fixture
    def bearish_market_data(self):
        """Market data with bearish indicators for short entry."""
        return MarketData(
            symbol="BTC",
            close=95000.0,
            mfi=45.0,  # Below mfi_bear (48)
            adx=25.0,  # Strong trend
            rsi=75.0,  # Overbought - good for short
            timestamp=1000000,
        )

    def test_allows_bear_trend(self, entry, bearish_market_data):
        """Short should allow entry when trend is BEAR."""
        context = MarketContext(
            trend="BEAR",
            regime="BEAR_STRONG",  # MFI=45, ADX=25 -> BEAR_STRONG
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(bearish_market_data, context)
        assert signal is not None
        assert signal.side == "sell"

    def test_skips_bull_trend(self, entry, bearish_market_data):
        """Short should skip entry when trend is BULL."""
        context = MarketContext(
            trend="BULL",
            regime="BULL_STRONG",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(bearish_market_data, context)
        assert signal is None

    def test_allows_neutral_trend(self, entry, bearish_market_data):
        """Short should allow entry when trend is NEUTRAL."""
        context = MarketContext(
            trend="NEUTRAL",
            regime="BEAR_STRONG",  # V35 regime with MFI=45, ADX=25
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(bearish_market_data, context)
        # Short strategy requires BEAR_STRONG regime from context
        assert signal is not None

    def test_does_not_filter_extreme_volatility(self, entry, bearish_market_data):
        """Short strategy does not filter on volatility (per design)."""
        context = MarketContext(
            trend="BEAR",
            regime="BEAR_STRONG",
            volatility_score=0.05,
            is_extreme_volatility=True,
            adx=25.0,
        )
        signal = entry.check_entry(bearish_market_data, context)
        # Short strategy doesn't check is_extreme_volatility
        assert signal is not None


class TestSidewaysContextFiltering:
    """Test Sideways entry context-based filtering."""

    @pytest.fixture
    def entry(self):
        """Create Sideways entry strategy."""
        return SidewaysEntryStrategy()

    @pytest.fixture
    def sideways_market_data(self):
        """Market data with sideways/neutral indicators."""
        return MarketData(
            symbol="ETH",
            close=3200.0,
            mfi=50.0,  # Neutral MFI
            adx=15.0,  # Low trend strength
            rsi=30.0,  # Oversold - good for mean reversion
            timestamp=1000000,
        )

    def test_allows_neutral_trend(self, entry, sideways_market_data):
        """Sideways should allow entry in NEUTRAL trend."""
        context = MarketContext(
            trend="NEUTRAL",
            regime="SIDEWAYS_FLAT",  # MFI=50, ADX=15 -> SIDEWAYS_FLAT
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=15.0,
        )
        signal = entry.check_entry(sideways_market_data, context)
        assert signal is not None
        assert signal.side == "buy"

    def test_allows_bull_trend(self, entry, sideways_market_data):
        """Sideways should allow entry in BULL trend (all trends allowed)."""
        context = MarketContext(
            trend="BULL",
            regime="SIDEWAYS_UP",  # Sideways regime for this test
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=15.0,
        )
        signal = entry.check_entry(sideways_market_data, context)
        assert signal is not None

    def test_allows_bear_trend(self, entry, sideways_market_data):
        """Sideways should allow entry in BEAR trend (all trends allowed)."""
        context = MarketContext(
            trend="BEAR",
            regime="SIDEWAYS_DOWN",  # Sideways regime for this test
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=15.0,
        )
        signal = entry.check_entry(sideways_market_data, context)
        assert signal is not None

    def test_skips_extreme_volatility(self, entry, sideways_market_data):
        """Sideways should skip entry during extreme volatility."""
        context = MarketContext(
            trend="NEUTRAL",
            regime="SIDEWAYS_FLAT",
            volatility_score=0.035,
            is_extreme_volatility=True,
            adx=15.0,
        )
        signal = entry.check_entry(sideways_market_data, context)
        assert signal is None

    def test_skips_extreme_volatility_any_trend(self, entry, sideways_market_data):
        """Sideways should skip extreme volatility regardless of trend."""
        regimes = {"BULL": "SIDEWAYS_UP", "BEAR": "SIDEWAYS_DOWN", "NEUTRAL": "SIDEWAYS_FLAT"}
        for trend, regime in regimes.items():
            context = MarketContext(
                trend=trend,
                regime=regime,
                volatility_score=0.04,
                is_extreme_volatility=True,
                adx=15.0,
            )
            signal = entry.check_entry(sideways_market_data, context)
            assert signal is None, f"Should skip entry in {trend} with extreme volatility"


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


class TestV35ADXSafetyFilter:
    """Test V35 entry ADX safety filter (weak trend detection)."""

    @pytest.fixture
    def entry(self):
        """Create V35 entry strategy."""
        return V35EntryStrategy()

    @pytest.fixture
    def bullish_market_data(self):
        """Market data with bullish indicators for momentum entry."""
        return MarketData(
            symbol="BTC",
            close=95000.0,
            mfi=55.0,
            adx=25.0,
            rsi=58.0,
            timestamp=1000000,
            macd=1.5,
            macd_signal=1.0,
        )

    def test_skips_entry_when_adx_below_threshold(self, entry, bullish_market_data):
        """V35 should skip entry when ADX indicates weak trend."""
        # ADX below adx_moderate_trend (18.0) should skip
        context = MarketContext(
            trend="BULL",
            regime="BULL_MODERATE",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=15.0,  # Below threshold
        )
        signal = entry.check_entry(bullish_market_data, context)
        assert signal is None

    def test_allows_entry_at_adx_threshold(self, entry, bullish_market_data):
        """V35 should allow entry when ADX exactly at moderate threshold."""
        context = MarketContext(
            trend="BULL",
            regime="BULL_MODERATE",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=18.0,  # At threshold
        )
        signal = entry.check_entry(bullish_market_data, context)
        assert signal is not None

    def test_allows_entry_above_adx_threshold(self, entry, bullish_market_data):
        """V35 should allow entry when ADX above threshold."""
        context = MarketContext(
            trend="BULL",
            regime="BULL_STRONG",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,  # Above threshold
        )
        signal = entry.check_entry(bullish_market_data, context)
        assert signal is not None


class TestSidewaysHighVolumeFilter:
    """Test Sideways entry high volume filter (breakout detection)."""

    @pytest.fixture
    def entry(self):
        """Create Sideways entry strategy."""
        return SidewaysEntryStrategy()

    @pytest.fixture
    def sideways_market_data(self):
        """Market data with sideways/neutral indicators."""
        return MarketData(
            symbol="ETH",
            close=3200.0,
            mfi=50.0,
            adx=15.0,
            rsi=30.0,  # Oversold
            timestamp=1000000,
        )

    def test_skips_entry_when_high_volume(self, entry, sideways_market_data):
        """Sideways should skip entry when high volume (potential breakout)."""
        context = MarketContext(
            trend="NEUTRAL",
            regime="SIDEWAYS_FLAT",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=15.0,
            volume_ratio=2.0,  # High volume
            is_high_volume=True,
        )
        signal = entry.check_entry(sideways_market_data, context)
        assert signal is None

    def test_allows_entry_normal_volume(self, entry, sideways_market_data):
        """Sideways should allow entry when volume is normal."""
        context = MarketContext(
            trend="NEUTRAL",
            regime="SIDEWAYS_FLAT",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=15.0,
            volume_ratio=1.2,  # Normal volume
            is_high_volume=False,
        )
        signal = entry.check_entry(sideways_market_data, context)
        assert signal is not None


class TestShortSidewaysVolatilityFilter:
    """Test Short entry SIDEWAYS + extreme volatility behavior."""

    @pytest.fixture
    def entry(self):
        """Create Short entry strategy."""
        return ShortEntryStrategy()

    @pytest.fixture
    def bearish_market_data(self):
        """Market data for short entry."""
        return MarketData(
            symbol="BTC",
            close=95000.0,
            mfi=45.0,
            adx=15.0,  # Weak trend for SIDEWAYS
            rsi=75.0,  # Overbought
            timestamp=1000000,
        )

    def test_allows_sideways_with_extreme_volatility(self, entry, bearish_market_data):
        """Short should allow entry in SIDEWAYS with extreme volatility."""
        context = MarketContext(
            trend="NEUTRAL",
            regime="SIDEWAYS_FLAT",
            volatility_score=0.05,
            is_extreme_volatility=True,
            adx=15.0,
        )
        signal = entry.check_entry(bearish_market_data, context)
        assert signal is not None

    def test_skips_sideways_without_extreme_volatility(self, entry, bearish_market_data):
        """Short should skip entry in SIDEWAYS without extreme volatility."""
        context = MarketContext(
            trend="NEUTRAL",
            regime="SIDEWAYS_FLAT",
            volatility_score=0.02,
            is_extreme_volatility=False,
            adx=15.0,
        )
        signal = entry.check_entry(bearish_market_data, context)
        assert signal is None

    def test_allows_bear_without_extreme_volatility(self, entry, bearish_market_data):
        """Short should allow BEAR regime without requiring extreme volatility."""
        context = MarketContext(
            trend="BEAR",
            regime="BEAR_STRONG",
            volatility_score=0.02,
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(bearish_market_data, context)
        assert signal is not None


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
