#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Multi-Year Backtest Runner
단일 전략을 2022-2025 각 연도별 자동 백테스팅
"""

import sys
import os
import argparse
import subprocess
import json
from pathlib import Path

def run_backtest_for_year(strategy_path, year, end_date=None):
    """
    특정 연도에 대해 백테스팅 실행

    Args:
        strategy_path: 전략 폴더 경로 (strategies/vXX_전략명)
        year: 연도 (2022, 2023, 2024, 2025)
        end_date: 종료일 (None이면 12월 31일)
    """
    if not end_date:
        if year == 2025:
            end_date = "2025-10-16"  # 현재까지
        else:
            end_date = f"{year}-12-31"

    start_date = f"{year}-01-01"

    print(f"\n{'='*80}")
    print(f"{year}년 백테스팅: {start_date} ~ {end_date}")
    print(f"{'='*80}")

    # backtest.py 실행
    backtest_py = strategy_path / "backtest.py"

    if not backtest_py.exists():
        print(f"❌ backtest.py를 찾을 수 없습니다: {backtest_py}")
        return False

    # backtest.py를 임시 수정하여 날짜 변경
    with open(backtest_py, 'r') as f:
        content = f.read()

    # 날짜 패턴 찾기 및 교체
    import re
    content_modified = re.sub(
        r"start_date=['\"][\d-]+['\"]",
        f"start_date='{start_date}'",
        content
    )
    content_modified = re.sub(
        r"end_date=['\"][\d-]+['\"]",
        f"end_date='{end_date}'",
        content_modified
    )

    # 임시 백업
    backtest_backup = strategy_path / "backtest_backup.py"
    with open(backtest_backup, 'w') as f:
        f.write(content)

    # 수정된 내용 저장
    with open(backtest_py, 'w') as f:
        f.write(content_modified)

    # 백테스팅 실행
    try:
        result = subprocess.run(
            [sys.executable, "backtest.py"],
            cwd=strategy_path,
            capture_output=True,
            text=True,
            timeout=300
        )

        print(result.stdout)

        if result.returncode != 0:
            print(f"❌ 백테스팅 실패:")
            print(result.stderr)
            return False

        # result.json을 result_{year}.json으로 이동
        result_json = strategy_path / "result.json"
        result_year_json = strategy_path / f"result_{year}.json"

        if result_json.exists():
            result_json.rename(result_year_json)
            print(f"✅ 결과 저장: result_{year}.json")
        else:
            print(f"⚠️  result.json이 생성되지 않았습니다")
            return False

        return True

    except subprocess.TimeoutExpired:
        print(f"❌ 백테스팅 타임아웃 (300초)")
        return False

    except Exception as e:
        print(f"❌ 오류 발생: {e}")
        return False

    finally:
        # 원본 복원
        with open(backtest_backup, 'r') as f:
            original_content = f.read()
        with open(backtest_py, 'w') as f:
            f.write(original_content)
        backtest_backup.unlink()


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Year Backtest Runner (2022-2025)"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        help="전략 이름 (예: v17_vwap_breakout)"
    )
    parser.add_argument(
        "--years",
        type=str,
        default="2022,2023,2024,2025",
        help="테스트할 연도 (쉼표 구분, 기본: 2022,2023,2024,2025)"
    )

    args = parser.parse_args()

    # 전략 경로 확인
    strategy_path = Path(f"strategies/{args.strategy}")

    if not strategy_path.exists():
        print(f"❌ 전략 폴더를 찾을 수 없습니다: {strategy_path}")
        sys.exit(1)

    print(f"🚀 Multi-Year Backtest: {args.strategy}")
    print(f"📁 경로: {strategy_path}")

    # 연도별 백테스팅
    years = [int(y.strip()) for y in args.years.split(",")]
    results_summary = {}

    for year in years:
        success = run_backtest_for_year(strategy_path, year)
        results_summary[year] = "✅ 완료" if success else "❌ 실패"

    # 요약
    print(f"\n{'='*80}")
    print("Multi-Year Backtest 요약")
    print(f"{'='*80}")

    for year, status in results_summary.items():
        print(f"{year}: {status}")

    # 모든 결과 파일 확인
    print(f"\n생성된 파일:")
    for year in years:
        result_file = strategy_path / f"result_{year}.json"
        if result_file.exists():
            with open(result_file, 'r') as f:
                data = json.load(f)
                total_return = data.get('total_return_pct', 0)
                print(f"  - result_{year}.json: {total_return:+.2f}%")

    print(f"\n다음 단계: automation/analyze_multi_year_results.py --strategy {args.strategy}")


if __name__ == "__main__":
    main()
