#!/usr/bin/env python3
"""
test_ema_macd.py
EMA + MACD Confirmation 알고리즘 독립 테스트

목표: v07의 EMA/MACD를 개선 (MACD 단독 진입 제거, 둘 다 필요)
합격 기준:
  - 시그널 >= 3개 (보수적)
  - 승률 >= 60%
  - 평균 수익 > 15%
"""

import sys
sys.path.append('../..')

import json
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# Config 로드
with open('config.json') as f:
    config = json.load(f)

EMA_FAST = config['entry_algorithms']['ema_macd']['ema_fast']
EMA_SLOW = config['entry_algorithms']['ema_macd']['ema_slow']
MACD_FAST = config['entry_algorithms']['ema_macd']['macd_fast']
MACD_SLOW = config['entry_algorithms']['ema_macd']['macd_slow']
MACD_SIGNAL = config['entry_algorithms']['ema_macd']['macd_signal']
REQUIRE_BOTH = config['entry_algorithms']['ema_macd']['require_both']

print("="*80)
print("EMA + MACD Confirmation 알고리즘 독립 테스트")
print("="*80)
print(f"\n파라미터:")
print(f"  EMA Fast/Slow: {EMA_FAST}/{EMA_SLOW}")
print(f"  MACD Fast/Slow/Signal: {MACD_FAST}/{MACD_SLOW}/{MACD_SIGNAL}")
print(f"  Require Both: {REQUIRE_BOTH}")

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

df = MarketAnalyzer.add_indicators(df, indicators=['ema', 'macd'])

print(f"\n데이터: 2024-01-01 ~ 2024-12-31 ({len(df)}개 캔들)")

# EMA Golden Cross 체크
def check_ema_cross(df, i):
    if i < EMA_SLOW:
        return False
    prev = df.iloc[i-1]
    curr = df.iloc[i]
    return (prev[f'ema_{EMA_FAST}'] <= prev[f'ema_{EMA_SLOW}']) and (curr[f'ema_{EMA_FAST}'] > curr[f'ema_{EMA_SLOW}'])

# MACD Golden Cross 체크
def check_macd_cross(df, i):
    if i < MACD_SLOW:
        return False
    prev = df.iloc[i-1]
    curr = df.iloc[i]
    return (prev['macd'] <= prev['macd_signal']) and (curr['macd'] > curr['macd_signal'])

# 통합 조건
def check_ema_macd(df, i):
    ema_golden = check_ema_cross(df, i)
    macd_golden = check_macd_cross(df, i)

    if REQUIRE_BOTH:
        # 둘 다 필요 (개선 버전)
        return ema_golden and macd_golden
    else:
        # 둘 중 하나 (v07 방식)
        return ema_golden or macd_golden

# 신호 생성
signals = []
for i in range(len(df)):
    if check_ema_macd(df, i):
        ema_ok = check_ema_cross(df, i)
        macd_ok = check_macd_cross(df, i)
        signals.append({
            'index': i,
            'date': df.iloc[i]['timestamp'],
            'price': df.iloc[i]['close'],
            'ema_golden': ema_ok,
            'macd_golden': macd_ok,
            'reason': 'BOTH' if (ema_ok and macd_ok) else ('EMA' if ema_ok else 'MACD')
        })

print(f"\n발견된 EMA+MACD 신호: {len(signals)}개")
print("\n신호 목록:")
for idx, sig in enumerate(signals, 1):
    print(f"  {idx}. {sig['date']} - 가격: {sig['price']:,.0f}원, 이유: {sig['reason']}")

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
                'entry_reason': sig['reason'],
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
            'entry_reason': sig['reason'],
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
    print(f"\n[거래 {idx}] 진입: {t['entry_reason']}")
    print(f"  진입: {t['entry_date']} @ {t['entry_price']:,.0f}원")
    print(f"  청산: {t['exit_date']} @ {t['exit_price']:,.0f}원")
    print(f"  손익: {t['pnl_pct']:+.2f}% ({t['holding_days']}일, {t['reason']})")

# 합격 판정
print("\n" + "="*80)
print("합격 기준 검증")
print("="*80)

criteria = {
    '시그널 개수 >= 3': len(signals) >= 3,
    '승률 >= 60%': win_rate >= 60,
    '평균 수익 > 15%': avg_profit > 15
}

print()
for criterion, passed in criteria.items():
    status = "✅ PASS" if passed else "❌ FAIL"
    print(f"  {criterion}: {status}")

all_passed = all(criteria.values())
print(f"\n종합 판정: {'✅ 합격' if all_passed else '❌ 불합격'}")

if not all_passed:
    print("\n파인튜닝 제안:")
    if len(signals) < 3:
        print("  - Require Both를 False로 변경 (OR 조건)")
    if win_rate < 60:
        print("  - Trailing Stop 확대 (20% → 25%)")
    if avg_profit <= 15:
        print("  - Stop Loss 축소 (-10% → -8%)")

# v07과 비교
print("\n" + "="*80)
print("v07 비교 분석")
print("="*80)

print(f"\nv07 (EMA OR MACD):")
print(f"  - 신호: 5개 (EMA 1 + MACD 4)")
print(f"  - 승률: 40% (2승 3패)")
print(f"  - 평균 수익: +25.1% (수동 검증 기준)")

print(f"\nv12 (EMA AND MACD):")
print(f"  - 신호: {len(signals)}개")
print(f"  - 승률: {win_rate:.1f}%")
print(f"  - 평균 수익: {avg_profit:+.2f}%")

if all_passed:
    print(f"\n✅ v07 대비 개선: 신호 품질 향상 (승률 증가)")
else:
    print(f"\n⚠️  추가 조정 필요")

# 결과 저장
result = {
    'algorithm': 'EMA_MACD',
    'parameters': {
        'ema_fast': EMA_FAST,
        'ema_slow': EMA_SLOW,
        'macd_fast': MACD_FAST,
        'macd_slow': MACD_SLOW,
        'macd_signal': MACD_SIGNAL,
        'require_both': REQUIRE_BOTH
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

with open('test_ema_macd_result.json', 'w') as f:
    json.dump(result, f, indent=2, default=str)

print(f"\n결과가 test_ema_macd_result.json에 저장되었습니다.")
print("="*80)
