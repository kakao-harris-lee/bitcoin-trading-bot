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
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(bearish_market_data, context)
        # Note: Short strategy also requires BEAR_STRONG regime internally
        # With MFI=45 and ADX=25, it should classify as BEAR_STRONG
        assert signal is not None

    def test_does_not_filter_extreme_volatility(self, entry, bearish_market_data):
        """Short strategy does not filter on volatility (per design)."""
        context = MarketContext(
            trend="BEAR",
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
            volatility_score=0.035,
            is_extreme_volatility=True,
            adx=15.0,
        )
        signal = entry.check_entry(sideways_market_data, context)
        assert signal is None

    def test_skips_extreme_volatility_any_trend(self, entry, sideways_market_data):
        """Sideways should skip extreme volatility regardless of trend."""
        for trend in ["BULL", "BEAR", "NEUTRAL"]:
            context = MarketContext(
                trend=trend,
                volatility_score=0.04,
                is_extreme_volatility=True,
                adx=15.0,
            )
            signal = entry.check_entry(sideways_market_data, context)
            assert signal is None, f"Should skip entry in {trend} with extreme volatility"


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
