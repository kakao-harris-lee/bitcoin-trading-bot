#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Short-Term Variant Generator
Base 전략(vXX)을 단타 변형(vXX-YY)으로 자동 생성
"""

import sys
import os
import argparse
import json
import shutil
from pathlib import Path


def generate_variant(base_strategy, variant_num, timeframe, trailing_stop):
    """
    단타 변형 생성

    Args:
        base_strategy: Base 전략 이름 (예: v17_vwap_breakout)
        variant_num: 변형 번호 (01, 02, 03, ...)
        timeframe: 새 타임프레임 (minute240, minute60, ...)
        trailing_stop: Trailing Stop 비율 (0.12, 0.08, ...)
    """
    # Base 전략 경로
    base_path = Path(f"strategies/{base_strategy}")

    if not base_path.exists():
        print(f"❌ Base 전략을 찾을 수 없습니다: {base_path}")
        sys.exit(1)

    # Base 전략 버전 추출 (예: v17)
    base_version = base_strategy.split("_")[0]  # v17

    # 변형 전략 경로
    variant_name = f"{base_version}-{variant_num}_{timeframe}"
    variant_path = Path(f"strategies/{variant_name}")

    if variant_path.exists():
        print(f"⚠️  변형 전략이 이미 존재합니다: {variant_path}")
        response = input("덮어쓰시겠습니까? (y/N): ")
        if response.lower() != 'y':
            print("취소됨")
            sys.exit(0)
        shutil.rmtree(variant_path)

    print(f"🚀 변형 전략 생성: {variant_name}")
    print(f"📁 Base: {base_strategy}")
    print(f"📁 변형: {variant_name}\n")

    # 폴더 생성
    variant_path.mkdir(parents=True)

    # 파일 복사
    files_to_copy = ["strategy.py", "backtest.py"]

    for filename in files_to_copy:
        src = base_path / filename
        dst = variant_path / filename

        if src.exists():
            shutil.copy(src, dst)
            print(f"✅ 복사: {filename}")
        else:
            print(f"⚠️  파일 없음: {filename}")

    # config.json 수정
    config_src = base_path / "config.json"

    if not config_src.exists():
        print(f"❌ config.json을 찾을 수 없습니다: {config_src}")
        sys.exit(1)

    with open(config_src, 'r', encoding='utf-8') as f:
        config = json.load(f)

    # 수정
    config['version'] = f"{base_version}-{variant_num}"
    config['strategy_name'] = f"{config['strategy_name']}_{timeframe}"
    config['description'] = f"{config.get('description', '')} (변형: {timeframe})"
    config['timeframe'] = timeframe
    config['trailing_stop'] = trailing_stop

    config_dst = variant_path / "config.json"

    with open(config_dst, 'w', encoding='utf-8') as f:
        json.dump(config, f, indent=2, ensure_ascii=False)

    print(f"✅ 생성: config.json (timeframe={timeframe}, trailing_stop={trailing_stop})")

    # README 생성
    readme_path = variant_path / "README.md"

    with open(readme_path, 'w', encoding='utf-8') as f:
        f.write(f"# {base_version}-{variant_num} ({timeframe})\n\n")
        f.write(f"## Base Strategy\n")
        f.write(f"- **Base**: {base_strategy}\n")
        f.write(f"- **변형 번호**: {variant_num}\n\n")
        f.write(f"## 변경 사항\n")
        f.write(f"- **타임프레임**: {config.get('timeframe', 'day')} → **{timeframe}**\n")
        f.write(f"- **Trailing Stop**: ? → **{trailing_stop*100:.0f}%**\n\n")
        f.write(f"## 목표\n")
        f.write(f"- 거래 횟수: Base × 3배 이상\n")
        f.write(f"- 승률: Base - 10%p 이상\n")
        f.write(f"- 수익률: Base × 0.8 이상\n\n")
        f.write(f"## 백테스팅\n")
        f.write(f"```bash\n")
        f.write(f"# 2022-2025 전체 테스트\n")
        f.write(f"cd strategies/{variant_name}\n\n")
        f.write(f"for year in 2022 2023 2024 2025; do\n")
        f.write(f"  python backtest.py --start-date ${{year}}-01-01 --end-date ${{year}}-12-31\n")
        f.write(f"  mv result.json result_${{year}}.json\n")
        f.write(f"done\n\n")
        f.write(f"# 4년 종합 분석\n")
        f.write(f"python ../../automation/analyze_multi_year_results.py --strategy-path .\n")
        f.write(f"```\n")

    print(f"✅ 생성: README.md")

    # 완료
    print(f"\n{'='*80}")
    print("✅ 변형 전략 생성 완료!")
    print(f"{'='*80}\n")

    print(f"📁 경로: {variant_path}")
    print(f"\n다음 단계:")
    print(f"  1. cd {variant_path}")
    print(f"  2. 백테스팅 실행 (README.md 참조)")
    print(f"  3. 결과 분석 및 Base 전략과 비교")


def main():
    parser = argparse.ArgumentParser(
        description="Short-Term Variant Generator (vXX → vXX-YY)"
    )
    parser.add_argument(
        "--base",
        type=str,
        required=True,
        help="Base 전략 이름 (예: v17_vwap_breakout)"
    )
    parser.add_argument(
        "--variant",
        type=str,
        required=True,
        help="변형 번호 (01, 02, 03, ...)"
    )
    parser.add_argument(
        "--timeframe",
        type=str,
        required=True,
        help="타임프레임 (minute240, minute60, minute15, ...)"
    )
    parser.add_argument(
        "--trailing-stop",
        type=float,
        required=True,
        help="Trailing Stop 비율 (0.12, 0.08, 0.05, ...)"
    )

    args = parser.parse_args()

    # 변형 번호 검증 (2자리 숫자)
    if not args.variant.isdigit() or len(args.variant) != 2:
        print("❌ 변형 번호는 2자리 숫자여야 합니다 (01, 02, 03, ...)")
        sys.exit(1)

    # Trailing Stop 범위 검증
    if not (0.01 <= args.trailing_stop <= 0.50):
        print("❌ Trailing Stop은 0.01 ~ 0.50 사이여야 합니다")
        sys.exit(1)

    generate_variant(
        base_strategy=args.base,
        variant_num=args.variant,
        timeframe=args.timeframe,
        trailing_stop=args.trailing_stop
    )


if __name__ == "__main__":
    main()
