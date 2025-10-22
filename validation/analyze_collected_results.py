#!/usr/bin/env python3
"""
수집된 결과 분석 및 Top 전략 선정
================================
현재까지 수집한 결과로 Top 전략을 선정하고, 누락 우선순위를 결정
"""

import json
import pandas as pd
from pathlib import Path
from collections import defaultdict

def load_results():
    """수집된 결과 로드"""
    with open('validation/all_existing_results.json') as f:
        return json.load(f)

def analyze_by_strategy(results):
    """전략별 분석"""
    by_strategy = defaultdict(list)

    for r in results:
        by_strategy[r['strategy']].append(r)

    # 전략별 통계
    stats = []

    for strategy, years_data in by_strategy.items():
        # 연도별 데이터 정렬
        years_data = sorted(years_data, key=lambda x: x['year'])

        # 평균 수익률
        avg_return = sum(r['total_return_pct'] for r in years_data) / len(years_data)

        # 2020-2024 평균
        data_2020_2024 = [r for r in years_data if 2020 <= r['year'] <= 2024]
        avg_return_2020_2024 = (
            sum(r['total_return_pct'] for r in data_2020_2024) / len(data_2020_2024)
            if data_2020_2024 else 0
        )

        # 2025 수익률
        data_2025 = [r for r in years_data if r['year'] == 2025]
        return_2025 = data_2025[0]['total_return_pct'] if data_2025 else None

        # 평균 Sharpe
        sharpes = [r['sharpe_ratio'] for r in years_data if r['sharpe_ratio'] != 0]
        avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0

        # 평균 승률
        win_rates = [r['win_rate'] for r in years_data if r['win_rate'] > 0]
        avg_win_rate = sum(win_rates) / len(win_rates) if win_rates else 0

        # 총 거래수
        total_trades = sum(r['total_trades'] for r in years_data)

        # 최대 수익 / 최대 손실
        max_return = max(r['total_return_pct'] for r in years_data)
        min_return = min(r['total_return_pct'] for r in years_data)

        # 연도 커버리지
        years_covered = sorted([r['year'] for r in years_data])

        stats.append({
            'strategy': strategy,
            'years_count': len(years_data),
            'years_covered': years_covered,
            'avg_return': avg_return,
            'avg_return_2020_2024': avg_return_2020_2024,
            'return_2025': return_2025,
            'avg_sharpe': avg_sharpe,
            'avg_win_rate': avg_win_rate,
            'total_trades': total_trades,
            'max_return': max_return,
            'min_return': min_return,
            'volatility': max_return - min_return
        })

    return pd.DataFrame(stats)

def rank_strategies(df):
    """전략 순위 매기기 (4가지 기준)"""

    # 1. 평균 수익률 (2020-2024)
    df['rank_return'] = df['avg_return_2020_2024'].rank(ascending=False)

    # 2. 평균 Sharpe Ratio
    df['rank_sharpe'] = df['avg_sharpe'].rank(ascending=False)

    # 3. 2025 Out-of-Sample 수익률
    df_with_2025 = df[df['return_2025'].notna()].copy()
    df_with_2025['rank_2025'] = df_with_2025['return_2025'].rank(ascending=False)
    df = df.merge(df_with_2025[['strategy', 'rank_2025']], on='strategy', how='left')

    # 4. 데이터 완전성 (6년 모두 있으면 보너스)
    df['rank_completeness'] = df['years_count'].rank(ascending=False)

    # 종합 점수 (가중 평균)
    df['composite_score'] = (
        df['rank_return'] * 0.4 +
        df['rank_sharpe'] * 0.3 +
        df['rank_2025'].fillna(df['rank_return']) * 0.2 +  # 2025 없으면 평균으로 대체
        df['rank_completeness'] * 0.1
    )

    # 최종 순위
    df['final_rank'] = df['composite_score'].rank()

    return df.sort_values('final_rank')

