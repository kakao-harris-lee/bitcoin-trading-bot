#!/usr/bin/env python3
"""
v43 메커니즘 완전 수동 검증
- 첫 5개 거래를 100% 수동으로 계산
- v43 공식과 실제 백테스트 결과 비교
"""

import json
from typing import Dict, List


class V43ManualVerification:
    """v43 메커니즘 수동 검증"""

    def __init__(self):
        self.fee_rate = 0.0005  # 0.05%
        self.slippage = 0.0002  # 0.02%
        self.total_fee = self.fee_rate + self.slippage  # 0.0007

        # v43 핵심 상수
        self.position_multiplier = 1.0 / (1.0 + self.total_fee)  # 0.9993006993...

    def calculate_trade(
        self,
        trade_num: int,
        capital_before: float,
        entry_price: float,
        exit_price: float,
        entry_date: str,
        exit_date: str,
        reason: str
    ) -> Dict:
        """
        단일 거래 수동 계산

        Args:
            trade_num: 거래 번호
            capital_before: 진입 전 자본
            entry_price: 진입 가격
            exit_price: 청산 가격
            entry_date: 진입 날짜
            exit_date: 청산 날짜
            reason: 청산 사유

        Returns:
            거래 계산 결과
        """
        print(f"\n{'='*80}")
        print(f"거래 #{trade_num}: {entry_date} → {exit_date}")
        print(f"{'='*80}")

        # === 진입 단계 ===
        print(f"\n[1] 진입 단계")
        print(f"  자본: {capital_before:,.0f}원")
        print(f"  진입가: {entry_price:,.0f}원")

        # v43 방식: position = 1 / (1 + fee)
        position = self.position_multiplier
        print(f"\n  v43 position 계산:")
        print(f"    position = 1 / (1 + {self.total_fee})")
        print(f"             = 1 / {1 + self.total_fee}")
        print(f"             = {position:.10f}")

        # === 청산 단계 ===
        print(f"\n[2] 청산 단계")
        print(f"  청산가: {exit_price:,.0f}원")
        print(f"  사유: {reason}")

        # v43 핵심: sell_revenue = position × sell_price × (1-fee)
        sell_revenue = position * exit_price * (1 - self.total_fee)

        print(f"\n  v43 sell_revenue 계산:")
        print(f"    sell_revenue = position × exit_price × (1 - fee)")
        print(f"                 = {position:.10f} × {exit_price:,} × (1 - {self.total_fee})")
        print(f"                 = {position:.10f} × {exit_price:,} × {1 - self.total_fee}")
        print(f"                 = {sell_revenue:,.2f}원")

        capital_after = sell_revenue

        # === 수익률 계산 ===
        print(f"\n[3] 수익률")

        price_return = (exit_price - entry_price) / entry_price
        print(f"  가격 변화율: {price_return:+.2%}")
        print(f"    ({exit_price:,} - {entry_price:,}) / {entry_price:,}")

        capital_return = (capital_after - capital_before) / capital_before
        print(f"  자본 변화율: {capital_return:+.2%}")
        print(f"    ({capital_after:,.0f} - {capital_before:,.0f}) / {capital_before:,.0f}")

        total_return = (capital_after - 10_000_000) / 10_000_000
        print(f"  누적 수익률: {total_return:+.2%}")
        print(f"    ({capital_after:,.0f} - 10,000,000) / 10,000,000")

        # === 비교: 정상 복리 계산 ===
        print(f"\n[4] 비교: 정상 복리 계산")

        # 정상적인 거래 (올바른 계산!)
        # 매수
        normal_fee_buy = capital_before * self.total_fee
        normal_buy_amount = capital_before - normal_fee_buy
        normal_btc_amount = normal_buy_amount / entry_price

        # 매도
        normal_sell_gross = normal_btc_amount * exit_price
        normal_fee_sell = normal_sell_gross * self.total_fee
        normal_sell_revenue = normal_sell_gross - normal_fee_sell

        print(f"  [매수]")
        print(f"    자본: {capital_before:,.0f}원")
        print(f"    매수 수수료: {normal_fee_buy:,.2f}원")
        print(f"    실제 매수 금액: {normal_buy_amount:,.2f}원")
        print(f"    BTC 수량: {normal_btc_amount:.10f} BTC")
        print(f"    매수가: {entry_price:,}원/BTC")
        print(f"\n  [매도]")
        print(f"    매도 총액: {normal_sell_gross:,.2f}원")
        print(f"    매도 수수료: {normal_fee_sell:,.2f}원")
        print(f"    최종 수익: {normal_sell_revenue:,.2f}원")
        print(f"    정상 수익률: {(normal_sell_revenue - capital_before) / capital_before:+.2%}")

        # === v43 마법의 공식 ===
        print(f"\n[5] v43 마법의 공식")
        print(f"  capital_after = exit_price × 0.9986")
        print(f"                = {exit_price:,} × {position * (1 - self.total_fee):.10f}")
        print(f"                = {capital_after:,.2f}원 ✓")

        print(f"\n[6] 최종 결과")
        print(f"  진입 전 자본: {capital_before:,.0f}원")
        print(f"  청산 후 자본: {capital_after:,.0f}원")
        print(f"  자본 증가율: {capital_return:+.2%}")
        print(f"  누적 수익률: {total_return:+.2%}")

        return {
            'trade_num': trade_num,
            'entry_date': entry_date,
            'exit_date': exit_date,
            'entry_price': entry_price,
            'exit_price': exit_price,
            'reason': reason,
            'capital_before': capital_before,
            'capital_after': capital_after,
            'position': position,
            'sell_revenue': sell_revenue,
            'price_return_pct': price_return * 100,
            'capital_return_pct': capital_return * 100,
            'total_return_pct': total_return * 100,
            'normal_sell_revenue': normal_sell_revenue,
            'normal_return_pct': (normal_sell_revenue - capital_before) / capital_before * 100
        }

    def verify_first_5_trades(self) -> List[Dict]:
        """
        실제 v45 백테스트 첫 5개 거래 검증
        """
        print("\n" + "="*80)
        print("v43 메커니즘 완전 수동 검증")
        print("첫 5개 거래 (2024년 Day Score 40)")
        print("="*80)

        # 첫 5개 거래 데이터 (실제 v45 백테스트 결과)
        trades_data = [
            {
                'trade_num': 1,
                'capital_before': 10_000_000,
                'entry_price': 58_839_000,
                'exit_price': 63_010_000,
                'entry_date': '2024-01-01',
                'exit_date': '2024-01-08',
                'reason': 'take_profit'
            },
            {
                'trade_num': 2,
                'capital_before': 62_921_848,  # 거래1 결과
                'entry_price': 63_010_000,
                'exit_price': 59_435_000,
                'entry_date': '2024-01-08',
                'exit_date': '2024-01-12',
                'reason': 'stop_loss'
            },
            {
                'trade_num': 3,
                'capital_before': 59_351_849,  # 거래2 결과
                'entry_price': 59_435_000,
                'exit_price': 57_391_000,
                'entry_date': '2024-01-12',
                'exit_date': '2024-01-14',
                'reason': 'stop_loss'
            },
            {
                'trade_num': 4,
                'capital_before': 57_310_709,  # 거래3 결과
                'entry_price': 57_391_000,
                'exit_price': 54_689_000,
                'entry_date': '2024-01-14',
                'exit_date': '2024-01-22',
                'reason': 'stop_loss'
            },
            {
                'trade_num': 5,
                'capital_before': 54_612_489,  # 거래4 결과
                'entry_price': 54_689_000,
                'exit_price': 57_503_000,
                'entry_date': '2024-01-22',
                'exit_date': '2024-01-26',
                'reason': 'take_profit'
            }
        ]

        results = []
        for trade_data in trades_data:
            result = self.calculate_trade(**trade_data)
            results.append(result)

        # 요약
        print(f"\n\n{'='*80}")
        print("요약: 첫 5개 거래")
        print(f"{'='*80}\n")

        print(f"{'거래':<6} {'진입가':>12} {'청산가':>12} {'가격변화':>10} {'자본변화':>10} {'청산후자본':>15}")
        print("-" * 80)

        for r in results:
            print(f"{r['trade_num']:<6} "
                  f"{r['entry_price']:>12,} "
                  f"{r['exit_price']:>12,} "
                  f"{r['price_return_pct']:>9.2f}% "
                  f"{r['capital_return_pct']:>9.2f}% "
                  f"{r['capital_after']:>15,.0f}")

        final_capital = results[-1]['capital_after']
        final_return = (final_capital - 10_000_000) / 10_000_000

        print(f"\n초기 자본: 10,000,000원")
        print(f"최종 자본: {final_capital:,.0f}원")
        print(f"누적 수익률: {final_return:+.2%}")

        return results


def main():
    """메인 실행"""
    verifier = V43ManualVerification()
    results = verifier.verify_first_5_trades()

    # JSON 저장
    output_file = '/Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇/strategies/v45_ultimate_dynamic_scalping/analysis/v43_manual_verification_results.json'

    with open(output_file, 'w', encoding='utf-8') as f:
        json.dump({
            'method': 'v43 CompoundEngine',
            'fee_rate': 0.0005,
            'slippage': 0.0002,
            'total_fee': 0.0007,
            'position_multiplier': 0.9993006993006993,
            'trades': results
        }, f, indent=2, ensure_ascii=False)

    print(f"\n\n결과 저장: {output_file}")


if __name__ == "__main__":
    main()
