#!/usr/bin/env python3
"""
test_algorithm.py
알고리즘 독립 테스트 자동화 프레임워크

목적:
  - 모든 알고리즘을 표준화된 방식으로 테스트
  - 합격 기준 자동 판정
  - 결과 JSON 저장 및 리포트 생성

사용법:
    tester = AlgorithmTester('bollinger_bounce')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={'window': 20, 'std': 2.0}
    )
"""

import sys
sys.path.append('..')

import json
from decimal import Decimal
from datetime import datetime
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer


class AlgorithmTester:
    """
    알고리즘 독립 테스트 자동화 클래스
    """

    def __init__(self, algorithm_name, algorithm_class=None):
        """
        Args:
            algorithm_name: 알고리즘 이름 (예: 'bollinger_bounce')
            algorithm_class: 알고리즘 클래스 (옵션, 동적 import 가능)
        """
        self.algorithm_name = algorithm_name
        self.algorithm_class = algorithm_class

        # 기본 합격 기준
        self.pass_criteria = {
            'min_signals': 5,
            'min_win_rate': 55.0,
            'min_avg_profit': 8.0
        }

    def run(self, timeframe='day', period='2024-01-01:2024-12-31',
            params=None, trailing_stop=0.20, stop_loss=0.10):
        """
        알고리즘 독립 테스트 실행

        Args:
            timeframe: 타임프레임 ('day', 'minute5', etc.)
            period: 테스트 기간 ('YYYY-MM-DD:YYYY-MM-DD')
            params: 알고리즘 파라미터 dict
            trailing_stop: Trailing Stop % (기본 20%)
            stop_loss: Stop Loss % (기본 10%)

        Returns:
            dict: 테스트 결과
        """
        start_date, end_date = period.split(':')

        print("=" * 80)
        print(f"{self.algorithm_name.upper()} 알고리즘 독립 테스트")
        print("=" * 80)
        print(f"\n테스트 기간: {start_date} ~ {end_date} ({timeframe})")
        if params:
            print(f"파라미터: {params}")

        # 데이터 로드
        with DataLoader('upbit_bitcoin.db') as loader:
            df = loader.load_timeframe(timeframe, start_date=start_date, end_date=end_date)

        print(f"데이터: {len(df)}개 캔들")

        # 신호 생성 (알고리즘별 구현 필요)
        signals = self._generate_signals(df, params)

        print(f"\n발견된 신호: {len(signals)}개")

        if len(signals) == 0:
            return self._create_result(signals=[], trades=[], passed=False,
                                        fail_reason="No signals generated")

        # 간이 백테스팅
        trades = self._backtest_signals(df, signals, trailing_stop, stop_loss)

        # 성과 분석
        metrics = self._calculate_metrics(trades)

        # 합격 판정
        passed, reasons = self._judge_pass(len(signals), metrics)

        # 결과 생성
        result = self._create_result(
            signals=signals,
            trades=trades,
            metrics=metrics,
            passed=passed,
            pass_reasons=reasons
        )

        # 결과 출력
        self._print_result(result)

        # JSON 저장
        self._save_result(result)

        return result

    def _generate_signals(self, df, params):
        """
        알고리즘별 신호 생성

        하위 클래스에서 오버라이드 또는
        algorithm_class 사용

        Args:
            df: DataFrame
            params: 파라미터 dict

        Returns:
            list of signals
        """
        if self.algorithm_class:
            algo = self.algorithm_class(**params) if params else self.algorithm_class()
            return algo.generate_signals(df)
        else:
            raise NotImplementedError(f"{self.algorithm_name}: _generate_signals not implemented")

    def _backtest_signals(self, df, signals, trailing_stop, stop_loss):
        """
        신호를 기반으로 간이 백테스팅

        Args:
            df: DataFrame
            signals: 신호 리스트
            trailing_stop: Trailing Stop %
            stop_loss: Stop Loss %

        Returns:
            list of trades
        """
        trades = []

        for sig in signals:
            if sig['signal'] != 'BUY':
                continue

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
                is_trailing_stop = drop_from_high >= trailing_stop
                is_stop_loss = pnl_ratio <= -stop_loss

                if is_trailing_stop or is_stop_loss:
                    trades.append({
                        'entry_date': sig['timestamp'] if 'timestamp' in sig else f"idx_{entry_idx}",
                        'entry_price': entry_price,
                        'exit_date': df.iloc[i]['timestamp'] if 'timestamp' in df.columns else f"idx_{i}",
                        'exit_price': curr_price,
                        'pnl_pct': pnl_ratio * 100,
                        'reason': 'TRAILING_STOP' if is_trailing_stop else 'STOP_LOSS',
                        'holding_days': i - entry_idx,
                        'highest_price': highest_price
                    })
                    break
            else:
                # 연말까지 보유
                final_price = df.iloc[-1]['close']
                pnl_ratio = (final_price - entry_price) / entry_price
                trades.append({
                    'entry_date': sig['timestamp'] if 'timestamp' in sig else f"idx_{entry_idx}",
                    'entry_price': entry_price,
                    'exit_date': df.iloc[-1]['timestamp'] if 'timestamp' in df.columns else f"idx_{len(df)-1}",
                    'exit_price': final_price,
                    'pnl_pct': pnl_ratio * 100,
                    'reason': 'FINAL_EXIT',
                    'holding_days': len(df) - 1 - entry_idx,
                    'highest_price': highest_price
                })

        return trades

    def _calculate_metrics(self, trades):
        """
        거래 성과 지표 계산

        Args:
            trades: 거래 리스트

        Returns:
            dict: 성과 지표
        """
        if not trades:
            return {
                'total_trades': 0,
                'wins': 0,
                'losses': 0,
                'win_rate': 0.0,
                'avg_profit': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0,
                'max_win': 0.0,
                'max_loss': 0.0,
                'avg_holding_days': 0.0
            }

        wins = [t for t in trades if t['pnl_pct'] > 0]
        losses = [t for t in trades if t['pnl_pct'] <= 0]

        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': (len(wins) / len(trades)) * 100 if trades else 0.0,
            'avg_profit': sum([t['pnl_pct'] for t in trades]) / len(trades) if trades else 0.0,
            'avg_win': sum([t['pnl_pct'] for t in wins]) / len(wins) if wins else 0.0,
            'avg_loss': sum([t['pnl_pct'] for t in losses]) / len(losses) if losses else 0.0,
            'max_win': max([t['pnl_pct'] for t in trades]) if trades else 0.0,
            'max_loss': min([t['pnl_pct'] for t in trades]) if trades else 0.0,
            'avg_holding_days': sum([t['holding_days'] for t in trades]) / len(trades) if trades else 0.0
        }

    def _judge_pass(self, num_signals, metrics):
        """
        합격 여부 판정

        Args:
            num_signals: 신호 개수
            metrics: 성과 지표

        Returns:
            (bool, dict): (합격 여부, 세부 판정)
        """
        reasons = {
            '시그널 개수 >= 5': num_signals >= self.pass_criteria['min_signals'],
            f'승률 >= {self.pass_criteria["min_win_rate"]}%': metrics['win_rate'] >= self.pass_criteria['min_win_rate'],
            f'평균 수익 > {self.pass_criteria["min_avg_profit"]}%': metrics['avg_profit'] > self.pass_criteria['min_avg_profit']
        }

        passed = all(reasons.values())

        return passed, reasons

    def _create_result(self, signals, trades, metrics=None, passed=False,
                       pass_reasons=None, fail_reason=None):
        """
        결과 dict 생성

        Args:
            signals: 신호 리스트
            trades: 거래 리스트
            metrics: 성과 지표
            passed: 합격 여부
            pass_reasons: 합격 판정 이유
            fail_reason: 실패 이유

        Returns:
            dict: 테스트 결과
        """
        result = {
            'algorithm': self.algorithm_name,
            'timestamp': datetime.now().isoformat(),
            'signals': len(signals),
            'trades': len(trades),
            'passed': passed
        }

        if metrics:
            result['metrics'] = metrics

        if pass_reasons:
            result['criteria'] = pass_reasons

        if fail_reason:
            result['fail_reason'] = fail_reason

        # 샘플 거래 (최대 5개)
        if trades:
            result['sample_trades'] = trades[:5]

        return result

    def _print_result(self, result):
        """
        결과 출력

        Args:
            result: 테스트 결과 dict
        """
        print("\n" + "=" * 80)
        print("테스트 결과")
        print("=" * 80)

        metrics = result.get('metrics', {})

        print(f"\n총 신호: {result['signals']}개")
        print(f"총 거래: {result['trades']}회")

        if metrics:
            print(f"  승리: {metrics['wins']}회 ({metrics['win_rate']:.1f}%)")
            print(f"  손실: {metrics['losses']}회")
            print(f"\n평균 수익: {metrics['avg_profit']:+.2f}%")
            print(f"  승리 거래 평균: {metrics['avg_win']:+.2f}%")
            print(f"  손실 거래 평균: {metrics['avg_loss']:+.2f}%")
            print(f"  최대 승리: {metrics['max_win']:+.2f}%")
            print(f"  최대 손실: {metrics['max_loss']:+.2f}%")
            print(f"\n평균 보유 기간: {metrics['avg_holding_days']:.1f}일")

        # 합격 판정
        print("\n" + "=" * 80)
        print("합격 기준 검증")
        print("=" * 80)

        if 'criteria' in result:
            for criterion, passed in result['criteria'].items():
                status = "✅ PASS" if passed else "❌ FAIL"
                print(f"  {criterion}: {status}")

        status_emoji = "✅ 합격" if result['passed'] else "❌ 불합격"
        print(f"\n종합 판정: {status_emoji}")

        if not result['passed'] and 'fail_reason' in result:
            print(f"  실패 이유: {result['fail_reason']}")

    def _save_result(self, result):
        """
        결과를 JSON 파일로 저장

        Args:
            result: 테스트 결과 dict
        """
        filename = f"test_{self.algorithm_name}_result.json"

        with open(filename, 'w') as f:
            json.dump(result, f, indent=2, default=str)

        print(f"\n결과가 {filename}에 저장되었습니다.")
        print("=" * 80)


# 사용 예시
if __name__ == '__main__':
    # Bollinger Bands 테스트
    from strategies._library.volatility.bollinger_bands import BollingerBands

    class BollingerBounceTester(AlgorithmTester):
        def _generate_signals(self, df, params):
            bb = BollingerBands(**(params or {}))
            return bb.generate_signals(df, strategy='bounce')

    tester = BollingerBounceTester('bollinger_bounce')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={'window': 20, 'num_std': 2.0},
        trailing_stop=0.20,
        stop_loss=0.10
    )

    print(f"\n최종 결과: {'합격' if result['passed'] else '불합격'}")
