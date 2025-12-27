"""
Unit tests for VA02 Long Strategy components.
"""

import pytest
import pandas as pd
import numpy as np

from trading.strategy.va02_long import VA02ScoreEngine, MarketClassifier


class TestVA02ScoreEngine:
    """Test VA02ScoreEngine score calculation and tier classification."""

    @pytest.fixture
    def default_config(self):
        """Default configuration for VA02ScoreEngine."""
        return {
            'weights': {
                'rsi_oversold': 8,
                'mfi_bullish': 28,
                'volume_spike': 8,
                'low_vol': 15,
                'local_min': 20,
                'trend_following': 12,
                'mean_reversion': 10,
            },
            'indicators': {
                'rsi_threshold': 30,
                'mfi_bullish_threshold': 50,
                'mfi_very_bullish_threshold': 60,
                'volume_spike_ratio': 1.5,
                'low_vol_atr_ratio': 0.8,
                'very_low_vol_atr_ratio': 0.6,
                'adx_trend_threshold': 25,
                'adx_strong_trend_threshold': 40,
            },
            'tier_thresholds': {
                'S': 28,
                'A': 18,
                'B': 12,
            }
        }

    @pytest.fixture
    def engine(self, default_config):
        """Create a VA02ScoreEngine instance."""
        return VA02ScoreEngine(default_config)

    def test_classify_tier_s(self, engine):
        """Score >= 28 should be S tier."""
        assert engine.classify_tier(28) == 'S'
        assert engine.classify_tier(50) == 'S'
        assert engine.classify_tier(100) == 'S'

    def test_classify_tier_a(self, engine):
        """Score >= 18 and < 28 should be A tier."""
        assert engine.classify_tier(18) == 'A'
        assert engine.classify_tier(27) == 'A'

    def test_classify_tier_b(self, engine):
        """Score >= 12 and < 18 should be B tier."""
        assert engine.classify_tier(12) == 'B'
        assert engine.classify_tier(17) == 'B'

    def test_classify_tier_c(self, engine):
        """Score < 12 should be C tier."""
        assert engine.classify_tier(0) == 'C'
        assert engine.classify_tier(11) == 'C'

    def test_calculate_score_rsi_oversold(self, engine):
        """RSI <= 30 should add 8 points."""
        row = pd.Series({
            'rsi': 25,
            'mfi': 40,
            'volume_ratio': 1.0,
            'atr_ratio': 1.0,
            'is_local_min': False,
            'adx': 15,
            'close': 100,
            'bb_lower': 90,
            'bb_position': 0.5,
        })
        score, signals = engine.calculate_score(row)
        assert 'RSI_OVERSOLD' in signals
        assert score >= 8

    def test_calculate_score_mfi_bullish(self, engine):
        """MFI >= 50 should add 28 points."""
        row = pd.Series({
            'rsi': 50,
            'mfi': 55,
            'volume_ratio': 1.0,
            'atr_ratio': 1.0,
            'is_local_min': False,
            'adx': 15,
            'close': 100,
            'bb_lower': 90,
            'bb_position': 0.5,
        })
        score, signals = engine.calculate_score(row)
        assert 'MFI_BULLISH' in signals
        assert score >= 28

    def test_calculate_score_mfi_very_bullish(self, engine):
        """MFI >= 60 should add extra bonus."""
        row = pd.Series({
            'rsi': 50,
            'mfi': 65,
            'volume_ratio': 1.0,
            'atr_ratio': 1.0,
            'is_local_min': False,
            'adx': 15,
            'close': 100,
            'bb_lower': 90,
            'bb_position': 0.5,
        })
        score, signals = engine.calculate_score(row)
        assert 'MFI_BULLISH' in signals
        assert 'MFI_VERY_BULLISH' in signals
        # 28 + 20% bonus = 28 + 5.6 = 33.6 -> 33
        assert score >= 33

    def test_calculate_score_volume_spike(self, engine):
        """Volume ratio >= 1.5 should add 8 points."""
        row = pd.Series({
            'rsi': 50,
            'mfi': 40,
            'volume_ratio': 2.0,
            'atr_ratio': 1.0,
            'is_local_min': False,
            'adx': 15,
            'close': 100,
            'bb_lower': 90,
            'bb_position': 0.5,
        })
        score, signals = engine.calculate_score(row)
        assert 'VOLUME_SPIKE' in signals
        assert score >= 8

    def test_calculate_score_low_volatility(self, engine):
        """ATR ratio <= 0.8 should add 15 points."""
        row = pd.Series({
            'rsi': 50,
            'mfi': 40,
            'volume_ratio': 1.0,
            'atr_ratio': 0.7,
            'is_local_min': False,
            'adx': 15,
            'close': 100,
            'bb_lower': 90,
            'bb_position': 0.5,
        })
        score, signals = engine.calculate_score(row)
        assert 'LOW_VOL' in signals
        assert score >= 15

    def test_calculate_score_local_min(self, engine):
        """Local minimum should add 20 points."""
        row = pd.Series({
            'rsi': 50,
            'mfi': 40,
            'volume_ratio': 1.0,
            'atr_ratio': 1.0,
            'is_local_min': True,
            'adx': 15,
            'close': 100,
            'bb_lower': 90,
            'bb_position': 0.5,
        })
        score, signals = engine.calculate_score(row)
        assert 'LOCAL_MIN' in signals
        assert score >= 20

    def test_calculate_score_trend_strong(self, engine):
        """ADX >= 25 should add 12 points."""
        row = pd.Series({
            'rsi': 50,
            'mfi': 40,
            'volume_ratio': 1.0,
            'atr_ratio': 1.0,
            'is_local_min': False,
            'adx': 30,
            'close': 100,
            'bb_lower': 90,
            'bb_position': 0.5,
        })
        score, signals = engine.calculate_score(row)
        assert 'TREND_STRONG' in signals
        assert score >= 12

    def test_calculate_score_bb_lower(self, engine):
        """Close below BB lower should add 10 points."""
        row = pd.Series({
            'rsi': 50,
            'mfi': 40,
            'volume_ratio': 1.0,
            'atr_ratio': 1.0,
            'is_local_min': False,
            'adx': 15,
            'close': 85,
            'bb_lower': 90,
            'bb_position': 0.1,
        })
        score, signals = engine.calculate_score(row)
        assert 'BB_LOWER' in signals
        assert 'BB_OVERSOLD' in signals

    def test_calculate_score_combined_s_tier(self, engine):
        """Combined strong signals should reach S tier."""
        row = pd.Series({
            'rsi': 25,  # RSI oversold: +8
            'mfi': 55,  # MFI bullish: +28
            'volume_ratio': 1.0,
            'atr_ratio': 1.0,
            'is_local_min': False,
            'adx': 15,
            'close': 100,
            'bb_lower': 90,
            'bb_position': 0.5,
        })
        score, signals = engine.calculate_score(row)
        tier = engine.classify_tier(score)
        # 8 + 28 = 36 -> S tier
        assert tier == 'S'
        assert score >= 36

    def test_calculate_score_zero_when_neutral(self, engine):
        """Neutral indicators should yield zero score."""
        row = pd.Series({
            'rsi': 50,  # Not oversold
            'mfi': 40,  # Not bullish
            'volume_ratio': 1.0,  # No spike
            'atr_ratio': 1.0,  # Normal vol
            'is_local_min': False,  # Not local min
            'adx': 15,  # Weak trend
            'close': 100,  # Inside BB
            'bb_lower': 90,
            'bb_position': 0.5,
        })
        score, signals = engine.calculate_score(row)
        assert score == 0
        assert len(signals) == 0


