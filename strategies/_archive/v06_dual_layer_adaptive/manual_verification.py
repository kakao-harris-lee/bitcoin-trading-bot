#!/usr/bin/env python3
"""
manual_verification.py
v4 DAY 전략 거래를 수동으로 계산하여 정답 확정

목표: v4(288%), v5(293%), v6 core(293%), v6 dual(97%) 중 어느 것이 정확한지 확정
"""

import sys
sys.path.append('../..')

import json
from decimal import Decimal, ROUND_DOWN
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# 설정
INITIAL_CAPITAL = 10_000_000
FEE_RATE = 0.0005  # 0.05%
SLIPPAGE = 0.0002  # 0.02%
POSITION_FRACTION = 0.95  # v4 파라미터

print("="*80)
print("v4 DAY 전략 수동 계산 검증")
print("="*80)

# 데이터 로드
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

df = MarketAnalyzer.add_indicators(df, indicators=['ema'])

print(f"\n초기 설정:")
print(f"  초기 자본: {INITIAL_CAPITAL:,}원")
print(f"  수수료: {FEE_RATE:.4%}")
print(f"  슬리피지: {SLIPPAGE:.4%}")
print(f"  포지션 비율: {POSITION_FRACTION:.2%}")

# v4 전략으로 거래 신호 생성 (간단 버전)
trades_history = []
cash = INITIAL_CAPITAL
position = 0.0
entry_price = 0.0
highest_price = 0.0
in_position = False

for i in range(len(df)):
    if i < 26:
        continue

    current = df.iloc[i]
    prev = df.iloc[i-1]

    price = current['close']
    ema12 = current['ema_12']
    ema26 = current['ema_26']
    prev_ema12 = prev['ema_12']
    prev_ema26 = prev['ema_26']

    # 매수 신호
    if not in_position:
        golden_cross = (prev_ema12 <= prev_ema26) and (ema12 > ema26)
        already_golden = (ema12 > ema26)

        if golden_cross or already_golden:
            trades_history.append({
                'type': 'BUY',
                'index': i,
                'timestamp': current['timestamp'],
                'price': price,
                'cash_before': cash,
                'position_before': position
            })
            in_position = True
            entry_price = price
            highest_price = price

    # 매도 신호
    else:
        if price > highest_price:
            highest_price = price

        pnl_ratio = (price - entry_price) / entry_price
        drop_from_high = (highest_price - price) / highest_price
        dead_cross = (prev_ema12 >= prev_ema26) and (ema12 < ema26)

        trailing_stop = drop_from_high >= 0.20
        stop_loss = pnl_ratio <= -0.10

        if dead_cross or trailing_stop or stop_loss:
            trades_history.append({
                'type': 'SELL',
                'index': i,
                'timestamp': current['timestamp'],
                'price': price,
                'cash_before': cash,
                'position_before': position
            })
            in_position = False

# 마지막 포지션 청산
if in_position:
    last = df.iloc[-1]
    trades_history.append({
        'type': 'SELL',
        'index': len(df)-1,
        'timestamp': last['timestamp'],
        'price': last['close'],
        'cash_before': cash,
        'position_before': position
    })

print(f"\n발견된 거래 신호: {len(trades_history)}개")

# 수동 계산 시작
print("\n" + "="*80)
print("수동 계산 (Decimal 정밀도)")
print("="*80)

cash = Decimal(str(INITIAL_CAPITAL))
position = Decimal('0')

