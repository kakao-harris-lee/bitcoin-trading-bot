#!/usr/bin/env python3
"""v10 Debug Backtest - 2024만 테스트"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from market_regime_detector import MarketRegimeDetector
from simple_backtester import SimpleBacktester
from adaptive_strategy import v10_strategy_function, reset_state

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

# Backtester
backtester = SimpleBacktester(10_000_000, 0.0005, 0.0002)
reset_state()

# Log
entry_signals = []
actual_entries = []
actual_exits = []

for i in range(len(df)):
    row = df.iloc[i]
    timestamp = row['timestamp']
    price = row['close']
    regime = detector.detect(df, i)

    # Check entry signal
    if i >= 30:
        prev_row = df.iloc[i-1]
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

        should_signal = False
        signal_type = ''

        if regime == 'bull':
            if config['bull_market']['require_golden_cross']:
                should_signal = ema_golden or macd_golden
                signal_type = 'BULL_GOLDEN'
        elif regime == 'sideways':
            if not config['sideways_market']['require_golden_cross']:
                min_momentum = config['sideways_market'].get('min_momentum', 0.03)
                should_signal = (ema12 > ema26 and momentum > min_momentum)
                signal_type = 'SIDEWAYS_EMA_MOMENTUM'
        elif regime == 'bear':
            if config['bear_market']['require_golden_cross'] and config['bear_market']['require_macd_cross']:
                min_momentum = config['bear_market'].get('min_momentum', 0.10)
                should_signal = (ema_golden and macd_golden and momentum > min_momentum)
                signal_type = 'BEAR_BOTH_GOLDEN'

        if should_signal:
            entry_signals.append({
                'date': timestamp.date(),
                'regime': regime,
                'signal_type': signal_type,
                'price': price,
                'in_position': backtester.position > 0
            })

    # Execute strategy
    decision = v10_strategy_function(df, i, config, detector)

    if decision['action'] == 'buy':
        actual_entries.append({
            'date': timestamp.date(),
            'regime': regime,
            'price': price
        })
        backtester.execute_buy(timestamp, price, decision['fraction'])

    elif decision['action'] == 'sell':
        actual_exits.append({
            'date': timestamp.date(),
            'regime': regime,
            'price': price,
            'reason': decision.get('reason', '')
        })
        backtester.execute_sell(timestamp, price, decision['fraction'])

    backtester.record_equity(timestamp, price)

print("="*80)
print("v10 Debug Backtest (2024)")
print("="*80)

print(f"\n진입 신호 발생: {len(entry_signals)}회")
print(f"실제 진입: {len(actual_entries)}회")
print(f"실제 청산: {len(actual_exits)}회")

print(f"\n--- 진입 신호 (처음 10개) ---")
for sig in entry_signals[:10]:
    status = "❌ 이미 보유 중" if sig['in_position'] else "✅ 매수 가능"
    print(f"{sig['date']} | {sig['regime'].upper():8s} | {sig['signal_type']:25s} | {sig['price']:>12,.0f}원 | {status}")

print(f"\n--- 실제 진입 ---")
for entry in actual_entries:
    print(f"{entry['date']} | {entry['regime'].upper():8s} | {entry['price']:>12,.0f}원")

print(f"\n--- 실제 청산 ---")
for exit in actual_exits:
    print(f"{exit['date']} | {exit['regime'].upper():8s} | {exit['price']:>12,.0f}원 | {exit['reason']}")

print("\n" + "="*80)

# Results
results = backtester.get_results()
print(f"\n최종 수익률: {results['total_return']:+.2f}%")
print(f"총 거래: {results['total_trades']}회")
print(f"승률: {results['win_rate']:.1%}")
