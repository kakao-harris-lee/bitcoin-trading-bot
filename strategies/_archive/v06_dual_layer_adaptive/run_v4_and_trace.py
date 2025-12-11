#!/usr/bin/env python3
"""
run_v4_and_trace.py
v4 backtest_simple.py를 실행하고 거래 내역 추적

목표: 288%가 어떻게 계산되었는지 확인
"""

import sys
sys.path.append('../..')

import json
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.backtester import Backtester

# v4 strategy 가져오기
sys.path.append('../../strategies/v04_adaptive_trend_rider')
from strategy_simple import SimpleTrendFollowing, simple_strategy_wrapper

print("="*80)
print("v4 backtest_simple.py 재현")
print("="*80)

# v4 config 로드
with open('../../strategies/v04_adaptive_trend_rider/config_simple.json') as f:
    config = json.load(f)

print(f"\nConfig:")
print(f"  position_fraction: {config['position_fraction']}")
print(f"  trailing_stop_pct: {config['trailing_stop_pct']}")
print(f"  stop_loss_pct: {config['stop_loss_pct']}")

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-30')

df = MarketAnalyzer.add_indicators(df, indicators=['ema'])

print(f"\n데이터: {len(df)} candles")

# 전략 및 백테스터 생성
strategy = SimpleTrendFollowing(config)
backtester = Backtester(
    initial_capital=config['initial_capital'],
    fee_rate=config['fee_rate'],
    slippage=config['slippage']
)

strategy_params = {
    'strategy_instance': strategy,
    'backtester': backtester
}

# 백테스팅 실행
results = backtester.run(df, simple_strategy_wrapper, strategy_params)

print(f"\n" + "="*80)
print("v4 backtest_simple.py 결과")
print("="*80)

print(f"\n초기 자본: {results['initial_capital']:,.0f}원")
print(f"최종 자본: {results['final_capital']:,.0f}원")
print(f"수익률: {results['total_return']:.2f}%")
print(f"거래 횟수: {results['total_trades']}")

# 거래 내역 출력
print(f"\n거래 내역:")
for i, trade in enumerate(results['trades'], 1):
    if trade.exit_time:
        print(f"\n[{i}] {trade.entry_time} ~ {trade.exit_time}")
        print(f"    Entry: {trade.entry_price:,.0f}원 × {trade.quantity:.8f} BTC")
        print(f"    Exit:  {trade.exit_price:,.0f}원")
        print(f"    PnL: {trade.profit_loss:+,.0f}원 ({trade.profit_loss_pct:+.2f}%)")

# Buy&Hold 계산
start_price = df.iloc[0]['close']
end_price = df.iloc[-1]['close']
buyhold_return = ((end_price - start_price) / start_price) * 100

print(f"\n" + "="*80)
print("비교")
print("="*80)
print(f"Buy&Hold: {buyhold_return:.2f}%")
print(f"v4 전략: {results['total_return']:.2f}%")
print(f"수동 계산 (정답): 94.77%")
print(f"\n차이: {results['total_return'] - 94.77:+.2f}%p")

if abs(results['total_return'] - 94.77) < 1.0:
    print("✅ v4가 정확합니다 (수동 계산과 일치)")
else:
    print("❌ v4가 부정확합니다 (수동 계산과 불일치)")
    print(f"   v4 결과가 {results['total_return'] / 94.77:.1f}배 과대평가되었습니다.")

print("="*80)