def main():
    """메인 함수"""
    print("=" * 60)
    print("수집된 결과 분석")
    print("=" * 60)

    # 데이터 로드
    results = load_results()
    print(f"\n📊 Total results: {len(results)}")

    # 전략별 분석
    df = analyze_by_strategy(results)
    print(f"📋 Strategies analyzed: {len(df)}")

    # 순위 매기기
    df_ranked = rank_strategies(df)

    # Top 10 출력
    print("\n" + "=" * 60)
    print("TOP 10 STRATEGIES")
    print("=" * 60)

    top10 = df_ranked.head(10)

    for i, row in top10.iterrows():
        print(f"\n[{int(row['final_rank'])}] {row['strategy']}")
        print(f"  Years: {row['years_covered']}")
        print(f"  Avg Return (2020-2024): {row['avg_return_2020_2024']:.2f}%")
        if row['return_2025'] is not None:
            print(f"  Return 2025: {row['return_2025']:.2f}%")
        print(f"  Avg Sharpe: {row['avg_sharpe']:.2f}")
        print(f"  Avg Win Rate: {row['avg_win_rate']*100:.1f}%")
        print(f"  Total Trades: {row['total_trades']}")

    # 전체 순위 저장
    output_file = Path("validation/strategy_rankings.json")
    df_ranked.to_json(output_file, orient='records', indent=2)
    print(f"\n💾 Full rankings saved to: {output_file}")

    # Top 10 상세 데이터 저장
    top10_file = Path("validation/top10_strategies.json")

    top10_detailed = []
    for _, row in top10.iterrows():
        strategy = row['strategy']
        strategy_results = [r for r in results if r['strategy'] == strategy]

        top10_detailed.append({
            'rank': int(row['final_rank']),
            'strategy': strategy,
            'summary': {
                'years_count': int(row['years_count']),
                'years_covered': row['years_covered'],
                'avg_return_2020_2024': round(row['avg_return_2020_2024'], 2),
                'return_2025': round(row['return_2025'], 2) if row['return_2025'] is not None else None,
                'avg_sharpe': round(row['avg_sharpe'], 2),
                'avg_win_rate': round(row['avg_win_rate'], 4),
                'total_trades': int(row['total_trades'])
            },
            'yearly_results': strategy_results
        })

    with open(top10_file, 'w') as f:
        json.dump(top10_detailed, f, indent=2)

    print(f"💾 Top 10 detailed data saved to: {top10_file}")

    # 누락된 중요 전략 찾기
    print("\n" + "=" * 60)
    print("MISSING CRITICAL DATA")
    print("=" * 60)

    # Phase 4-5 전략 (CLAUDE.md 언급)
    critical_strategies = [
        'v17_vwap_breakout',
        'v19_market_adaptive_hybrid',
        'v20_simplified_adaptive',
        'v30_perfect_longterm',
        'v31_scalping_with_classifier',
        'v32_aggressive',
        'v32_ensemble',
        'v32_optimized',
        'v34_supreme',
        'v35_optimized',
        'v36_multi_timeframe',
        'v37_supreme',
        'v38_ensemble',
        'v39_voting',
        'v40_adaptive_voting',
        'v41_scalping_voting',
        'v42_ultimate_scalping',
        'v43_supreme_scalping',
        'v44_supreme_hybrid_scalping',
        'v45_ultimate_dynamic_scalping'
    ]

    for strategy in critical_strategies:
        strategy_data = df[df['strategy'] == strategy]

        if strategy_data.empty:
            print(f"❌ {strategy}: NO DATA")
        elif strategy_data.iloc[0]['years_count'] < 6:
            years = strategy_data.iloc[0]['years_covered']
            missing_years = [y for y in [2020, 2021, 2022, 2023, 2024, 2025] if y not in years]
            print(f"⚠️  {strategy}: Missing {len(missing_years)} years {missing_years}")

if __name__ == "__main__":
    main()
