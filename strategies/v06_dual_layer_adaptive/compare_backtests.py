#!/usr/bin/env python3
"""
backtest_simple (DAY 단독) vs backtest_full (Dual Layer) 비교
"""

import sys
sys.path.append('../..')

import json
from core.data_loader import DataLoader
from core.backtester import Backtester
from core.market_analyzer import MarketAnalyzer

from layer1_day import DayStrategy
from dual_backtester import DualLayerBacktester

# Config 로드
with open('config.json', 'r') as f:
    config = json.load(f)

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df_day = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

df_day = MarketAnalyzer.add_indicators(df_day, indicators=['ema'])

print("="*80)
print("backtest_simple (DAY 단독) vs backtest_full (Dual Layer) 비교")
print("="*80)

# ========== backtest_simple 방식 (core.Backtester) ==========
print("\n[1/2] backtest_simple 방식...")
day_strategy1 = DayStrategy(config['layer1_day'])

def simple_wrapper(df, i, params):
    strategy = params['strategy']
    backtester = params['backtester']
    current_capital = backtester.cash + backtester.position_value
    signal = strategy.generate_signal(df, i, current_capital)

    if signal['action'] == 'buy':
        strategy.on_buy(df.iloc[i]['timestamp'], df.iloc[i]['close'])
    elif signal['action'] == 'sell':
        strategy.on_sell()

    return signal

backtester1 = Backtester(
    initial_capital=config['backtest_settings']['initial_capital'],
    fee_rate=config['backtest_settings']['fee_rate'],
    slippage=config['backtest_settings']['slippage']
)

results1 = backtester1.run(
    df=df_day,
    strategy_func=simple_wrapper,
    strategy_params={'strategy': day_strategy1, 'backtester': backtester1}
)

print(f"최종 자본: {results1['final_capital']:,.0f} KRW ({results1['total_return']:.2f}%)")
print(f"거래: {results1['total_trades']}회")

# ========== backtest_full 방식 (DualLayerBacktester) ==========
print("\n[2/2] backtest_full 방식...")
day_strategy2 = DayStrategy(config['layer1_day'])
backtester2 = DualLayerBacktester(
    initial_capital=config['backtest_settings']['initial_capital'],
    fee_rate=config['backtest_settings']['fee_rate'],
    slippage=config['backtest_settings']['slippage']
)

for day_idx in range(len(df_day)):
    day_candle = df_day.iloc[day_idx]
    day_time = day_candle['timestamp']
    day_price = day_candle['close']

    day_signal = day_strategy2.generate_signal(df_day, day_idx, backtester2.day_cash)

    if day_signal['action'] == 'buy':
        success = backtester2.execute_day_buy(day_time, day_price, day_signal['fraction'])
        if success:
            day_strategy2.on_buy(day_time, day_price)

    elif day_signal['action'] == 'sell':
        success, pnl = backtester2.execute_day_sell(day_time, day_price, day_signal['fraction'])
        if success:
            day_strategy2.on_sell()

    backtester2.record_equity(day_time, day_price, day_price)

# 마지막 포지션 청산
final_time = df_day.iloc[-1]['timestamp']
final_price = df_day.iloc[-1]['close']

if backtester2.day_position > 0:
    backtester2.execute_day_sell(final_time, final_price, 1.0)

backtester2.record_equity(final_time, final_price, final_price)

results2 = backtester2.get_results()

print(f"최종 자본: {results2['final_capital']:,.0f} KRW ({results2['total_return']:.2f}%)")
print(f"거래: {results2['day_stats']['total_trades']}회")

# ========== 비교 ==========
print("\n" + "="*80)
print("비교")
print("="*80)
print(f"backtest_simple:  {results1['total_return']:7.2f}%  (core.Backtester)")
print(f"backtest_full:    {results2['total_return']:7.2f}%  (DualLayerBacktester)")
print(f"차이:             {results2['total_return'] - results1['total_return']:+7.2f}pp")
print("="*80)
