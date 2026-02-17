import numpy as np
import talib

from trading.strategies.indicators import calculate_adx, calculate_mfi, calculate_rsi


def _sample_ohlcv(rows: int = 320) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    rng = np.random.default_rng(42)
    close = 50000.0 + np.cumsum(rng.normal(0, 120, rows))
    high = close + np.abs(rng.normal(0, 80, rows))
    low = close - np.abs(rng.normal(0, 80, rows))
    volume = rng.integers(100, 100000, rows).astype(np.float64)
    return high.astype(np.float64), low.astype(np.float64), close.astype(np.float64), volume


def test_calculate_mfi_matches_talib_last_value():
    high, low, close, volume = _sample_ohlcv()
    ours = calculate_mfi(high, low, close, volume, period=14)
    ref = talib.MFI(high, low, close, volume, timeperiod=14)[-1]
    assert np.isfinite(ref)
    assert ours == ref


def test_calculate_adx_matches_talib_last_value():
    high, low, close, _ = _sample_ohlcv()
    ours = calculate_adx(high, low, close, period=14)
    ref = talib.ADX(high, low, close, timeperiod=14)[-1]
    assert np.isfinite(ref)
    assert ours == ref


def test_calculate_rsi_matches_talib_last_value():
    _, _, close, _ = _sample_ohlcv()
    ours = calculate_rsi(close, period=14)
    ref = talib.RSI(close, timeperiod=14)[-1]
    assert np.isfinite(ref)
    assert ours == ref

