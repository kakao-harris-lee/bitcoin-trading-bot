#!/usr/bin/env python3
"""
Re-Evaluate Trades - Standard Compound Engine으로 재평가
==========================================================

목적:
  TradeExtractor로 추출한 signals를 StandardEvaluator로 재평가하여
  원본 백테스트 결과와 비교 검증

Usage:
  python validation/re_evaluate_trades.py v38 2024
"""

import json
import sys
from pathlib import Path
from typing import Dict

# 현재 파일 기준 프로젝트 루트 추가
sys.path.append(str(Path(__file__).parent.parent))

from validation.standard_evaluator import StandardEvaluator


class TradeReEvaluator:
    """거래 내역 재평가"""

    def __init__(self, project_root: Path = None):
        if project_root is None:
            self.root = Path(__file__).parent.parent
        else:
            self.root = Path(project_root)

        self.signals_dir = self.root / "validation" / "signals"
        self.evaluator = StandardEvaluator(
            initial_capital=10_000_000,
            fee_rate=0.0005,
            slippage=0.0002
        )

    def load_signals(self, version: str, year: int) -> Dict:
        """
        시그널 파일 로드

        Args:
            version: 전략 버전 (e.g., "v38")
            year: 연도

        Returns:
            signals 딕셔너리
        """
        signal_file = self.signals_dir / f"{version}_{year}_signals.json"

        if not signal_file.exists():
            raise FileNotFoundError(f"시그널 파일 없음: {signal_file}")

        with open(signal_file, 'r', encoding='utf-8') as f:
            return json.load(f)

    def re_evaluate(self, version: str, year: int) -> Dict:
        """
        재평가 실행

        Args:
            version: 전략 버전
            year: 연도

        Returns:
            {
                'version': 'v38',
                'year': 2024,
                'original': {...},  # 원본 결과
                'reeval': {...},    # 재평가 결과
                'diff': {...}       # 차이
            }
        """
        # 시그널 로드
        signals = self.load_signals(version, year)

        # 재평가
        reeval_result = self.evaluator.evaluate_signals(signals)

        # 원본 결과
        original = {
            'total_return_pct': signals['original_total_return'],
            'sharpe_ratio': signals['original_sharpe'],
            'max_drawdown_pct': signals['original_max_drawdown'],
            'total_trades': signals['original_total_trades'],
            'win_rate': signals['original_win_rate']
        }

        # 차이 계산
        diff = {
            'total_return_diff': reeval_result['total_return_pct'] - original['total_return_pct'],
            'sharpe_diff': reeval_result['sharpe_ratio'] - original['sharpe_ratio'],
            'mdd_diff': reeval_result['max_drawdown_pct'] - original['max_drawdown_pct'],
            'trades_diff': reeval_result['total_trades'] - original['total_trades'],
            'win_rate_diff': reeval_result['win_rate'] - original['win_rate']
        }

        return {
            'version': version,
            'year': year,
            'signal_count': signals['signal_count'],
            'original': original,
            'reeval': reeval_result,
            'diff': diff
        }

    def compare_and_print(self, version: str, year: int):
        """재평가 및 비교 출력"""
        print(f"\n{'='*70}")
        print(f"  {version} {year}년 재평가")
        print(f"{'='*70}\n")

        result = self.re_evaluate(version, year)

        print(f"[원본 백테스트 결과]")
        print(f"  총 수익률: {result['original']['total_return_pct']:>8.2f}%")
        print(f"  Sharpe Ratio: {result['original']['sharpe_ratio']:>8.2f}")
        print(f"  Max Drawdown: {result['original']['max_drawdown_pct']:>8.2f}%")
        print(f"  총 거래: {result['original']['total_trades']:>8d}회")
        print(f"  승률: {result['original']['win_rate']:>8.1f}%")

        print(f"\n[StandardEvaluator 재평가]")
        print(f"  총 수익률: {result['reeval']['total_return_pct']:>8.2f}%")
        print(f"  Sharpe Ratio: {result['reeval']['sharpe_ratio']:>8.2f}")
        print(f"  Max Drawdown: {result['reeval']['max_drawdown_pct']:>8.2f}%")
        print(f"  총 거래: {result['reeval']['total_trades']:>8d}회")
        print(f"  승률: {result['reeval']['win_rate']:>8.1f}%")

        print(f"\n[차이]")
        print(f"  수익률: {result['diff']['total_return_diff']:>+8.2f}%p")
        print(f"  Sharpe: {result['diff']['sharpe_diff']:>+8.2f}")
        print(f"  MDD: {result['diff']['mdd_diff']:>+8.2f}%p")
        print(f"  거래 수: {result['diff']['trades_diff']:>+8d}회")
        print(f"  승률: {result['diff']['win_rate_diff']:>+8.1f}%p")

        # 검증
        is_valid = (
            abs(result['diff']['total_return_diff']) < 0.01 and
            abs(result['diff']['sharpe_diff']) < 0.01 and
            result['diff']['trades_diff'] == 0
        )

        print(f"\n[검증]")
        if is_valid:
            print(f"  ✅ 일치 (허용 오차 ±0.01%)")
        else:
            print(f"  ⚠️  불일치 감지!")
            print(f"     수익률 차이: {abs(result['diff']['total_return_diff']):.4f}%")
            print(f"     Sharpe 차이: {abs(result['diff']['sharpe_diff']):.4f}")

        print(f"\n{'='*70}\n")

        return result

    def batch_re_evaluate(self, version: str) -> Dict:
        """
        버전별 모든 연도 재평가

        Args:
            version: 전략 버전

        Returns:
            {
                '2020': {...},
                '2021': {...},
                ...
            }
        """
        # 해당 버전의 모든 시그널 파일 찾기
        signal_files = sorted(self.signals_dir.glob(f"{version}_*_signals.json"))

        if not signal_files:
            print(f"❌ {version}: 시그널 파일 없음")
            return {}

        results = {}

        print(f"\n{'='*70}")
        print(f"  {version} 전체 연도 재평가 ({len(signal_files)}개 파일)")
        print(f"{'='*70}")

        for signal_file in signal_files:
            # 파일명에서 연도 추출 (v38_2024_signals.json -> 2024)
            year_str = signal_file.stem.split('_')[1]
            year = int(year_str)

            result = self.compare_and_print(version, year)
            results[year] = result

        # 요약
        print(f"\n{'='*70}")
        print(f"  {version} 재평가 요약")
        print(f"{'='*70}\n")

        print(f"{'연도':>6s} | {'원본':>8s} | {'재평가':>8s} | {'차이':>8s} | {'상태':>6s}")
        print(f"{'-'*50}")

        all_valid = True
        for year, result in sorted(results.items()):
            orig = result['original']['total_return_pct']
            reev = result['reeval']['total_return_pct']
            diff = result['diff']['total_return_diff']
            is_valid = abs(diff) < 0.01

            status = "✅" if is_valid else "⚠️"
            all_valid = all_valid and is_valid

            print(f"{year:>6d} | {orig:>7.2f}% | {reev:>7.2f}% | {diff:>+7.3f}%p | {status:>6s}")

        print(f"\n[전체 검증]")
        if all_valid:
            print(f"  ✅ 모든 연도 일치")
        else:
            print(f"  ⚠️  일부 연도 불일치")

        print(f"\n{'='*70}\n")

        return results


if __name__ == '__main__':
    """실행"""

    reeval = TradeReEvaluator()

    # 명령행 인자 처리
    if len(sys.argv) >= 2:
        version = sys.argv[1]

        if len(sys.argv) >= 3:
            # 단일 연도 재평가
            year = int(sys.argv[2])
            reeval.compare_and_print(version, year)
        else:
            # 전체 연도 재평가
            reeval.batch_re_evaluate(version)

    else:
        # 기본: v38 전체 연도
        print("Usage: python re_evaluate_trades.py <version> [year]")
        print("예시: python re_evaluate_trades.py v38")
        print("예시: python re_evaluate_trades.py v38 2024\n")

        print("기본 실행: v38 전체 연도 재평가\n")
        reeval.batch_re_evaluate("v38")
