"""Unit tests for individual indicator functions."""

import numpy as np
import pandas as pd
import pytest

from trading.indicators import technical as ta


@pytest.fixture
def sample_ohlcv():
    """300 candles of realistic price data."""
    np.random.seed(42)
    close = 50000 + np.cumsum(np.random.randn(300) * 100)
    high = close + np.abs(np.random.randn(300) * 100)
    low = close - np.abs(np.random.randn(300) * 100)
    return pd.DataFrame({
        'open': close + np.random.randn(300) * 50,
        'high': high,
        'low': low,
        'close': close,
        'volume': np.random.randint(100, 10000, 300).astype(float),
    })


class TestRSI:
    def test_rsi_range(self, sample_ohlcv):
        """RSI should be between 0 and 100."""
        rsi = ta.rsi(sample_ohlcv['close'])
        valid = rsi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_rsi_default_period(self, sample_ohlcv):
        """Default period is 14."""
        rsi = ta.rsi(sample_ohlcv['close'])
        # First 14 values should be NaN (talib uses period values to warm up)
        assert rsi.iloc[:14].isna().sum() >= 13  # Allow some flexibility

    def test_rsi_custom_period(self, sample_ohlcv):
        """Custom period should work."""
        rsi_7 = ta.rsi(sample_ohlcv['close'], period=7)
        rsi_21 = ta.rsi(sample_ohlcv['close'], period=21)
        # Different periods should give different results
        assert not np.allclose(rsi_7.dropna().values[-10:], rsi_21.dropna().values[-10:])

    def test_rsi_preserves_index(self, sample_ohlcv):
        """Output should have same index as input."""
        rsi = ta.rsi(sample_ohlcv['close'])
        assert rsi.index.equals(sample_ohlcv.index)


class TestBBands:
    def test_bbands_ordering(self, sample_ohlcv):
        """Upper >= Middle >= Lower always."""
        upper, middle, lower = ta.bbands(sample_ohlcv['close'])
        valid_idx = upper.notna()
        assert (upper[valid_idx] >= middle[valid_idx]).all()
        assert (middle[valid_idx] >= lower[valid_idx]).all()

    def test_bbands_middle_is_sma(self, sample_ohlcv):
        """Middle band should be SMA(20)."""
        upper, middle, lower = ta.bbands(sample_ohlcv['close'], period=20)
        expected_sma = sample_ohlcv['close'].rolling(20).mean()
        # Compare where both are valid
        valid_idx = middle.notna() & expected_sma.notna()
        assert np.allclose(middle[valid_idx], expected_sma[valid_idx], rtol=1e-10)

    def test_bbands_preserves_index(self, sample_ohlcv):
        """Output should have same index as input."""
        upper, middle, lower = ta.bbands(sample_ohlcv['close'])
        assert upper.index.equals(sample_ohlcv.index)
        assert middle.index.equals(sample_ohlcv.index)
        assert lower.index.equals(sample_ohlcv.index)


class TestStochastic:
    def test_stochastic_range(self, sample_ohlcv):
        """Stochastic K and D should be between 0 and 100."""
        k, d = ta.stochastic(sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close'])
        valid_k = k.dropna()
        valid_d = d.dropna()
        assert (valid_k >= 0).all() and (valid_k <= 100).all()
        assert (valid_d >= 0).all() and (valid_d <= 100).all()

    def test_stochastic_d_smoother_than_k(self, sample_ohlcv):
        """D line should be smoother (lower std) than K line."""
        k, d = ta.stochastic(sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close'])
        # D is a moving average of K, so should have lower variance
        assert d.dropna().std() <= k.dropna().std()

    def test_stochastic_preserves_index(self, sample_ohlcv):
        """Output should have same index as input."""
        k, d = ta.stochastic(sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close'])
        assert k.index.equals(sample_ohlcv.index)
        assert d.index.equals(sample_ohlcv.index)


class TestMFI:
    def test_mfi_range(self, sample_ohlcv):
        """MFI should be between 0 and 100."""
        mfi = ta.mfi(sample_ohlcv['high'], sample_ohlcv['low'],
                     sample_ohlcv['close'], sample_ohlcv['volume'])
        valid = mfi.dropna()
        assert (valid >= 0).all() and (valid <= 100).all()

    def test_mfi_preserves_index(self, sample_ohlcv):
        """Output should have same index as input."""
        mfi = ta.mfi(sample_ohlcv['high'], sample_ohlcv['low'],
                     sample_ohlcv['close'], sample_ohlcv['volume'])
        assert mfi.index.equals(sample_ohlcv.index)


class TestADX:
    def test_adx_range(self, sample_ohlcv):
        """ADX, +DI, -DI should be between 0 and 100."""
        adx, plus_di, minus_di = ta.adx(
            sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close']
        )
        for series in [adx, plus_di, minus_di]:
            valid = series.dropna()
            assert (valid >= 0).all() and (valid <= 100).all()

    def test_adx_preserves_index(self, sample_ohlcv):
        """Output should have same index as input."""
        adx, plus_di, minus_di = ta.adx(
            sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close']
        )
        assert adx.index.equals(sample_ohlcv.index)
        assert plus_di.index.equals(sample_ohlcv.index)
        assert minus_di.index.equals(sample_ohlcv.index)


class TestMACD:
    def test_macd_returns_three_series(self, sample_ohlcv):
        """MACD should return macd line, signal line, and histogram."""
        macd, signal, hist = ta.macd(sample_ohlcv['close'])
        assert isinstance(macd, pd.Series)
        assert isinstance(signal, pd.Series)
        assert isinstance(hist, pd.Series)

    def test_macd_histogram_is_difference(self, sample_ohlcv):
        """Histogram should be macd - signal."""
        macd, signal, hist = ta.macd(sample_ohlcv['close'])
        valid_idx = macd.notna() & signal.notna() & hist.notna()
        expected = macd[valid_idx] - signal[valid_idx]
        assert np.allclose(hist[valid_idx], expected, rtol=1e-10)

    def test_macd_preserves_index(self, sample_ohlcv):
        """Output should have same index as input."""
        macd, signal, hist = ta.macd(sample_ohlcv['close'])
        assert macd.index.equals(sample_ohlcv.index)
        assert signal.index.equals(sample_ohlcv.index)
        assert hist.index.equals(sample_ohlcv.index)


class TestEMA:
    def test_ema_different_periods(self, sample_ohlcv):
        """Different periods should give different results."""
        ema_50 = ta.ema(sample_ohlcv['close'], 50)
        ema_200 = ta.ema(sample_ohlcv['close'], 200)
        assert not np.allclose(ema_50.dropna().values[-10:], ema_200.dropna().values[-10:])

    def test_ema_preserves_index(self, sample_ohlcv):
        """Output should have same index as input."""
        ema = ta.ema(sample_ohlcv['close'], 50)
        assert ema.index.equals(sample_ohlcv.index)


class TestATR:
    def test_atr_positive(self, sample_ohlcv):
        """ATR should always be positive."""
        atr = ta.atr(sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close'])
        valid = atr.dropna()
        assert (valid >= 0).all()

    def test_atr_preserves_index(self, sample_ohlcv):
        """Output should have same index as input."""
        atr = ta.atr(sample_ohlcv['high'], sample_ohlcv['low'], sample_ohlcv['close'])
        assert atr.index.equals(sample_ohlcv.index)
