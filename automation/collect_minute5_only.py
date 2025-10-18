#!/usr/bin/env python3
"""
minute5 데이터만 수집하는 스크립트

Usage:
    python automation/collect_minute5_only.py
"""

import sys
from pathlib import Path

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "v1_db생성"))

from upbit_bitcoin_collector import UpbitBitcoinCollector


def main():
    """메인 실행 함수"""

    print("\n" + "="*60)
    print("🚀 minute5 데이터 수집 시작")
    print("="*60)
    print("\n📊 현재 상태:")
    print("   - 현재: 119,680개 (2024-08-26 ~ 2025-10-16)")
    print("   - 목표: 210,240개 (2024-01-01 ~ 2025-12-31)")
    print("   - 수집: 90,560개 캔들")
    print("\n⏱️  예상 소요 시간:")
    print("   - 약 1시간 (API Rate Limit 준수)")
    print("   - 90,560개 캔들 × 0.1초 = 약 2.5시간")
    print("   - 실제로는 200개씩 묶어서 가져와서 더 빠름")
    print("\n💡 진행 방식:")
    print("   1. 업비트 API에서 과거 데이터 조회")
    print("   2. 200개씩 묶어서 수집")
    print("   3. 중복 체크 후 DB 저장")
    print("   4. 자동으로 선형보간 적용")
    print("\n⚠️  주의사항:")
    print("   - Ctrl+C로 언제든지 중단 가능")
    print("   - 진행된 데이터는 자동 저장됨")
    print("   - 재실행 시 이어서 수집됨")
    print("\n" + "="*60)

    response = input("\n계속 진행하시겠습니까? (y/N): ").strip().lower()

    if response != 'y':
        print("\n❌ 사용자에 의해 취소되었습니다.")
        return

    # DB 경로 설정
    db_path = project_root / "upbit_bitcoin.db"

    if not db_path.exists():
        print(f"\n❌ DB 파일을 찾을 수 없습니다: {db_path}")
        return

    # 수집기 초기화
    collector = UpbitBitcoinCollector(str(db_path))

    try:
        print("\n" + "="*60)
        print("📊 minute5 데이터 수집 시작")
        print("="*60)

        # minute5만 수집
        collector.collect_all_data('minute5')

        print("\n" + "="*60)
        print("✅ minute5 데이터 수집 완료!")
        print("="*60)

        # 통계 출력
        collector.print_statistics()

        print("\n다음 단계:")
        print("   1. python automation/interpolate_gaps.py  # 선형보간")
        print("   2. python automation/verify_all_timeframes.py  # 최종 검증")

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
