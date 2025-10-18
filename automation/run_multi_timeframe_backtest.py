#!/usr/bin/env python3
"""
멀티 타임프레임 백테스팅 자동화 도구

모든 전략을 여러 타임프레임에서 자동으로 백테스팅하고 결과를 저장합니다.
"""

import sys
import json
import os
import shutil
import subprocess
from pathlib import Path
from datetime import datetime
from typing import List, Dict


class MultiTimeframeBacktester:
    """멀티 타임프레임 백테스트 실행기"""

    # 백테스팅 기준 (claude.md 규칙 준수)
    TIMEFRAMES = ['minute5', 'minute15', 'minute30', 'minute60', 'minute240', 'day']
    START_DATE = '2024-01-01'
    END_DATE = '2024-12-30'

    def __init__(self, strategies_dir: str = "strategies"):
        self.strategies_dir = Path(strategies_dir)
        self.results_summary = []

    def find_strategies(self) -> List[Path]:
        """전략 디렉토리 찾기 (v로 시작하는 폴더)"""
        strategies = []
        for item in self.strategies_dir.iterdir():
            if item.is_dir() and item.name.startswith('v'):
                # backtest.py와 config.json이 있는지 확인
                if (item / 'backtest.py').exists() and (item / 'config.json').exists():
                    strategies.append(item)
        return sorted(strategies)

    def backup_config(self, strategy_path: Path) -> bool:
        """config.json 백업"""
        config_path = strategy_path / 'config.json'
        backup_path = strategy_path / 'config.json.backup'
        try:
            shutil.copy2(config_path, backup_path)
            return True
        except Exception as e:
            print(f"  ✗ 백업 실패: {e}")
            return False

    def restore_config(self, strategy_path: Path):
        """config.json 복원"""
        config_path = strategy_path / 'config.json'
        backup_path = strategy_path / 'config.json.backup'
        if backup_path.exists():
            shutil.copy2(backup_path, config_path)
            backup_path.unlink()

    def modify_config(self, strategy_path: Path, timeframe: str) -> Dict:
        """config.json을 타임프레임에 맞게 수정"""
        config_path = strategy_path / 'config.json'

        with open(config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)

        # 타임프레임 변경
        original_timeframe = config.get('timeframe', 'unknown')
        config['timeframe'] = timeframe

        # 저장
        with open(config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2, ensure_ascii=False)

        return {'original': original_timeframe, 'modified': timeframe}

    def run_backtest(self, strategy_path: Path, timeframe: str) -> Dict:
        """단일 백테스트 실행"""
        backtest_script = 'backtest.py'  # 상대 경로로 변경

        try:
            # 백테스트 실행 (현재 디렉토리를 전략 디렉토리로 변경)
            result = subprocess.run(
                [sys.executable, backtest_script],
                cwd=str(strategy_path),
                capture_output=True,
                text=True,
                timeout=600  # 10분 타임아웃
            )

            if result.returncode != 0:
                print(f"    ✗ 실행 실패 (exit code {result.returncode})")
                print(f"    stderr: {result.stderr[:200]}")
                return None

            # results.json 읽기
            results_path = strategy_path / 'results.json'
            if results_path.exists():
                with open(results_path, 'r', encoding='utf-8') as f:
                    results = json.load(f)

                # 타임프레임별로 저장
                timeframe_results_path = strategy_path / f'results_{timeframe}.json'
                with open(timeframe_results_path, 'w', encoding='utf-8') as f:
                    json.dump(results, f, indent=2, ensure_ascii=False, default=str)

                return results
            else:
                print(f"    ✗ results.json 없음")
                return None

        except subprocess.TimeoutExpired:
            print(f"    ✗ 타임아웃 (10분 초과)")
            return None
        except Exception as e:
            print(f"    ✗ 실행 오류: {e}")
            return None

    def run_strategy_all_timeframes(self, strategy_path: Path):
        """하나의 전략을 모든 타임프레임에서 실행"""
        strategy_name = strategy_path.name
        print(f"\n{'='*70}")
        print(f"📊 전략: {strategy_name}")
        print(f"{'='*70}")

        # config.json 백업
        if not self.backup_config(strategy_path):
            print(f"  ⚠️  백업 실패. 건너뜀.")
            return

        strategy_results = {
            'strategy_name': strategy_name,
            'strategy_path': str(strategy_path),
            'timeframes': {}
        }

        try:
            for timeframe in self.TIMEFRAMES:
                print(f"\n  [{timeframe}] 백테스팅 시작...")

                # config.json 수정
                config_change = self.modify_config(strategy_path, timeframe)
                print(f"    타임프레임 변경: {config_change['original']} → {config_change['modified']}")

                # 백테스트 실행
                results = self.run_backtest(strategy_path, timeframe)

                if results:
                    metrics = results.get('metrics', {})
                    print(f"    ✓ 완료")
                    print(f"      수익률: {metrics.get('total_return', 0):.2f}%")
                    print(f"      Sharpe: {metrics.get('sharpe_ratio', 0):.3f}")
                    print(f"      MDD: {metrics.get('max_drawdown', 0):.2f}%")
                    print(f"      승률: {metrics.get('win_rate', 0)*100:.1f}%")

                    strategy_results['timeframes'][timeframe] = {
                        'total_return': metrics.get('total_return', 0),
                        'sharpe_ratio': metrics.get('sharpe_ratio', 0),
                        'max_drawdown': metrics.get('max_drawdown', 0),
                        'win_rate': metrics.get('win_rate', 0),
                        'total_trades': metrics.get('total_trades', 0),
                        'profit_factor': metrics.get('profit_factor', 0)
                    }
                else:
                    strategy_results['timeframes'][timeframe] = None

        finally:
            # config.json 복원
            self.restore_config(strategy_path)
            print(f"\n  ✓ 원본 config.json 복원 완료")

        self.results_summary.append(strategy_results)

    def run_all(self):
        """모든 전략, 모든 타임프레임 백테스팅"""
        strategies = self.find_strategies()

        if not strategies:
            print("✗ 전략을 찾을 수 없습니다.")
            return

        print(f"\n발견된 전략: {len(strategies)}개")
        for s in strategies:
            print(f"  - {s.name}")

        print(f"\n백테스팅 기준:")
        print(f"  기간: {self.START_DATE} ~ {self.END_DATE}")
        print(f"  타임프레임: {', '.join(self.TIMEFRAMES)}")
        print(f"  총 실행 횟수: {len(strategies)} × {len(self.TIMEFRAMES)} = {len(strategies) * len(self.TIMEFRAMES)}회")

        # 실행
        for strategy_path in strategies:
            self.run_strategy_all_timeframes(strategy_path)

        # 요약 저장
        self.save_summary()

    def save_summary(self):
        """전체 요약 저장"""
        summary_path = self.strategies_dir / 'multi_timeframe_summary.json'

        summary = {
            'timestamp': datetime.now().isoformat(),
            'period': {
                'start': self.START_DATE,
                'end': self.END_DATE
            },
            'timeframes': self.TIMEFRAMES,
            'strategies': self.results_summary
        }

        with open(summary_path, 'w', encoding='utf-8') as f:
            json.dump(summary, f, indent=2, ensure_ascii=False, default=str)

        print(f"\n{'='*70}")
        print(f"✅ 전체 백테스팅 완료")
        print(f"{'='*70}")
        print(f"요약 파일: {summary_path}")
        print(f"\n다음 단계: python automation/compare_timeframe_results.py")


def main():
    """메인 실행"""
    print("="*70)
    print("🚀 멀티 타임프레임 백테스팅 자동화 도구")
    print("="*70)

    backtester = MultiTimeframeBacktester()
    backtester.run_all()


if __name__ == '__main__':
    main()
