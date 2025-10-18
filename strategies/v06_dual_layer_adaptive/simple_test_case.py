#!/usr/bin/env python3
"""
simple_test_case.py
간단한 고정 가격 시나리오로 백테스터 검증

시나리오:
- 초기 자본: 1000만원
- 거래 1: 100만원에 매수 (fraction=0.95)
- 거래 2: 200만원에 매도 (fraction=1.0)
"""

import sys
sys.path.append('../..')

import pandas as pd
from datetime import datetime, timedelta
from decimal import Decimal, ROUND_DOWN

from core.backtester import Backtester
from dual_backtester import DualLayerBacktester

# 테스트 설정
INITIAL_CAPITAL = 10_000_000
FEE_RATE = 0.0005
SLIPPAGE = 0.0002
POSITION_FRACTION = 0.95

print("="*80)
print("간단한 테스트 케이스: 고정 가격 시나리오")
print("="*80)

# 가짜 데이터 생성
dates = [
    datetime(2024, 1, 1),
    datetime(2024, 1, 2),  # 매수
    datetime(2024, 1, 3),  # 매도
]

prices = [
    1_000_000,  # 초기
    1_000_000,  # 매수: 100만원
    2_000_000,  # 매도: 200만원
]

df = pd.DataFrame({
    'timestamp': dates,
    'open': prices,
    'high': prices,
    'low': prices,
    'close': prices,
    'volume': [1000] * len(dates),
    'ema_12': prices,
    'ema_26': [p * 0.99 for p in prices],  # EMA26이 항상 낮음 (골든크로스 상태)
})

print(f"\n테스트 데이터:")
print(df[['timestamp', 'close', 'ema_12', 'ema_26']])

# ============================================================================
# 1. 수동 계산 (정답)
# ============================================================================
print("\n" + "="*80)
print("1. 수동 계산 (Decimal 정밀도)")
print("="*80)

cash = Decimal(str(INITIAL_CAPITAL))
position = Decimal('0')

# 거래 1: 매수 @ 100만원
print("\n[거래 1] BUY @ 1,000,000원")
market_price = Decimal('1000000')
available_cash = cash * Decimal(str(POSITION_FRACTION))
execution_price = market_price * (Decimal('1') + Decimal(str(SLIPPAGE)))
quantity = available_cash / (execution_price * (Decimal('1') + Decimal(str(FEE_RATE))))
cost = quantity * execution_price * (Decimal('1') + Decimal(str(FEE_RATE)))

print(f"  투자 가능: {available_cash:,.2f}원")
print(f"  체결 가격: {execution_price:,.2f}원")
print(f"  구매 수량: {quantity:.8f} BTC")
print(f"  비용: {cost:,.2f}원")

cash -= cost
position += quantity
entry_price_d = execution_price

print(f"  Cash: {float(cash):,.2f}원, Position: {float(position):.8f} BTC")

# 거래 2: 매도 @ 200만원
print("\n[거래 2] SELL @ 2,000,000원")
market_price = Decimal('2000000')
sell_quantity = position
execution_price = market_price * (Decimal('1') - Decimal(str(SLIPPAGE)))
proceeds = sell_quantity * execution_price * (Decimal('1') - Decimal(str(FEE_RATE)))
pnl = (execution_price - entry_price_d) * sell_quantity

print(f"  매도 수량: {float(sell_quantity):.8f} BTC")
print(f"  체결 가격: {execution_price:,.2f}원")
print(f"  수령액: {proceeds:,.2f}원")
print(f"  손익: {float(pnl):+,.2f}원")

cash += proceeds
position -= sell_quantity

print(f"  Cash: {float(cash):,.2f}원, Position: {float(position):.8f} BTC")

manual_final = float(cash)
manual_return = (manual_final - INITIAL_CAPITAL) / INITIAL_CAPITAL * 100

print(f"\n최종 자본: {manual_final:,.2f}원")
print(f"수익률: {manual_return:.2f}%")

# ============================================================================
# 2. core.Backtester
# ============================================================================
print("\n" + "="*80)
print("2. core.Backtester")
print("="*80)

backtester_core = Backtester(
    initial_capital=INITIAL_CAPITAL,
    fee_rate=FEE_RATE,
    slippage=SLIPPAGE
)

def test_strategy(df, i, params):
    """테스트용 전략: 2일째 매수, 3일째 매도"""
    if i == 1:
        return {'action': 'buy', 'fraction': POSITION_FRACTION}
    elif i == 2:
        return {'action': 'sell', 'fraction': 1.0}
    return {'action': 'hold', 'fraction': 0.0}

results_core = backtester_core.run(df, test_strategy, {})

print(f"최종 자본: {results_core['final_capital']:,.2f}원")
print(f"수익률: {results_core['total_return']:.2f}%")

# ============================================================================
# 3. DualLayerBacktester (DAY only)
# ============================================================================
print("\n" + "="*80)
print("3. DualLayerBacktester (DAY only)")
print("="*80)

backtester_dual = DualLayerBacktester(
    initial_capital=INITIAL_CAPITAL,
    fee_rate=FEE_RATE,
    slippage=SLIPPAGE
)

# 수동으로 거래 실행
for i in range(len(df)):
    timestamp = df.iloc[i]['timestamp']
    price = df.iloc[i]['close']

    if i == 1:  # 매수
        backtester_dual.execute_day_buy(timestamp, price, POSITION_FRACTION)
    elif i == 2:  # 매도
        backtester_dual.execute_day_sell(timestamp, price, 1.0)

    backtester_dual.record_equity(timestamp, price, price)

results_dual = backtester_dual.get_results()

print(f"최종 자본: {results_dual['final_capital']:,.2f}원")
print(f"수익률: {results_dual['total_return']:.2f}%")

# ============================================================================
# 비교
# ============================================================================
print("\n" + "="*80)
print("결과 비교")
print("="*80)

results_comparison = [
    ("수동 계산 (정답)", manual_return, manual_final),
    ("core.Backtester", results_core['total_return'], results_core['final_capital']),
    ("DualLayerBacktester", results_dual['total_return'], results_dual['final_capital']),
]

for name, return_pct, final_capital in results_comparison:
    diff = return_pct - manual_return
    capital_diff = final_capital - manual_final
    status = "✅" if abs(diff) < 0.01 else "❌"
    print(f"{name:25s}: {return_pct:7.2f}%  (차이: {diff:+7.2f}%p, {capital_diff:+,.2f}원) {status}")

print("\n" + "="*80)
print("결론")
print("="*80)

if abs(results_core['total_return'] - manual_return) < 0.01:
    print("✅ core.Backtester가 정확합니다.")
else:
    print("❌ core.Backtester에 버그가 있습니다!")
    print(f"   예상: {manual_return:.2f}%, 실제: {results_core['total_return']:.2f}%")

if abs(results_dual['total_return'] - manual_return) < 0.01:
    print("✅ DualLayerBacktester가 정확합니다.")
else:
    print("❌ DualLayerBacktester에 버그가 있습니다!")
    print(f"   예상: {manual_return:.2f}%, 실제: {results_dual['total_return']:.2f}%")

print("="*80)
