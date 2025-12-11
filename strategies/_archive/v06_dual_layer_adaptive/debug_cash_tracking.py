#!/usr/bin/env python3
"""
거래별 cash 변화 추적
"""

import sys
sys.path.append('../..')

import json
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from dual_backtester import DualLayerBacktester
from layer1_day import DayStrategy

# Config 로드
with open('config.json', 'r') as f:
    config = json.load(f)

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df_day = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

df_day = MarketAnalyzer.add_indicators(df_day, indicators=['ema'])

day_strategy = DayStrategy(config['layer1_day'])
backtester = DualLayerBacktester(
    initial_capital=10_000_000,
    fee_rate=0.0005,
    slippage=0.0002
)

print("="*80)
print("거래별 Cash 추적")
print("="*80)
print(f"초기 cash: {backtester.day_cash:,.0f}\n")

trade_num = 0

for day_idx in range(len(df_day)):
    day_candle = df_day.iloc[day_idx]
    day_time = day_candle['timestamp']
    day_price = day_candle['close']

    day_signal = day_strategy.generate_signal(df_day, day_idx, backtester.day_cash)

    if day_signal['action'] == 'buy':
        before_cash = backtester.day_cash
        success = backtester.execute_day_buy(day_time, day_price, day_signal['fraction'])
        if success:
            trade_num += 1
            day_strategy.on_buy(day_time, day_price)
            after_cash = backtester.day_cash
            used = before_cash - after_cash
            print(f"[{trade_num}] {day_time} BUY {day_price:,.0f}")
            print(f"    Before cash: {before_cash:,.0f}")
            print(f"    Used: {used:,.0f} (qty={backtester.day_position:.4f} BTC)")
            print(f"    After cash: {after_cash:,.0f}\n")

    elif day_signal['action'] == 'sell':
        before_cash = backtester.day_cash
        before_pos = backtester.day_position
        success, pnl = backtester.execute_day_sell(day_time, day_price, day_signal['fraction'])
        if success:
            trade_num += 1
            day_strategy.on_sell()
            after_cash = backtester.day_cash
            proceeds = after_cash - before_cash
            print(f"[{trade_num}] {day_time} SELL {day_price:,.0f}")
            print(f"    Before cash: {before_cash:,.0f}")
            print(f"    Sold qty: {before_pos:.4f} BTC")
            print(f"    Proceeds: {proceeds:,.0f}")
            print(f"    PnL (reported): {pnl:,.0f}")
            print(f"    After cash: {after_cash:,.0f}\n")

    backtester.record_equity(day_time, day_price, day_price)

# 마지막 포지션 청산
final_time = df_day.iloc[-1]['timestamp']
final_price = df_day.iloc[-1]['close']

if backtester.day_position > 0:
    before_cash = backtester.day_cash
    before_pos = backtester.day_position
    backtester.execute_day_sell(final_time, final_price, 1.0)
    after_cash = backtester.day_cash
    proceeds = after_cash - before_cash
    trade_num += 1
    print(f"[{trade_num}] {final_time} SELL {final_price:,.0f} (Final)")
    print(f"    Before cash: {before_cash:,.0f}")
    print(f"    Sold qty: {before_pos:.4f} BTC")
    print(f"    Proceeds: {proceeds:,.0f}")
    print(f"    After cash: {after_cash:,.0f}\n")

backtester.record_equity(final_time, final_price, final_price)

print("="*80)
print(f"최종 cash: {backtester.day_cash:,.0f}")
print(f"총 PnL (cash - initial): {backtester.day_cash - 10_000_000:,.0f}")
print(f"수익률: {(backtester.day_cash / 10_000_000 - 1) * 100:.2f}%")
print("="*80)
