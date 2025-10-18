#!/usr/bin/env python3
"""
전체 타임프레임 데이터 검증 및 누락 구간 리포트 생성

Usage:
    python automation/verify_all_timeframes.py
"""

import sqlite3
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Tuple


class TimeframeVerifier:
    """타임프레임 데이터 검증기"""

    # 타임프레임별 분 단위
    TIMEFRAMES = {
        'minute5': 5,
        'minute15': 15,
        'minute30': 30,
        'minute60': 60,
        'minute240': 240,
        'day': 1440
    }

    def __init__(self, db_path: str = "upbit_bitcoin.db"):
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"DB 파일을 찾을 수 없습니다: {db_path}")

        self.conn = sqlite3.connect(str(self.db_path))
        self.cursor = self.conn.cursor()

    def calculate_expected_candles(self, timeframe: str, start_date: str, end_date: str) -> int:
        """
        기대되는 캔들 개수 계산

        Args:
            timeframe: 타임프레임 (minute5, minute15, etc.)
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)

        Returns:
            기대되는 캔들 개수
        """
        start = datetime.fromisoformat(start_date)
        end = datetime.fromisoformat(end_date)

        total_minutes = (end - start).total_seconds() / 60
        interval_minutes = self.TIMEFRAMES[timeframe]

        expected = int(total_minutes / interval_minutes)

        return expected

    def get_actual_candles(self, timeframe: str, start_date: str, end_date: str) -> int:
        """
        실제 저장된 캔들 개수 확인

        Args:
            timeframe: 타임프레임
            start_date: 시작일
            end_date: 종료일

        Returns:
            실제 캔들 개수
        """
        self.cursor.execute(f"""
            SELECT COUNT(*) FROM bitcoin_{timeframe}
            WHERE timestamp >= ? AND timestamp <= ?
        """, (start_date, end_date))

        return self.cursor.fetchone()[0]

    def find_gaps(self, timeframe: str, start_date: str, end_date: str) -> List[Dict]:
        """
        누락 구간 찾기

        Args:
            timeframe: 타임프레임
            start_date: 시작일
            end_date: 종료일

        Returns:
            누락 구간 리스트 [{"start": "...", "end": "...", "missing_count": N}, ...]
        """
        interval_minutes = self.TIMEFRAMES[timeframe]

        # 모든 데이터 가져오기 (시간순 정렬)
        self.cursor.execute(f"""
            SELECT timestamp FROM bitcoin_{timeframe}
            WHERE timestamp >= ? AND timestamp <= ?
            ORDER BY timestamp ASC
        """, (start_date, end_date))

        rows = self.cursor.fetchall()

        if len(rows) < 2:
            return []

        gaps = []

        for i in range(len(rows) - 1):
            current_time = datetime.fromisoformat(rows[i][0])
            next_time = datetime.fromisoformat(rows[i+1][0])

            expected_next = current_time + timedelta(minutes=interval_minutes)

            # 누락 구간 확인
            if next_time > expected_next:
                gap_minutes = (next_time - current_time).total_seconds() / 60
                missing_count = int(gap_minutes / interval_minutes) - 1

                if missing_count > 0:
                    gaps.append({
                        "start": current_time.isoformat(),
                        "end": next_time.isoformat(),
                        "missing_count": missing_count
                    })

        return gaps

    def get_data_range(self, timeframe: str) -> Tuple[str, str]:
        """
        데이터 범위 확인

        Args:
            timeframe: 타임프레임

        Returns:
            (최소 시간, 최대 시간)
        """
        self.cursor.execute(f"""
            SELECT MIN(timestamp), MAX(timestamp)
            FROM bitcoin_{timeframe}
        """)

        result = self.cursor.fetchone()
        return result[0] or "", result[1] or ""

    def verify_period(self, timeframe: str, start_date: str, end_date: str) -> Dict:
        """
        특정 기간의 완전성 검증

        Args:
            timeframe: 타임프레임
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)

        Returns:
            검증 결과 딕셔너리
        """
        print(f"\n{'='*60}")
        print(f"🔍 {timeframe} 검증 중...")
        print(f"{'='*60}")

        # 데이터 범위 확인
        data_start, data_end = self.get_data_range(timeframe)

        print(f"  실제 데이터 범위: {data_start} ~ {data_end}")
        print(f"  검증 대상 기간: {start_date} ~ {end_date}")

        # 기대 캔들 개수
        expected = self.calculate_expected_candles(timeframe, start_date, end_date)

        # 실제 캔들 개수
        actual = self.get_actual_candles(timeframe, start_date, end_date)

        # 누락 개수
        missing = expected - actual

        # 완전성 비율
        completeness = (actual / expected * 100) if expected > 0 else 0

        print(f"\n  📊 통계:")
        print(f"    기대 캔들: {expected:,}개")
        print(f"    실제 캔들: {actual:,}개")
        print(f"    누락 캔들: {missing:,}개")
        print(f"    완전성: {completeness:.2f}%")

        # 누락 구간 찾기
        gaps = self.find_gaps(timeframe, start_date, end_date)

        if gaps:
            print(f"\n  ⚠️  누락 구간: {len(gaps)}개")
            total_missing = sum(g['missing_count'] for g in gaps)
            print(f"    총 누락 캔들: {total_missing:,}개")

            # 상위 5개 구간 표시
            print(f"\n  📋 주요 누락 구간 (상위 5개):")
            for gap in sorted(gaps, key=lambda x: x['missing_count'], reverse=True)[:5]:
                print(f"    - {gap['start']} ~ {gap['end']}: {gap['missing_count']:,}개")
        else:
            print(f"\n  ✅ 누락 구간 없음 (완전)")

        return {
            "timeframe": timeframe,
            "period": {
                "start": start_date,
                "end": end_date
            },
            "data_range": {
                "start": data_start,
                "end": data_end
            },
            "statistics": {
                "expected_candles": expected,
                "actual_candles": actual,
                "missing_candles": missing,
                "completeness_percent": round(completeness, 2)
            },
            "gaps": gaps,
            "is_complete": len(gaps) == 0 and missing == 0
        }

    def verify_all(self, start_date: str = "2024-01-01", end_date: str = "2025-12-31") -> Dict:
        """
        모든 타임프레임 검증

        Args:
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)

        Returns:
            전체 검증 결과
        """
        print("\n" + "="*60)
        print("🚀 전체 타임프레임 데이터 검증 시작")
        print("="*60)
        print(f"기간: {start_date} ~ {end_date}")

        results = {
            "verification_date": datetime.now().isoformat(),
            "target_period": {
                "start": start_date,
                "end": end_date
            },
            "timeframes": {}
        }

        for timeframe in self.TIMEFRAMES.keys():
            result = self.verify_period(timeframe, start_date, end_date)
            results["timeframes"][timeframe] = result

        # 요약
        print("\n" + "="*60)
        print("📊 검증 요약")
        print("="*60)

        complete_count = sum(1 for r in results["timeframes"].values() if r["is_complete"])
        total_count = len(results["timeframes"])

        print(f"\n완전한 타임프레임: {complete_count}/{total_count}")

        for tf, result in results["timeframes"].items():
            status = "✅" if result["is_complete"] else "❌"
            completeness = result["statistics"]["completeness_percent"]
            missing = result["statistics"]["missing_candles"]

            print(f"  {status} {tf:12s}: {completeness:6.2f}% "
                  f"(누락: {missing:,}개)")

        results["summary"] = {
            "complete_timeframes": complete_count,
            "total_timeframes": total_count,
            "all_complete": complete_count == total_count
        }

        return results

    def save_report(self, results: Dict, output_path: str = "data_gap_report.json"):
        """
        검증 결과를 JSON 파일로 저장

        Args:
            results: 검증 결과
            output_path: 출력 파일 경로
        """
        output_file = Path(output_path)

        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(results, f, indent=2, ensure_ascii=False)

        print(f"\n✅ 검증 리포트 저장: {output_file.absolute()}")
        print(f"   파일 크기: {output_file.stat().st_size:,} bytes")

    def close(self):
        """데이터베이스 연결 종료"""
        if self.conn:
            self.conn.close()


