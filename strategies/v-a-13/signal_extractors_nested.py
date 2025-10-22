"""
v-a-13: Nested Timeframe Signal Extractors

4H와 1H 레벨에서 Day Sideways 신호 기간 내 정밀 진입점 탐지
"""

import pandas as pd
import numpy as np


def calculate_indicators_4h(df: pd.DataFrame) -> pd.DataFrame:
    """
    4H 타임프레임 지표 계산

    Args:
        df: bitcoin_minute240 데이터프레임

    Returns:
        지표가 추가된 데이터프레임
    """
    df = df.copy()

    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # MACD (12, 26, 9)
    exp1 = df['close'].ewm(span=12, adjust=False).mean()
    exp2 = df['close'].ewm(span=26, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=9, adjust=False).mean()
    df['macd_hist'] = df['macd'] - df['macd_signal']

    # Bollinger Bands (20, 2)
    df['bb_mid'] = df['close'].rolling(window=20).mean()
    bb_std = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_mid'] + (bb_std * 2)
    df['bb_lower'] = df['bb_mid'] - (bb_std * 2)
    df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

    # Volume Ratio (vs 20-period average)
    df['volume_ma20'] = df['volume'].rolling(window=20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma20']

    # ATR (14) for dynamic trailing
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.rolling(window=14).mean()
    df['atr_ratio'] = df['atr'] / df['close']

    return df


def calculate_indicators_1h(df: pd.DataFrame) -> pd.DataFrame:
    """
    1H 타임프레임 지표 계산

    Args:
        df: bitcoin_minute60 데이터프레임

    Returns:
        지표가 추가된 데이터프레임
    """
    df = df.copy()

    # RSI (14)
    delta = df['close'].diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
    rs = gain / loss
    df['rsi'] = 100 - (100 / (1 + rs))

    # Stochastic Oscillator (14, 3, 3)
    low_14 = df['low'].rolling(window=14).min()
    high_14 = df['high'].rolling(window=14).max()
    df['stoch_k'] = 100 * ((df['close'] - low_14) / (high_14 - low_14))
    df['stoch_d'] = df['stoch_k'].rolling(window=3).mean()

    # Bollinger Bands (20, 2)
    df['bb_mid'] = df['close'].rolling(window=20).mean()
    bb_std = df['close'].rolling(window=20).std()
    df['bb_upper'] = df['bb_mid'] + (bb_std * 2)
    df['bb_lower'] = df['bb_mid'] - (bb_std * 2)
    df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

    # Volume Ratio (vs 20-period average)
    df['volume_ma20'] = df['volume'].rolling(window=20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma20']

    # ATR (14) for dynamic trailing
    high_low = df['high'] - df['low']
    high_close = np.abs(df['high'] - df['close'].shift())
    low_close = np.abs(df['low'] - df['close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = ranges.max(axis=1)
    df['atr'] = true_range.rolling(window=14).mean()
    df['atr_ratio'] = df['atr'] / df['close']

    return df


def extract_4h_signals(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    4H 레벨 진입 시그널 추출

    Args:
        df: 지표가 계산된 4H 데이터프레임
        config: 4h_config from config.json

    Returns:
        시그널 데이터프레임 (timestamp, close, signal_strength 등)
    """
    entry_cfg = config['entry']

    # Entry conditions
    rsi_oversold = df['rsi'] < entry_cfg['rsi_threshold']

    # MACD bullish: MACD > Signal OR MACD > 0
    if entry_cfg['macd_bullish']:
        macd_condition = (df['macd'] > df['macd_signal']) | (df['macd'] > 0)
    else:
        macd_condition = True

    bb_lower = df['bb_position'] < entry_cfg['bb_position_max']
    volume_spike = df['volume_ratio'] >= entry_cfg['volume_ratio_min']

    # Combined signal
    signal = rsi_oversold & macd_condition & bb_lower & volume_spike

    # Signal strength (0-100)
    signal_strength = pd.Series(0, index=df.index)
    signal_strength += (35 - df['rsi']).clip(0, 35) / 35 * 40  # RSI contribution (max 40)
    signal_strength += ((entry_cfg['bb_position_max'] - df['bb_position']).clip(0, 1) * 30)  # BB (max 30)
    signal_strength += ((df['volume_ratio'] - 1).clip(0, 2) / 2 * 30)  # Volume (max 30)

    # Extract signals
    signals_df = df[signal].copy()
    signals_df['signal_strength'] = signal_strength[signal]
    signals_df['timeframe'] = '4h'

    # Keep only necessary columns
    keep_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume',
                 'rsi', 'macd', 'macd_signal', 'bb_position', 'volume_ratio',
                 'atr', 'atr_ratio', 'signal_strength', 'timeframe']

    existing_cols = [col for col in keep_cols if col in signals_df.columns]
    signals_df = signals_df[existing_cols]

    return signals_df


def extract_1h_signals(df: pd.DataFrame, config: dict) -> pd.DataFrame:
    """
    1H 레벨 진입 시그널 추출

    Args:
        df: 지표가 계산된 1H 데이터프레임
        config: 1h_config from config.json

    Returns:
        시그널 데이터프레임
    """
    entry_cfg = config['entry']

    # Entry conditions
    rsi_oversold = df['rsi'] < entry_cfg['rsi_threshold']
    stoch_oversold = df['stoch_k'] < entry_cfg['stoch_k_threshold']
    bb_extreme = df['bb_position'] < entry_cfg['bb_position_max']
    volume_spike = df['volume_ratio'] >= entry_cfg['volume_ratio_min']

    # Combined signal
    signal = rsi_oversold & stoch_oversold & bb_extreme & volume_spike

    # Signal strength (0-100)
    signal_strength = pd.Series(0, index=df.index)
    signal_strength += (30 - df['rsi']).clip(0, 30) / 30 * 35  # RSI (max 35)
    signal_strength += (20 - df['stoch_k']).clip(0, 20) / 20 * 25  # Stoch (max 25)
    signal_strength += ((entry_cfg['bb_position_max'] - df['bb_position']).clip(0, 1) * 20)  # BB (max 20)
    signal_strength += ((df['volume_ratio'] - 1).clip(0, 3) / 3 * 20)  # Volume (max 20)

    # Extract signals
    signals_df = df[signal].copy()
    signals_df['signal_strength'] = signal_strength[signal]
    signals_df['timeframe'] = '1h'

    # Keep only necessary columns
    keep_cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume',
                 'rsi', 'stoch_k', 'stoch_d', 'bb_position', 'volume_ratio',
                 'atr', 'atr_ratio', 'signal_strength', 'timeframe']

    existing_cols = [col for col in keep_cols if col in signals_df.columns]
    signals_df = signals_df[existing_cols]

    return signals_df


if __name__ == '__main__':
    """
    테스트: 2024년 4H/1H 시그널 생성
    """
    import json
    import sqlite3
    from pathlib import Path

    # Load config
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path, 'r') as f:
        config = json.load(f)

    # Load data
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'
    conn = sqlite3.connect(db_path)

    # Test 4H
    print("="*70)
    print("  4H Signal Test (2024)")
    print("="*70)

    query_4h = """
    SELECT
        timestamp,
        opening_price as open,
        high_price as high,
        low_price as low,
        trade_price as close,
        candle_acc_trade_volume as volume
    FROM bitcoin_minute240
    WHERE timestamp >= '2024-01-01' AND timestamp < '2025-01-01'
    ORDER BY timestamp
    """
    df_4h = pd.read_sql_query(query_4h, conn)
    df_4h = calculate_indicators_4h(df_4h)
    signals_4h = extract_4h_signals(df_4h, config['4h_config'])

    print(f"\n발견된 4H 시그널: {len(signals_4h)}개")
    print(f"평균 Signal Strength: {signals_4h['signal_strength'].mean():.2f}")
    print(f"\n샘플 (상위 5개):")
    print(signals_4h.nlargest(5, 'signal_strength')[['timestamp', 'close', 'rsi', 'signal_strength']])

    # Test 1H
    print("\n" + "="*70)
    print("  1H Signal Test (2024)")
    print("="*70)

    query_1h = """
    SELECT
        timestamp,
        opening_price as open,
        high_price as high,
        low_price as low,
        trade_price as close,
        candle_acc_trade_volume as volume
    FROM bitcoin_minute60
    WHERE timestamp >= '2024-01-01' AND timestamp < '2025-01-01'
    ORDER BY timestamp
    """
    df_1h = pd.read_sql_query(query_1h, conn)
    df_1h = calculate_indicators_1h(df_1h)
    signals_1h = extract_1h_signals(df_1h, config['1h_config'])

    print(f"\n발견된 1H 시그널: {len(signals_1h)}개")
    print(f"평균 Signal Strength: {signals_1h['signal_strength'].mean():.2f}")
    print(f"\n샘플 (상위 5개):")
    print(signals_1h.nlargest(5, 'signal_strength')[['timestamp', 'close', 'rsi', 'stoch_k', 'signal_strength']])

    conn.close()

    print("\n✅ 테스트 완료!")
