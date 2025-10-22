"""
전략 전체 스캔 및 분류 스크립트
- v01-v45 모든 전략 폴더 확인
- 백테스트 스크립트 존재 여부
- config.json 존재 여부
- 우선순위 분류
"""

import os
import json
from pathlib import Path
from typing import Dict, List
import glob

BASE_DIR = Path("/Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇/strategies")

def scan_strategy(strategy_path: Path) -> Dict:
    """단일 전략 폴더 스캔"""
    version = strategy_path.name

    # backtest.py 또는 backtest/ 폴더 확인
    has_backtest_py = (strategy_path / "backtest.py").exists()
    has_backtest_dir = (strategy_path / "backtest").is_dir()
    backtest_scripts = []

    if has_backtest_dir:
        backtest_scripts = list((strategy_path / "backtest").glob("*.py"))
    elif has_backtest_py:
        backtest_scripts = [strategy_path / "backtest.py"]

    # config.json 확인
    has_config = (strategy_path / "config.json").exists()
    config_content = None
    timeframe = None

    if has_config:
        try:
            with open(strategy_path / "config.json") as f:
                config_content = json.load(f)
                timeframe = config_content.get("timeframe", None)
        except:
            pass

    # results.json 또는 backtest_results.json 확인
    has_results = (
        (strategy_path / "results.json").exists() or
        (strategy_path / "backtest_results.json").exists()
    )

    return {
        "version": version,
        "path": str(strategy_path),
        "has_backtest": len(backtest_scripts) > 0,
        "backtest_scripts": [str(s) for s in backtest_scripts],
        "has_config": has_config,
        "timeframe": timeframe,
        "has_results": has_results,
        "status": determine_status(version, len(backtest_scripts) > 0, has_config)
    }

def determine_status(version: str, has_backtest: bool, has_config: bool) -> str:
    """전략 상태 결정"""
    # 폐기 확정
    if version in ["v43_supreme_scalping", "v45_ultimate_dynamic_scalping"]:
        return "DISCARD (복리 버그)"

    # 개발 미완성
    if version == "v42_ultimate_scalping":
        return "INCOMPLETE (개발 중)"

    # 백테스트 없음
    if not has_backtest:
        return "NO_BACKTEST"

    # config 없음
    if not has_config:
        return "NO_CONFIG"

    # Priority 1 (신뢰 가능)
    if version in [
        "v31_scalping_with_classifier",
        "v34_supreme",
        "v35_optimized",
        "v36_multi_timeframe",
        "v37_supreme",
        "v38_ensemble"
    ]:
        return "PRIORITY_1 (신뢰 가능)"

    # Priority 2 (검증 필요)
    if version in [
        "v30_perfect_longterm",
        "v32_aggressive", "v32_ensemble", "v32_optimized",
        "v33_minute240",
        "v39_voting",
        "v40_adaptive_voting",
        "v41_scalping_voting",
        "v44_supreme_hybrid_scalping"
    ]:
        return "PRIORITY_2 (검증 필요)"

    # Priority 3 (초기 전략)
    return "PRIORITY_3 (초기 전략)"

def classify_strategies(all_strategies: List[Dict]) -> Dict:
    """전략 분류"""
    priority_1 = []
    priority_2 = []
    priority_3 = []
    discard = []
    incomplete = []
    no_backtest = []

    for strategy in all_strategies:
        status = strategy["status"]

        if "DISCARD" in status:
            discard.append(strategy)
        elif "INCOMPLETE" in status:
            incomplete.append(strategy)
        elif "NO_BACKTEST" in status:
            no_backtest.append(strategy)
        elif "PRIORITY_1" in status:
            priority_1.append(strategy)
        elif "PRIORITY_2" in status:
            priority_2.append(strategy)
        elif "PRIORITY_3" in status:
            priority_3.append(strategy)

    return {
        "priority_1": priority_1,
        "priority_2": priority_2,
        "priority_3": priority_3,
        "discard": discard,
        "incomplete": incomplete,
        "no_backtest": no_backtest
    }

def main():
    """메인 실행"""
    print("=" * 80)
    print("전략 전체 스캔 시작")
    print("=" * 80)

    # 모든 v* 폴더 찾기
    strategy_folders = sorted(
        [p for p in BASE_DIR.glob("v*") if p.is_dir()],
        key=lambda x: x.name
    )

    print(f"\n발견된 전략 폴더: {len(strategy_folders)}개\n")

    # 각 전략 스캔
    all_strategies = []
    for strategy_path in strategy_folders:
        result = scan_strategy(strategy_path)
        all_strategies.append(result)

        # 간단한 상태 출력
        status_icon = "✅" if result["has_backtest"] else "❌"
        config_icon = "📋" if result["has_config"] else "⚠️"
        print(f"{status_icon} {config_icon} {result['version']:40s} | {result['status']}")

    # 분류
    classification = classify_strategies(all_strategies)

    print("\n" + "=" * 80)
    print("분류 결과 요약")
    print("=" * 80)

    print(f"\n🟢 Priority 1 (신뢰 가능): {len(classification['priority_1'])}개")
    for s in classification['priority_1']:
        print(f"   - {s['version']}")

    print(f"\n🟡 Priority 2 (검증 필요): {len(classification['priority_2'])}개")
    for s in classification['priority_2']:
        print(f"   - {s['version']}")

    print(f"\n🔵 Priority 3 (초기 전략): {len(classification['priority_3'])}개")
    print(f"   (총 {len(classification['priority_3'])}개 - 생략)")

    print(f"\n❌ 폐기: {len(classification['discard'])}개")
    for s in classification['discard']:
        print(f"   - {s['version']}: {s['status']}")

    print(f"\n⚠️ 개발 미완성: {len(classification['incomplete'])}개")
    for s in classification['incomplete']:
        print(f"   - {s['version']}")

    print(f"\n❓ 백테스트 없음: {len(classification['no_backtest'])}개")
    for s in classification['no_backtest']:
        print(f"   - {s['version']}")

    # JSON 저장
    output = {
        "scan_date": "2025-10-21",
        "total_strategies": len(all_strategies),
        "classification": classification,
        "all_strategies": all_strategies
    }

    output_path = Path("/Users/bongbong/SynologyDrive/vendor/sandbox/251015_봉봇/validation/strategy_scan_result.json")
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"\n결과 저장: {output_path}")

    # 통계
    total_with_backtest = sum(1 for s in all_strategies if s['has_backtest'])
    total_processable = len(classification['priority_1']) + len(classification['priority_2']) + len(classification['priority_3'])

    print("\n" + "=" * 80)
    print("통계")
    print("=" * 80)
    print(f"전체 전략: {len(all_strategies)}개")
    print(f"백테스트 있음: {total_with_backtest}개")
    print(f"처리 가능: {total_processable}개")
    print(f"폐기: {len(classification['discard'])}개")
    print(f"미완성: {len(classification['incomplete'])}개")
    print(f"백테스트 없음: {len(classification['no_backtest'])}개")

if __name__ == "__main__":
    main()
