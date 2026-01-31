"""Integration tests for pre-computation layer."""

import numpy as np
import pandas as pd
import pytest

from trading.indicators.precompute import add_all_indicators, INDICATOR_COLUMNS


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


@pytest.fixture
def small_ohlcv():
    """50 candles - insufficient for EMA-200."""
    np.random.seed(42)
    close = 50000 + np.cumsum(np.random.randn(50) * 100)
    high = close + np.abs(np.random.randn(50) * 100)
    low = close - np.abs(np.random.randn(50) * 100)
    return pd.DataFrame({
        'open': close + np.random.randn(50) * 50,
        'high': high,
        'low': low,
        'close': close,
        'volume': np.random.randint(100, 10000, 50).astype(float),
    })


class TestAddAllIndicators:
    def test_all_columns_added(self, sample_ohlcv):
        """All expected indicator columns should be present."""
        df = add_all_indicators(sample_ohlcv)
        for col in INDICATOR_COLUMNS:
            assert col in df.columns, f"Missing column: {col}"

    def test_original_columns_preserved(self, sample_ohlcv):
        """Original OHLCV columns should still be present."""
        df = add_all_indicators(sample_ohlcv)
        for col in ['open', 'high', 'low', 'close', 'volume']:
            assert col in df.columns, f"Missing original column: {col}"

    def test_returns_same_dataframe(self, sample_ohlcv):
        """Should return the same DataFrame object (mutates in place)."""
        result = add_all_indicators(sample_ohlcv)
        assert result is sample_ohlcv

    def test_insufficient_data_skips(self, small_ohlcv):
        """Should skip gracefully when data < 200 rows."""
        df = add_all_indicators(small_ohlcv)
        # No indicator columns should be added
        for col in INDICATOR_COLUMNS:
            assert col not in df.columns

    def test_missing_columns_raises(self):
        """Should raise ValueError if required columns missing."""
        df = pd.DataFrame({'close': [1, 2, 3]})  # Missing other columns
        with pytest.raises(ValueError, match="Missing required columns"):
            add_all_indicators(df)

    def test_indicator_values_reasonable(self, sample_ohlcv):
        """Indicator values should be in expected ranges."""
        df = add_all_indicators(sample_ohlcv)

        # RSI: 0-100
        valid_rsi = df['rsi'].dropna()
        assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all()

        # BBands: upper >= middle >= lower
        valid_idx = df['bb_upper'].notna()
        assert (df.loc[valid_idx, 'bb_upper'] >= df.loc[valid_idx, 'bb_middle']).all()
        assert (df.loc[valid_idx, 'bb_middle'] >= df.loc[valid_idx, 'bb_lower']).all()

        # ADX: 0-100
        valid_adx = df['adx'].dropna()
        assert (valid_adx >= 0).all() and (valid_adx <= 100).all()

        # ATR: positive
        valid_atr = df['atr'].dropna()
        assert (valid_atr >= 0).all()

    def test_index_preserved(self, sample_ohlcv):
        """DataFrame index should be preserved."""
        original_index = sample_ohlcv.index.copy()
        df = add_all_indicators(sample_ohlcv)
        assert df.index.equals(original_index)

    def test_idempotent(self, sample_ohlcv):
        """Calling twice should give same result."""
        df1 = add_all_indicators(sample_ohlcv.copy())
        df2 = add_all_indicators(sample_ohlcv.copy())

        for col in INDICATOR_COLUMNS:
            valid_idx = df1[col].notna() & df2[col].notna()
            assert np.allclose(df1.loc[valid_idx, col], df2.loc[valid_idx, col])


class TestIndicatorColumns:
    def test_indicator_columns_count(self):
        """Keep indicator contract stable (used by add_all_indicators tests)."""
        # 19 base + 2 breakout indicators (breakout_signal, target_price)
        assert len(INDICATOR_COLUMNS) == 21

    def test_indicator_columns_unique(self):
        """All column names should be unique."""
        assert len(INDICATOR_COLUMNS) == len(set(INDICATOR_COLUMNS))
