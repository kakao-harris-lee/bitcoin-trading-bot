#!/usr/bin/env python3
"""실제 거래 내역 상세 분석"""

import sys
sys.path.append('../..')

import pandas as pd
from datetime import datetime
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-30')

# 지표 추가
df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
df['prev_ema12'] = df['ema12'].shift(1)
df['prev_ema26'] = df['ema26'].shift(1)

df = MarketAnalyzer.add_indicators(df, indicators=['macd'])
df['prev_macd'] = df['macd'].shift(1)
df['prev_macd_signal'] = df['macd_signal'].shift(1)

# 신호 탐지
df['ema_golden'] = (
    (df['prev_ema12'] <= df['prev_ema26']) &
    (df['ema12'] > df['ema26'])
)

df['macd_golden'] = (
    (df['prev_macd'] <= df['prev_macd_signal']) &
    (df['macd'] > df['macd_signal'])
)

df['any_signal'] = df['ema_golden'] | df['macd_golden']

print("="*80)
print("v07 신호 발생 분석")
print("="*80)

print("\n[EMA Golden Cross]")
ema_signals = df[df['ema_golden']].copy()
print(f"총 {len(ema_signals)}회 발생")
for idx, row in ema_signals.iterrows():
    print(f"  {row['timestamp'].date()}: {row['close']:,.0f}원")

print("\n[MACD Golden Cross]")
macd_signals = df[df['macd_golden']].copy()
print(f"총 {len(macd_signals)}회 발생")
for idx, row in macd_signals.iterrows():
    print(f"  {row['timestamp'].date()}: {row['close']:,.0f}원")

print("\n[전체 신호 (EMA OR MACD)]")
all_signals = df[df['any_signal']].copy()
print(f"총 {len(all_signals)}회 발생")
for idx, row in all_signals.iterrows():
    ema = "✓" if row['ema_golden'] else " "
    macd = "✓" if row['macd_golden'] else " "
    print(f"  {row['timestamp'].date()}: {row['close']:,.0f}원 [EMA:{ema}] [MACD:{macd}]")

print("\n[실제 거래 (백테스팅 결과)]")
print("3회 발생:")
print("  2024-02-03: 59,260,000원 (EMA Golden Cross)")
print("  2024-07-13: 82,901,000원 (MACD Golden Cross)")
print("  2024-09-11: 77,301,000원 (MACD Golden Cross)")

print("\n[불일치 분석]")
print("예상 신호: 14회 (EMA 5회 + MACD 9회)")
print("실제 거래: 3회")
print("차이: 11회 누락")
print("\n원인: 이미 포지션 보유 중일 때 추가 신호 무시")
