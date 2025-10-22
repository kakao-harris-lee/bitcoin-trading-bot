#!/usr/bin/env python3
"""
전략 인벤토리 생성
=================
51개 전략의 상세 정보를 수집하여 JSON 파일로 저장

작성일: 2025-10-20
"""

import json
import os
from pathlib import Path
from typing import Dict, List


def analyze_strategy(strategy_path: Path) -> Dict:
    """단일 전략 분석"""
    strategy_name = strategy_path.name

    info = {
        'name': strategy_name,
        'path': str(strategy_path),
        'has_config': False,
        'has_strategy_py': False,
        'has_backtest': False,
        'has_results': False,
        'timeframe': None,
        'entry_logic': None,
        'exit_logic': None,
        'backtest_type': None,
        'status': 'pending'
    }

    # config.json 확인
    config_path = strategy_path / 'config.json'
    if config_path.exists():
        info['has_config'] = True
        try:
            with open(config_path) as f:
                config = json.load(f)
                info['timeframe'] = config.get('timeframe')
                info['entry_logic'] = config.get('entry_conditions') or config.get('strategy_name')
                info['exit_logic'] = f"TP: {config.get('take_profit_1', config.get('take_profit', 'N/A'))}, SL: {config.get('stop_loss', 'N/A')}"
        except:
            pass

    # strategy.py 확인
    if (strategy_path / 'strategy.py').exists():
        info['has_strategy_py'] = True

    # backtest 확인
    if (strategy_path / 'backtest.py').exists():
        info['has_backtest'] = True
        info['backtest_type'] = 'single_file'
    elif (strategy_path / 'backtest').exists():
        info['has_backtest'] = True
        info['backtest_type'] = 'directory'

    # results 확인
    if (strategy_path / 'results.json').exists():
        info['has_results'] = True
    elif (strategy_path / 'results').exists():
        info['has_results'] = True

    return info


def create_inventory(strategies_dir: Path) -> List[Dict]:
    """전체 전략 인벤토리 생성"""
    inventory = []

    # v01-v45 패턴으로 전략 찾기
    for item in sorted(strategies_dir.iterdir()):
        if not item.is_dir():
            continue

        # v로 시작하는 디렉터리만
        if not item.name.startswith('v'):
            continue

        # v 다음이 숫자인지 확인
        version_part = item.name.split('_')[0]
        if len(version_part) < 2 or not version_part[1].isdigit():
            continue

        # 분석
        info = analyze_strategy(item)
        inventory.append(info)

    return inventory


def classify_tiers(inventory: List[Dict]) -> Dict[str, List[str]]:
    """Tier 분류"""
    tiers = {
        'tier1_ready': [],      # backtest.py 있고 바로 실행 가능
        'tier2_strategy': [],   # strategy.py만 있음, Universal Engine 사용
        'tier3_incomplete': []  # 재구현 필요
    }

    for strategy in inventory:
        name = strategy['name']

        if strategy['has_backtest'] and strategy['has_strategy_py']:
            tiers['tier1_ready'].append(name)
        elif strategy['has_strategy_py']:
            tiers['tier2_strategy'].append(name)
        else:
            tiers['tier3_incomplete'].append(name)

    return tiers


def print_summary(inventory: List[Dict], tiers: Dict):
    """요약 출력"""
    print("=" * 80)
    print("전략 인벤토리 요약")
    print("=" * 80)
    print(f"\n총 전략 수: {len(inventory)}개")

    print(f"\n파일 보유 현황:")
    print(f"  - config.json:   {sum(1 for s in inventory if s['has_config']):2d}개 ({sum(1 for s in inventory if s['has_config'])/len(inventory)*100:.1f}%)")
    print(f"  - strategy.py:   {sum(1 for s in inventory if s['has_strategy_py']):2d}개 ({sum(1 for s in inventory if s['has_strategy_py'])/len(inventory)*100:.1f}%)")
    print(f"  - backtest:      {sum(1 for s in inventory if s['has_backtest']):2d}개 ({sum(1 for s in inventory if s['has_backtest'])/len(inventory)*100:.1f}%)")
    print(f"  - results:       {sum(1 for s in inventory if s['has_results']):2d}개 ({sum(1 for s in inventory if s['has_results'])/len(inventory)*100:.1f}%)")

    print(f"\nTier 분류:")
    print(f"  Tier 1 (Ready):      {len(tiers['tier1_ready']):2d}개 - 즉시 실행 가능")
    print(f"  Tier 2 (Strategy):   {len(tiers['tier2_strategy']):2d}개 - Universal Engine 필요")
    print(f"  Tier 3 (Incomplete): {len(tiers['tier3_incomplete']):2d}개 - 재구현 필요")

    print(f"\n타임프레임 분포:")
    timeframes = {}
    for strategy in inventory:
        tf = strategy['timeframe'] or 'unknown'
        timeframes[tf] = timeframes.get(tf, 0) + 1

    for tf, count in sorted(timeframes.items(), key=lambda x: -x[1]):
        print(f"  - {tf:15s}: {count:2d}개")

    print("\n" + "=" * 80)


def main():
    project_root = Path(__file__).parent.parent
    strategies_dir = project_root / 'strategies'
    output_path = project_root / 'validation' / 'strategy_inventory.json'

    print("전략 인벤토리 생성 중...")
    print("-" * 80)

    # 인벤토리 생성
    inventory = create_inventory(strategies_dir)

    # Tier 분류
    tiers = classify_tiers(inventory)

    # 결과 저장
    result = {
        'total_strategies': len(inventory),
        'inventory': inventory,
        'tiers': tiers,
        'summary': {
            'has_config': sum(1 for s in inventory if s['has_config']),
            'has_strategy': sum(1 for s in inventory if s['has_strategy_py']),
            'has_backtest': sum(1 for s in inventory if s['has_backtest']),
            'has_results': sum(1 for s in inventory if s['has_results'])
        }
    }

    with open(output_path, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\n✅ 인벤토리 저장: {output_path}")

    # 요약 출력
    print_summary(inventory, tiers)

    # Tier별 전략 목록
    print("\n=== Tier 1: Ready ({}) ===".format(len(tiers['tier1_ready'])))
    for name in tiers['tier1_ready'][:10]:
        print(f"  - {name}")
    if len(tiers['tier1_ready']) > 10:
        print(f"  ... and {len(tiers['tier1_ready']) - 10} more")

    print("\n=== Tier 2: Strategy ({}) ===".format(len(tiers['tier2_strategy'])))
    for name in tiers['tier2_strategy'][:10]:
        print(f"  - {name}")
    if len(tiers['tier2_strategy']) > 10:
        print(f"  ... and {len(tiers['tier2_strategy']) - 10} more")

    print("\n=== Tier 3: Incomplete ({}) ===".format(len(tiers['tier3_incomplete'])))
    for name in tiers['tier3_incomplete'][:10]:
        print(f"  - {name}")
    if len(tiers['tier3_incomplete']) > 10:
        print(f"  ... and {len(tiers['tier3_incomplete']) - 10} more")


if __name__ == '__main__':
    main()
