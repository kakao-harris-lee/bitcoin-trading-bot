#!/usr/bin/env python3
"""
완전한 전략 분석
===============
51개 전략의 완전한 인벤토리 및 백테스팅 가능성 분석
"""

import os
import json
from pathlib import Path
from collections import defaultdict

def analyze_strategy_folder(folder: Path) -> dict:
    """전략 폴더의 상세 분석"""

    # 기본 정보
    info = {
        'name': folder.name,
        'path': str(folder),
        'has_config': False,
        'has_strategy': False,
        'has_backtest': False,
        'backtest_files': [],
        'has_results': False,
        'result_files': [],
        'timeframe': 'unknown',
        'executable': False,
        'execution_method': None,
        'dependencies': [],
        'notes': []
    }

    # config.json 확인
    config_file = folder / 'config.json'
    if config_file.exists():
        info['has_config'] = True
        try:
            with open(config_file) as f:
                config = json.load(f)
                info['timeframe'] = config.get('timeframe', 'unknown')
        except:
            pass

    # strategy.py 확인
    strategy_file = folder / 'strategy.py'
    if strategy_file.exists():
        info['has_strategy'] = True

        # strategy.py 내용 분석 (의존성 체크)
        try:
            with open(strategy_file) as f:
                content = f.read()

                # ML 모델 의존성
                if 'pickle' in content or '.pkl' in content or 'MLSignalValidator' in content:
                    info['dependencies'].append('ML_model')

                # 특수 모듈 의존성
                if 'adaptive_threshold' in content:
                    info['dependencies'].append('adaptive_threshold')
                if 'market_classifier' in content:
                    info['dependencies'].append('market_classifier')
                if 'holding_manager' in content:
                    info['dependencies'].append('holding_manager')

        except:
            pass

    # backtest*.py 확인
    backtest_files = list(folder.glob('backtest*.py'))
    if backtest_files:
        info['has_backtest'] = True
        info['backtest_files'] = [f.name for f in backtest_files]

        # 실행 가능성 판단
        main_backtest = folder / 'backtest.py'
        if main_backtest.exists():
            info['executable'] = True
            info['execution_method'] = 'direct'  # python backtest.py

        # 내용 분석
        try:
            with open(backtest_files[0]) as f:
                content = f.read()

                # 연도 인자 받는지 확인
                if 'sys.argv' in content or 'argparse' in content:
                    info['execution_method'] = 'with_args'

                # 하드코딩된 날짜 확인
                if '2024-01-01' in content or '2025-01-01' in content:
                    info['notes'].append('hardcoded_dates')

        except:
            pass

    # result*.json 확인
    result_files = list(folder.rglob('result*.json'))
    if result_files:
        info['has_results'] = True
        info['result_files'] = [f.name for f in result_files[:5]]  # 최대 5개만

    # 실행 가능성 최종 판단
    if info['has_backtest'] and info['has_strategy']:
        info['executable'] = True
        if not info['execution_method']:
            info['execution_method'] = 'needs_adaptation'

    return info

def categorize_strategies(strategies: list) -> dict:
    """전략을 카테고리별로 분류"""

    categories = {
        'ready': [],      # 즉시 실행 가능
        'adaptable': [],  # 약간 수정 필요
        'complex': [],    # 복잡한 수정 필요
        'incomplete': []  # 불완전
    }

    for s in strategies:
        if s['executable'] and s['execution_method'] == 'direct':
            if not s['dependencies'] or set(s['dependencies']) <= {'adaptive_threshold', 'market_classifier'}:
                categories['ready'].append(s)
            else:
                categories['adaptable'].append(s)
        elif s['executable'] and s['execution_method'] in ['with_args', 'needs_adaptation']:
            categories['adaptable'].append(s)
        elif s['has_strategy'] and not s['has_backtest']:
            categories['complex'].append(s)
        else:
            categories['incomplete'].append(s)

    return categories

