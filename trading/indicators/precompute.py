"""Pre-compute all standard indicators for strategy consumption."""

import pandas as pd

from . import technical as ta

INDICATOR_COLUMNS = [
    'rsi',
    'bb_upper',
    'bb_middle',
    'bb_lower',
    'stoch_k',
    'stoch_d',
    'mfi',
    'adx',
    'plus_di',
    'minus_di',
    'macd',
    'macd_signal',
    'macd_hist',
    'ema_50',
    'ema_200',
    'atr',
]


def add_all_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """
    Add all pre-computed indicators to DataFrame.

    Expects columns: open, high, low, close, volume
    Returns the same DataFrame with indicator columns added.
    Mutates DataFrame in place for efficiency.
    """
    required = ['open', 'high', 'low', 'close', 'volume']
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    # Skip if insufficient data (need at least 200 for EMA-200)
    if len(df) < 200:
        return df

    # RSI
    df['rsi'] = ta.rsi(df['close'])

    # Bollinger Bands
    df['bb_upper'], df['bb_middle'], df['bb_lower'] = ta.bbands(df['close'])

    # Stochastic
    df['stoch_k'], df['stoch_d'] = ta.stochastic(
        df['high'], df['low'], df['close']
    )

    # MFI
    df['mfi'] = ta.mfi(df['high'], df['low'], df['close'], df['volume'])

    # ADX with DI
    df['adx'], df['plus_di'], df['minus_di'] = ta.adx(
        df['high'], df['low'], df['close']
    )

    # MACD
    df['macd'], df['macd_signal'], df['macd_hist'] = ta.macd(df['close'])

    # EMAs
    df['ema_50'] = ta.ema(df['close'], 50)
    df['ema_200'] = ta.ema(df['close'], 200)

    # ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'])

    return df
