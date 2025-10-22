#!/usr/bin/env python3
"""
Tier 1 Group A Runner
=====================
기존 backtest.py가 있는 18개 전략을 연도별로 자동 실행

대상 전략:
- v01, v02a, v02b, v02c, v03, v04, v07, v08
- v11, v13, v14, v15, v16, v17, v18, v19, v20, v21

작성일: 2025-10-20
"""

import os
import sys
import json
import subprocess
import importlib.util
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime


class Tier1GroupARunner:
    """Tier 1 Group A 전략 자동 실행기"""

    def __init__(self, project_root: Path):
        self.project_root = project_root
        self.strategies_dir = project_root / 'strategies'
        self.validation_dir = project_root / 'validation'
        self.results_dir = self.validation_dir / 'results'
        self.results_dir.mkdir(parents=True, exist_ok=True)

        # Tier 1 Group A 전략 목록
        self.strategies = [
            'v01_adaptive_rsi_ml',
            'v02a_dynamic_kelly',
            'v02b_split_exit',
            'v02c_volatility_adjusted',
            'v03_bull_trend_hold',
            'v04_adaptive_trend_rider',
            'v07_enhanced_day',
            'v08_market_adaptive',
            'v11_multi_entry_ensemble',
            'v13_voting_ensemble',
            'v14_high_confidence',
            'v15_adaptive',
            'v16_improved_voting',
            'v17_vwap_breakout',
            'v18_vwap_only',
            'v19_market_adaptive_hybrid',
            'v20_simplified_adaptive',
            'v21_perfect_timing_day'
        ]

        self.years = [2020, 2021, 2022, 2023, 2024, 2025]

    def find_backtest_script(self, strategy_name: str) -> Optional[Path]:
        """백테스팅 스크립트 찾기"""
        strategy_path = self.strategies_dir / strategy_name

        # backtest.py 직접 찾기
        backtest_py = strategy_path / 'backtest.py'
        if backtest_py.exists():
            return backtest_py

        # backtest/ 폴더 내 스크립트 찾기
        backtest_dir = strategy_path / 'backtest'
        if backtest_dir.exists():
            # 일반적인 이름들
            candidates = [
                'backtest.py',
                'run_backtest.py',
                'main.py',
                f'{strategy_name}_backtest.py'
            ]

            for candidate in candidates:
                script = backtest_dir / candidate
                if script.exists():
                    return script

            # 첫 번째 .py 파일 사용
            py_files = list(backtest_dir.glob('*.py'))
            if py_files:
                return py_files[0]

        return None

    def run_strategy_year(
        self,
        strategy_name: str,
        year: int
    ) -> Optional[Dict]:
        """
        단일 전략의 특정 연도 백테스팅 실행

        Returns:
            결과 딕셔너리 또는 None (실패 시)
        """
        print(f"\n[{strategy_name}] {year}년 백테스팅...")

        # 백테스팅 스크립트 찾기
        backtest_script = self.find_backtest_script(strategy_name)

        if not backtest_script:
            print(f"  ❌ 백테스팅 스크립트를 찾을 수 없습니다")
            return None

        print(f"  Script: {backtest_script.name}")

        # 방법 1: 스크립트를 직접 import하여 실행
        result = self._run_by_import(strategy_name, backtest_script, year)

        if result is None:
            # 방법 2: subprocess로 실행 (fallback)
            result = self._run_by_subprocess(strategy_name, backtest_script, year)

        if result:
            # 결과 저장
            self._save_result(strategy_name, year, result)
            print(f"  ✅ 완료: {result.get('total_return_pct', 0):.2f}%")
        else:
            print(f"  ❌ 실행 실패")

        return result

    def _run_by_import(
        self,
        strategy_name: str,
        backtest_script: Path,
        year: int
    ) -> Optional[Dict]:
        """Python import를 통한 실행"""
        try:
            # 전략 경로를 sys.path에 추가
            strategy_path = self.strategies_dir / strategy_name
            if str(strategy_path) not in sys.path:
                sys.path.insert(0, str(strategy_path))

            # 모듈 동적 import
            spec = importlib.util.spec_from_file_location(
                f"{strategy_name}_backtest",
                backtest_script
            )
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)

            # 백테스팅 함수 찾기
            # 일반적인 함수 이름들
            func_candidates = [
                'run_backtest',
                'backtest',
                'main',
                'run',
                f'{strategy_name}_backtest'
            ]

            backtest_func = None
            for func_name in func_candidates:
                if hasattr(module, func_name):
                    backtest_func = getattr(module, func_name)
                    break

            if backtest_func is None:
                # main block 실행
                if hasattr(module, '__main__'):
                    # year 파라미터를 환경변수로 전달
                    os.environ['BACKTEST_YEAR'] = str(year)
                    return None  # subprocess로 fallback

            # 함수 실행 (year 파라미터 시도)
            try:
                result = backtest_func(year=year)
                return result
            except TypeError:
                # year 파라미터 없는 경우 환경변수 사용
                os.environ['BACKTEST_YEAR'] = str(year)
                result = backtest_func()
                return result

        except Exception as e:
            print(f"  ⚠️  Import 실행 실패: {e}")
            return None

    def _run_by_subprocess(
        self,
        strategy_name: str,
        backtest_script: Path,
        year: int
    ) -> Optional[Dict]:
        """Subprocess를 통한 실행"""
        try:
            # 환경변수로 year 전달
            env = os.environ.copy()
            env['BACKTEST_YEAR'] = str(year)

            # Python 실행
            result = subprocess.run(
                ['python', str(backtest_script)],
                cwd=backtest_script.parent,
                env=env,
                capture_output=True,
                text=True,
                timeout=600  # 10분 타임아웃
            )

            if result.returncode != 0:
                print(f"  ⚠️  프로세스 실패: {result.stderr[:200]}")
                return None

            # 결과 파일 찾기 (일반적인 위치)
            result_paths = [
                backtest_script.parent / 'results.json',
                backtest_script.parent.parent / 'results.json',
                backtest_script.parent / f'results_{year}.json',
            ]

            for result_path in result_paths:
                if result_path.exists():
                    with open(result_path) as f:
                        return json.load(f)

            print(f"  ⚠️  결과 파일을 찾을 수 없습니다")
            return None

        except subprocess.TimeoutExpired:
            print(f"  ⚠️  타임아웃 (10분 초과)")
            return None
        except Exception as e:
            print(f"  ⚠️  Subprocess 실행 실패: {e}")
            return None

    def _save_result(self, strategy_name: str, year: int, result: Dict):
        """결과 저장"""
        output_path = self.results_dir / f"{strategy_name}_{year}.json"

        with open(output_path, 'w') as f:
            json.dump(result, f, indent=2)

    def run_all(self):
        """모든 전략 × 모든 연도 실행"""
        print("=" * 80)
        print("Tier 1 Group A Runner")
        print("=" * 80)
        print(f"전략 수: {len(self.strategies)}")
        print(f"연도 수: {len(self.years)}")
        print(f"총 백테스팅: {len(self.strategies) * len(self.years)}회")
        print("=" * 80)

        total_success = 0
        total_fail = 0

        for strategy in self.strategies:
            print(f"\n{'=' * 80}")
            print(f"전략: {strategy}")
            print(f"{'=' * 80}")

            for year in self.years:
                result = self.run_strategy_year(strategy, year)

                if result:
                    total_success += 1
                else:
                    total_fail += 1

        print("\n" + "=" * 80)
        print("최종 결과")
        print("=" * 80)
        print(f"성공: {total_success}회")
        print(f"실패: {total_fail}회")
        print(f"성공률: {total_success / (total_success + total_fail) * 100:.1f}%")
        print("=" * 80)


def main():
    project_root = Path(__file__).parent.parent
    runner = Tier1GroupARunner(project_root)
    runner.run_all()


if __name__ == '__main__':
    main()
