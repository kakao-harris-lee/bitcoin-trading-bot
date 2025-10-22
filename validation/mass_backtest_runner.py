#!/usr/bin/env python3
"""
Mass Backtest Runner
====================
51개 전략 × 6년 = 306 백테스트 자동 실행

전략:
1. 각 전략의 backtest.py를 분석하여 연도 주입 방법 파악
2. 연도별로 실행 (2020-2025)
3. 결과를 표준 JSON 형식으로 저장
4. 실패 시 재시도 및 상세 로깅
"""

import os
import sys
import json
import subprocess
import time
import shutil
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

class MassBacktestRunner:
    """대규모 백테스트 러너"""

    def __init__(self):
        self.base_dir = Path("strategies")
        self.validation_dir = Path("validation/results")
        self.validation_dir.mkdir(parents=True, exist_ok=True)

        # 로그 파일
        self.log_file = Path("validation/mass_backtest_log.txt")
        self.progress_file = Path("validation/mass_backtest_progress.json")

        # 진행 상황
        self.progress = self._load_progress()

        # 설정
        self.timeout = 600  # 10분
        self.years = [2020, 2021, 2022, 2023, 2024, 2025]

    def _load_progress(self) -> Dict:
        """진행 상황 로드"""
        if self.progress_file.exists():
            with open(self.progress_file) as f:
                return json.load(f)
        return {
            "completed": [],
            "failed": [],
            "skipped": [],
            "started_at": datetime.now().isoformat(),
            "last_updated": datetime.now().isoformat()
        }

    def _save_progress(self):
        """진행 상황 저장"""
        self.progress['last_updated'] = datetime.now().isoformat()
        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)

    def _log(self, message: str):
        """로그 기록"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"

        print(log_message.strip())

        with open(self.log_file, 'a') as f:
            f.write(log_message)

    def _modify_backtest_for_year(self, backtest_file: Path, year: int) -> Optional[Path]:
        """backtest.py를 연도별로 수정 (임시 파일 생성)"""

        try:
            with open(backtest_file) as f:
                content = f.read()

            # 날짜 범위 패턴 찾기 및 교체
            modified = content

            # 패턴 1: start_date = "YYYY-MM-DD"
            import re

            # 시작 날짜
            modified = re.sub(
                r'start_date\s*=\s*["\'](\d{4})-\d{2}-\d{2}["\']',
                f'start_date = "{year}-01-01"',
                modified
            )

            # 종료 날짜
            modified = re.sub(
                r'end_date\s*=\s*["\'](\d{4})-\d{2}-\d{2}["\']',
                f'end_date = "{year+1}-01-01"',
                modified
            )

            # 패턴 2: YYYY-MM-DD 직접 사용
            # (주의: 너무 공격적으로 교체하면 문제 발생 가능)

            # 임시 파일 생성
            temp_file = backtest_file.parent / f"backtest_temp_{year}.py"
            with open(temp_file, 'w') as f:
                f.write(modified)

            return temp_file

        except Exception as e:
            self._log(f"⚠️  Failed to modify {backtest_file}: {e}")
            return None

    def run_single_backtest(
        self,
        strategy_name: str,
        strategy_folder: Path,
        year: int
    ) -> Optional[Dict]:
        """단일 백테스트 실행"""

        task_id = f"{strategy_name}_{year}"

        # 이미 완료된 항목 확인
        if task_id in self.progress['completed']:
            self._log(f"⏭️  {task_id}: Already completed")
            return None

        self._log(f"🚀 Running: {task_id}")

        # backtest.py 찾기
        backtest_file = strategy_folder / "backtest.py"
        if not backtest_file.exists():
            self._log(f"❌ {task_id}: No backtest.py found")
            self.progress['skipped'].append(task_id)
            self._save_progress()
            return None

        try:
            # 백테스트 파일 수정 (연도 주입)
            temp_backtest = self._modify_backtest_for_year(backtest_file, year)

            if not temp_backtest:
                self._log(f"⚠️  {task_id}: Failed to modify backtest.py")
                self.progress['failed'].append({
                    "task": task_id,
                    "error": "Modification failed",
                    "timestamp": datetime.now().isoformat()
                })
                self._save_progress()
                return None

            # 실행
            cmd = [
                sys.executable,
                str(temp_backtest)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=str(strategy_folder)
            )

            # 임시 파일 삭제
            temp_backtest.unlink()

            if result.returncode != 0:
                error_msg = result.stderr[-500:] if result.stderr else "Unknown error"
                self._log(f"❌ {task_id}: Failed with code {result.returncode}")
                self._log(f"   Error: {error_msg}")

                self.progress['failed'].append({
                    "task": task_id,
                    "error": error_msg,
                    "timestamp": datetime.now().isoformat()
                })
                self._save_progress()
                return None

            # 결과 파일 찾기
            result_file = self._find_result_file(strategy_folder, year)

            if not result_file:
                self._log(f"⚠️  {task_id}: No result file found")
                self.progress['failed'].append({
                    "task": task_id,
                    "error": "Result file not found",
                    "timestamp": datetime.now().isoformat()
                })
                self._save_progress()
                return None

            # 결과 읽기
            with open(result_file) as f:
                result_data = json.load(f)

            # 표준 형식으로 변환 및 저장
            standardized = self._standardize_result(
                strategy_name,
                year,
                result_data
            )

            # validation/results/에 저장
            output_file = self.validation_dir / f"{strategy_name}_{year}.json"
            with open(output_file, 'w') as f:
                json.dump(standardized, f, indent=2)

            self._log(f"✅ {task_id}: Success (return: {standardized.get('total_return_pct', 0):.2f}%)")

            self.progress['completed'].append(task_id)
            self._save_progress()

            return standardized

        except subprocess.TimeoutExpired:
            self._log(f"⏱️  {task_id}: Timeout after {self.timeout}s")
            self.progress['failed'].append({
                "task": task_id,
                "error": f"Timeout after {self.timeout}s",
                "timestamp": datetime.now().isoformat()
            })
            self._save_progress()

            # 임시 파일 정리
            if temp_backtest and temp_backtest.exists():
                temp_backtest.unlink()

            return None

        except Exception as e:
            self._log(f"❌ {task_id}: Exception: {str(e)}")
            self.progress['failed'].append({
                "task": task_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            self._save_progress()

            # 임시 파일 정리
            if 'temp_backtest' in locals() and temp_backtest and temp_backtest.exists():
                temp_backtest.unlink()

            return None

    def _find_result_file(self, folder: Path, year: int) -> Optional[Path]:
        """결과 파일 찾기"""

        # 가능한 파일명 패턴
        patterns = [
            f"results_{year}.json",
            f"result_{year}.json",
            "results.json",
            "result.json"
        ]

        for pattern in patterns:
            result_file = folder / pattern
            if result_file.exists():
                # 파일이 최근 생성되었는지 확인 (2분 이내)
                mtime = result_file.stat().st_mtime
                if time.time() - mtime < 120:
                    return result_file

        # results/ 폴더도 확인
        results_folder = folder / "results"
        if results_folder.exists():
            for pattern in patterns:
                result_file = results_folder / pattern
                if result_file.exists():
                    mtime = result_file.stat().st_mtime
                    if time.time() - mtime < 120:
                        return result_file

        return None

    def _standardize_result(
        self,
        strategy_name: str,
        year: int,
        raw_data: Dict
    ) -> Dict:
        """결과를 표준 형식으로 변환"""

        total_return = raw_data.get('total_return_pct') or \
                      raw_data.get('total_return') or \
                      raw_data.get('return_pct') or 0.0

        total_trades = raw_data.get('total_trades') or \
                      raw_data.get('num_trades') or \
                      raw_data.get('trades') or 0

        if isinstance(total_trades, list):
            total_trades = len(total_trades)

        win_rate = raw_data.get('win_rate') or \
                  raw_data.get('win_ratio') or 0.0

        sharpe = raw_data.get('sharpe_ratio') or \
                raw_data.get('sharpe') or 0.0

        max_dd = raw_data.get('max_drawdown') or \
                raw_data.get('mdd') or 0.0

        profit_factor = raw_data.get('profit_factor') or 0.0

        return {
            "strategy": strategy_name,
            "year": year,
            "total_return_pct": float(total_return),
            "total_trades": int(total_trades),
            "win_rate": float(win_rate),
            "sharpe_ratio": float(sharpe),
            "max_drawdown": float(max_dd),
            "profit_factor": float(profit_factor),
            "raw_data": raw_data,
            "timestamp": datetime.now().isoformat()
        }

    def run_all(self, strategy_list: Optional[List[str]] = None):
        """모든 전략 × 모든 연도 실행"""

        self._log("=" * 80)
        self._log("MASS BACKTEST RUNNER STARTED")
        self._log("=" * 80)

        # 전략 목록
        if strategy_list:
            strategy_folders = [self.base_dir / s for s in strategy_list]
        else:
            strategy_folders = sorted([f for f in self.base_dir.glob("v*") if f.is_dir()])

        total_tasks = len(strategy_folders) * len(self.years)

        self._log(f"📋 Total: {len(strategy_folders)} strategies × {len(self.years)} years = {total_tasks} backtests")
        self._log("")

        # 실행
        for i, folder in enumerate(strategy_folders, 1):
            strategy_name = folder.name

            self._log(f"\n{'='*80}")
            self._log(f"[{i}/{len(strategy_folders)}] Processing: {strategy_name}")
            self._log(f"{'='*80}")

            for year in self.years:
                self.run_single_backtest(strategy_name, folder, year)

                # 진행률 표시
                completed = len(self.progress['completed'])
                failed = len(self.progress['failed'])
                skipped = len(self.progress['skipped'])
                progress_pct = (completed + failed + skipped) / total_tasks * 100

                self._log(f"📊 Progress: {completed} completed, {failed} failed, {skipped} skipped ({progress_pct:.1f}%)")

        # 최종 요약
        self._log("\n" + "=" * 80)
        self._log("MASS BACKTEST RUNNER COMPLETED")
        self._log("=" * 80)
        self._log(f"✅ Completed: {len(self.progress['completed'])}")
        self._log(f"❌ Failed: {len(self.progress['failed'])}")
        self._log(f"⏭️  Skipped: {len(self.progress['skipped'])}")
        self._log(f"📊 Total: {total_tasks}")

def main():
    """메인 함수"""
    import argparse

    parser = argparse.ArgumentParser(description='Mass Backtest Runner')
    parser.add_argument('--strategies', nargs='+', help='Specific strategies to run')
    parser.add_argument('--priority', action='store_true', help='Run priority strategies only')

    args = parser.parse_args()

    runner = MassBacktestRunner()

    if args.priority:
        # Phase 4-6 핵심 전략만
        priority_strategies = [
            'v30_perfect_longterm',
            'v31_improved',
            'v31_scalping_with_classifier',
            'v32_aggressive',
            'v32_ensemble',
            'v32_optimized',
            'v33_minute240',
            'v34_supreme',
            'v35_optimized',
            'v36_multi_timeframe',
            'v37_supreme',
            'v38_ensemble',
            'v39_voting',
            'v40_adaptive_voting',
            'v41_scalping_voting'
        ]
        runner.run_all(priority_strategies)
    elif args.strategies:
        runner.run_all(args.strategies)
    else:
        runner.run_all()

if __name__ == "__main__":
    main()
