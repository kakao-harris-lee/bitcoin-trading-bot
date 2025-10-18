#!/usr/bin/env python3
"""
v13 Voting Ensemble 수동 검증
백테스팅 결과가 정확한지 실제 거래를 수동 계산으로 재확인
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader

# 초기 설정
INITIAL_CAPITAL = 10_000_000
FEE_RATE = 0.0005

print("="*80)
print("v13 Voting Ensemble 수동 검증")
print("="*80)

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

# DataFrame을 딕셔너리로 변환 (날짜 기반 조회 용이)
price_dict = {}
for i, row in df.iterrows():
    date_str = str(row['timestamp']).split()[0]
    price_dict[date_str] = {
        'close': row['close'],
        'high': row['high'],
        'low': row['low']
    }

# 거래 내역 (v13 백테스팅 결과 기반)
trades = [
    {
        'entry_date': '2024-02-07',
        'exit_date': '2024-05-02',
        'reason': 'TRAILING_STOP',
        'signal': 'VWAP+BREAKOUT'
    },
    {
        'entry_date': '2024-07-05',
        'exit_date': '2024-09-06',
        'reason': 'TRAILING_STOP',
        'signal': 'VWAP+STOCHASTIC'
    },
    {
        'entry_date': '2024-09-07',
        'exit_date': '2024-12-30',
        'reason': 'END_OF_PERIOD',
        'signal': 'VWAP+STOCHASTIC'
    }
]

# 수동 계산
capital = INITIAL_CAPITAL
print(f"\n초기 자본: {capital:,}원\n")

for i, trade in enumerate(trades, 1):
    entry_date = trade['entry_date']
    exit_date = trade['exit_date']

    # 가격 조회
    entry_price = price_dict[entry_date]['close']
    exit_price = price_dict[exit_date]['close']

    # 매수
    buy_fee = capital * FEE_RATE
    btc = (capital - buy_fee) / entry_price

    # 최고가 추적 (Trailing Stop 계산용)
    highest_price = entry_price
    for date_str in price_dict:
        if entry_date <= date_str <= exit_date:
            day_high = price_dict[date_str]['high']
            if day_high > highest_price:
                highest_price = day_high

    # 매도
    sell_value = btc * exit_price
    sell_fee = sell_value * FEE_RATE
    capital = sell_value - sell_fee

    # 수익 계산
    pnl_pct = ((exit_price - entry_price) / entry_price) * 100

    # Trailing Stop 가격 (20%)
    trailing_stop_price = highest_price * 0.8

    print(f"[거래 {i}] {entry_date} → {exit_date}")
    print(f"  진입가: {entry_price:,.0f}원")
    print(f"  청산가: {exit_price:,.0f}원")
    print(f"  최고가: {highest_price:,.0f}원")
    print(f"  Trailing Stop 가격: {trailing_stop_price:,.0f}원")
    print(f"  수익률: {pnl_pct:+.2f}%")
    print(f"  자본: {capital:,.0f}원")
    print(f"  신호: {trade['signal']}")
    print(f"  청산 이유: {trade['reason']}")
    print()

# 최종 결과
total_return = ((capital - INITIAL_CAPITAL) / INITIAL_CAPITAL) * 100

print("="*80)
print("최종 검증 결과")
print("="*80)
print(f"초기 자본: {INITIAL_CAPITAL:,}원")
print(f"최종 자본: {capital:,.0f}원")
print(f"총 수익: {capital - INITIAL_CAPITAL:+,.0f}원")
print(f"수익률: {total_return:+.2f}%")
print()

# 백테스팅 결과와 비교
backtest_return = 133.78
backtest_capital = 23_377_656

print("백테스팅 결과와 비교:")
print(f"  백테스팅 수익률: +{backtest_return:.2f}%")
print(f"  수동 계산 수익률: {total_return:+.2f}%")
print(f"  차이: {total_return - backtest_return:+.2f}%p")
print()
print(f"  백테스팅 최종 자본: {backtest_capital:,}원")
print(f"  수동 계산 최종 자본: {capital:,.0f}원")
print(f"  차이: {capital - backtest_capital:+,.0f}원")
print()

if abs(total_return - backtest_return) < 0.5:
    print("✅ 검증 성공: 백테스팅 결과가 정확합니다!")
else:
    print("⚠️  검증 실패: 백테스팅 결과에 오차가 있습니다.")
    print(f"   허용 오차: ±0.5%p, 실제 오차: {total_return - backtest_return:+.2f}%p")

print("="*80)
