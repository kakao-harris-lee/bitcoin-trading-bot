"""
수동 검증 도구
평가 엔진이 올바르게 작동하는지 수동 계산과 비교하여 검증
"""

from pathlib import Path
import sys
import json
from typing import Dict

sys.path.insert(0, str(Path(__file__).parent))
from standard_evaluator import StandardEvaluator


class ManualVerifier:
    """평가 엔진 수동 검증"""

    def __init__(self):
        self.evaluator = StandardEvaluator(
            initial_capital=10_000_000,
            fee_rate=0.0005,
            slippage=0.0002
        )

    def create_test_case_1(self) -> Dict:
        """테스트 케이스 1: v39 2020년 재현

        실제 거래:
        - 매수: 2020-03-22, 7,367,473원, 66.7% 투자
        - 매도: 2020-12-30, 31,884,621원
        - 예상 수익: +510%
        """
        return {
            'version': 'test_v39_2020',
            'strategy_name': 'v39_voting_replica',
            'year': 2020,
            'timeframe': 'day',
            'buy_signals': [{
                'timestamp': '2020-03-22 09:00:00',
                'price': 7367473.2,
                'position_size': 0.667  # 66.7%
            }],
            'sell_signals': [{
                'buy_index': 0,
                'timestamp': '2020-12-30 09:00:00',
                'price': 31884621.8,
                'reason': 'Test Exit'
            }],
            'signal_count': 1,
            'expected': {
                'description': 'v39 2020년 실제 거래',
                'invested': 6670000,  # 10M * 0.667
                'btc_bought': None,  # 계산 필요
                'btc_price_change_pct': 332.77,  # (31.8M / 7.3M - 1) * 100
                'final_capital': 60999251,  # 실제 결과
                'return_pct': 509.99
            }
        }

    def create_test_case_2(self) -> Dict:
        """테스트 케이스 2: 단순 2배 수익

        간단한 시나리오:
        - 매수: 10M원에 100% 투자, BTC 가격 10M
        - 매도: BTC 가격 20M (2배)
        - 예상 수익: ~+99.3% (수수료 차감)
        """
        return {
            'version': 'test_simple_2x',
            'strategy_name': 'simple_2x_test',
            'year': 2020,
            'timeframe': 'day',
            'buy_signals': [{
                'timestamp': '2020-01-01 09:00:00',
                'price': 10000000.0,
                'position_size': 1.0  # 100%
            }],
            'sell_signals': [{
                'buy_index': 0,
                'timestamp': '2020-12-31 09:00:00',
                'price': 20000000.0,  # 2배
                'reason': 'Test Exit'
            }],
            'signal_count': 1,
            'expected': {
                'description': '2배 단순 케이스',
                'invested': 10000000,
                'btc_price_change': 2.0,  # 2배
                'expected_return_approx': 99.3  # (2.0 - 1) * 100 * (1-0.0007)^2
            }
        }

    def create_test_case_3(self) -> Dict:
        """테스트 케이스 3: 손실 케이스

        - 매수: 10M원에 50% 투자, BTC 가격 20M
        - 매도: BTC 가격 15M (-25% 하락)
        - 예상: 초기 자본 대비 약 -12.5% 손실
        """
        return {
            'version': 'test_loss',
            'strategy_name': 'loss_test',
            'year': 2020,
            'timeframe': 'day',
            'buy_signals': [{
                'timestamp': '2020-01-01 09:00:00',
                'price': 20000000.0,
                'position_size': 0.5  # 50%
            }],
            'sell_signals': [{
                'buy_index': 0,
                'timestamp': '2020-06-30 09:00:00',
                'price': 15000000.0,  # -25%
                'reason': 'Test Exit'
            }],
            'signal_count': 1,
            'expected': {
                'description': '손실 케이스',
                'invested': 5000000,  # 50%
                'btc_price_change': -0.25,  # -25%
                'expected_final_capital_approx': 8750000  # 5M 미투자 + 5M * 0.75 * (1-수수료)
            }
        }

    def manual_calculate(self, test_case: Dict) -> Dict:
        """수동 계산

        Args:
            test_case: create_test_case_X()의 반환값

        Returns:
            {
                'manual_btc_bought': 0.9044,
                'manual_final_capital': 32173949,
                'manual_return_pct': 221.74,
                ...
            }
        """
        buy_sig = test_case['buy_signals'][0]
        sell_sig = test_case['sell_signals'][0]

        initial_capital = 10_000_000
        fee_rate = 0.0005
        slippage = 0.0002
        total_fee = fee_rate + slippage  # 0.0007

        # 매수
        invest_amount = initial_capital * buy_sig['position_size']
        buy_price = buy_sig['price']

        # BTC 수량 계산 (수수료 차감)
        btc_bought = (invest_amount * (1 - total_fee)) / buy_price

        # 매도
        sell_price = sell_sig['price']
        proceeds = btc_bought * sell_price * (1 - total_fee)

        # 최종 자본
        uninvested_cash = initial_capital - invest_amount
        final_capital = uninvested_cash + proceeds

        # 수익률
        total_return_pct = (final_capital / initial_capital - 1) * 100

        # 트레이드 수익률 (투자 금액 대비)
        trade_return_pct = (proceeds / invest_amount - 1) * 100

        return {
            'manual_invest_amount': invest_amount,
            'manual_btc_bought': btc_bought,
            'manual_proceeds': proceeds,
            'manual_uninvested_cash': uninvested_cash,
            'manual_final_capital': final_capital,
            'manual_return_pct': total_return_pct,
            'manual_trade_return_pct': trade_return_pct,
            'manual_price_change_pct': (sell_price / buy_price - 1) * 100
        }

    def verify_test_case(self, test_case: Dict) -> bool:
        """테스트 케이스 검증

        Args:
            test_case: create_test_case_X()의 반환값

        Returns:
            True if evaluator matches manual calculation
        """
        print("=" * 80)
        print(f"테스트 케이스: {test_case['version']}")
        print(f"설명: {test_case['expected'].get('description', '')}")
        print("=" * 80)

        # 수동 계산
        manual = self.manual_calculate(test_case)

        print("\n[수동 계산 결과]")
        print(f"투자 금액: {manual['manual_invest_amount']:,.0f}원")
        print(f"매수 BTC: {manual['manual_btc_bought']:.8f} BTC")
        print(f"매도 대금: {manual['manual_proceeds']:,.0f}원")
        print(f"미투자 현금: {manual['manual_uninvested_cash']:,.0f}원")
        print(f"최종 자본: {manual['manual_final_capital']:,.0f}원")
        print(f"총 수익률: {manual['manual_return_pct']:.2f}%")
        print(f"거래 수익률: {manual['manual_trade_return_pct']:.2f}%")
        print(f"가격 변동: {manual['manual_price_change_pct']:.2f}%")

        # 평가 엔진 실행
        print("\n[평가 엔진 실행]")
        result = self.evaluator.evaluate_signals(test_case)

        print(f"최종 자본: {result['final_capital']:,.0f}원")
        print(f"총 수익률: {result['total_return_pct']:.2f}%")
        print(f"거래 수: {result['total_trades']}회")
        print(f"승률: {result['win_rate']*100:.1f}%")

        # 비교
        print("\n[비교 결과]")
        final_capital_diff = abs(result['final_capital'] - manual['manual_final_capital'])
        return_pct_diff = abs(result['total_return_pct'] - manual['manual_return_pct'])

        print(f"최종 자본 차이: {final_capital_diff:,.0f}원")
        print(f"수익률 차이: {return_pct_diff:.4f}%p")

        # 허용 오차: 0.01% (반올림 오차 고려)
        tolerance_capital = manual['manual_final_capital'] * 0.0001  # 0.01%
        tolerance_return = 0.01  # 0.01%p

        if final_capital_diff < tolerance_capital and return_pct_diff < tolerance_return:
            print("\n✅ 검증 성공: 평가 엔진이 수동 계산과 일치합니다!")
            return True
        else:
            print("\n❌ 검증 실패: 평가 엔진 결과가 수동 계산과 다릅니다!")
            print(f"   허용 오차: 자본 {tolerance_capital:,.0f}원, 수익률 {tolerance_return:.2f}%p")
            return False

    def verify_v39_2020(self) -> bool:
        """v39 2020년 실제 거래 검증 (핵심 검증)"""
        test_case = self.create_test_case_1()
        return self.verify_test_case(test_case)

    def run_all_tests(self) -> bool:
        """모든 테스트 케이스 실행"""
        print("\n" + "="*80)
        print("평가 엔진 수동 검증 시작")
        print("="*80 + "\n")

        test_cases = [
            self.create_test_case_1(),  # v39 2020년
            self.create_test_case_2(),  # 2배 수익
            self.create_test_case_3(),  # 손실 케이스
        ]

        results = []
        for test_case in test_cases:
            result = self.verify_test_case(test_case)
            results.append(result)
            print("\n")

        # 최종 결과
        print("="*80)
        print("최종 검증 결과")
        print("="*80)

        total = len(results)
        passed = sum(results)

        print(f"총 테스트: {total}개")
        print(f"통과: {passed}개")
        print(f"실패: {total - passed}개")

        if all(results):
            print("\n✅✅✅ 모든 테스트 통과! 평가 엔진이 정상 작동합니다.")
            print("     이제 Phase 2 (전략별 시그널 추출)를 진행할 수 있습니다.")
            return True
        else:
            print("\n❌❌❌ 일부 테스트 실패! 평가 엔진을 수정해야 합니다.")
            print("     Phase 2로 진행하기 전에 평가 엔진을 먼저 수정하세요.")
            return False


if __name__ == "__main__":
    verifier = ManualVerifier()
    success = verifier.run_all_tests()

    # 결과 저장
    result_file = Path(__file__).parent / "verification_result.json"
    with open(result_file, 'w', encoding='utf-8') as f:
        json.dump({
            'all_tests_passed': success,
            'verification_date': __import__('datetime').datetime.now().isoformat(),
            'note': '평가 엔진 검증 완료' if success else '평가 엔진 수정 필요'
        }, f, indent=2)

    print(f"\n검증 결과 저장: {result_file}")

    sys.exit(0 if success else 1)
