#!/usr/bin/env python3
"""
walk_forward_validation.py

Walk-Forward 검증 시스템
- 시간 분할 검증으로 오버피팅 방지
- 학습 기간과 검증 기간을 슬라이딩 윈도우로 이동
- Out-of-sample 성과 검증
"""

import sys
sys.path.append('..')

import json
import argparse
from pathlib import Path
from datetime import datetime, timedelta
from typing import List, Dict
import pandas as pd

from core.data_loader import DataLoader
from core.backtester import Backtester
from core.evaluator import Evaluator


class WalkForwardValidator:
    """Walk-Forward 검증기"""

    def __init__(self, strategy_path: str, train_months: int = 6, test_months: int = 1):
        """
        Args:
            strategy_path: 전략 디렉토리 경로
            train_months: 학습 기간 (개월)
            test_months: 검증 기간 (개월)
        """
        self.strategy_path = Path(strategy_path)
        self.train_months = train_months
        self.test_months = test_months

        # Config 로드
        config_path = self.strategy_path / 'config.json'
        with open(config_path) as f:
            self.config = json.load(f)

        self.db_path = Path('upbit_bitcoin.db')

        # 결과 저장
        self.results = []

    def generate_periods(self, start_date: str, end_date: str) -> List[Dict]:
        """
        Walk-Forward 기간 생성

        예: train=6개월, test=1개월
        - Period 1: 2024-01-01~06-30 (학습) → 2024-07-01~07-31 (검증)
        - Period 2: 2024-02-01~07-31 (학습) → 2024-08-01~08-31 (검증)
        ...
        """
        periods = []

        start = pd.Timestamp(start_date)
        end = pd.Timestamp(end_date)

        current_train_start = start

        while True:
            # 학습 기간 종료
            train_end = current_train_start + pd.DateOffset(months=self.train_months)

            # 검증 기간
            test_start = train_end + pd.DateOffset(days=1)
            test_end = test_start + pd.DateOffset(months=self.test_months)

            # 검증 종료가 전체 종료를 넘으면 중단
            if test_end > end:
                break

            periods.append({
                'train_start': current_train_start.strftime('%Y-%m-%d'),
                'train_end': train_end.strftime('%Y-%m-%d'),
                'test_start': test_start.strftime('%Y-%m-%d'),
                'test_end': test_end.strftime('%Y-%m-%d')
            })

            # 다음 기간 (1개월 이동)
            current_train_start += pd.DateOffset(months=1)

        return periods

    def run_backtest(self, start_date: str, end_date: str) -> Dict:
        """백테스팅 실행"""
        # 전략 로드
        strategy_module = __import__(
            f"strategies.{self.strategy_path.name}.strategy",
            fromlist=['']
        )

        # 데이터 로드
        with DataLoader(str(self.db_path)) as loader:
            df = loader.load_timeframe(
                self.config['timeframe'],
                start_date=start_date,
                end_date=end_date
            )

        # 백테스팅
        backtester = Backtester(
            initial_capital=self.config['initial_capital'],
            fee_rate=self.config['fee_rate'],
            slippage=self.config['slippage']
        )

        # 전략 함수 찾기
        strategy_func = None
        for attr in dir(strategy_module):
            if 'strategy' in attr.lower() and callable(getattr(strategy_module, attr)):
                strategy_func = getattr(strategy_module, attr)
                break

        if not strategy_func:
            raise ValueError(f"전략 함수를 찾을 수 없습니다")

        results = backtester.run(df, strategy_func, self.config)

        # 평가
        metrics = Evaluator.calculate_all_metrics(results)

        return metrics

    def validate(self, start_date: str = '2024-01-01', end_date: str = '2024-12-30'):
        """Walk-Forward 검증 실행"""
        print(f"\n{'='*70}")
        print(f"Walk-Forward 검증 시작")
        print(f"{'='*70}")
        print(f"전략: {self.strategy_path.name}")
        print(f"학습 기간: {self.train_months}개월")
        print(f"검증 기간: {self.test_months}개월")
        print(f"{'='*70}\n")

        # 기간 생성
        periods = self.generate_periods(start_date, end_date)
        print(f"총 {len(periods)}개 기간 검증\n")

        # 각 기간 검증
        for i, period in enumerate(periods, 1):
            print(f"[Period {i}/{len(periods)}]")
            print(f"  학습: {period['train_start']} ~ {period['train_end']}")
            print(f"  검증: {period['test_start']} ~ {period['test_end']}")

            try:
                # 학습 기간 성과 (In-Sample)
                train_metrics = self.run_backtest(
                    period['train_start'],
                    period['train_end']
                )

                # 검증 기간 성과 (Out-of-Sample)
                test_metrics = self.run_backtest(
                    period['test_start'],
                    period['test_end']
                )

                # 결과 저장
                result = {
                    'period': i,
                    'train': {
                        'start': period['train_start'],
                        'end': period['train_end'],
                        'return': train_metrics['total_return'],
                        'sharpe': train_metrics['sharpe_ratio'],
                        'mdd': train_metrics['max_drawdown'],
                        'trades': train_metrics['total_trades']
                    },
                    'test': {
                        'start': period['test_start'],
                        'end': period['test_end'],
                        'return': test_metrics['total_return'],
                        'sharpe': test_metrics['sharpe_ratio'],
                        'mdd': test_metrics['max_drawdown'],
                        'trades': test_metrics['total_trades']
                    },
                    'degradation': {
                        'return': test_metrics['total_return'] - train_metrics['total_return'],
                        'sharpe': test_metrics['sharpe_ratio'] - train_metrics['sharpe_ratio']
                    }
                }

                self.results.append(result)

                print(f"    학습 수익률: {train_metrics['total_return']:>7.2f}% | Sharpe: {train_metrics['sharpe_ratio']:>6.3f}")
                print(f"    검증 수익률: {test_metrics['total_return']:>7.2f}% | Sharpe: {test_metrics['sharpe_ratio']:>6.3f}")
                print(f"    성능 저하:   {result['degradation']['return']:>7.2f}%p | Sharpe: {result['degradation']['sharpe']:>6.3f}")
                print()

            except Exception as e:
                print(f"    ✗ 오류: {e}\n")
                continue

        # 분석 및 리포트 생성
        self.analyze_results()
        self.save_report()

    def analyze_results(self):
        """결과 분석"""
        if not self.results:
            print("결과 없음")
            return

        # 통계 계산
        train_returns = [r['train']['return'] for r in self.results]
        test_returns = [r['test']['return'] for r in self.results]
        degradations = [r['degradation']['return'] for r in self.results]

        print(f"\n{'='*70}")
        print(f"Walk-Forward 검증 결과 분석")
        print(f"{'='*70}")
        print(f"\n학습 기간 (In-Sample):")
        print(f"  평균 수익률: {sum(train_returns)/len(train_returns):.2f}%")
        print(f"  최고: {max(train_returns):.2f}% | 최저: {min(train_returns):.2f}%")

        print(f"\n검증 기간 (Out-of-Sample):")
        print(f"  평균 수익률: {sum(test_returns)/len(test_returns):.2f}%")
        print(f"  최고: {max(test_returns):.2f}% | 최저: {min(test_returns):.2f}%")

        print(f"\n성능 저하:")
        print(f"  평균: {sum(degradations)/len(degradations):.2f}%p")
        print(f"  최대: {max(degradations):.2f}%p | 최소: {min(degradations):.2f}%p")

        # 오버피팅 판정
        avg_degradation = sum(degradations) / len(degradations)
        if avg_degradation < -20:
            print(f"\n⚠️  심각한 오버피팅 감지 (평균 {avg_degradation:.2f}%p 저하)")
        elif avg_degradation < -10:
            print(f"\n⚠️  오버피팅 의심 (평균 {avg_degradation:.2f}%p 저하)")
        else:
            print(f"\n✅ 오버피팅 없음 (평균 {avg_degradation:.2f}%p 저하)")

        print(f"{'='*70}\n")

    def save_report(self):
        """리포트 저장"""
        timestamp = datetime.now().strftime('%y%m%d_%H%M%S')
        report_path = self.strategy_path / f'walk_forward_report_{timestamp}.md'

        with open(report_path, 'w') as f:
            f.write(f"# Walk-Forward 검증 리포트\n\n")
            f.write(f"**전략**: {self.strategy_path.name}\n")
            f.write(f"**시간**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**학습 기간**: {self.train_months}개월\n")
            f.write(f"**검증 기간**: {self.test_months}개월\n")
            f.write(f"**검증 횟수**: {len(self.results)}\n\n")

            f.write(f"## 기간별 결과\n\n")
            f.write(f"| Period | 학습 수익률 | 검증 수익률 | 저하 |\n")
            f.write(f"|--------|------------|------------|------|\n")

            for r in self.results:
                f.write(f"| {r['period']} | ")
                f.write(f"{r['train']['return']:.2f}% | ")
                f.write(f"{r['test']['return']:.2f}% | ")
                f.write(f"{r['degradation']['return']:+.2f}%p |\n")

            # 통계
            if self.results:
                train_returns = [r['train']['return'] for r in self.results]
                test_returns = [r['test']['return'] for r in self.results]
                degradations = [r['degradation']['return'] for r in self.results]

                f.write(f"\n## 통계\n\n")
                f.write(f"### 학습 기간 (In-Sample)\n")
                f.write(f"- 평균: {sum(train_returns)/len(train_returns):.2f}%\n")
                f.write(f"- 최고: {max(train_returns):.2f}%\n")
                f.write(f"- 최저: {min(train_returns):.2f}%\n\n")

                f.write(f"### 검증 기간 (Out-of-Sample)\n")
                f.write(f"- 평균: {sum(test_returns)/len(test_returns):.2f}%\n")
                f.write(f"- 최고: {max(test_returns):.2f}%\n")
                f.write(f"- 최저: {min(test_returns):.2f}%\n\n")

                f.write(f"### 성능 저하\n")
                avg_deg = sum(degradations) / len(degradations)
                f.write(f"- 평균: {avg_deg:.2f}%p\n")
                f.write(f"- 최대: {max(degradations):.2f}%p\n")
                f.write(f"- 최소: {min(degradations):.2f}%p\n\n")

                f.write(f"## 평가\n\n")
                if avg_deg < -20:
                    f.write(f"⚠️ **심각한 오버피팅** (평균 {avg_deg:.2f}%p 저하)\n")
                    f.write(f"- 전략 재설계 권장\n")
                elif avg_deg < -10:
                    f.write(f"⚠️ **오버피팅 의심** (평균 {avg_deg:.2f}%p 저하)\n")
                    f.write(f"- 파라미터 단순화 또는 정규화 고려\n")
                else:
                    f.write(f"✅ **검증 통과** (평균 {avg_deg:.2f}%p 저하)\n")
                    f.write(f"- 실전 적용 가능\n")

        print(f"✓ Walk-Forward 리포트 저장: {report_path}")


def main():
    """메인 실행"""
    parser = argparse.ArgumentParser(description='Walk-Forward 검증')
    parser.add_argument('--strategy', required=True, help='전략 디렉토리')
    parser.add_argument('--train-months', type=int, default=6, help='학습 기간 (개월)')
    parser.add_argument('--test-months', type=int, default=1, help='검증 기간 (개월)')
    parser.add_argument('--start-date', default='2024-01-01', help='시작 날짜')
    parser.add_argument('--end-date', default='2024-12-30', help='종료 날짜')

    args = parser.parse_args()

    # 검증기 생성
    validator = WalkForwardValidator(
        strategy_path=args.strategy,
        train_months=args.train_months,
        test_months=args.test_months
    )

    # 검증 실행
    validator.validate(
        start_date=args.start_date,
        end_date=args.end_date
    )


if __name__ == '__main__':
    main()
