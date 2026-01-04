"""Verification tests for v35_long migration to shared indicator library.

Compares old manual calculations vs new talib-based library to ensure
the migration doesn't change behavior significantly.
"""

import numpy as np
import pandas as pd
import pytest

from trading.indicators import add_all_indicators


@pytest.fixture
def realistic_btc_data():
    """300 candles of realistic BTC price data."""
    np.random.seed(42)
    # Start at ~50000 with realistic volatility
    returns = np.random.randn(300) * 0.01  # 1% daily volatility
    close = 50000 * np.exp(np.cumsum(returns))

    # Generate OHLC with realistic spreads
    high = close * (1 + np.abs(np.random.randn(300) * 0.005))
    low = close * (1 - np.abs(np.random.randn(300) * 0.005))
    open_ = close * (1 + np.random.randn(300) * 0.003)
    volume = np.random.randint(100, 10000, 300).astype(float)

    return pd.DataFrame({
        'open': open_,
        'high': high,
        'low': low,
        'close': close,
        'volume': volume,
    })


def _calc_rsi_legacy(df: pd.DataFrame) -> pd.Series:
    """Legacy RSI calculation (copied from v35_long.py)"""
    delta = df['close'].diff()
    gain = delta.where(delta > 0, 0).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _calc_macd_legacy(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Legacy MACD calculation"""
    ema12 = df['close'].ewm(span=12, adjust=False).mean()
    ema26 = df['close'].ewm(span=26, adjust=False).mean()
    macd = ema12 - ema26
    macd_signal = macd.ewm(span=9, adjust=False).mean()
    return macd, macd_signal


def _calc_mfi_legacy(df: pd.DataFrame) -> pd.Series:
    """Legacy MFI calculation"""
    typical_price = (df['high'] + df['low'] + df['close']) / 3
    raw_money_flow = typical_price * df['volume']
    positive_flow = raw_money_flow.where(typical_price > typical_price.shift(1), 0)
    negative_flow = raw_money_flow.where(typical_price < typical_price.shift(1), 0)
    positive_mf = positive_flow.rolling(window=14).sum()
    negative_mf = negative_flow.rolling(window=14).sum()
    mfi_ratio = positive_mf / negative_mf.replace(0, np.nan)
    return 100 - (100 / (1 + mfi_ratio))


def _calc_bbands_legacy(df: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Legacy Bollinger Bands calculation"""
    bb_middle = df['close'].rolling(window=20).mean()
    bb_std = df['close'].rolling(window=20).std()
    bb_upper = bb_middle + 2 * bb_std
    bb_lower = bb_middle - 2 * bb_std
    return bb_upper, bb_middle, bb_lower


def _calc_stochastic_legacy(df: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """Legacy Stochastic calculation"""
    low_14 = df['low'].rolling(window=14).min()
    high_14 = df['high'].rolling(window=14).max()
    stoch_k = 100 * (df['close'] - low_14) / (high_14 - low_14).replace(0, np.nan)
    stoch_d = stoch_k.rolling(window=3).mean()
    return stoch_k, stoch_d


class TestMigrationVerification:
    """Verify that new library produces similar results to old calculations.

    Note: RSI, MFI, MACD may differ slightly because talib uses different
    smoothing algorithms. We use relaxed tolerances where appropriate.
    """

    def test_bbands_match(self, realistic_btc_data):
        """Bollinger Bands middle should match exactly (same SMA algorithm).

        Note: Upper/lower bands differ slightly because talib uses population std
        (ddof=0) while pandas uses sample std (ddof=1). This is a known difference.
        """
        df = realistic_btc_data.copy()

        # Calculate legacy
        old_upper, old_middle, old_lower = _calc_bbands_legacy(df)

        # Calculate new
        add_all_indicators(df)

        # Middle band should match exactly (both use SMA)
        valid = old_middle.notna() & df['bb_middle'].notna()
        assert np.allclose(old_middle[valid], df['bb_middle'][valid], rtol=1e-10)

        # Upper/lower bands: talib uses ddof=0, pandas uses ddof=1
        # Correlation should still be very high
        upper_corr = np.corrcoef(old_upper[valid], df['bb_upper'][valid])[0, 1]
        lower_corr = np.corrcoef(old_lower[valid], df['bb_lower'][valid])[0, 1]
        assert upper_corr > 0.999, f"Upper band correlation too low: {upper_corr}"
        assert lower_corr > 0.999, f"Lower band correlation too low: {lower_corr}"

    def test_stochastic_close(self, realistic_btc_data):
        """Stochastic values should be correlated.

        Note: talib STOCH returns Slow Stochastic (applies SMA smoothing to %K),
        while legacy calculates Fast Stochastic (raw %K). Values will differ
        but should still be correlated and in valid ranges.
        """
        df = realistic_btc_data.copy()

        # Calculate legacy
        old_k, old_d = _calc_stochastic_legacy(df)

        # Calculate new
        add_all_indicators(df)

        # Both should be in 0-100 range
        valid_k = old_k.notna() & df['stoch_k'].notna()
        assert (df['stoch_k'][valid_k] >= 0).all() and (df['stoch_k'][valid_k] <= 100).all()

        # Correlation should be reasonable (Slow vs Fast stochastic will differ)
        correlation = np.corrcoef(old_k[valid_k], df['stoch_k'][valid_k])[0, 1]
        assert correlation > 0.7, f"Stochastic correlation too low: {correlation}"

    def test_rsi_correlation(self, realistic_btc_data):
        """RSI values should be reasonably correlated.

        Note: talib uses Wilder's smoothing (EMA with alpha=1/period), while
        legacy uses simple rolling mean. This creates noticeable differences,
        but talib's implementation is the industry standard.
        """
        df = realistic_btc_data.copy()

        # Calculate legacy
        old_rsi = _calc_rsi_legacy(df)

        # Calculate new
        add_all_indicators(df)

        # Compare correlation (>0.8 is acceptable given different algorithms)
        valid = old_rsi.notna() & df['rsi'].notna()
        correlation = np.corrcoef(old_rsi[valid], df['rsi'][valid])[0, 1]
        assert correlation > 0.8, f"RSI correlation too low: {correlation}"

        # Both should be in valid 0-100 range
        assert (df['rsi'][valid] >= 0).all() and (df['rsi'][valid] <= 100).all()

        # Values should be in similar range (within 15 points on average)
        mean_diff = np.abs(old_rsi[valid] - df['rsi'][valid]).mean()
        assert mean_diff < 15, f"RSI mean difference too high: {mean_diff}"

    def test_mfi_correlation(self, realistic_btc_data):
        """MFI values should be highly correlated."""
        df = realistic_btc_data.copy()

        # Calculate legacy
        old_mfi = _calc_mfi_legacy(df)

        # Calculate new
        add_all_indicators(df)

        # Compare correlation
        valid = old_mfi.notna() & df['mfi'].notna()
        correlation = np.corrcoef(old_mfi[valid], df['mfi'][valid])[0, 1]
        assert correlation > 0.95, f"MFI correlation too low: {correlation}"

    def test_macd_correlation(self, realistic_btc_data):
        """MACD values should be highly correlated."""
        df = realistic_btc_data.copy()

        # Calculate legacy
        old_macd, old_signal = _calc_macd_legacy(df)

        # Calculate new
        add_all_indicators(df)

        # Compare correlation
        valid = old_macd.notna() & df['macd'].notna()
        correlation = np.corrcoef(old_macd[valid], df['macd'][valid])[0, 1]
        assert correlation > 0.99, f"MACD correlation too low: {correlation}"

        valid_signal = old_signal.notna() & df['macd_signal'].notna()
        signal_corr = np.corrcoef(old_signal[valid_signal], df['macd_signal'][valid_signal])[0, 1]
        assert signal_corr > 0.99, f"MACD signal correlation too low: {signal_corr}"

    def test_all_indicators_present(self, realistic_btc_data):
        """All indicators used by v35_long should be present."""
        df = realistic_btc_data.copy()
        add_all_indicators(df)

        required = ['rsi', 'macd', 'macd_signal', 'mfi', 'adx',
                    'bb_upper', 'bb_middle', 'bb_lower',
                    'stoch_k', 'stoch_d']

        for col in required:
            assert col in df.columns, f"Missing required column: {col}"

    def test_indicator_ranges_valid(self, realistic_btc_data):
        """All indicator values should be in valid ranges."""
        df = realistic_btc_data.copy()
        add_all_indicators(df)

        # RSI: 0-100
        valid_rsi = df['rsi'].dropna()
        assert (valid_rsi >= 0).all() and (valid_rsi <= 100).all()

        # MFI: 0-100
        valid_mfi = df['mfi'].dropna()
        assert (valid_mfi >= 0).all() and (valid_mfi <= 100).all()

        # ADX: 0-100
        valid_adx = df['adx'].dropna()
        assert (valid_adx >= 0).all() and (valid_adx <= 100).all()

        # Stochastic: 0-100
        valid_k = df['stoch_k'].dropna()
        valid_d = df['stoch_d'].dropna()
        assert (valid_k >= 0).all() and (valid_k <= 100).all()
        assert (valid_d >= 0).all() and (valid_d <= 100).all()
