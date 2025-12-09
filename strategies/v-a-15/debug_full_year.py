#!/usr/bin/env python3
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

db_path = project_root / 'upbit_bitcoin.db'

with DataLoader(str(db_path)) as loader:
    df = loader.load_timeframe('day', '2024-01-01', '2024-12-31')

df = MarketAnalyzer.add_indicators(df, ['rsi', 'macd', 'adx'])

print("="*70)
print("2024년 전체 MACD 분석")
print("="*70)

gc_count = 0
macd_positive_days = 0

for i in range(1, len(df)):
    row = df.iloc[i]
    prev_row = df.iloc[i-1]
    
    macd = row.get('macd', 0)
    macd_signal = row.get('macd_signal', 0)
    prev_macd = prev_row.get('macd', 0)
    prev_signal = prev_row.get('macd_signal', 0)
    
    # Golden Cross
    if (prev_macd <= prev_signal) and (macd > macd_signal):
        gc_count += 1
        print(f"골든크로스 #{gc_count}: {row['timestamp'].strftime('%Y-%m-%d')}")
    
    # MACD > Signal 일수
    if macd > macd_signal:
        macd_positive_days += 1

print(f"\n총 골든크로스: {gc_count}회")
print(f"MACD > Signal 일수: {macd_positive_days}/{len(df)}일 ({macd_positive_days/len(df)*100:.1f}%)")

print(f"\n해결 방안:")
print(f"1. MACD 골든크로스 → MACD > Signal로 완화 (추천)")
print(f"2. MACD 조건 완전 제거 (ADX + RSI + Volume만 사용)")
