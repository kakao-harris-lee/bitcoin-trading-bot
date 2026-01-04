"""Technical indicators using talib. All functions are pure and stateless."""

import talib
import pandas as pd


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index."""
    return pd.Series(talib.RSI(close.values, timeperiod=period), index=close.index)


def bbands(
    close: pd.Series, period: int = 20, std: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Bollinger Bands. Returns (upper, middle, lower)."""
    upper, middle, lower = talib.BBANDS(
        close.values, timeperiod=period, nbdevup=std, nbdevdn=std
    )
    return (
        pd.Series(upper, index=close.index),
        pd.Series(middle, index=close.index),
        pd.Series(lower, index=close.index),
    )


def stochastic(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    k_period: int = 14,
    d_period: int = 3,
) -> tuple[pd.Series, pd.Series]:
    """Stochastic K and D. Returns (stoch_k, stoch_d)."""
    k, d = talib.STOCH(
        high.values,
        low.values,
        close.values,
        fastk_period=k_period,
        slowk_period=d_period,
        slowd_period=d_period,
    )
    return pd.Series(k, index=close.index), pd.Series(d, index=close.index)


def mfi(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    volume: pd.Series,
    period: int = 14,
) -> pd.Series:
    """Money Flow Index."""
    return pd.Series(
        talib.MFI(
            high.values, low.values, close.values, volume.values, timeperiod=period
        ),
        index=close.index,
    )


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """ADX with directional indicators. Returns (adx, plus_di, minus_di)."""
    adx_val = talib.ADX(high.values, low.values, close.values, timeperiod=period)
    plus_di = talib.PLUS_DI(high.values, low.values, close.values, timeperiod=period)
    minus_di = talib.MINUS_DI(high.values, low.values, close.values, timeperiod=period)
    return (
        pd.Series(adx_val, index=close.index),
        pd.Series(plus_di, index=close.index),
        pd.Series(minus_di, index=close.index),
    )


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> tuple[pd.Series, pd.Series, pd.Series]:
    """MACD. Returns (macd, signal, histogram)."""
    m, s, h = talib.MACD(
        close.values, fastperiod=fast, slowperiod=slow, signalperiod=signal
    )
    return (
        pd.Series(m, index=close.index),
        pd.Series(s, index=close.index),
        pd.Series(h, index=close.index),
    )


def ema(close: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return pd.Series(talib.EMA(close.values, timeperiod=period), index=close.index)


def atr(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.Series:
    """Average True Range."""
    return pd.Series(
        talib.ATR(high.values, low.values, close.values, timeperiod=period),
        index=close.index,
    )
