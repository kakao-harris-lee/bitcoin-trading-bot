#!/usr/bin/env python3
"""
기존 Results 완전 수집
====================
모든 전략 폴더에서 result*.json 파일을 찾아서 표준화된 형식으로 수집
"""

import os
import json
from pathlib import Path
from typing import Dict, List
from datetime import datetime


def find_all_result_files(base_dir: str = "strategies") -> List[Dict]:
    """모든 전략 폴더에서 result 파일 찾기"""
    results = []

    for strategy_folder in sorted(Path(base_dir).glob("v*")):
        if not strategy_folder.is_dir():
            continue

        strategy_name = strategy_folder.name

        # result*.json, *all_years.json, multi_year_results.json 파일 찾기 (재귀적)
        result_patterns = ["result*.json", "*all_years.json", "multi_year_results.json"]

        for pattern in result_patterns:
            for result_file in strategy_folder.rglob(pattern):
                # v43의 버그 있는 파일 제외
                if 'v43_supreme_scalping' in str(result_file) and 'v43_day_score40_all_years.json' in str(result_file):
                    continue  # v43의 버그 있는 파일 스킵
                if 'v43_supreme_scalping' in str(result_file) and 'v41_all_years.json' in str(result_file):
                    continue  # v41 데이터도 v43 폴더에 있지만 스킵 (중복)
                # .json 파일인지 확인
                if not result_file.suffix == '.json':
                    continue

                # 파일 크기 확인 (빈 파일 제외)
                if result_file.stat().st_size < 10:
                    continue

                try:
                    with open(result_file) as f:
                        data = json.load(f)

                    results.append({
                        "strategy": strategy_name,
                        "file_path": str(result_file),
                        "file_name": result_file.name,
                        "data": data
                    })
                except Exception as e:
                    print(f"⚠️  Failed to read {result_file}: {e}")

    return results


def extract_year_from_filename(filename: str) -> int:
    """파일명에서 연도 추출"""
    # result_2020.json → 2020
    # results_day_2021.json → 2021
    # result_minute60_2022.json → 2022

    for year in [2020, 2021, 2022, 2023, 2024, 2025]:
        if str(year) in filename:
            return year

    return 0  # 연도 없음


def parse_year_based_results(data: Dict) -> List[Dict]:
    """연도별 키가 있는 결과 파싱 (v43, v44, v45 형식)"""
    # {"2020": {...}, "2021": {...}}
    results = []

    for key, value in data.items():
        # 연도인지 확인
        if isinstance(key, str) and key.isdigit() and 2020 <= int(key) <= 2025:
            year = int(key)
            results.append({
                "year": year,
                "data": value
            })

    return results


def standardize_result(
    strategy: str,
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

    # total_trades가 리스트인 경우 처리
    if isinstance(total_trades, list):
        total_trades = len(total_trades) if total_trades else 0

    win_rate = raw_data.get('win_rate') or \
              raw_data.get('win_ratio') or 0.0

    sharpe = raw_data.get('sharpe_ratio') or \
            raw_data.get('sharpe') or 0.0

    max_dd = raw_data.get('max_drawdown') or \
            raw_data.get('mdd') or 0.0

    profit_factor = raw_data.get('profit_factor') or 0.0

    return {
        "strategy": strategy,
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


def main():
    """메인 함수"""
    print("=" * 60)
    print("기존 Results 완전 수집 시작")
    print("=" * 60)

    # 모든 result 파일 찾기
    all_results = find_all_result_files()
    print(f"\n📁 Found {len(all_results)} result files")

    # 표준화된 결과 수집
    standardized_results = []

    for item in all_results:
        strategy = item['strategy']
        filename = item['file_name']
        data = item['data']

        # 연도별 키가 있는지 확인 (v43/v44/v45 형식)
        year_based = parse_year_based_results(data)

        if year_based:
            # 연도별 결과가 있음
            print(f"✅ {strategy}/{filename}: Found {len(year_based)} years")
            for yb in year_based:
                std = standardize_result(strategy, yb['year'], yb['data'])
                standardized_results.append(std)
        else:
            # 단일 결과 (연도는 파일명에서 추출)
            year = extract_year_from_filename(filename)
            if year > 0:
                print(f"✅ {strategy}/{filename}: Year {year}")
                std = standardize_result(strategy, year, data)
                standardized_results.append(std)
            else:
                print(f"⚠️  {strategy}/{filename}: No year found")

    # 저장
    output_file = Path("validation/all_existing_results.json")
    output_file.parent.mkdir(parents=True, exist_ok=True)

    with open(output_file, 'w') as f:
        json.dump(standardized_results, f, indent=2)

    print(f"\n📊 Standardized {len(standardized_results)} results")
    print(f"💾 Saved to: {output_file}")

    # 통계
    strategies = set(r['strategy'] for r in standardized_results)
    years = set(r['year'] for r in standardized_results)

    print(f"\n📈 Statistics:")
    print(f"  - Strategies: {len(strategies)}")
    print(f"  - Years: {sorted(years)}")
    print(f"  - Total results: {len(standardized_results)}")

    # 전략별 카운트
    from collections import Counter
    strategy_counts = Counter(r['strategy'] for r in standardized_results)

    print(f"\n🏆 Top strategies by result count:")
    for strategy, count in strategy_counts.most_common(10):
        print(f"  - {strategy}: {count} results")

    # 누락된 조합 찾기
    print(f"\n🔍 Missing combinations:")
    all_strategies = [f.name for f in sorted(Path("strategies").glob("v*")) if f.is_dir()]
    all_years = [2020, 2021, 2022, 2023, 2024, 2025]

    existing_combos = set((r['strategy'], r['year']) for r in standardized_results)
    total_combos = len(all_strategies) * len(all_years)
    missing_count = total_combos - len(existing_combos)

    print(f"  - Total possible: {total_combos}")
    print(f"  - Existing: {len(existing_combos)}")
    print(f"  - Missing: {missing_count}")

    # 누락된 전략 목록 (연도별)
    missing_by_strategy = {}
    for strategy in all_strategies:
        missing_years = []
        for year in all_years:
            if (strategy, year) not in existing_combos:
                missing_years.append(year)
        if missing_years:
            missing_by_strategy[strategy] = missing_years

    # 누락 많은 전략 출력
    print(f"\n❌ Strategies with most missing results:")
    sorted_missing = sorted(missing_by_strategy.items(), key=lambda x: len(x[1]), reverse=True)
    for strategy, years in sorted_missing[:10]:
        print(f"  - {strategy}: missing {len(years)} years {years}")

    # 누락 목록 저장
    missing_file = Path("validation/missing_results.json")
    with open(missing_file, 'w') as f:
        json.dump({
            "total_missing": missing_count,
            "missing_by_strategy": missing_by_strategy,
            "timestamp": datetime.now().isoformat()
        }, f, indent=2)

    print(f"\n💾 Missing list saved to: {missing_file}")


if __name__ == "__main__":
    main()
