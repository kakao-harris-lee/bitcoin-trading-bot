#!/usr/bin/env python3
"""
거래 내역 상세 비교
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

# ========== core.Backtester ==========
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

print("="*80)
print("core.Backtester 거래 내역")
print("="*80)
for trade in backtester1.trades:
    if trade.exit_time:
        print(f"{trade.entry_time} BUY  {trade.entry_price:,.0f}  qty={trade.quantity:.4f}")
        print(f"{trade.exit_time}  SELL {trade.exit_price:,.0f}  PnL={trade.profit_loss:,.0f} ({trade.profit_loss_pct:+.2f}%)\n")

print(f"최종 자본: {results1['final_capital']:,.0f} KRW ({results1['total_return']:.2f}%)\n")

# ========== DualLayerBacktester ==========
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

print("="*80)
print("DualLayerBacktester 거래 내역")
print("="*80)
for trade in backtester2.trades:
    if trade.exit_time:
        print(f"{trade.entry_time} BUY  {trade.entry_price:,.0f}  qty={trade.quantity:.4f}")
        print(f"{trade.exit_time}  SELL {trade.exit_price:,.0f}  PnL={trade.profit_loss:,.0f} ({trade.profit_loss_pct:+.2f}%)\n")

print(f"최종 자본: {results2['final_capital']:,.0f} KRW ({results2['total_return']:.2f}%)")
print(f"DAY cash: {backtester2.day_cash:,.0f}, position={backtester2.day_position:.4f}")
print(f"Layer2 cash: {backtester2.layer2_cash:,.0f}, allocated={backtester2.layer2_allocated:,.0f}")
print(f"Layer2 position: {backtester2.layer2_position:.4f}, cumulative PnL={backtester2.layer2_cumulative_pnl:,.0f}")
print(f"Total: {backtester2.get_total_equity(final_price, final_price):,.0f}\n")
