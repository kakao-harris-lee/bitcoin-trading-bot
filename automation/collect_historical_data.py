#!/usr/bin/env python3
"""
과거 데이터 수집 스크립트 (2020-2025)
minute5, minute15 누락 데이터 수집
"""

import sys
sys.path.append('..')

import requests
import sqlite3
from datetime import datetime, timedelta
import time

DB_PATH = '../upbit_bitcoin.db'
MARKET = 'KRW-BTC'

def fetch_candles(market, to, count=200, interval='minutes/5'):
    """Upbit API에서 캔들 데이터 가져오기"""
    url = f"https://api.upbit.com/v1/candles/{interval}"
    params = {
        'market': market,
        'to': to,
        'count': count
    }

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()
        data = response.json()
        if isinstance(data, list) and len(data) > 0:
            return data
        else:
            print(f"  ⚠️  빈 응답: {to}")
            return None
    except Exception as e:
        print(f"  ❌ API 오류: {e}")
        return None

def collect_timeframe_data(timeframe, start_date, end_date, interval_str, interval_minutes):
    """특정 타임프레임 데이터 수집"""

    table_name = f"bitcoin_{timeframe}"

    print(f"\n{'='*70}")
    print(f"{timeframe.upper()} 데이터 수집 시작")
    print(f"{'='*70}")
    print(f"기간: {start_date} ~ {end_date}")
    print(f"API 간격: {interval_str}")
    print()

    # DB 연결
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()

    # 기존 데이터 확인
    cursor.execute(f"SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM {table_name}")
    existing = cursor.fetchone()
    print(f"📊 기존 데이터: {existing[0]} ~ {existing[1]} ({existing[2]:,}개)\n")

    # 수집 시작
    end_time = datetime.strptime(end_date, '%Y-%m-%d')
    start_time = datetime.strptime(start_date, '%Y-%m-%d')
    current_time = end_time

    total_fetched = 0
    total_inserted = 0
    api_calls = 0
    last_progress_time = time.time()

    while current_time > start_time:
        # API 호출
        to_str = current_time.strftime('%Y-%m-%dT%H:%M:%S')
        candles = fetch_candles(MARKET, to_str, count=200, interval=interval_str)

        api_calls += 1

        if not candles:
            print(f"  ⚠️  데이터 없음, 재시도 중... (API 호출: {api_calls})")
            time.sleep(1)
            continue

        total_fetched += len(candles)

        # DB 삽입
        inserted_count = 0
        for candle in candles:
            try:
                cursor.execute(f"""
                    INSERT OR IGNORE INTO {table_name}
                    (timestamp, open, high, low, close, volume, value)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                """, (
                    candle['candle_date_time_kst'],
                    candle['opening_price'],
                    candle['high_price'],
                    candle['low_price'],
                    candle['trade_price'],
                    candle['candle_acc_trade_volume'],
                    candle['candle_acc_trade_price']
                ))

                if cursor.rowcount > 0:
                    inserted_count += 1
                    total_inserted += 1

            except Exception as e:
                pass  # 중복 무시

        # 커밋 (매 20회마다)
        if api_calls % 20 == 0:
            conn.commit()

            # 진행 상황 출력 (5초마다)
            now = time.time()
            if now - last_progress_time >= 5:
                days_collected = (end_time - current_time).days
                print(f"  ✅ 진행: {days_collected}일 수집 | "
                      f"API 호출: {api_calls:,}회 | "
                      f"신규 추가: {total_inserted:,}개 | "
                      f"현재: {current_time.strftime('%Y-%m-%d')}")
                last_progress_time = now

        # 다음 타임스탬프 (가장 오래된 캔들의 timestamp)
        oldest_candle_time = candles[-1]['candle_date_time_kst']
        current_time = datetime.fromisoformat(oldest_candle_time)

        # 시작 시점 도달 확인
        if current_time <= start_time:
            print(f"  ✅ 시작 시점 도달: {current_time}")
            break

        # Rate limit (초당 10회 → 0.12초 간격)
        time.sleep(0.12)

    # 최종 커밋
    conn.commit()

    # 결과 확인
    cursor.execute(f"SELECT MIN(timestamp), MAX(timestamp), COUNT(*) FROM {table_name}")
    final = cursor.fetchone()

    print(f"\n{'='*70}")
    print(f"{timeframe.upper()} 데이터 수집 완료!")
    print(f"{'='*70}")
    print(f"📊 최종 데이터: {final[0]} ~ {final[1]} ({final[2]:,}개)")
    print(f"📥 총 fetch: {total_fetched:,}개 | 신규 추가: {total_inserted:,}개")
    print(f"🌐 API 호출: {api_calls:,}회")
    print(f"{'='*70}\n")

    conn.close()

    return total_inserted

def main():
    """메인 실행 함수"""

    print(f"\n{'='*70}")
    print(f"🚀 과거 데이터 수집 시작 (2020~2025)")
    print(f"{'='*70}\n")

    # minute5 수집 (2020-01-01 ~ 2023-12-30)
    print("📌 Step 1/2: minute5 데이터 수집")
    minute5_inserted = collect_timeframe_data(
        timeframe='minute5',
        start_date='2020-01-01',
        end_date='2023-12-30',
        interval_str='minutes/5',
        interval_minutes=5
    )

    # minute15 수집 (2020-01-01 ~ 2023-01-29)
    print("\n📌 Step 2/2: minute15 데이터 수집")
    minute15_inserted = collect_timeframe_data(
        timeframe='minute15',
        start_date='2020-01-01',
        end_date='2023-01-29',
        interval_str='minutes/15',
        interval_minutes=15
    )

    # 최종 요약
    print(f"\n{'='*70}")
    print(f"✅ 전체 데이터 수집 완료!")
    print(f"{'='*70}")
    print(f"minute5:  {minute5_inserted:,}개 추가")
    print(f"minute15: {minute15_inserted:,}개 추가")
    print(f"총계:     {minute5_inserted + minute15_inserted:,}개 추가")
    print(f"{'='*70}\n")

if __name__ == '__main__':
    main()
