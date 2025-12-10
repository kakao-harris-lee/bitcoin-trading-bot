#!/usr/bin/env python3
"""
run_v4_optimized_params.py
v4 auto_optimized_all_timeframes.json의 DAY 파라미터로 실행

파라미터:
  position_fraction: 0.95
  trailing_stop_pct: 0.2
  stop_loss_pct: 0.1

목표: 288.67%를 재현
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.backtester import Backtester

sys.path.append('../../strategies/v04_adaptive_trend_rider')
from strategy_simple import SimpleTrendFollowing, simple_strategy_wrapper

print("="*80)
print("v4 auto_optimized DAY 파라미터로 재현")
print("="*80)

# auto_optimized 파라미터
config = {
    'position_fraction': 0.95,
    'trailing_stop_pct': 0.2,
    'stop_loss_pct': 0.1,
    'initial_capital': 10_000_000,
    'fee_rate': 0.0005,
    'slippage': 0.0002
}

print(f"\nConfig (auto_optimized):")
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
print("백테스팅 결과")
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
print(f"v4 auto_optimized: {results['total_return']:.2f}%")
print(f"v4 기록값: 288.67%")
print(f"수동 계산 (정답): 94.77%")

print(f"\n차이 분석:")
print(f"  v4 결과 vs 기록값: {results['total_return'] - 288.67:+.2f}%p")
print(f"  v4 결과 vs 수동 계산: {results['total_return'] - 94.77:+.2f}%p")

if abs(results['total_return'] - 288.67) < 1.0:
    print("\n✅ v4 auto_optimized 결과 재현 성공 (288.67%)")
else:
    print(f"\n❌ v4 auto_optimized 결과 재현 실패 ({results['total_return']:.2f}% vs 288.67%)")

if abs(results['total_return'] - 94.77) < 1.0:
    print("✅ 수동 계산과 일치")
else:
    print(f"❌ 수동 계산과 불일치 ({results['total_return'] / 94.77:.1f}배 차이)")

print("="*80)
