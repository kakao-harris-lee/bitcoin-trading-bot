#!/usr/bin/env python3
"""
debug_signals.py
v04 전략 신호 디버깅 - 왜 매수가 발생하지 않았는지 분석
"""

import sys
sys.path.append('../..')

import json
import pandas as pd

from mtf_loader import MTFLoader
from strategy import AdaptiveTrendRiderStrategy
from regime_classifier import RegimeClassifier
from signal_ensemble import SignalEnsemble


# Config 로드
with open('config.json', 'r') as f:
    config = json.load(f)

# 데이터 로드
mtf_loader = MTFLoader(db_path='../../upbit_bitcoin.db')
df_trade, df_day = mtf_loader.load_with_day_context(
    trade_timeframe='minute240',
    start_date='2024-01-01',
    end_date='2024-12-30'
)

print(f"Day 캔들: {len(df_day):,}")
print(f"Trade 캔들: {len(df_trade):,}")
print(f"\nDay 컬럼: {list(df_day.columns)}")
print(f"Trade 컬럼: {list(df_trade.columns)}\n")

# 전략 인스턴스
strategy = AdaptiveTrendRiderStrategy(config, df_day)

# === 샘플 분석 (100번째 캔들부터 10개) ===
print("="*80)
print("샘플 신호 분석 (캔들 100~110)")
print("="*80)

for i in range(100, 110):
    row = df_trade.iloc[i]
    day_idx = int(row['day_idx'])

    if day_idx < 0 or day_idx >= len(df_day):
        print(f"\n[{i}] Day index invalid: {day_idx}")
        continue

    # 시장 상태
    regime_info = strategy.regime_classifier.classify(df_day, day_idx)
    regime = regime_info['regime']
    regime_params = strategy.regime_classifier.get_regime_params(regime)

    # 매수 신호
    entry_signals = strategy.signal_ensemble.generate_signals(df_trade, i)
    required_votes = regime_params['entry_signals_needed']
    should_buy = strategy.signal_ensemble.should_buy(entry_signals, required_votes)

    print(f"\n[{i}] {row['timestamp']} | Price: {row['close']:,.0f}")
    print(f"  Regime: {regime} (ADX={regime_info['adx']:.1f}, Return={regime_info['recent_return']:.2%})")
    print(f"  Signals: {entry_signals['vote_count']}/{required_votes} - {entry_signals['details']}")
    print(f"  Should Buy: {'✅ YES' if should_buy else '❌ NO'}")

# === 전체 기간 통계 ===
print("\n" + "="*80)
print("전체 기간 통계")
print("="*80)

regime_counts = {'strong_bull': 0, 'moderate_bull': 0, 'neutral_bear': 0}
signal_stats = {
    'total_checked': 0,
    'vote_4': 0,
    'vote_3': 0,
    'vote_2': 0,
    'vote_1': 0,
    'vote_0': 0
}

for i in range(50, len(df_trade)):
    day_idx = int(df_trade.iloc[i]['day_idx'])
    if day_idx < 0 or day_idx >= len(df_day):
        continue

    regime_info = strategy.regime_classifier.classify(df_day, day_idx)
    regime = regime_info['regime']
    regime_counts[regime] += 1

    entry_signals = strategy.signal_ensemble.generate_signals(df_trade, i)
    signal_stats['total_checked'] += 1
    signal_stats[f'vote_{entry_signals["vote_count"]}'] += 1

print(f"\n시장 상태 분포 (캔들 50~{len(df_trade)}):")
for regime, count in regime_counts.items():
    pct = count / sum(regime_counts.values()) * 100
    print(f"  {regime}: {count:,} ({pct:.1f}%)")

print(f"\n신호 투표 분포:")
for vote in [4, 3, 2, 1, 0]:
    count = signal_stats[f'vote_{vote}']
    pct = count / signal_stats['total_checked'] * 100 if signal_stats['total_checked'] > 0 else 0
    print(f"  {vote}/4 신호: {count:,} ({pct:.1f}%)")

# === 매수 기회 분석 ===
buy_opportunities = 0
for i in range(50, len(df_trade)):
    day_idx = int(df_trade.iloc[i]['day_idx'])
    if day_idx < 0 or day_idx >= len(df_day):
        continue

    regime_info = strategy.regime_classifier.classify(df_day, day_idx)
    regime = regime_info['regime']
    regime_params = strategy.regime_classifier.get_regime_params(regime)

    entry_signals = strategy.signal_ensemble.generate_signals(df_trade, i)
    required_votes = regime_params['entry_signals_needed']

    if strategy.signal_ensemble.should_buy(entry_signals, required_votes):
        buy_opportunities += 1

print(f"\n매수 기회:")
print(f"  Total: {buy_opportunities}회 (전체의 {buy_opportunities/signal_stats['total_checked']*100:.2f}%)")