class TestMarketClassifier:
    """Test MarketClassifier regime classification."""

    @pytest.fixture
    def default_config(self):
        """Default configuration for MarketClassifier."""
        return {
            'mfi_bull_strong': 52,
            'mfi_bull_moderate': 45,
            'mfi_sideways_up': 42,
            'mfi_bear_moderate': 38,
            'mfi_bear_strong': 35,
            'adx_strong_trend': 20,
            'adx_moderate_trend': 15,
        }

    @pytest.fixture
    def classifier(self, default_config):
        """Create a MarketClassifier instance."""
        return MarketClassifier(default_config)

    def test_bull_strong(self, classifier):
        """High MFI with strong ADX should be BULL_STRONG."""
        row = pd.Series({'mfi': 55, 'adx': 25})
        assert classifier.classify(row) == 'BULL_STRONG'

    def test_bull_moderate(self, classifier):
        """Moderate MFI with moderate ADX should be BULL_MODERATE."""
        row = pd.Series({'mfi': 48, 'adx': 18})
        assert classifier.classify(row) == 'BULL_MODERATE'

    def test_sideways_up(self, classifier):
        """MFI around 42 should be SIDEWAYS_UP."""
        row = pd.Series({'mfi': 43, 'adx': 12})
        assert classifier.classify(row) == 'SIDEWAYS_UP'

    def test_sideways_flat(self, classifier):
        """MFI around 38-42 should be SIDEWAYS_FLAT."""
        row = pd.Series({'mfi': 40, 'adx': 12})
        assert classifier.classify(row) == 'SIDEWAYS_FLAT'

    def test_sideways_down(self, classifier):
        """MFI around 35-38 should be SIDEWAYS_DOWN."""
        row = pd.Series({'mfi': 36, 'adx': 12})
        assert classifier.classify(row) == 'SIDEWAYS_DOWN'

    def test_bear_strong(self, classifier):
        """Low MFI with strong ADX should be BEAR_STRONG."""
        row = pd.Series({'mfi': 30, 'adx': 25})
        assert classifier.classify(row) == 'BEAR_STRONG'

    def test_bear_moderate(self, classifier):
        """Low MFI with weak ADX should be BEAR_MODERATE."""
        row = pd.Series({'mfi': 30, 'adx': 15})
        assert classifier.classify(row) == 'BEAR_MODERATE'