def create_execution_plan(categories: dict) -> list:
    """실행 계획 생성"""

    plan = []

    # Phase 1: Ready 전략 (즉시 실행)
    if categories['ready']:
        plan.append({
            'phase': 1,
            'name': 'Ready Strategies (즉시 실행)',
            'strategies': [s['name'] for s in categories['ready']],
            'count': len(categories['ready']),
            'total_backtests': len(categories['ready']) * 6,
            'method': 'direct_execution',
            'priority': 'high'
        })

    # Phase 2: Adaptable 전략 (약간 수정)
    if categories['adaptable']:
        plan.append({
            'phase': 2,
            'name': 'Adaptable Strategies (약간 수정)',
            'strategies': [s['name'] for s in categories['adaptable']],
            'count': len(categories['adaptable']),
            'total_backtests': len(categories['adaptable']) * 6,
            'method': 'modify_and_run',
            'priority': 'high'
        })

    # Phase 3: Complex 전략 (복잡한 작업)
    if categories['complex']:
        plan.append({
            'phase': 3,
            'name': 'Complex Strategies (백테스트 작성)',
            'strategies': [s['name'] for s in categories['complex']],
            'count': len(categories['complex']),
            'total_backtests': len(categories['complex']) * 6,
            'method': 'create_backtest',
            'priority': 'medium'
        })

    # Phase 4: Incomplete 전략 (재구현)
    if categories['incomplete']:
        plan.append({
            'phase': 4,
            'name': 'Incomplete Strategies (재구현)',
            'strategies': [s['name'] for s in categories['incomplete']],
            'count': len(categories['incomplete']),
            'total_backtests': len(categories['incomplete']) * 6,
            'method': 'full_implementation',
            'priority': 'low'
        })

    return plan

def main():
    """메인 함수"""
    print("=" * 80)
    print("전체 전략 완전 분석")
    print("=" * 80)

    # 모든 전략 폴더 찾기
    base_dir = Path("strategies")
    strategy_folders = sorted([f for f in base_dir.glob("v*") if f.is_dir()])

    print(f"\n📁 Total strategy folders: {len(strategy_folders)}")

    # 각 전략 분석
    strategies = []
    for folder in strategy_folders:
        info = analyze_strategy_folder(folder)
        strategies.append(info)

        # 간단 출력
        status = "✅" if info['executable'] else "❌"
        deps = f" [{', '.join(info['dependencies'])}]" if info['dependencies'] else ""
        print(f"{status} {info['name']}: {info['execution_method']}{deps}")

    # 카테고리 분류
    categories = categorize_strategies(strategies)

    print("\n" + "=" * 80)
    print("카테고리별 분류")
    print("=" * 80)

    for cat_name, cat_strategies in categories.items():
        print(f"\n{cat_name.upper()}: {len(cat_strategies)} strategies")
        for s in cat_strategies[:5]:  # 최대 5개만 출력
            print(f"  - {s['name']}")
        if len(cat_strategies) > 5:
            print(f"  ... and {len(cat_strategies) - 5} more")

    # 실행 계획 생성
    plan = create_execution_plan(categories)

    print("\n" + "=" * 80)
    print("실행 계획")
    print("=" * 80)

    total_backtests = 0
    for phase in plan:
        print(f"\n[Phase {phase['phase']}] {phase['name']}")
        print(f"  Strategies: {phase['count']}")
        print(f"  Backtests: {phase['total_backtests']} (6 years each)")
        print(f"  Method: {phase['method']}")
        print(f"  Priority: {phase['priority']}")
        total_backtests += phase['total_backtests']

        # 전략 목록 (처음 3개만)
        print(f"  Strategies:")
        for s in phase['strategies'][:3]:
            print(f"    - {s}")
        if len(phase['strategies']) > 3:
            print(f"    ... and {len(phase['strategies']) - 3} more")

    print(f"\n{'=' * 80}")
    print(f"TOTAL: {total_backtests} backtests across {len(strategies)} strategies")
    print(f"{'=' * 80}")

    # 결과 저장
    output = {
        'total_strategies': len(strategies),
        'categories': {
            'ready': len(categories['ready']),
            'adaptable': len(categories['adaptable']),
            'complex': len(categories['complex']),
            'incomplete': len(categories['incomplete'])
        },
        'total_backtests': total_backtests,
        'strategies': strategies,
        'execution_plan': plan
    }

    output_file = Path("validation/complete_strategy_analysis.json")
    with open(output_file, 'w') as f:
        json.dump(output, f, indent=2)

    print(f"\n💾 Saved to: {output_file}")

    # 우선순위 전략 (Phase 4-6 핵심)
    print("\n" + "=" * 80)
    print("우선순위 전략 (Phase 4-6 핵심)")
    print("=" * 80)

    priority_names = [
        'v30_perfect_longterm',
        'v31_scalping_with_classifier',
        'v31_improved',
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
        'v41_scalping_voting',
        'v42_ultimate_scalping',
    ]

    priority_strategies = [s for s in strategies if s['name'] in priority_names]

    for s in priority_strategies:
        status = "✅" if s['executable'] else "❌"
        method = s['execution_method'] or "N/A"
        print(f"{status} {s['name']}: {method}")

if __name__ == "__main__":
    main()