def main():
    """메인 실행 함수"""

    # DB 경로 설정
    db_path = Path(__file__).parent.parent / "upbit_bitcoin.db"

    if not db_path.exists():
        print(f"❌ DB 파일을 찾을 수 없습니다: {db_path}")
        print(f"   현재 작업 디렉토리: {Path.cwd()}")
        return

    verifier = TimeframeVerifier(str(db_path))

    try:
        # 2024~2025년 전체 검증
        results = verifier.verify_all(
            start_date="2024-01-01",
            end_date="2025-12-31"
        )

        # 리포트 저장
        report_path = Path(__file__).parent.parent / "data_gap_report.json"
        verifier.save_report(results, str(report_path))

        # 최종 결과
        print("\n" + "="*60)
        if results["summary"]["all_complete"]:
            print("🎉 모든 타임프레임이 완전합니다!")
        else:
            incomplete = len(results["timeframes"]) - results["summary"]["complete_timeframes"]
            print(f"⚠️  {incomplete}개 타임프레임에 누락 데이터가 있습니다.")
            print(f"   다음 단계: python automation/collect_missing_data.py")
        print("="*60)

    except Exception as e:
        print(f"\n❌ 오류 발생: {e}")
        import traceback
        traceback.print_exc()

    finally:
        verifier.close()


if __name__ == "__main__":
    main()
