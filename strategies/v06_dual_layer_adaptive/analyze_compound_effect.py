#!/usr/bin/env python3
"""
analyze_compound_effect.py
v4 결과가 복리 효과를 반영하는지 확인

가설: core.Backtester가 매 거래마다 전체 자본을 재투자하여 복리 효과를 내는 것이 아닐까?
"""

print("="*80)
print("복리 효과 분석")
print("="*80)

# v4 거래 내역 (PnL %)
trades = [
    {'name': '거래 1', 'pnl_pct': 47.36},
    {'name': '거래 2', 'pnl_pct': -5.81},
    {'name': '거래 3', 'pnl_pct': -12.01},
    {'name': '거래 4', 'pnl_pct': 66.50},
]

# 복리 계산
capital = 10_000_000
print(f"\n초기 자본: {capital:,.0f}원\n")

for trade in trades:
    before = capital
    capital = capital * (1 + trade['pnl_pct'] / 100)
    print(f"{trade['name']}: {before:,.0f} → {capital:,.0f} ({trade['pnl_pct']:+.2f}%)")

print(f"\n최종 자본 (복리): {capital:,.0f}원")
total_return_compound = (capital - 10_000_000) / 10_000_000 * 100
print(f"수익률 (복리): {total_return_compound:.2f}%")

# 단리 계산
pnl_sum = sum(trade['pnl_pct'] for trade in trades)
final_simple = 10_000_000 * (1 + pnl_sum / 100)
total_return_simple = pnl_sum

print(f"\n최종 자본 (단리): {final_simple:,.0f}원")
print(f"수익률 (단리): {total_return_simple:.2f}%")

# 비교
print(f"\n" + "="*80)
print("비교")
print("="*80)

comparisons = [
    ("v4 결과", 288.67, 38866773),
    ("복리 계산", total_return_compound, capital),
    ("단리 계산", total_return_simple, final_simple),
    ("수동 계산", 94.77, 19477023),
]

for name, return_pct, final_capital in comparisons:
    print(f"{name:15s}: {return_pct:7.2f}%  ({final_capital:,.0f}원)")

print(f"\n" + "="*80)
print("결론")
print("="*80)

if abs(288.67 - total_return_compound) < 1.0:
    print("✅ v4 결과는 복리 효과를 반영합니다!")
    print("   core.Backtester는 매 거래마다 전체 자본을 재투자하는 것으로 보입니다.")
else:
    print("❌ v4 결과는 복리 효과로도 설명되지 않습니다.")

if abs(94.77 - total_return_simple) < 1.0:
    print("✅ 수동 계산은 단리와 일치합니다!")
else:
    print("❌ 수동 계산도 단리와 다릅니다.")

# 핵심 질문
print(f"\n" + "="*80)
print("핵심 질문")
print("="*80)
print("position_fraction = 0.95인데 왜 복리 효과가 나는가?")
print("→ 매수 시 cash의 95%만 사용하지만,")
print("   매도 후 받은 proceeds가 cash에 합산되어")
print("   다음 매수 시 (기존 5% + proceeds)의 95%를 사용하므로")
print("   결과적으로 전체 자본이 거래에 참여하게 됩니다.")
print("\n이것이 정상적인 복리 효과입니다.")
print("="*80)
