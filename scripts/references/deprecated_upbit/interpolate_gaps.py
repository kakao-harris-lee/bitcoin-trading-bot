#!/usr/bin/env python3
"""
데이터 누락 구간 선형보간 처리

API에서도 확보할 수 없는 미세한 누락 구간을
이전 값과 이후 값을 기준으로 선형보간합니다.

[DEPRECATED]
Spot/Binance 운영 전환으로 현재 파이프라인에서는 사용하지 않습니다.

Usage:
    python scripts/references/deprecated_upbit/interpolate_gaps.py
"""

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict


class DataInterpolator:
    """데이터 보간 처리기"""

    # 타임프레임별 분 단위
    TIMEFRAMES = {
        'minute5': 5,
        'minute15': 15,
        'minute30': 30,
        'minute60': 60,
        'minute240': 240,
        'day': 1440
    }

    def __init__(self, db_path: str = "data/upbit_bitcoin.db"):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"DB 파일을 찾을 수 없습니다: {db_path}")

        self.conn = sqlite3.connect(str(self.db_path))
        self.cursor = self.conn.cursor()

    def interpolate_timeframe(self, timeframe: str) -> int:
        """
        특정 타임프레임의 결측값 보간

        Args:
            timeframe: 타임프레임 (minute5, minute15, etc.)

        Returns:
            보간된 캔들 개수
        """
        print(f"\n{'='*60}")
        print(f"🔧 {timeframe} 결측값 보간 시작...")
        print(f"{'='*60}")

        # 모든 데이터 가져오기 (시간순 정렬, 보간 데이터 제외)
        self.cursor.execute(f"""
            SELECT timestamp, opening_price, high_price, low_price,
                   trade_price, candle_acc_trade_volume, candle_acc_trade_price
            FROM bitcoin_{timeframe}
            WHERE is_interpolated = 0
            ORDER BY timestamp ASC
        """)

        rows = self.cursor.fetchall()

        if len(rows) < 2:
            print("  ⚠️  데이터 부족으로 보간 불가")
            return 0

        interval_minutes = self.TIMEFRAMES[timeframe]
        interpolated_count = 0
        gaps_found = 0

        for i in range(len(rows) - 1):
            current_time = datetime.fromisoformat(rows[i][0])
            next_time = datetime.fromisoformat(rows[i+1][0])

            expected_next = current_time + timedelta(minutes=interval_minutes)

            # 결측 구간 확인
            if next_time > expected_next:
                gaps_found += 1

                # 결측값 개수 계산
                gap = (next_time - current_time).total_seconds() / 60 / interval_minutes
                missing_count = int(gap) - 1

                if missing_count > 0:
                    # 양쪽 값
                    current_values = rows[i][1:]
                    next_values = rows[i+1][1:]

                    # 선형보간
                    for j in range(1, missing_count + 1):
                        ratio = j / (missing_count + 1)
                        interpolated_time = current_time + timedelta(minutes=interval_minutes * j)

                        interpolated_values = [
                            current_values[k] + (next_values[k] - current_values[k]) * ratio
                            for k in range(len(current_values))
                        ]

                        # DB에 삽입
                        try:
                            self.cursor.execute(f"""
                                INSERT OR REPLACE INTO bitcoin_{timeframe}
                                (timestamp, opening_price, high_price, low_price,
                                 trade_price, candle_acc_trade_volume, candle_acc_trade_price, is_interpolated)
                                VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                            """, (
                                interpolated_time.isoformat(),
                                *interpolated_values
                            ))

                            interpolated_count += 1

                        except Exception as e:
                            print(f"  ✗ 보간 실패 ({interpolated_time}): {e}")

        self.conn.commit()

        print(f"\n  📊 결과:")
        print(f"    누락 구간 발견: {gaps_found}개")
        print(f"    보간된 캔들: {interpolated_count}개")

        if interpolated_count > 0:
            print(f"    ✅ 보간 완료")
        else:
            print(f"    ✅ 보간 불필요 (연속 데이터)")

        return interpolated_count

    def interpolate_all(self) -> Dict[str, int]:
        """
        모든 타임프레임 보간

        Returns:
            타임프레임별 보간 개수
        """
        print("\n" + "="*60)
        print("🚀 전체 타임프레임 데이터 보간 시작")
        print("="*60)

        results = {}

        for timeframe in self.TIMEFRAMES.keys():
            try:
                count = self.interpolate_timeframe(timeframe)
                results[timeframe] = count

            except Exception as e:
                print(f"\n✗ {timeframe} 보간 실패: {e}")
                results[timeframe] = 0

        # 요약
        print("\n" + "="*60)
        print("📊 보간 요약")
        print("="*60)

        total_interpolated = sum(results.values())

        for tf, count in results.items():
            status = "✅" if count == 0 else f"🔧 {count:,}개 보간"
            print(f"  {tf:12s}: {status}")

        print(f"\n총 보간 캔들: {total_interpolated:,}개")

        return results

    def get_interpolation_stats(self) -> Dict:
        """
        보간 통계 확인

        Returns:
            타임프레임별 보간 통계
        """
        print("\n" + "="*60)
        print("📊 보간 데이터 통계")
        print("="*60)

        stats = {}

        for timeframe in self.TIMEFRAMES.keys():
            self.cursor.execute(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_interpolated = 0 THEN 1 ELSE 0 END) as original,
                    SUM(CASE WHEN is_interpolated = 1 THEN 1 ELSE 0 END) as interpolated
                FROM bitcoin_{timeframe}
            """)

            row = self.cursor.fetchone()

            total = row[0]
            original = row[1] or 0
            interpolated = row[2] or 0

            interpolation_rate = (interpolated / total * 100) if total > 0 else 0

            stats[timeframe] = {
                "total": total,
                "original": original,
                "interpolated": interpolated,
                "interpolation_rate": interpolation_rate
            }

            print(f"\n{timeframe}:")
            print(f"  전체: {total:,}개")
            print(f"  원본: {original:,}개")
            print(f"  보간: {interpolated:,}개 ({interpolation_rate:.2f}%)")

        return stats

    def close(self):
        """데이터베이스 연결 종료"""
        if self.conn:
            self.conn.close()


def main():
    """메인 실행 함수"""

    # DB 경로 설정
    db_path = Path(__file__).parent.parent / "data" / "upbit_bitcoin.db"

    if not db_path.exists():
        print(f"❌ DB 파일을 찾을 수 없습니다: {db_path}")
        return

    interpolator = DataInterpolator(str(db_path))

    try:
        # 모든 타임프레임 보간
        results = interpolator.interpolate_all()

        # 보간 통계 확인
        stats = interpolator.get_interpolation_stats()

        # 최종 결과
        print("\n" + "="*60)
        total_interpolated = sum(results.values())

        if total_interpolated > 0:
            print(f"✅ 총 {total_interpolated:,}개 캔들 보간 완료")
        else:
            print("✅ 모든 데이터가 연속적입니다 (보간 불필요)")

        print("="*60)

        print("\n다음 단계:")
        print("   python automation/verify_all_timeframes.py  # 최종 검증")

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    finally:
        interpolator.close()


if __name__ == "__main__":
    main()
