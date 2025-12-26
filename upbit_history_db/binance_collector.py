#!/usr/bin/env python3
"""
Binance BTCUSDT Futures 데이터 수집기

Upbit DB와 동일한 SQLite 형식으로 Binance 데이터를 저장
- binance_bitcoin.db에 저장
- 테이블 구조: timestamp, open, high, low, close, volume, quote_volume, funding_rate
"""

import os
import sys
import sqlite3
import time
import requests
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict

# DB 경로
DB_DIR = Path(__file__).parent
DB_PATH = DB_DIR / "binance_bitcoin.db"

# 테이블 정의
TIMEFRAMES = {
    'minute1': '1m',
    'minute5': '5m',
    'minute15': '15m',
    'minute30': '30m',
    'minute60': '1h',
    'minute240': '4h',
    'day': '1d',
}


class BinanceSQLiteCollector:
    """Binance 데이터를 SQLite로 수집"""

    BASE_URL = "https://api.binance.com/api/v3"
    FUTURES_URL = "https://fapi.binance.com/fapi/v1"

    def __init__(self, db_path: Path = DB_PATH):
        self.db_path = db_path
        self.conn = None
        self._init_db()

    def _init_db(self):
        """DB 초기화 및 테이블 생성"""
        self.conn = sqlite3.connect(str(self.db_path))

        for table_name in TIMEFRAMES.keys():
            self.conn.execute(f'''
                CREATE TABLE IF NOT EXISTS binance_{table_name} (
                    timestamp TEXT PRIMARY KEY,
                    open REAL NOT NULL,
                    high REAL NOT NULL,
                    low REAL NOT NULL,
                    close REAL NOT NULL,
                    volume REAL NOT NULL,
                    quote_volume REAL,
                    trades INTEGER,
                    funding_rate REAL DEFAULT 0.0
                )
            ''')

        # 펀딩비 테이블
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS binance_funding_rate (
                timestamp TEXT PRIMARY KEY,
                funding_rate REAL NOT NULL,
                mark_price REAL
            )
        ''')

        self.conn.commit()
        print(f"✅ DB 초기화: {self.db_path}")

    def fetch_klines(
        self,
        interval: str,
        start_ts: int,
        end_ts: int,
        limit: int = 1000
    ) -> List[List]:
        """Binance API에서 캔들 데이터 가져오기"""
        url = f"{self.BASE_URL}/klines"
        params = {
            'symbol': 'BTCUSDT',
            'interval': interval,
            'startTime': start_ts,
            'endTime': end_ts,
            'limit': limit
        }

        try:
            response = requests.get(url, params=params, timeout=30)
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"API 오류: {e}")
            return []

    def fetch_funding_rates(self, start_ts: int, end_ts: int) -> List[Dict]:
        """펀딩비 데이터 가져오기"""
        url = f"{self.FUTURES_URL}/fundingRate"
        all_data = []
        current_ts = start_ts

        while current_ts < end_ts:
            params = {
                'symbol': 'BTCUSDT',
                'startTime': current_ts,
                'endTime': end_ts,
                'limit': 1000
            }

            try:
                response = requests.get(url, params=params, timeout=30)
                response.raise_for_status()
                data = response.json()

                if not data:
                    break

                all_data.extend(data)
                current_ts = data[-1]['fundingTime'] + 1
                time.sleep(0.1)

            except Exception as e:
                print(f"펀딩비 API 오류: {e}")
                break

        return all_data

    def collect_timeframe(
        self,
        timeframe: str,
        start_date: str,
        end_date: str,
        update_mode: bool = True
    ) -> int:
        """
        특정 타임프레임 데이터 수집

        Args:
            timeframe: 'minute240', 'day' 등
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
            update_mode: True면 기존 데이터 이후부터 수집

        Returns:
            수집된 캔들 수
        """
        if timeframe not in TIMEFRAMES:
            raise ValueError(f"지원하지 않는 타임프레임: {timeframe}")

        interval = TIMEFRAMES[timeframe]
        table_name = f"binance_{timeframe}"

        # 업데이트 모드: 마지막 데이터 이후부터 수집
        if update_mode:
            cursor = self.conn.execute(
                f"SELECT MAX(timestamp) FROM {table_name}"
            )
            last_ts = cursor.fetchone()[0]
            if last_ts:
                start_date = (pd.to_datetime(last_ts) + timedelta(minutes=1)).strftime('%Y-%m-%d')
                print(f"  업데이트 모드: {last_ts} 이후부터 수집")

        start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)

        print(f"\n📊 {timeframe} 수집 시작 ({start_date} ~ {end_date})")

        all_data = []
        current_ts = start_ts

        while current_ts < end_ts:
            klines = self.fetch_klines(interval, current_ts, end_ts)

            if not klines:
                break

            all_data.extend(klines)
            current_ts = klines[-1][0] + 1

            print(f"  수집: {len(all_data)}개", end='\r')
            time.sleep(0.1)

        if not all_data:
            print(f"  새 데이터 없음")
            return 0

        # DB 저장
        inserted = 0
        for k in all_data:
            timestamp = pd.to_datetime(k[0], unit='ms').strftime('%Y-%m-%dT%H:%M:%S')
            try:
                self.conn.execute(f'''
                    INSERT OR REPLACE INTO {table_name}
                    (timestamp, open, high, low, close, volume, quote_volume, trades)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ''', (
                    timestamp,
                    float(k[1]),  # open
                    float(k[2]),  # high
                    float(k[3]),  # low
                    float(k[4]),  # close
                    float(k[5]),  # volume
                    float(k[7]),  # quote_volume
                    int(k[8]),    # trades
                ))
                inserted += 1
            except Exception as e:
                print(f"  저장 오류: {e}")

        self.conn.commit()
        print(f"  ✅ {inserted}개 저장 완료")
        return inserted

    def collect_funding(self, start_date: str, end_date: str) -> int:
        """펀딩비 데이터 수집"""
        start_ts = int(pd.Timestamp(start_date).timestamp() * 1000)
        end_ts = int(pd.Timestamp(end_date).timestamp() * 1000)

        print(f"\n💰 펀딩비 수집 ({start_date} ~ {end_date})")

        data = self.fetch_funding_rates(start_ts, end_ts)

        if not data:
            print("  펀딩비 데이터 없음")
            return 0

        inserted = 0
        for d in data:
            timestamp = pd.to_datetime(d['fundingTime'], unit='ms').strftime('%Y-%m-%dT%H:%M:%S')
            try:
                self.conn.execute('''
                    INSERT OR REPLACE INTO binance_funding_rate
                    (timestamp, funding_rate, mark_price)
                    VALUES (?, ?, ?)
                ''', (
                    timestamp,
                    float(d.get('fundingRate', 0)),
                    float(d.get('markPrice', 0)) if d.get('markPrice') else None,
                ))
                inserted += 1
            except Exception as e:
                print(f"  저장 오류: {e}")

        self.conn.commit()
        print(f"  ✅ {inserted}개 저장 완료")
        return inserted

    def collect_all(self, start_date: str = "2020-01-01", end_date: str = None):
        """모든 타임프레임 데이터 수집"""
        if end_date is None:
            end_date = datetime.now().strftime('%Y-%m-%d')

        print(f"\n{'='*60}")
        print(f"🚀 Binance BTCUSDT 전체 데이터 수집")
        print(f"   기간: {start_date} ~ {end_date}")
        print(f"   DB: {self.db_path}")
        print(f"{'='*60}")

        # 주요 타임프레임만 수집 (용량 관리)
        priority_timeframes = ['minute240', 'day', 'minute60']

        for tf in priority_timeframes:
            self.collect_timeframe(tf, start_date, end_date)

        # 펀딩비 수집
        self.collect_funding(start_date, end_date)

        print(f"\n✅ 전체 수집 완료!")
        self.show_stats()

    def show_stats(self):
        """DB 통계 출력"""
        print(f"\n📈 DB 통계:")
        for tf in TIMEFRAMES.keys():
            table = f"binance_{tf}"
            try:
                cursor = self.conn.execute(f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table}")
                count, min_ts, max_ts = cursor.fetchone()
                if count > 0:
                    print(f"   {tf}: {count:,}개 ({min_ts[:10]} ~ {max_ts[:10]})")
            except:
                pass

        # 펀딩비
        try:
            cursor = self.conn.execute("SELECT COUNT(*) FROM binance_funding_rate")
            count = cursor.fetchone()[0]
            print(f"   funding_rate: {count:,}개")
        except:
            pass

    def close(self):
        """DB 연결 종료"""
        if self.conn:
            self.conn.close()


def main():
    """메인 실행"""
    import argparse

    parser = argparse.ArgumentParser(description='Binance BTCUSDT 데이터 수집기')
    parser.add_argument('--start', type=str, default='2020-01-01', help='시작일 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=None, help='종료일 (YYYY-MM-DD)')
    parser.add_argument('--timeframe', type=str, default=None, help='특정 타임프레임만 수집')
    parser.add_argument('--stats', action='store_true', help='통계만 출력')

    args = parser.parse_args()

    collector = BinanceSQLiteCollector()

    try:
        if args.stats:
            collector.show_stats()
        elif args.timeframe:
            end_date = args.end or datetime.now().strftime('%Y-%m-%d')
            collector.collect_timeframe(args.timeframe, args.start, end_date)
            collector.show_stats()
        else:
            collector.collect_all(args.start, args.end)
    finally:
        collector.close()


if __name__ == '__main__':
    main()
