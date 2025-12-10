#!/usr/bin/env python3
"""Debug script to check indicators"""

import sys
sys.path.append('../..')

import sqlite3
import pandas as pd
import talib
import json

with open('config.json', 'r') as f:
    config = json.load(f)

DB_PATH = '../../upbit_bitcoin.db'

conn = sqlite3.connect(DB_PATH)
query = f"""
    SELECT timestamp, opening_price as open, high_price as high,
           low_price as low, trade_price as close,
           candle_acc_trade_volume as volume
    FROM bitcoin_day
    WHERE timestamp >= '2022-01-01' AND timestamp <= '2024-12-31'
    ORDER BY timestamp ASC
"""
df = pd.read_sql_query(query, conn)
conn.close()

df['timestamp'] = pd.to_datetime(df['timestamp'])

# Calculate indicators
close = df['close'].values
high = df['high'].values
low = df['low'].values
volume = df['volume'].values

df['mfi'] = talib.MFI(high, low, close, volume, timeperiod=14)
macd, macd_signal, macd_hist = talib.MACD(close, fastperiod=12, slowperiod=26, signalperiod=9)
df['macd'] = macd
df['macd_signal'] = macd_signal
df['adx'] = talib.ADX(high, low, close, timeperiod=14)
volume_sma = talib.SMA(volume, timeperiod=20)
df['volume_ratio'] = volume / (volume_sma + 1e-10)
df['rsi_14'] = talib.RSI(close, timeperiod=14)
upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
df['bb_position'] = (close - lower) / (upper - lower + 1e-10)

# Check for NaN
print(f"Total records: {len(df)}")
print(f"NaN counts:")
print(df[['mfi', 'macd', 'macd_signal', 'adx', 'volume_ratio']].isna().sum())

# Show sample data
print("\nSample data (rows 30-40):")
print(df.iloc[30:40][['timestamp', 'close', 'mfi', 'macd', 'macd_signal', 'adx', 'volume_ratio']].to_string())

# Check for golden cross opportunities
df['prev_macd'] = df['macd'].shift(1)
df['prev_macd_signal'] = df['macd_signal'].shift(1)
df['golden_cross'] = (df['prev_macd'] <= df['prev_macd_signal']) & (df['macd'] > df['macd_signal'])

print(f"\nGolden crosses found: {df['golden_cross'].sum()}")
print(df[df['golden_cross']][['timestamp', 'close', 'mfi', 'adx', 'volume_ratio']].to_string())

# Check entry conditions
df['entry_signal'] = (
    (df['mfi'] >= 50) &
    (df['golden_cross']) &
    (df['adx'] >= 25) &
    (df['volume_ratio'] >= 1.5) &
    (df['rsi_14'] <= 70) &
    (df['bb_position'] <= 0.8)
)

print(f"\nEntry signals found: {df['entry_signal'].sum()}")
if df['entry_signal'].sum() > 0:
    print(df[df['entry_signal']][['timestamp', 'close', 'mfi', 'adx', 'volume_ratio']].to_string())
else:
    print("\nNO ENTRY SIGNALS FOUND!")
    print("\nChecking each condition separately:")
    print(f"MFI >= 50: {(df['mfi'] >= 50).sum()}")
    print(f"Golden cross: {df['golden_cross'].sum()}")
    print(f"ADX >= 25: {(df['adx'] >= 25).sum()}")
    print(f"Volume ratio >= 1.5: {(df['volume_ratio'] >= 1.5).sum()}")
    print(f"MFI >= 50 AND golden cross: {((df['mfi'] >= 50) & df['golden_cross']).sum()}")
    print(f"MFI >= 50 AND golden cross AND ADX >= 25: {((df['mfi'] >= 50) & df['golden_cross'] & (df['adx'] >= 25)).sum()}")

    # Show golden crosses with all conditions
    gc_df = df[df['golden_cross']].copy()
    print(f"\nGolden cross events with condition checks:")
    gc_df['mfi_ok'] = gc_df['mfi'] >= 50
    gc_df['adx_ok'] = gc_df['adx'] >= 25
    gc_df['vol_ok'] = gc_df['volume_ratio'] >= 1.5
    print(gc_df[['timestamp', 'close', 'mfi', 'mfi_ok', 'adx', 'adx_ok', 'volume_ratio', 'vol_ok']].to_string())
