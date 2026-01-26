"""Pre-compute all standard indicators for strategy consumption."""

import numpy as np
import pandas as pd

from . import technical as ta


def calculate_market_stress(df: pd.DataFrame) -> pd.Series:
    """Calculate market stress score (0-100).

    Combines multiple stress signals:
    - Volatility stress: ATR as % of price (high ATR = stress)
    - Drawdown stress: Current price vs recent high
    - Volume stress: Volume spike above average
    - Trend stress: Distance below EMA200

    Score interpretation:
    - 0-30: Normal conditions
    - 30-50: Elevated stress
    - 50-70: High stress
    - 70+: Extreme stress (should pause trading)

    Args:
        df: DataFrame with close, high, atr, ema_200, volume, avg_volume_20

    Returns:
        Series with market_stress score (0-100)
    """
    stress = pd.Series(0.0, index=df.index)

    # 1. Volatility stress (0-30 points)
    # ATR as % of price, normalized
    if 'atr' in df.columns:
        atr_pct = (df['atr'] / df['close']) * 100
        # 1% ATR = 10 points, 3% ATR = 30 points (capped)
        vol_stress = (atr_pct * 10).clip(0, 30)
        stress += vol_stress

    # 2. Drawdown stress (0-30 points)
    # How far below recent 20-period high
    recent_high = df['high'].rolling(window=20).max()
    drawdown_pct = ((recent_high - df['close']) / recent_high) * 100
    # 5% drawdown = 15 points, 10% = 30 points (capped)
    dd_stress = (drawdown_pct * 3).clip(0, 30)
    stress += dd_stress

    # 3. Volume stress (0-20 points)
    # Volume spike indicates panic
    if 'avg_volume_20' in df.columns:
        vol_ratio = df['volume'] / df['avg_volume_20'].replace(0, 1)
        # 2x volume = 10 points, 4x = 20 points (capped)
        volume_stress = ((vol_ratio - 1) * 10).clip(0, 20)
        stress += volume_stress

    # 4. Trend stress (0-20 points)
    # Distance below EMA200 indicates bear market stress
    if 'ema_200' in df.columns:
        ema_dist_pct = ((df['ema_200'] - df['close']) / df['ema_200']) * 100
        # Only count if below EMA200 (positive distance)
        trend_stress = (ema_dist_pct.clip(0, None) * 2).clip(0, 20)
        stress += trend_stress

    return stress.clip(0, 100).fillna(0)

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
    'ema_20',
    'ema_50',
    'ema_200',
    'atr',
    'market_stress',
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

    # EMAs (short/mid/long)
    df['ema_20'] = ta.ema(df['close'], 20)
    df['ema_50'] = ta.ema(df['close'], 50)
    df['ema_200'] = ta.ema(df['close'], 200)

    # ATR
    df['atr'] = ta.atr(df['high'], df['low'], df['close'])

    # Support/Resistance levels (20-period high/low)
    df['prev_high_20'] = df['high'].rolling(window=20).max()
    df['prev_low_20'] = df['low'].rolling(window=20).min()

    # 30-day high for drawdown-based BEAR detection (720 hours for hourly data)
    # This is used to detect significant drawdowns from recent highs
    df['high_30d'] = df['high'].rolling(window=720, min_periods=20).max()

    # Average volume (20-period)
    df['avg_volume_20'] = df['volume'].rolling(window=20).mean()

    # Market stress indicator (0-100)
    df['market_stress'] = calculate_market_stress(df)

    return df
