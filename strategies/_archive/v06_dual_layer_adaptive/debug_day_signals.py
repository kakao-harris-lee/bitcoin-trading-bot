#!/usr/bin/env python3
import sys
sys.path.append('../..')
import json
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from layer1_day import DayStrategy

with open('config.json') as f:
    config = json.load(f)

with DataLoader('../../upbit_bitcoin.db') as loader:
    df_day = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

df_day = MarketAnalyzer.add_indicators(df_day, indicators=['ema'])

strategy = DayStrategy(config['layer1_day'])

trades = []
for i in range(len(df_day)):
    signal = strategy.generate_signal(df_day, i, 10_000_000)
    if signal['action'] != 'hold':
        candle = df_day.iloc[i]
        trades.append({
            'idx': i,
            'date': str(candle['timestamp']),
            'action': signal['action'],
            'price': candle['close']
        })
        if signal['action'] == 'buy':
            strategy.on_buy(candle['timestamp'], candle['close'])
        elif signal['action'] == 'sell':
            strategy.on_sell()

print('=== DAY 전략 신호 (독립 실행) ===')
for t in trades:
    print(f"{t['idx']:3d} | {t['date']} | {t['action']:4s} | {t['price']:,.0f}")
print(f'총 신호: {len(trades)}개')
