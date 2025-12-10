#!/usr/bin/env python3
"""
DAY 전략이 backtest_full에서 왜 3번만 거래하는지 디버그
"""

import sys
sys.path.append('../..')

import json
import pandas as pd
from core.data_loader import DataLoader
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

# 전략 및 백테스터 생성
day_strategy = DayStrategy(config['layer1_day'])
backtester = DualLayerBacktester(
    initial_capital=config['backtest_settings']['initial_capital'],
    fee_rate=config['backtest_settings']['fee_rate'],
    slippage=config['backtest_settings']['slippage']
)

print("=== DAY 신호 추적 (backtest_full 방식) ===\n")

signals = []
for day_idx in range(len(df_day)):
    day_candle = df_day.iloc[day_idx]
    day_time = day_candle['timestamp']
    day_price = day_candle['close']

    # DAY 신호
    day_signal = day_strategy.generate_signal(df_day, day_idx, backtester.day_cash)

    if day_signal['action'] != 'hold':
        signals.append({
            'idx': day_idx,
            'time': day_time,
            'action': day_signal['action'],
            'price': day_price,
            'cash': backtester.day_cash,
            'position': backtester.day_position,
            'executed': False
        })

        if day_signal['action'] == 'buy':
            before_cash = backtester.day_cash
            success = backtester.execute_day_buy(day_time, day_price, day_signal['fraction'])
            signals[-1]['executed'] = success
            if success:
                day_strategy.on_buy(day_time, day_price)
                print(f"[{day_idx:3d}] {day_time} | BUY  {day_price:,.0f}")
                print(f"         Before: cash={before_cash:,.0f}")
                print(f"         After:  cash={backtester.day_cash:,.0f}, pos={backtester.day_position:.4f} BTC")
                print(f"         Fraction: {day_signal['fraction']:.2f}, Used: {before_cash - backtester.day_cash:,.0f} ✅")
            else:
                print(f"[{day_idx:3d}] {day_time} | BUY  {day_price:,.0f} | FAILED (cash: {backtester.day_cash:,.0f}) ❌")

        elif day_signal['action'] == 'sell':
            success, pnl = backtester.execute_day_sell(day_time, day_price, day_signal['fraction'])
            signals[-1]['executed'] = success
            if success:
                day_strategy.on_sell()
                print(f"[{day_idx:3d}] {day_time} | SELL {day_price:,.0f} | PnL: {pnl:+,.0f} | Cash: {backtester.day_cash:,.0f} ✅")
            else:
                print(f"[{day_idx:3d}] {day_time} | SELL {day_price:,.0f} | FAILED (no position) ❌")

    # Equity curve 기록 (backtest_full과 동일하게)
    backtester.record_equity(day_time, day_price, day_price)

print(f"\n총 신호: {len(signals)}개")
print(f"성공: {sum(1 for s in signals if s['executed'])}개")
print(f"실패: {sum(1 for s in signals if not s['executed'])}개")

print(f"\n=== 최종 상태 ===")
print(f"Cash: {backtester.day_cash:,.0f} KRW")
print(f"Position: {backtester.day_position:.4f} BTC")
print(f"마지막 가격: {df_day.iloc[-1]['close']:,.0f} KRW")
print(f"포지션 가치: {backtester.day_position * df_day.iloc[-1]['close']:,.0f} KRW")
print(f"총 자본 (계산): {backtester.day_cash + backtester.day_position * df_day.iloc[-1]['close']:,.0f} KRW")

results = backtester.get_results()
print(f"\n=== get_results() 결과 ===")
print(f"최종 자본: {results['final_capital']:,.0f} KRW ({results['total_return']:.2f}%)")
print(f"DAY 거래: {results['day_stats']['total_trades']}회")
print(f"Equity curve 레코드: {len(results['equity_curve'])}개")
