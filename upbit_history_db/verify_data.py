"""
업비트 비트코인 DB 데이터 검증 스크립트
"""

import sqlite3
from datetime import datetime

def verify_database(db_path="upbit_bitcoin.db"):
    """데이터베이스 검증"""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    timeframes = ['minute1', 'minute3', 'minute5', 'minute10', 'minute15',
                  'minute30', 'minute60', 'minute240', 'day', 'week', 'month']

    print("="*80)
    print("📊 업비트 비트코인 데이터베이스 검증")
    print("="*80)

    for timeframe in timeframes:
        print(f"\n{'='*80}")
        print(f"🔍 {timeframe} 테이블 검증")
        print('='*80)

        # 테이블 존재 확인
        cursor.execute(f"""
            SELECT name FROM sqlite_master
            WHERE type='table' AND name='bitcoin_{timeframe}'
        """)

        if not cursor.fetchone():
            print(f"  ✗ 테이블이 존재하지 않습니다.")
            continue

        # 전체 데이터 개수
        cursor.execute(f"SELECT COUNT(*) FROM bitcoin_{timeframe}")
        total_count = cursor.fetchone()[0]

        # 원본 데이터 개수
        cursor.execute(f"""
            SELECT COUNT(*) FROM bitcoin_{timeframe}
            WHERE is_interpolated = 0
        """)
        original_count = cursor.fetchone()[0]

        # 보간 데이터 개수
        cursor.execute(f"""
            SELECT COUNT(*) FROM bitcoin_{timeframe}
            WHERE is_interpolated = 1
        """)
        interpolated_count = cursor.fetchone()[0]

        # 시간 범위
        cursor.execute(f"""
            SELECT MIN(timestamp), MAX(timestamp)
            FROM bitcoin_{timeframe}
        """)
        time_range = cursor.fetchone()

        # 샘플 데이터 (최신 5개)
        cursor.execute(f"""
            SELECT timestamp, opening_price, high_price, low_price,
                   trade_price, is_interpolated
            FROM bitcoin_{timeframe}
            ORDER BY timestamp DESC
            LIMIT 5
        """)
        samples = cursor.fetchall()

        print(f"\n  📈 통계:")
        print(f"    전체 데이터: {total_count:,}개")
        print(f"    원본 데이터: {original_count:,}개")
        print(f"    보간 데이터: {interpolated_count:,}개")

        if total_count > 0:
            print(f"    보간 비율: {interpolated_count/total_count*100:.2f}%")

        print(f"\n  📅 시간 범위:")
        print(f"    최고: {time_range[0]}")
        print(f"    최신: {time_range[1]}")

        print(f"\n  💾 샘플 데이터 (최신 5개):")
        print(f"    {'시간':<20} {'시가':<15} {'고가':<15} {'저가':<15} {'종가':<15} {'보간'}")
        print(f"    {'-'*95}")

        for sample in samples:
            interpolated_mark = "✓" if sample[5] == 1 else ""
            print(f"    {sample[0]:<20} {sample[1]:<15,.0f} {sample[2]:<15,.0f} "
                  f"{sample[3]:<15,.0f} {sample[4]:<15,.0f} {interpolated_mark}")

        # 데이터 무결성 검증
        print(f"\n  🔧 데이터 무결성 검증:")

        # NULL 값 확인
        cursor.execute(f"""
            SELECT COUNT(*) FROM bitcoin_{timeframe}
            WHERE opening_price IS NULL OR high_price IS NULL
               OR low_price IS NULL OR trade_price IS NULL
        """)
        null_count = cursor.fetchone()[0]

        if null_count == 0:
            print(f"    ✓ NULL 값 없음")
        else:
            print(f"    ✗ NULL 값 발견: {null_count}개")

        # 가격 유효성 검증 (고가 >= 저가, 시가/종가가 고가-저가 범위 내)
        cursor.execute(f"""
            SELECT COUNT(*) FROM bitcoin_{timeframe}
            WHERE high_price < low_price
               OR opening_price > high_price
               OR opening_price < low_price
               OR trade_price > high_price
               OR trade_price < low_price
        """)
        invalid_price_count = cursor.fetchone()[0]

        if invalid_price_count == 0:
            print(f"    ✓ 가격 데이터 유효성 확인")
        else:
            print(f"    ✗ 유효하지 않은 가격 데이터: {invalid_price_count}개")

        # 시간 중복 확인
        cursor.execute(f"""
            SELECT timestamp, COUNT(*) as cnt
            FROM bitcoin_{timeframe}
            GROUP BY timestamp
            HAVING cnt > 1
        """)
        duplicates = cursor.fetchall()

        if len(duplicates) == 0:
            print(f"    ✓ 시간 중복 없음")
        else:
            print(f"    ✗ 중복된 타임스탬프: {len(duplicates)}개")

    conn.close()

    print("\n" + "="*80)
    print("✅ 검증 완료")
    print("="*80)

if __name__ == "__main__":
    verify_database()
