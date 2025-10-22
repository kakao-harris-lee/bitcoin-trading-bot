#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime

print("🔍 Scanning all backtest result files...")

# 전체 백테스트 결과 파일 수집
result_files = []
for pattern in ['*/backtest_results.json', '*/results/*all_years*.json', '*/results.json']:
    result_files.extend(Path('strategies').glob(pattern))

print(f"📊 Found {len(result_files)} result files\n")

all_strategies = {}

for file_path in result_files:
    strategy_name = file_path.parts[1]

    # v43 buggy 제외
    if 'v43' in strategy_name and 'v43_day_score40' in str(file_path):
        continue

    try:
        with open(file_path) as f:
            data = json.load(f)

        # 연도별 데이터 추출 (두 가지 구조 지원)
        yearly_raw = None

        if 'results' in data:  # v39/v40 스타일
            yearly_raw = data['results']
        elif '2020' in data:  # 직접 연도 키 스타일
            yearly_raw = data
        else:
            continue

        yearly_data = {}
        years = ['2020', '2021', '2022', '2023', '2024', '2025']

        for year in years:
            if year in yearly_raw:
                yr = yearly_raw[year]

                # 수익률 (total_return은 이미 퍼센트!)
                if 'total_return_pct' in yr:
                    ret_pct = yr['total_return_pct']
                elif 'total_return' in yr:
                    ret_pct = yr['total_return']  # ✅ 이미 퍼센트!
                else:
                    continue

                # 거래 횟수
                trades = yr.get('total_trades', 0)
                if isinstance(trades, list):
                    trades = len(trades)

                # 승률
                win_rate = yr.get('win_rate', 0)
                if isinstance(win_rate, float) and win_rate <= 1:
                    win_rate = win_rate * 100

                yearly_data[year] = {
                    'return_pct': ret_pct,
                    'sharpe': yr.get('sharpe_ratio', 0),
                    'mdd': yr.get('max_drawdown', 0),
                    'trades': trades,
                    'win_rate': win_rate
                }

        if yearly_data and (strategy_name not in all_strategies or len(yearly_data) > len(all_strategies.get(strategy_name, {}).get('yearly', {}))):
            all_strategies[strategy_name] = {
                'file': str(file_path),
                'yearly': yearly_data
            }
            print(f"  ✅ {strategy_name}: {len(yearly_data)} years")

    except Exception as e:
        print(f"  ⚠️  {file_path}: {e}")

print(f"\n✅ Total strategies processed: {len(all_strategies)}\n")

# 통계 계산
summary = []

for strategy_name, info in all_strategies.items():
    yearly = info['yearly']

    if not yearly or len(yearly) < 3:
        continue

    returns = [y['return_pct'] for y in yearly.values()]
    sharpes = [y['sharpe'] for y in yearly.values() if y['sharpe'] != 0]
    mdds = [abs(y['mdd']) for y in yearly.values() if y['mdd'] != 0]
    trades_list = [y['trades'] for y in yearly.values() if y['trades'] != 0]
    winrates = [y['win_rate'] for y in yearly.values() if y['win_rate'] != 0]

    avg_return = sum(returns) / len(returns)
    avg_sharpe = sum(sharpes) / len(sharpes) if sharpes else 0
    avg_mdd = sum(mdds) / len(mdds) if mdds else 0
    avg_trades = sum(trades_list) / len(trades_list) if trades_list else 0
    avg_winrate = sum(winrates) / len(winrates) if winrates else 0

    oos_2025 = yearly.get('2025', {}).get('return_pct', None)

    summary.append({
        'strategy': strategy_name,
        'file': info['file'],
        'years_tested': len(yearly),
        'avg_return': avg_return,
        'avg_sharpe': avg_sharpe,
        'avg_mdd': avg_mdd,
        'avg_trades': avg_trades,
        'avg_winrate': avg_winrate,
        'oos_2025': oos_2025,
        'yearly': yearly
    })

# 평균 수익률 기준 정렬
summary.sort(key=lambda x: x['avg_return'], reverse=True)

