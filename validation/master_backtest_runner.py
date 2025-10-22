#!/usr/bin/env python3
"""
Master Backtest Runner
======================
51개 전략 × 6년(2020-2025) = 306 backtests 자동 실행

전략:
1. 각 전략의 backtest.py를 발견
2. 연도별로 실행 (2020, 2021, 2022, 2023, 2024, 2025)
3. 결과를 표준 JSON 형식으로 저장
4. 실패 시 재시도 및 로깅
"""

import os
import sys
import json
import subprocess
import time
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

class MasterBacktestRunner:
    """마스터 백테스트 러너"""

    def __init__(self, base_dir: str = "strategies"):
        self.base_dir = Path(base_dir)
        self.validation_dir = Path("validation/results")
        self.validation_dir.mkdir(parents=True, exist_ok=True)

        # 로그 파일
        self.log_file = Path("validation/master_backtest_log.txt")
        self.progress_file = Path("validation/progress.json")

        # 진행 상황 추적
        self.progress = self._load_progress()

        # 타임아웃 (초)
        self.timeout = 600  # 10분

    def _load_progress(self) -> Dict:
        """진행 상황 로드"""
        if self.progress_file.exists():
            with open(self.progress_file) as f:
                return json.load(f)
        return {
            "completed": [],
            "failed": [],
            "skipped": [],
            "total": 0,
            "started_at": datetime.now().isoformat()
        }

    def _save_progress(self):
        """진행 상황 저장"""
        with open(self.progress_file, 'w') as f:
            json.dump(self.progress, f, indent=2)

    def _log(self, message: str):
        """로그 기록"""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_message = f"[{timestamp}] {message}\n"

        print(log_message.strip())

        with open(self.log_file, 'a') as f:
            f.write(log_message)

    def discover_strategies(self) -> List[Dict]:
        """전략 폴더 발견 및 메타데이터 수집"""
        strategies = []

        for folder in sorted(self.base_dir.glob("v*")):
            if not folder.is_dir():
                continue

            # 전략 이름 추출
            strategy_name = folder.name

            # backtest.py 찾기
            backtest_files = list(folder.glob("backtest*.py"))

            if not backtest_files:
                self._log(f"⚠️  {strategy_name}: No backtest.py found")
                continue

            # 메인 backtest.py 우선 선택
            backtest_file = None
            for bf in backtest_files:
                if bf.name == "backtest.py":
                    backtest_file = bf
                    break

            if not backtest_file:
                backtest_file = backtest_files[0]

            # config.json 확인
            config_file = folder / "config.json"
            timeframe = "unknown"

            if config_file.exists():
                try:
                    with open(config_file) as f:
                        config = json.load(f)
                        timeframe = config.get("timeframe", "unknown")
                except:
                    pass

            strategies.append({
                "name": strategy_name,
                "folder": str(folder),
                "backtest_script": str(backtest_file),
                "timeframe": timeframe
            })

        self._log(f"✅ Discovered {len(strategies)} strategies with backtest.py")
        return strategies

    def run_single_backtest(
        self,
        strategy: Dict,
        year: int
    ) -> Optional[Dict]:
        """단일 백테스트 실행"""

        strategy_name = strategy['name']
        backtest_script = strategy['backtest_script']

        # 이미 완료된 항목 확인
        task_id = f"{strategy_name}_{year}"
        if task_id in self.progress['completed']:
            self._log(f"⏭️  {task_id}: Already completed")
            return None

        self._log(f"🚀 Running: {task_id}")

        try:
            # backtest.py 실행 (연도 인자 전달)
            # 대부분의 backtest.py는 sys.argv[1]로 연도 받음
            cmd = [
                sys.executable,
                backtest_script,
                str(year)
            ]

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout,
                cwd=os.path.dirname(backtest_script)
            )

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
            result_file = self._find_result_file(strategy, year)

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

            self._log(f"✅ {task_id}: Success (return: {standardized['total_return_pct']:.2f}%)")

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
            return None

        except Exception as e:
            self._log(f"❌ {task_id}: Exception: {str(e)}")
            self.progress['failed'].append({
                "task": task_id,
                "error": str(e),
                "timestamp": datetime.now().isoformat()
            })
            self._save_progress()
            return None

    def _find_result_file(self, strategy: Dict, year: int) -> Optional[Path]:
        """결과 파일 찾기"""
        folder = Path(strategy['folder'])
        timeframe = strategy['timeframe']

        # 가능한 파일명 패턴
        patterns = [
            f"results_{year}.json",
            f"result_{year}.json",
            f"results_{timeframe}_{year}.json",
            f"result_{timeframe}_{year}.json",
            "results.json",  # 최신 결과 (연도 없음)
        ]

        for pattern in patterns:
            result_file = folder / pattern
            if result_file.exists():
                # 파일이 최근 생성되었는지 확인 (1분 이내)
                mtime = result_file.stat().st_mtime
                if time.time() - mtime < 60:
                    return result_file

        # results/ 폴더도 확인
        results_folder = folder / "results"
        if results_folder.exists():
            for pattern in patterns:
                result_file = results_folder / pattern
                if result_file.exists():
                    mtime = result_file.stat().st_mtime
                    if time.time() - mtime < 60:
                        return result_file

        return None

    def _standardize_result(
        self,
        strategy_name: str,
        year: int,
        raw_data: Dict
    ) -> Dict:
        """결과를 표준 형식으로 변환"""

        # 다양한 키 형식 지원
        total_return = raw_data.get('total_return_pct') or \
                      raw_data.get('total_return') or \
                      raw_data.get('return_pct') or 0.0

        total_trades = raw_data.get('total_trades') or \
                      raw_data.get('num_trades') or \
                      raw_data.get('trades') or 0

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
            "raw_data": raw_data,  # 원본 데이터 보존
            "timestamp": datetime.now().isoformat()
        }

    def run_all(self, years: List[int] = [2020, 2021, 2022, 2023, 2024, 2025]):
        """모든 전략 × 모든 연도 실행"""

        self._log("=" * 60)
        self._log("MASTER BACKTEST RUNNER STARTED")
        self._log("=" * 60)

        # 전략 발견
        strategies = self.discover_strategies()
        total_tasks = len(strategies) * len(years)

        self.progress['total'] = total_tasks
        self._save_progress()

        self._log(f"📋 Total: {len(strategies)} strategies × {len(years)} years = {total_tasks} backtests")
        self._log("")

        # 실행
        for i, strategy in enumerate(strategies, 1):
            self._log(f"\n{'='*60}")
            self._log(f"[{i}/{len(strategies)}] Processing: {strategy['name']}")
            self._log(f"{'='*60}")

            for year in years:
                self.run_single_backtest(strategy, year)

                # 진행률 표시
                completed = len(self.progress['completed'])
                failed = len(self.progress['failed'])
                progress_pct = (completed + failed) / total_tasks * 100

                self._log(f"📊 Progress: {completed} completed, {failed} failed ({progress_pct:.1f}%)")

        # 최종 요약
        self._log("\n" + "=" * 60)
        self._log("MASTER BACKTEST RUNNER COMPLETED")
        self._log("=" * 60)
        self._log(f"✅ Completed: {len(self.progress['completed'])}")
        self._log(f"❌ Failed: {len(self.progress['failed'])}")
        self._log(f"⏭️  Skipped: {len(self.progress['skipped'])}")
        self._log(f"📊 Total: {total_tasks}")

        # 실패 목록 출력
        if self.progress['failed']:
            self._log("\n❌ Failed tasks:")
            for failed in self.progress['failed']:
                self._log(f"  - {failed['task']}: {failed['error'][:100]}")


def main():
    """메인 함수"""
    runner = MasterBacktestRunner()
    runner.run_all()


if __name__ == "__main__":
    main()
