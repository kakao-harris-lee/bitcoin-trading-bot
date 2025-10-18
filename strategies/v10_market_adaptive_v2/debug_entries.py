#!/usr/bin/env python3
"""v10 Entry Signal Debug"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from market_regime_detector import MarketRegimeDetector

# Config
with open('config.json') as f:
    config = json.load(f)

# Data
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-30')

# Indicators
df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'macd'])
df = df.rename(columns={'ema_12': 'ema12', 'ema_26': 'ema26'})

detector = MarketRegimeDetector(config['market_detector'])
df = detector.add_indicators(df)

# Detect signals
bull_entries = []
sideways_entries = []
bear_entries = []

for i in range(30, len(df)):
    row = df.iloc[i]
    prev_row = df.iloc[i-1]

    regime = detector.detect(df, i)

    ema12 = row['ema12']
    ema26 = row['ema26']
    macd = row['macd']
    macd_signal = row['macd_signal']
    momentum = row['momentum']

    prev_ema12 = prev_row['ema12']
    prev_ema26 = prev_row['ema26']
    prev_macd = prev_row['macd']
    prev_macd_signal = prev_row['macd_signal']

    ema_golden = (prev_ema12 <= prev_ema26) and (ema12 > ema26)
    macd_golden = (prev_macd <= prev_macd_signal) and (macd > macd_signal)

    # Bull
    if regime == 'bull':
        if config['bull_market']['require_golden_cross']:
            if ema_golden or macd_golden:
                bull_entries.append({
                    'date': row['timestamp'].date(),
                    'price': row['close'],
                    'signal': 'EMA_GOLDEN' if ema_golden else 'MACD_GOLDEN'
                })

    # Sideways
    elif regime == 'sideways':
        if config['sideways_market']['require_golden_cross']:
            if ema_golden or macd_golden:
                sideways_entries.append({
                    'date': row['timestamp'].date(),
                    'price': row['close'],
                    'signal': 'GOLDEN_CROSS'
                })
        else:
            min_momentum = config['sideways_market'].get('min_momentum', 0.03)
            if ema12 > ema26 and momentum > min_momentum:
                sideways_entries.append({
                    'date': row['timestamp'].date(),
                    'price': row['close'],
                    'signal': f'EMA_UP+MOMENTUM({momentum*100:.1f}%)'
                })

    # Bear
    elif regime == 'bear':
        if config['bear_market']['require_golden_cross'] and config['bear_market']['require_macd_cross']:
            min_momentum = config['bear_market'].get('min_momentum', 0.10)
            if ema_golden and macd_golden and momentum > min_momentum:
                bear_entries.append({
                    'date': row['timestamp'].date(),
                    'price': row['close'],
                    'signal': 'BOTH_GOLDEN+MOMENTUM'
                })

print("="*80)
print("v10 Entry Signal Analysis (2024)")
print("="*80)

print(f"\n시장 분류:")
bull_days = (df.apply(lambda r: detector.detect(df, r.name), axis=1) == 'bull').sum() if len(df) > 0 else 0
sideways_days = (df.apply(lambda r: detector.detect(df, r.name) if r.name >= 30 else 'sideways', axis=1) == 'sideways').sum()
bear_days = (df.apply(lambda r: detector.detect(df, r.name) if r.name >= 30 else 'sideways', axis=1) == 'bear').sum()

print(f"  Bull:     {bull_days}일")
print(f"  Sideways: {sideways_days}일")
print(f"  Bear:     {bear_days}일")

print(f"\n진입 신호 발생 횟수:")
print(f"  Bull:     {len(bull_entries)}회")
print(f"  Sideways: {len(sideways_entries)}회")
print(f"  Bear:     {len(bear_entries)}회")
print(f"  합계:     {len(bull_entries) + len(sideways_entries) + len(bear_entries)}회")

if len(bull_entries) > 0:
    print(f"\n--- Bull 진입 신호 ---")
    for entry in bull_entries[:10]:
        print(f"  {entry['date']}: {entry['price']:,.0f}원 | {entry['signal']}")

if len(sideways_entries) > 0:
    print(f"\n--- Sideways 진입 신호 ---")
    for entry in sideways_entries[:10]:
        print(f"  {entry['date']}: {entry['price']:,.0f}원 | {entry['signal']}")

if len(bear_entries) > 0:
    print(f"\n--- Bear 진입 신호 ---")
    for entry in bear_entries[:10]:
        print(f"  {entry['date']}: {entry['price']:,.0f}원 | {entry['signal']}")

print("\n" + "="*80)
print("설정 확인:")
print("="*80)
print(f"\nBull Market:")
print(f"  Require Golden Cross: {config['bull_market']['require_golden_cross']}")

print(f"\nSideways Market:")
print(f"  Require Golden Cross: {config['sideways_market']['require_golden_cross']}")
print(f"  Min Momentum: {config['sideways_market'].get('min_momentum', 'N/A')}")

print(f"\nBear Market:")
print(f"  Require Golden Cross: {config['bear_market']['require_golden_cross']}")
print(f"  Require MACD Cross: {config['bear_market']['require_macd_cross']}")
print(f"  Min Momentum: {config['bear_market'].get('min_momentum', 'N/A')}")
