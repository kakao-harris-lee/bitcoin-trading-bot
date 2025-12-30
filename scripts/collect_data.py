#!/usr/bin/env python3
"""
누락된 데이터 수집 스크립트

기존 수집기(upbit_bitcoin_collector.py)를 활용하여
2024-01-01부터 시작하는 데이터를 확보합니다.

Usage:
    python automation/collect_missing_data.py
"""

import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "upbit_history_db"))

from upbit_bitcoin_collector import UpbitBitcoinCollector


def main():
    """메인 실행 함수"""

    print("\n" + "="*60)
    print("🚀 누락 데이터 수집 시작")
    print("="*60)
    print("\n📌 전략:")
    print("   1. 기존 수집기(upbit_bitcoin_collector.py) 사용")
    print("   2. 자동으로 기존 데이터와 비교하여 누락분만 수집")
    print("   3. 선형보간 자동 적용")
    print("\n⏱️  예상 소요 시간:")
    print("   - minute5: ~1시간 (90,560개 캔들)")
    print("   - minute15: ~15분 (7,247개 캔들)")
    print("   - minute30: ~8분 (3,623개 캔들)")
    print("   - minute60: ~4분 (1,811개 캔들)")
    print("   - minute240: ~1분 (453개 캔들)")
    print("   - day: ~10초 (75개 캔들)")
    print("\n⚠️  주의사항:")
    print("   - API Rate Limit: 업비트 초당 10회 제한 준수")
    print("   - 중단 시에도 진행된 데이터는 저장됨")
    print("   - Ctrl+C로 언제든지 중단 가능")
    print("\n" + "="*60)

    response = input("\n계속 진행하시겠습니까? (y/N): ").strip().lower()

    if response != 'y':
        print("\n❌ 사용자에 의해 취소되었습니다.")
        return

    # DB 경로 설정
    db_path = project_root / "data" / "upbit_bitcoin.db"

    if not db_path.exists():
        print(f"\n❌ DB 파일을 찾을 수 없습니다: {db_path}")
        return

    # 수집기 초기화
    collector = UpbitBitcoinCollector(str(db_path))

    try:
        print("\n" + "="*60)
        print("📊 데이터 수집 시작")
        print("="*60)
        print("\n💡 팁:")
        print("   - 각 타임프레임마다 즉시 DB에 저장됩니다")
        print("   - 중단해도 진행된 데이터는 보존됩니다")
        print("   - 재실행 시 중복 체크로 누락분만 추가 수집됩니다")
        print()

        # 모든 타임프레임 수집
        collector.collect_all_timeframes()

        print("\n" + "="*60)
        print("✅ 데이터 수집 완료!")
        print("="*60)
        print("\n다음 단계:")
        print("   1. python automation/interpolate_gaps.py  # 미세 누락 보간")
        print("   2. python automation/verify_all_timeframes.py  # 재검증")

    except KeyboardInterrupt:
        print("\n\n⚠️  사용자에 의해 중단되었습니다.")
        print("   진행된 데이터는 저장되었습니다.")
        print("   재실행 시 이어서 수집됩니다.")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    finally:
        collector.close()


if __name__ == "__main__":
    main()
