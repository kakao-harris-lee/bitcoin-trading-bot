"""
업비트 비트코인 데이터 수집 및 SQLite 저장
- 모든 시간단위 수집 (1분, 3분, 5분, 10분, 15분, 30분, 60분, 240분, 일, 주, 월)
- 결측값 선형보간 처리
"""

import requests
import sqlite3
import time
from datetime import datetime, timedelta
from typing import List, Dict, Optional
import pandas as pd


class UpbitBitcoinCollector:
    """업비트 비트코인 데이터 수집기"""

    # 업비트 지원 시간단위 (분 단위)
    TIMEFRAMES = {
        'minute1': 1,
        'minute3': 3,
        'minute5': 5,
        'minute10': 10,
        'minute15': 15,
        'minute30': 30,
        'minute60': 60,
        'minute240': 240,
        'day': 1440,
        'week': 10080,
        'month': 43200
    }

    API_URL = "https://api.upbit.com/v1/candles"
    MARKET = "KRW-BTC"
    MAX_COUNT = 200  # API 최대 요청 개수

    def __init__(self, db_path: str = "upbit_bitcoin.db"):
        self.db_path = db_path
        self.conn = None
        self.init_database()

    def init_database(self):
        """데이터베이스 초기화"""
        self.conn = sqlite3.connect(self.db_path)
        cursor = self.conn.cursor()

        # 각 시간단위별 테이블 생성
        for timeframe in self.TIMEFRAMES.keys():
            cursor.execute(f"""
                CREATE TABLE IF NOT EXISTS bitcoin_{timeframe} (
                    timestamp TEXT PRIMARY KEY,
                    opening_price REAL NOT NULL,
                    high_price REAL NOT NULL,
                    low_price REAL NOT NULL,
                    trade_price REAL NOT NULL,
                    candle_acc_trade_volume REAL NOT NULL,
                    candle_acc_trade_price REAL NOT NULL,
                    is_interpolated INTEGER DEFAULT 0
                )
            """)

        self.conn.commit()
        print(f"✓ 데이터베이스 초기화 완료: {self.db_path}")

    def fetch_candles(self, timeframe: str, to: Optional[str] = None) -> List[Dict]:
        """
        업비트 API로부터 캔들 데이터 가져오기

        Args:
            timeframe: 시간단위 (minute1, minute3, etc.)
            to: 마지막 캔들 시각 (ISO 8601 format)

        Returns:
            캔들 데이터 리스트
        """
        if timeframe.startswith('minute'):
            unit = timeframe.replace('minute', '')
            url = f"{self.API_URL}/minutes/{unit}"
        elif timeframe == 'day':
            url = f"{self.API_URL}/days"
        elif timeframe == 'week':
            url = f"{self.API_URL}/weeks"
        elif timeframe == 'month':
            url = f"{self.API_URL}/months"
        else:
            raise ValueError(f"Unknown timeframe: {timeframe}")

        params = {
            'market': self.MARKET,
            'count': self.MAX_COUNT
        }

        if to:
            params['to'] = to

        try:
            response = requests.get(url, params=params)
            response.raise_for_status()
            time.sleep(0.1)  # API 요청 제한 준수
            return response.json()
        except Exception as e:
            print(f"✗ API 요청 실패 ({timeframe}): {e}")
            return []

    def collect_all_data(self, timeframe: str):
        """
        특정 시간단위의 모든 가능한 데이터 수집

        Args:
            timeframe: 시간단위
        """
        print(f"\n{'='*60}")
        print(f"📊 {timeframe} 데이터 수집 시작")
        print(f"{'='*60}")

        total_count = 0
        to_timestamp = None
        iteration = 0
        prev_oldest_timestamp = None

        while True:
            iteration += 1
            candles = self.fetch_candles(timeframe, to_timestamp)

            if not candles:
                print("  ⚠️ 더 이상 데이터가 없습니다.")
                break

            oldest = candles[-1]
            current_oldest_timestamp = oldest['candle_date_time_kst']

            # 같은 데이터를 계속 반환하는 경우 중단
            if prev_oldest_timestamp == current_oldest_timestamp:
                print(f"  ⚠️ 동일한 데이터 반복 감지. 수집 중단.")
                break

            # 즉시 DB에 저장 (중단되어도 데이터 보존)
            saved_count = self.save_candles(timeframe, candles)

            total_count += saved_count
            # UTC 시간을 사용해야 과거 데이터를 가져올 수 있음
            to_timestamp = oldest['candle_date_time_utc']
            prev_oldest_timestamp = current_oldest_timestamp

            print(f"  반복 {iteration}: {len(candles)}개 수집, {saved_count}개 저장 (총 {total_count}개)")
            print(f"    최신: {candles[0]['candle_date_time_kst']}")
            print(f"    최고: {current_oldest_timestamp}")

            # 저장된 데이터가 없으면 (모두 중복) 중단
            if saved_count == 0:
                print(f"  ⚠️ 모든 데이터가 이미 존재합니다. 수집 중단.")
                break

            # 2019년 이전 데이터는 중단 (업비트 서비스 시작 시점)
            if datetime.fromisoformat(to_timestamp.replace('Z', '+00:00')).year < 2019:
                print(f"  ✓ 2019년 이전 데이터 도달. 수집 완료.")
                break

            time.sleep(0.2)  # API 요청 제한 준수

        print(f"\n✓ 총 {total_count}개 캔들 수집 및 저장 완료")

        # 결측값 보간
        self.interpolate_missing_data(timeframe)

    def save_candles(self, timeframe: str, candles: List[Dict]):
        """캔들 데이터를 DB에 저장하고 실제 저장된 개수 반환"""
        cursor = self.conn.cursor()

        inserted = 0
        for candle in candles:
            try:
                # 이미 존재하는지 확인
                cursor.execute(f"""
                    SELECT COUNT(*) FROM bitcoin_{timeframe}
                    WHERE timestamp = ?
                """, (candle['candle_date_time_kst'],))

                exists = cursor.fetchone()[0] > 0

                if not exists:
                    cursor.execute(f"""
                        INSERT INTO bitcoin_{timeframe}
                        (timestamp, opening_price, high_price, low_price,
                         trade_price, candle_acc_trade_volume, candle_acc_trade_price, is_interpolated)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 0)
                    """, (
                        candle['candle_date_time_kst'],
                        candle['opening_price'],
                        candle['high_price'],
                        candle['low_price'],
                        candle['trade_price'],
                        candle['candle_acc_trade_volume'],
                        candle['candle_acc_trade_price']
                    ))
                    inserted += 1
            except Exception as e:
                print(f"✗ 저장 실패: {e}")

        self.conn.commit()
        return inserted

    def interpolate_missing_data(self, timeframe: str):
        """
        결측값 선형보간 처리

        연속된 타임스탬프 사이의 빈 구간을 찾아서 양쪽 값을 기준으로 선형보간
        """
        print(f"\n🔧 {timeframe} 결측값 보간 시작...")

        cursor = self.conn.cursor()

        # 모든 데이터 가져오기 (시간순 정렬)
        cursor.execute(f"""
            SELECT timestamp, opening_price, high_price, low_price,
                   trade_price, candle_acc_trade_volume, candle_acc_trade_price
            FROM bitcoin_{timeframe}
            WHERE is_interpolated = 0
            ORDER BY timestamp ASC
        """)

        rows = cursor.fetchall()
        if len(rows) < 2:
            print("  데이터 부족으로 보간 불가")
            return

        interval_minutes = self.TIMEFRAMES[timeframe]
        interpolated_count = 0

        for i in range(len(rows) - 1):
            current_time = datetime.fromisoformat(rows[i][0])
            next_time = datetime.fromisoformat(rows[i+1][0])

            expected_next = current_time + timedelta(minutes=interval_minutes)

            # 결측 구간 확인
            if next_time > expected_next:
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
                        cursor.execute(f"""
                            INSERT OR REPLACE INTO bitcoin_{timeframe}
                            (timestamp, opening_price, high_price, low_price,
                             trade_price, candle_acc_trade_volume, candle_acc_trade_price, is_interpolated)
                            VALUES (?, ?, ?, ?, ?, ?, ?, 1)
                        """, (
                            interpolated_time.isoformat(),
                            *interpolated_values
                        ))

                        interpolated_count += 1

        self.conn.commit()
        print(f"✓ {interpolated_count}개 결측값 보간 완료")

    def collect_all_timeframes(self):
        """모든 시간단위 데이터 수집"""
        print("\n" + "="*60)
        print("🚀 업비트 비트코인 전체 데이터 수집 시작")
        print("="*60)

        for timeframe in self.TIMEFRAMES.keys():
            try:
                self.collect_all_data(timeframe)
            except Exception as e:
                print(f"\n✗ {timeframe} 수집 실패: {e}")
                continue

        print("\n" + "="*60)
        print("✅ 모든 시간단위 데이터 수집 완료")
        print("="*60)

        self.print_statistics()

    def print_statistics(self):
        """수집된 데이터 통계 출력"""
        print("\n📈 데이터 통계:")
        print("-" * 60)

        cursor = self.conn.cursor()

        for timeframe in self.TIMEFRAMES.keys():
            cursor.execute(f"""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN is_interpolated = 0 THEN 1 ELSE 0 END) as original,
                    SUM(CASE WHEN is_interpolated = 1 THEN 1 ELSE 0 END) as interpolated,
                    MIN(timestamp) as oldest,
                    MAX(timestamp) as newest
                FROM bitcoin_{timeframe}
            """)

            stats = cursor.fetchone()

            if stats[0] > 0:  # 데이터가 있을 때만 출력
                print(f"\n{timeframe}:")
                print(f"  전체: {stats[0]:,}개")
                print(f"  원본: {stats[1] or 0:,}개")
                print(f"  보간: {stats[2] or 0:,}개")
                print(f"  기간: {stats[3]} ~ {stats[4]}")

    def close(self):
        """데이터베이스 연결 종료"""
        if self.conn:
            self.conn.close()
            print("\n✓ 데이터베이스 연결 종료")


def main():
    """메인 실행 함수"""
    collector = UpbitBitcoinCollector("upbit_bitcoin.db")

    try:
        collector.collect_all_timeframes()
    except KeyboardInterrupt:
        print("\n\n⚠️ 사용자에 의해 중단됨")
    except Exception as e:
        print(f"\n✗ 오류 발생: {e}")
    finally:
        collector.close()


if __name__ == "__main__":
    main()
