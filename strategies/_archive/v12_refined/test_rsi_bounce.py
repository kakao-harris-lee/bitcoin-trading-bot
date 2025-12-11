#!/usr/bin/env python3
"""
test_rsi_bounce.py
RSI Bounce + ADX Filter 알고리즘 독립 테스트

목표: v11의 RSI Bounce 성공 재현 + ADX 필터 추가
합격 기준:
  - 시그널 >= 5개
  - 승률 >= 55%
  - 평균 수익 > 10%
"""

import sys
sys.path.append('../..')

import json
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# Config 로드
with open('config.json') as f:
    config = json.load(f)

RSI_PERIOD = config['entry_algorithms']['rsi_bounce']['rsi_period']
RSI_OVERSOLD = config['entry_algorithms']['rsi_bounce']['rsi_oversold']
MIN_BOUNCE_DAYS = config['entry_algorithms']['rsi_bounce']['min_bounce_days']
MIN_ADX = config['entry_algorithms']['rsi_bounce']['min_adx']

print("="*80)
print("RSI Bounce + ADX Filter 알고리즘 독립 테스트")
print("="*80)
print(f"\n파라미터:")
print(f"  RSI Period: {RSI_PERIOD}")
print(f"  RSI Oversold: {RSI_OVERSOLD}")
print(f"  Min Bounce Days: {MIN_BOUNCE_DAYS}")
print(f"  Min ADX: {MIN_ADX}")

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'adx'])

print(f"\n데이터: 2024-01-01 ~ 2024-12-31 ({len(df)}개 캔들)")

# RSI Bounce 조건 검사
def check_rsi_bounce(df, i):
    if i < RSI_PERIOD + MIN_BOUNCE_DAYS:
        return False

    # 1. RSI가 과매도 → 반등
    prev_rsi = df.iloc[i - MIN_BOUNCE_DAYS]['rsi']
    curr_rsi = df.iloc[i]['rsi']

    # 2. ADX 확인 (추세 존재)
    adx = df.iloc[i]['adx']

    rsi_bounce = prev_rsi < RSI_OVERSOLD and curr_rsi >= RSI_OVERSOLD
    adx_ok = adx >= MIN_ADX

    return rsi_bounce and adx_ok

# 신호 생성
signals = []
for i in range(len(df)):
    if check_rsi_bounce(df, i):
        signals.append({
            'index': i,
            'date': df.iloc[i]['timestamp'],
            'price': df.iloc[i]['close'],
            'rsi': df.iloc[i]['rsi'],
            'adx': df.iloc[i]['adx'],
            'prev_rsi': df.iloc[i - MIN_BOUNCE_DAYS]['rsi']
        })

print(f"\n발견된 RSI BOUNCE 신호: {len(signals)}개")
print("\n신호 목록:")
for idx, sig in enumerate(signals, 1):
    print(f"  {idx}. {sig['date']} - 가격: {sig['price']:,.0f}원, RSI: {sig['prev_rsi']:.1f}→{sig['rsi']:.1f}, ADX: {sig['adx']:.1f}")

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
    '시그널 개수 >= 5': len(signals) >= 5,
    '승률 >= 55%': win_rate >= 55,
    '평균 수익 > 10%': avg_profit > 10
}

print()
for criterion, passed in criteria.items():
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {criterion}: {status}")

all_passed = all(criteria.values())
print(f"\n종합 판정: {'✅ 합격' if all_passed else '❌ 불합격'}")

if not all_passed:
    print("\n파인튜닝 제안:")
    if len(signals) < 5:
        print("  - RSI Oversold 증가 (35 → 40)")
        print("  - Min ADX 감소 (15 → 12)")
    if win_rate < 55:
        print("  - Trailing Stop 확대 (20% → 25%)")
    if avg_profit <= 10:
        print("  - Stop Loss 축소 (-10% → -8%)")

# v11과 비교
print("\n" + "="*80)
print("v11 비교 분석")
print("="*80)

print(f"\nv11 (RSI Bounce):")
print(f"  - 신호: 2개")
print(f"  - 승률: 50% (1승 1패)")
print(f"  - 평균 수익: +34.05% (수동 검증 기준)")

print(f"\nv12 (RSI + ADX Filter):")
print(f"  - 신호: {len(signals)}개")
print(f"  - 승률: {win_rate:.1f}%")
print(f"  - 평균 수익: {avg_profit:+.2f}%")

if all_passed:
    print(f"\n✅ v11 대비 개선: 신호 증가, 안정적 승률")
else:
    print(f"\n⚠️  추가 조정 필요")

# 결과 저장
result = {
    'algorithm': 'RSI_BOUNCE',
    'parameters': {
        'rsi_period': RSI_PERIOD,
        'rsi_oversold': RSI_OVERSOLD,
        'min_bounce_days': MIN_BOUNCE_DAYS,
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

with open('test_rsi_bounce_result.json', 'w') as f:
    json.dump(result, f, indent=2, default=str)

print(f"\n결과가 test_rsi_bounce_result.json에 저장되었습니다.")
print("="*80)
