#!/usr/bin/env python3
"""
minute5 데이터 수집 (과거 데이터까지 수집)

기존 collect_all_data의 중복 중단 로직을 우회하여
2024-01-01까지 과거 데이터를 강제로 수집합니다.

Usage:
    python automation/collect_minute5_fixed.py
"""

import sys
import time
from pathlib import Path
from datetime import datetime

# 프로젝트 루트를 경로에 추가
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "upbit_history_db"))

from upbit_bitcoin_collector import UpbitBitcoinCollector


class ExtendedCollector(UpbitBitcoinCollector):
    """확장된 수집기 (과거 데이터까지 수집)"""

    def collect_to_target_date(self, timeframe: str, target_date: str):
        """
        목표 날짜까지 데이터 수집

        Args:
            timeframe: 시간단위
            target_date: 목표 날짜 (YYYY-MM-DD)
        """
        print(f"\n{'='*60}")
        print(f"📊 {timeframe} 데이터 수집 시작")
        print(f"   목표: {target_date}까지 수집")
        print(f"{'='*60}")

        total_count = 0
        total_saved = 0
        to_timestamp = None
        iteration = 0
        prev_oldest_timestamp = None
        consecutive_duplicates = 0

        target_dt = datetime.fromisoformat(target_date)

        while True:
            iteration += 1
            candles = self.fetch_candles(timeframe, to_timestamp)

            if not candles:
                print("  ⚠️  더 이상 데이터가 없습니다.")
                break

            oldest = candles[-1]
            current_oldest_timestamp = oldest['candle_date_time_kst']
            current_oldest_dt = datetime.fromisoformat(current_oldest_timestamp)

            # 목표 날짜 도달 확인
            if current_oldest_dt <= target_dt:
                print(f"\n  ✅ 목표 날짜 도달: {current_oldest_timestamp}")
                # 마지막 배치 저장
                saved_count = self.save_candles(timeframe, candles)
                total_count += len(candles)
                total_saved += saved_count
                break

            # 같은 데이터를 계속 반환하는 경우 중단
            if prev_oldest_timestamp == current_oldest_timestamp:
                print(f"  ⚠️  동일한 데이터 반복 감지. 수집 중단.")
                break

            # DB에 저장
            saved_count = self.save_candles(timeframe, candles)

            total_count += len(candles)
            total_saved += saved_count

            # UTC 시간을 사용해야 과거 데이터를 가져올 수 있음
            to_timestamp = oldest['candle_date_time_utc']
            prev_oldest_timestamp = current_oldest_timestamp

            # 진행 상황 출력
            if iteration % 10 == 0 or saved_count > 0:
                print(f"  반복 {iteration}: {len(candles)}개 수집, {saved_count}개 저장 "
                      f"(총 수집: {total_count:,}개, 저장: {total_saved:,}개)")
                print(f"    최고: {current_oldest_timestamp}")

            # 연속 중복 체크 (10회 연속 중복이면 경고)
            if saved_count == 0:
                consecutive_duplicates += 1
                if consecutive_duplicates >= 10:
                    print(f"  ⚠️  연속 {consecutive_duplicates}회 중복 - 계속 진행 중...")
                    consecutive_duplicates = 0
            else:
                consecutive_duplicates = 0

            # 2019년 이전 데이터는 중단
            if current_oldest_dt.year < 2019:
                print(f"  ✓ 2019년 이전 데이터 도달. 수집 완료.")
                break

            time.sleep(0.15)  # API 요청 제한 준수

        print(f"\n✅ 총 {total_count:,}개 캔들 수집, {total_saved:,}개 저장 완료")

        # 결측값 보간
        print(f"\n🔧 결측값 보간 시작...")
        self.interpolate_missing_data(timeframe)


def main():
    """메인 실행 함수"""

    target_date = "2024-01-01"

    print("\n" + "="*60)
    print("🚀 minute5 데이터 수집 (과거 데이터 포함)")
    print("="*60)
    print(f"\n🎯 목표:")
    print(f"   - 수집 범위: {target_date} ~ 현재")
    print(f"   - 예상: 약 90,000개 캔들")
    print("\n⏱️  예상 소요 시간:")
    print(f"   - 약 1~2시간")
    print(f"   - 200개씩 묶어서 수집")
    print(f"   - 약 450회 반복 (90,000 / 200)")
    print("\n💡 개선사항:")
    print("   - 중복 데이터 구간도 건너뛰지 않고 계속 진행")
    print("   - 목표 날짜까지 강제로 수집")
    print("   - 진행 상황 실시간 표시")
    print("\n⚠️  주의사항:")
    print("   - Ctrl+C로 언제든지 중단 가능")
    print("   - 진행된 데이터는 자동 저장됨")
    print("   - 재실행 시 이어서 수집됨")
    print("\n" + "="*60)

    # 자동 진행 (백그라운드 실행 시)
    import sys
    if sys.stdin.isatty():
        response = input("\n계속 진행하시겠습니까? (y/N): ").strip().lower()
        if response != 'y':
            print("\n❌ 사용자에 의해 취소되었습니다.")
            return
    else:
        print("\n✅ 자동 진행 모드")

    # DB 경로 설정
    db_path = project_root / "upbit_bitcoin.db"

    if not db_path.exists():
        print(f"\n❌ DB 파일을 찾을 수 없습니다: {db_path}")
        return

    # 확장 수집기 초기화
    collector = ExtendedCollector(str(db_path))

    try:
        # 시작 시간 기록
        start_time = datetime.now()
        print(f"\n⏰ 시작 시간: {start_time.strftime('%Y-%m-%d %H:%M:%S')}")

        # minute5 데이터 수집 (2024-01-01까지)
        collector.collect_to_target_date('minute5', target_date)

        # 종료 시간
        end_time = datetime.now()
        duration = end_time - start_time
        print(f"\n⏰ 종료 시간: {end_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"   소요 시간: {duration}")

        # 최종 통계
        print("\n" + "="*60)
        print("📊 최종 통계")
        print("="*60)
        collector.print_statistics()

        print("\n다음 단계:")
        print("   python automation/verify_all_timeframes.py  # 최종 검증")

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
