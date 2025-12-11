#!/usr/bin/env python3
"""
test_breakout.py
BREAKOUT 알고리즘 독립 테스트

목표: v11의 02-07 BREAKOUT 성공 재현
합격 기준:
  - 시그널 >= 10개
  - 승률 >= 50%
  - 평균 수익 > 5%
"""

import sys
sys.path.append('../..')

import json
from decimal import Decimal
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# Config 로드
with open('config.json') as f:
    config = json.load(f)

LOOKBACK = config['entry_algorithms']['breakout']['lookback_period']
VOL_MULT = config['entry_algorithms']['breakout']['volume_multiplier']
MIN_ADX = config['entry_algorithms']['breakout']['min_adx']

print("="*80)
print("BREAKOUT 알고리즘 독립 테스트")
print("="*80)
print(f"\n파라미터:")
print(f"  Lookback Period: {LOOKBACK}일")
print(f"  Volume Multiplier: {VOL_MULT}x")
print(f"  Min ADX: {MIN_ADX}")

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

df = MarketAnalyzer.add_indicators(df, indicators=['adx'])

print(f"\n데이터: 2024-01-01 ~ 2024-12-31 ({len(df)}개 캔들)")

# BREAKOUT 조건 검사
def check_breakout(df, i):
    if i < LOOKBACK:
        return False

    # 1. 최고가 돌파
    lookback_high = df.iloc[i-LOOKBACK:i]['high'].max()
    curr_price = df.iloc[i]['close']

    # 2. 거래량 확인
    avg_volume = df.iloc[i-LOOKBACK:i]['volume'].mean()
    curr_volume = df.iloc[i]['volume']

    # 3. ADX 확인
    adx = df.iloc[i]['adx']

    breakout = curr_price > lookback_high
    volume_ok = curr_volume > avg_volume * VOL_MULT
    adx_ok = adx >= MIN_ADX

    return breakout and volume_ok and adx_ok

# 신호 생성
signals = []
for i in range(len(df)):
    if check_breakout(df, i):
        signals.append({
            'index': i,
            'date': df.iloc[i]['timestamp'],
            'price': df.iloc[i]['close'],
            'adx': df.iloc[i]['adx'],
            'volume_ratio': df.iloc[i]['volume'] / df.iloc[i-LOOKBACK:i]['volume'].mean()
        })

print(f"\n발견된 BREAKOUT 신호: {len(signals)}개")
print("\n신호 목록:")
for idx, sig in enumerate(signals, 1):
    print(f"  {idx}. {sig['date']} - 가격: {sig['price']:,.0f}원, ADX: {sig['adx']:.1f}, 거래량: {sig['volume_ratio']:.2f}x")

# 간이 성능 측정 (고정 Trailing Stop 20%, Stop Loss -10%)
TRAILING_STOP = 0.20
STOP_LOSS = 0.10

trades = []
for sig in signals:
    entry_idx = sig['index']
    entry_price = sig['price']
    highest_price = entry_price

    # 진입 후 추적
    for i in range(entry_idx + 1, len(df)):
        curr_price = df.iloc[i]['close']

        # 최고가 갱신
        if curr_price > highest_price:
            highest_price = curr_price

        # 손익률
        pnl_ratio = (curr_price - entry_price) / entry_price
        drop_from_high = (highest_price - curr_price) / highest_price

        # 청산 조건
        trailing_stop = drop_from_high >= TRAILING_STOP
        stop_loss = pnl_ratio <= -STOP_LOSS

        if trailing_stop or stop_loss:
            trades.append({
                'entry_date': sig['date'],
                'entry_price': entry_price,
                'exit_date': df.iloc[i]['timestamp'],
                'exit_price': curr_price,
                'pnl_pct': pnl_ratio * 100,
                'reason': 'TRAILING_STOP' if trailing_stop else 'STOP_LOSS',
                'holding_days': i - entry_idx
            })
            break
    else:
        # 연말까지 보유
        final_price = df.iloc[-1]['close']
        pnl_ratio = (final_price - entry_price) / entry_price
        trades.append({
            'entry_date': sig['date'],
            'entry_price': entry_price,
            'exit_date': df.iloc[-1]['timestamp'],
            'exit_price': final_price,
            'pnl_pct': pnl_ratio * 100,
            'reason': 'FINAL_EXIT',
            'holding_days': len(df) - 1 - entry_idx
        })

# 성과 계산
wins = [t for t in trades if t['pnl_pct'] > 0]
losses = [t for t in trades if t['pnl_pct'] <= 0]
win_rate = len(wins) / len(trades) * 100 if trades else 0
avg_profit = sum([t['pnl_pct'] for t in trades]) / len(trades) if trades else 0
avg_win = sum([t['pnl_pct'] for t in wins]) / len(wins) if wins else 0
avg_loss = sum([t['pnl_pct'] for t in losses]) / len(losses) if losses else 0

print("\n" + "="*80)
print("성과 측정 (Trailing Stop 20%, Stop Loss -10%)")
print("="*80)

print(f"\n총 거래: {len(trades)}회")
print(f"  승리: {len(wins)}회 ({win_rate:.1f}%)")
print(f"  손실: {len(losses)}회 ({100-win_rate:.1f}%)")
print(f"\n평균 수익: {avg_profit:+.2f}%")
print(f"  승리 거래 평균: {avg_win:+.2f}%")
print(f"  손실 거래 평균: {avg_loss:+.2f}%")

# 거래 상세
print("\n거래 상세:")
for idx, t in enumerate(trades, 1):
    print(f"\n[거래 {idx}]")
    print(f"  진입: {t['entry_date']} @ {t['entry_price']:,.0f}원")
    print(f"  청산: {t['exit_date']} @ {t['exit_price']:,.0f}원")
    print(f"  손익: {t['pnl_pct']:+.2f}% ({t['holding_days']}일, {t['reason']})")

# 합격 판정
print("\n" + "="*80)
print("합격 기준 검증")
print("="*80)

criteria = {
    '시그널 개수 >= 10': len(signals) >= 10,
    '승률 >= 50%': win_rate >= 50,
    '평균 수익 > 5%': avg_profit > 5
}

print()
for criterion, passed in criteria.items():
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {criterion}: {status}")

all_passed = all(criteria.values())
print(f"\n종합 판정: {'✅ 합격' if all_passed else '❌ 불합격'}")

if not all_passed:
    print("\n파인튜닝 제안:")
    if len(signals) < 10:
        print("  - Lookback Period 감소 (15 → 12)")
        print("  - Volume Multiplier 감소 (1.5 → 1.3)")
        print("  - Min ADX 감소 (20 → 15)")
    if win_rate < 50:
        print("  - Trailing Stop 확대 (20% → 25%)")
        print("  - Stop Loss 축소 (-10% → -8%)")
    if avg_profit <= 5:
        print("  - 진입 조건 강화 (ADX 증가)")

# 결과 저장
result = {
    'algorithm': 'BREAKOUT',
    'parameters': {
        'lookback_period': LOOKBACK,
        'volume_multiplier': VOL_MULT,
        'min_adx': MIN_ADX
    },
    'signals': len(signals),
    'trades': len(trades),
    'win_rate': win_rate,
    'avg_profit': avg_profit,
    'avg_win': avg_win,
    'avg_loss': avg_loss,
    'passed': all_passed,
    'criteria': criteria
}

with open('test_breakout_result.json', 'w') as f:
    json.dump(result, f, indent=2, default=str)

print(f"\n결과가 test_breakout_result.json에 저장되었습니다.")
print("="*80)