# 리포트 생성
print("=" * 110)
print(" " * 30 + "전략 검증 최종 분석 리포트 (2020-2025)")
print("=" * 110)
print(f"\n분석 일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
print(f"분석 전략: {len(summary)}개 (3년 이상 데이터)")
print(f"검증 기간: 2020-2025 (6년)\n")

print("=" * 110)
print("🏆 Top 10 전략 (6년 평균 수익률 기준)")
print("=" * 110)
print(f"\n{'#':<4} {'전략':<35} {'평균':<11} {'Sharpe':<9} {'MDD':<10} {'거래/년':<10} {'승률':<9} {'2025 OOS':<12}")
print("-" * 110)

for i, s in enumerate(summary[:10], 1):
    oos_str = f"{s['oos_2025']:.1f}%" if s['oos_2025'] else "N/A"
    mdd_str = f"-{s['avg_mdd']:.1f}%" if s['avg_mdd'] > 0 else "N/A"
    print(f"{i:<4} {s['strategy']:<35} {s['avg_return']:>9.1f}%  {s['avg_sharpe']:>7.2f}  {mdd_str:>9}  {s['avg_trades']:>8.1f}회  {s['avg_winrate']:>7.1f}%  {oos_str:>11}")

# 연도별 최고 전략
print("\n" + "=" * 110)
print("📊 연도별 최고 전략 Top 3")
print("=" * 110)
print()

years = ['2020', '2021', '2022', '2023', '2024', '2025']
for year in years:
    year_best = []
    for s in summary:
        if year in s['yearly']:
            year_best.append((s['strategy'], s['yearly'][year]['return_pct']))

    if year_best:
        year_best.sort(key=lambda x: x[1], reverse=True)
        print(f"{year}:")
        for rank, (strategy, ret) in enumerate(year_best[:3], 1):
            print(f"  {rank}. {strategy:<40} {ret:>9.2f}%")
        print()

# 핵심 발견
print("=" * 110)
print("🎯 핵심 발견")
print("=" * 110)
print()

if summary:
    print("1. 최고 전략 Top 3:")
    for i, s in enumerate(summary[:3], 1):
        print(f"\n   {i}. {s['strategy']}")
        print(f"      6년 평균: {s['avg_return']:.2f}% | Sharpe: {s['avg_sharpe']:.2f} | MDD: -{s['avg_mdd']:.2f}%")
        print(f"      거래: {s['avg_trades']:.1f}회/년 | 승률: {s['avg_winrate']:.1f}%")
        if s['oos_2025']:
            print(f"      2025 OOS: {s['oos_2025']:.2f}%")
        print(f"      연도별: " + " | ".join([f"{yr}: {data['return_pct']:.1f}%" for yr, data in sorted(s['yearly'].items())]))

# Voting 전략 비교
v39 = next((s for s in summary if s['strategy'] == 'v39_voting'), None)
v40 = next((s for s in summary if s['strategy'] == 'v40_adaptive_voting'), None)

if v39 and v40:
    print("\n2. Voting 전략 비교 (v39 vs v40):")
    print(f"\n   v39 (손절 없음):")
    print(f"     6년 평균: {v39['avg_return']:.2f}% | Sharpe: {v39['avg_sharpe']:.2f}")
    print(f"   v40 (적응형 손절):")
    print(f"     6년 평균: {v40['avg_return']:.2f}% | Sharpe: {v40['avg_sharpe']:.2f}")

    if '2022' in v39['yearly'] and '2022' in v40['yearly']:
        v39_2022 = v39['yearly']['2022']['return_pct']
        v40_2022 = v40['yearly']['2022']['return_pct']
        improvement = v40_2022 - v39_2022
        print(f"\n   2022 하락장 개선:")
        print(f"     v39: {v39_2022:.2f}% → v40: {v40_2022:.2f}% ({improvement:+.2f}%p)")

# 100% 초과 전략
high_performers = [s for s in summary if s['avg_return'] >= 100]
if high_performers:
    print(f"\n3. 100% 이상 연평균 전략: {len(high_performers)}개")
    for s in high_performers[:5]:
        print(f"   - {s['strategy']:<40} {s['avg_return']:>7.2f}% (Sharpe {s['avg_sharpe']:.2f})")

# 저장
output = {
    'generated_at': datetime.now().isoformat(),
    'period': '2020-2025',
    'strategies_analyzed': len(summary),
    'top_10': [
        {
            'rank': i,
            'strategy': s['strategy'],
            'avg_return': s['avg_return'],
            'avg_sharpe': s['avg_sharpe'],
            'avg_mdd': s['avg_mdd'],
            'avg_trades': s['avg_trades'],
            'avg_winrate': s['avg_winrate'],
            'oos_2025': s['oos_2025'],
            'yearly_returns': {yr: data['return_pct'] for yr, data in s['yearly'].items()}
        }
        for i, s in enumerate(summary[:10], 1)
    ],
    'all_strategies': summary
}

output_file = Path('strategies/251020-2144_FINAL_VALIDATION_REPORT_CORRECTED.json')
with open(output_file, 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print(f"\n✅ 상세 결과 저장: {output_file}")
print()
