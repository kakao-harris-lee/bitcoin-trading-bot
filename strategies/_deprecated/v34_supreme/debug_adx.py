#!/usr/bin/env python3
import sys
sys.path.append('../..')
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
import pandas as pd

with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'mfi', 'adx'])

print("ADX 통계:")
print(f"  최소값: {df['adx'].min():.2f}")
print(f"  최대값: {df['adx'].max():.2f}")
print(f"  평균값: {df['adx'].mean():.2f}")
print(f"  중앙값: {df['adx'].median():.2f}")
print(f"\nADX >= 20인 캔들: {len(df[df['adx'] >= 20])}개 ({len(df[df['adx'] >= 20])/len(df)*100:.1f}%)")
print(f"ADX >= 25인 캔들: {len(df[df['adx'] >= 25])}개 ({len(df[df['adx'] >= 25])/len(df)*100:.1f}%)")

print("\nMFI 통계:")
print(f"  최소값: {df['mfi'].min():.2f}")
print(f"  최대값: {df['mfi'].max():.2f}")
print(f"  평균값: {df['mfi'].mean():.2f}")
print(f"  중앙값: {df['mfi'].median():.2f}")
print(f"\nMFI >= 52인 캔들: {len(df[df['mfi'] >= 52])}개 ({len(df[df['mfi'] >= 52])/len(df)*100:.1f}%)")
print(f"MFI < 35인 캔들: {len(df[df['mfi'] < 35])}개 ({len(df[df['mfi'] < 35])/len(df)*100:.1f}%)")

print("\nBULL_STRONG 조건 (MFI>=52 AND MACD>Signal AND ADX>=20):")
bull_strong = df[(df['mfi'] >= 52) & (df['macd'] > df['macd_signal']) & (df['adx'] >= 20)]
print(f"  해당 캔들: {len(bull_strong)}개 ({len(bull_strong)/len(df)*100:.1f}%)")

print("\nBEAR_STRONG 조건 (MFI<35 AND ADX>=20):")
bear_strong = df[(df['mfi'] < 35) & (df['adx'] >= 20)]
print(f"  해당 캔들: {len(bear_strong)}개 ({len(bear_strong)/len(df)*100:.1f}%)")
