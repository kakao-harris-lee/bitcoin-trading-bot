#!/usr/bin/env python3
import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
import pandas as pd

db_path = project_root / 'upbit_bitcoin.db'

with DataLoader(str(db_path)) as loader:
    df = loader.load_timeframe('day', '2024-02-10', '2024-03-10')

df = MarketAnalyzer.add_indicators(df, ['rsi', 'macd', 'adx', 'bb', 'stoch'])

print("="*70)
print("2024년 2월-3월 MACD 골든크로스 분석")
print("="*70)

gc_count = 0

for i in range(1, len(df)):
    row = df.iloc[i]
    prev_row = df.iloc[i-1]
    
    macd = row.get('macd', 0)
    macd_signal = row.get('macd_signal', 0)
    prev_macd = prev_row.get('macd', 0)
    prev_signal = prev_row.get('macd_signal', 0)
    
    golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)
    
    if golden_cross:
        gc_count += 1
        adx = row.get('adx', 0)
        rsi = row.get('rsi', 0)
        volume = row.get('volume', 0)
        avg_volume = df['volume'].iloc[max(0,i-20):i].mean() if i >= 20 else volume
        volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0
        
        print(f"\n[골든크로스 #{gc_count}] {row['timestamp'].strftime('%Y-%m-%d')}")
        print(f"  MACD: {prev_macd:,.0f} → {macd:,.0f}")
        print(f"  Signal: {prev_signal:,.0f} → {macd_signal:,.0f}")
        print(f"  ADX: {adx:.1f} (필요: >= 15) {'✅' if adx >= 15 else '❌'}")
        print(f"  RSI: {rsi:.1f} (필요: < 70) {'✅' if rsi < 70 else '❌'}")
        print(f"  Volume: {volume_ratio:.2f}x (필요: >= 1.2x) {'✅' if volume_ratio >= 1.2 else '❌'}")
        
        all_pass = adx >= 15 and rsi < 70 and volume_ratio >= 1.2
        print(f"  결과: {'✅ 조건 충족!' if all_pass else '❌ 조건 불충족'}")

print(f"\n총 골든크로스: {gc_count}회")

if gc_count == 0:
    print("\n⚠️  MACD 골든크로스가 전혀 발생하지 않았습니다!")
    print("원인: MACD가 계속 Signal보다 위에 있거나, 아래에 있거나")
