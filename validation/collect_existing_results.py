#!/usr/bin/env python3
"""
기존 결과 수집 스크립트
=====================
모든 전략 폴더에서 results.json, result_*.json 등을 수집하여 통합 DB 생성

작성일: 2025-10-20
"""

import json
import os
from pathlib import Path
from typing import Dict, List, Optional
import pandas as pd


def find_all_strategies(strategies_dir: Path) -> List[str]:
    """모든 전략 디렉터리 찾기"""
    strategies = []

    for item in strategies_dir.iterdir():
        if item.is_dir() and item.name.startswith('v'):
            # v01~v45 형식 필터링
            version_part = item.name.split('_')[0]  # 'v43_supreme' → 'v43'
            if version_part.startswith('v') and len(version_part) >= 2:
                try:
                    # v01, v02a, v10, v43 등 추출
                    strategies.append(item.name)
                except:
                    pass

    return sorted(strategies)


def find_result_files(strategy_path: Path) -> List[Path]:
    """전략 폴더에서 모든 결과 파일 찾기"""
    result_files = []

    # 1. results.json (루트)
    if (strategy_path / 'results.json').exists():
        result_files.append(strategy_path / 'results.json')

    # 2. results/ 디렉터리
    results_dir = strategy_path / 'results'
    if results_dir.exists():
        for file in results_dir.glob('*.json'):
            result_files.append(file)

    # 3. backtest/ 디렉터리
    backtest_dir = strategy_path / 'backtest'
    if backtest_dir.exists():
        for file in backtest_dir.glob('*result*.json'):
            result_files.append(file)

    # 4. validation/ 디렉터리
    validation_dir = strategy_path / 'validation'
    if validation_dir.exists():
        for file in validation_dir.glob('*.json'):
            result_files.append(file)

    return result_files


def extract_year_from_filename(filename: str) -> Optional[int]:
    """파일명에서 연도 추출"""
    for year in range(2020, 2026):
        if str(year) in filename:
            return year
    return None


def parse_result_file(file_path: Path) -> Dict:
    """결과 파일 파싱"""
    try:
        with open(file_path) as f:
            data = json.load(f)

        # 연도별 데이터 구조 확인
        if isinstance(data, dict):
            # Case 1: {2020: {...}, 2021: {...}}
            if any(str(year) in data for year in range(2020, 2026)):
                return data

            # Case 2: {"total_return_pct": ..., "total_trades": ...}
            if 'total_return_pct' in data or 'total_trades' in data:
                # 파일명에서 연도 추출
                year = extract_year_from_filename(file_path.name)
                if year:
                    return {str(year): data}
                else:
                    return {'unknown': data}

        return {}

    except Exception as e:
        print(f"  ⚠️  Error parsing {file_path.name}: {e}")
        return {}


def collect_strategy_results(strategy_name: str, strategy_path: Path) -> Dict:
    """단일 전략의 모든 결과 수집"""
    results = {}

    # 모든 결과 파일 찾기
    result_files = find_result_files(strategy_path)

    if not result_files:
        return results

    print(f"  Found {len(result_files)} result file(s)")

    # 각 파일 파싱
    for file_path in result_files:
        parsed = parse_result_file(file_path)

        for year, data in parsed.items():
            if year not in results:
                results[year] = data
            else:
                # 중복 데이터 - 더 완전한 것 선택
                if len(data) > len(results[year]):
                    results[year] = data

    return results


def collect_all_results(strategies_dir: Path) -> Dict:
    """모든 전략의 결과 수집"""
    all_strategies = find_all_strategies(strategies_dir)
    print(f"Found {len(all_strategies)} strategies\n")

    collected_results = {}

    for strategy_name in all_strategies:
        print(f"[{strategy_name}]")
        strategy_path = strategies_dir / strategy_name

        # 결과 수집
        results = collect_strategy_results(strategy_name, strategy_path)

        if results:
            collected_results[strategy_name] = results
            years = sorted([k for k in results.keys() if k != 'unknown'])
            print(f"  ✅ Collected: {', '.join(years)}")
        else:
            print(f"  ❌ No results found")

    return collected_results


def create_summary_table(all_results: Dict) -> pd.DataFrame:
    """요약 테이블 생성"""
    rows = []

    for strategy, years_data in all_results.items():
        row = {'strategy': strategy}

        # 연도별 수익률 추출
        for year in range(2020, 2026):
            year_str = str(year)
            if year_str in years_data:
                data = years_data[year_str]
                return_pct = data.get('total_return_pct', None)
                trades = data.get('total_trades', None)
                win_rate = data.get('win_rate', None)
                sharpe = data.get('sharpe_ratio', None)

                row[f'{year}_return'] = return_pct
                row[f'{year}_trades'] = trades
                row[f'{year}_win_rate'] = win_rate
                row[f'{year}_sharpe'] = sharpe
            else:
                row[f'{year}_return'] = None
                row[f'{year}_trades'] = None
                row[f'{year}_win_rate'] = None
                row[f'{year}_sharpe'] = None

        # 평균 계산
        returns = [row[f'{y}_return'] for y in range(2020, 2026) if row[f'{y}_return'] is not None]
        if returns:
            row['avg_return'] = sum(returns) / len(returns)
            row['years_count'] = len(returns)
        else:
            row['avg_return'] = None
            row['years_count'] = 0

        rows.append(row)

    df = pd.DataFrame(rows)
    return df


def main():
    print("=" * 80)
    print("기존 결과 수집 스크립트")
    print("=" * 80)
    print()

    # 프로젝트 루트
    project_root = Path(__file__).parent.parent
    strategies_dir = project_root / 'strategies'

    # 결과 수집
    print("Step 1: Collecting existing results...")
    print("-" * 80)
    all_results = collect_all_results(strategies_dir)

    print("\n" + "=" * 80)
    print(f"Total strategies with results: {len(all_results)}")
    print("=" * 80)

    # JSON 저장
    output_path = project_root / 'validation' / 'results' / 'collected_all_results.json'
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, 'w') as f:
        json.dump(all_results, f, indent=2)

    print(f"\n✅ Results saved to: {output_path}")

    # 요약 테이블 생성
    print("\nStep 2: Creating summary table...")
    df = create_summary_table(all_results)

    # 평균 수익률 기준 정렬
    df_sorted = df.sort_values('avg_return', ascending=False, na_position='last')

    # CSV 저장
    csv_path = project_root / 'validation' / 'results' / 'summary_table.csv'
    df_sorted.to_csv(csv_path, index=False)

    print(f"✅ Summary table saved to: {csv_path}")

    # Top 10 출력
    print("\n" + "=" * 80)
    print("Top 10 Strategies (by average return)")
    print("=" * 80)

    top10 = df_sorted.head(10)
    for idx, row in top10.iterrows():
        strategy = row['strategy']
        avg_return = row['avg_return']
        years_count = row['years_count']

        if pd.notna(avg_return):
            print(f"{idx+1:2d}. {strategy:40s} {avg_return:+8.2f}% ({int(years_count)} years)")
        else:
            print(f"{idx+1:2d}. {strategy:40s} {'N/A':>8s}")

    print("\n" + "=" * 80)
    print(f"Total collected: {len(all_results)} strategies")
    print(f"With results:    {len(df[df['years_count'] > 0])} strategies")
    print(f"No results:      {len(df[df['years_count'] == 0])} strategies")
    print("=" * 80)


if __name__ == '__main__':
    main()