for idx, trade in enumerate(trades_history, 1):
    print(f"\n[거래 {idx}] {trade['type']} @ {trade['timestamp']}")
    print(f"  시장 가격: {trade['price']:,.0f}원")

    if trade['type'] == 'BUY':
        # 매수 계산
        market_price = Decimal(str(trade['price']))

        # 1. 투자 가능 금액
        available_cash = cash * Decimal(str(POSITION_FRACTION))
        print(f"  1) 투자 가능 금액: {cash:,.2f} × {POSITION_FRACTION} = {available_cash:,.2f}원")

        # 2. 슬리피지 적용 (매수 시 불리하게)
        execution_price = market_price * (Decimal('1') + Decimal(str(SLIPPAGE)))
        print(f"  2) 체결 가격: {market_price:,.2f} × 1.0002 = {execution_price:,.2f}원")

        # 3. 수수료 포함 구매 수량
        quantity = available_cash / (execution_price * (Decimal('1') + Decimal(str(FEE_RATE))))
        print(f"  3) 구매 수량: {available_cash:,.2f} / ({execution_price:,.2f} × 1.0005) = {quantity:.8f} BTC")

        # 4. 실제 비용
        cost = quantity * execution_price * (Decimal('1') + Decimal(str(FEE_RATE)))
        print(f"  4) 실제 비용: {quantity:.8f} × {execution_price:,.2f} × 1.0005 = {cost:,.2f}원")

        # 5. 잔고 업데이트
        cash_after = cash - cost
        position_after = position + quantity

        print(f"  5) 잔고 변화:")
        print(f"     Cash: {cash:,.2f} → {cash_after:,.2f} (사용: {cost:,.2f})")
        print(f"     Position: {position:.8f} → {position_after:.8f} BTC")

        cash = cash_after
        position = position_after
        entry_price_d = execution_price

    else:  # SELL
        # 매도 계산
        market_price = Decimal(str(trade['price']))

        # 1. 매도 수량 (전량)
        sell_quantity = position
        print(f"  1) 매도 수량: {sell_quantity:.8f} BTC (전량)")

        # 2. 슬리피지 적용 (매도 시 불리하게)
        execution_price = market_price * (Decimal('1') - Decimal(str(SLIPPAGE)))
        print(f"  2) 체결 가격: {market_price:,.2f} × 0.9998 = {execution_price:,.2f}원")

        # 3. 수수료 차감 후 수령액
        proceeds = sell_quantity * execution_price * (Decimal('1') - Decimal(str(FEE_RATE)))
        print(f"  3) 수령액: {sell_quantity:.8f} × {execution_price:,.2f} × 0.9995 = {proceeds:,.2f}원")

        # 4. 손익 계산
        pnl = (execution_price - entry_price_d) * sell_quantity
        pnl_pct = (execution_price - entry_price_d) / entry_price_d * Decimal('100')
        print(f"  4) 손익: {pnl:+,.2f}원 ({pnl_pct:+.2f}%)")

        # 5. 잔고 업데이트
        cash_after = cash + proceeds
        position_after = position - sell_quantity

        print(f"  5) 잔고 변화:")
        print(f"     Cash: {cash:,.2f} → {cash_after:,.2f} (수령: {proceeds:,.2f})")
        print(f"     Position: {position:.8f} → {position_after:.8f} BTC")

        cash = cash_after
        position = position_after

# 최종 결과
print("\n" + "="*80)
print("최종 결과 (수동 계산)")
print("="*80)

final_capital = cash
total_return = (final_capital - Decimal(str(INITIAL_CAPITAL))) / Decimal(str(INITIAL_CAPITAL)) * Decimal('100')

print(f"\n초기 자본: {INITIAL_CAPITAL:,.0f}원")
print(f"최종 자본: {float(final_capital):,.2f}원")
print(f"수익: {float(final_capital - Decimal(str(INITIAL_CAPITAL))):+,.2f}원")
print(f"수익률: {float(total_return):.2f}%")

# 비교
print("\n" + "="*80)
print("기존 결과와 비교")
print("="*80)

comparisons = {
    'v4 (auto_optimized)': 288.67,
    'v5 (optimized)': 293.38,
    'v6 core.Backtester': 293.38,
    'v6 DualLayerBacktester': 97.84,
    '수동 계산 (정답)': float(total_return)
}

for name, return_pct in comparisons.items():
    diff = return_pct - float(total_return)
    status = "✅" if abs(diff) < 1.0 else "❌"
    print(f"{name:30s}: {return_pct:7.2f}%  (차이: {diff:+7.2f}%p) {status}")

print("\n" + "="*80)
print("결론")
print("="*80)

if abs(float(total_return) - 288.67) < 1.0:
    print("✅ v4 결과 (288.67%)가 정확합니다.")
elif abs(float(total_return) - 293.38) < 1.0:
    print("✅ v5/v6 core.Backtester 결과 (293.38%)가 정확합니다.")
elif abs(float(total_return) - 97.84) < 1.0:
    print("⚠️  v6 DualLayerBacktester 결과 (97.84%)가 정확합니다.")
    print("    → v4/v5/v6 core.Backtester에 버그가 있을 가능성!")
else:
    print("⚠️  수동 계산 결과가 모든 기존 결과와 다릅니다.")
    print(f"    정답: {float(total_return):.2f}%")
    print("    → 모든 백테스터를 재검토해야 합니다.")

print("="*80)
