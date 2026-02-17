#!/usr/bin/env python3
"""
Binance BTCUSDT Spot 데이터 수집기

Upbit DB와 동일한 SQLite 형식으로 Binance 데이터를 저장
- binance_bitcoin.db에 저장
- 테이블 구조: timestamp, open, high, low, close, volume, quote_volume

추가 기능:
- 래리 윌리엄스 변동성 돌파 지표 (target_price, breakout_signal)
- LSTM 학습용 MinMax 스케일링 (전체 + Rolling)
"""

import os
import sys
import sqlite3
import time
import requests
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Tuple

# DB 경로
PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH = PROJECT_ROOT / "data" / "binance_bitcoin.db"

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
                    trades INTEGER
                )
            ''')

        # 스케일링 파라미터 테이블 (LSTM용)
        self.conn.execute('''
            CREATE TABLE IF NOT EXISTS scaling_params (
                column_name TEXT PRIMARY KEY,
                min_value REAL NOT NULL,
                max_value REAL NOT NULL,
                rolling_window INTEGER,
                updated_at TEXT NOT NULL
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

    def close(self):
        """DB 연결 종료"""
        if self.conn:
            self.conn.close()

    # ============================================================
    # 변동성 돌파 & LSTM 스케일링 기능
    # ============================================================

    def _add_column_if_not_exists(self, table: str, column: str, col_type: str = "REAL"):
        """테이블에 컬럼이 없으면 추가"""
        cursor = self.conn.execute(f"PRAGMA table_info({table})")
        columns = [row[1] for row in cursor.fetchall()]
        if column not in columns:
            self.conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
            self.conn.commit()

    def _get_prev_day_data(self, date_str: str) -> Tuple[Optional[float], Optional[float]]:
        """전일 고/저가 조회

        Args:
            date_str: 현재 날짜 (YYYY-MM-DD 또는 YYYY-MM-DDTHH:MM:SS)

        Returns:
            (prev_day_high, prev_day_low) 또는 (None, None)
        """
        # 날짜만 추출
        current_date = pd.to_datetime(date_str).date()
        prev_date = current_date - timedelta(days=1)
        prev_date_str = prev_date.strftime('%Y-%m-%d')

        cursor = self.conn.execute('''
            SELECT high, low FROM binance_day
            WHERE timestamp LIKE ?
            LIMIT 1
        ''', (f"{prev_date_str}%",))

        row = cursor.fetchone()
        if row:
            return float(row[0]), float(row[1])
        return None, None

    def add_volatility_breakout(
        self,
        timeframe: str = 'minute60',
        k: float = 0.5
    ) -> int:
        """변동성 돌파 지표 추가 (래리 윌리엄스 전략)

        전일 고/저가를 기준으로 target_price 계산:
        target_price = 당일 시가 + (전일 고가 - 전일 저가) × k

        Args:
            timeframe: 대상 타임프레임 (기본: minute60)
            k: 레인지 승수 (기본: 0.5, Optuna로 최적화 가능)

        Returns:
            업데이트된 행 수
        """
        table_name = f"binance_{timeframe}"

        # 필요한 컬럼 추가
        for col in ['prev_day_high', 'prev_day_low', 'prev_day_range', 'target_price', 'breakout_signal']:
            col_type = "INTEGER" if col == 'breakout_signal' else "REAL"
            self._add_column_if_not_exists(table_name, col, col_type)

        print(f"\n📈 변동성 돌파 지표 추가 (k={k})")

        # 시간봉 데이터 로드
        df = pd.read_sql_query(
            f"SELECT timestamp, open, high, low, close FROM {table_name} ORDER BY timestamp",
            self.conn
        )

        if df.empty:
            print("  데이터 없음")
            return 0

        # 날짜 컬럼 추가
        df['date'] = pd.to_datetime(df['timestamp']).dt.date

        # 일봉 데이터 로드
        daily_df = pd.read_sql_query(
            "SELECT timestamp, high, low FROM binance_day ORDER BY timestamp",
            self.conn
        )

        if daily_df.empty:
            print("  ⚠️ 일봉 데이터 필요 - 먼저 일봉을 수집하세요")
            return 0

        daily_df['date'] = pd.to_datetime(daily_df['timestamp']).dt.date
        daily_df = daily_df.rename(columns={'high': 'day_high', 'low': 'day_low'})

        # 전일 고/저가 매핑 (shift 사용)
        daily_df['prev_day_high'] = daily_df['day_high'].shift(1)
        daily_df['prev_day_low'] = daily_df['day_low'].shift(1)
        daily_df['prev_day_range'] = daily_df['prev_day_high'] - daily_df['prev_day_low']

        # 시간봉과 일봉 조인
        df = df.merge(
            daily_df[['date', 'prev_day_high', 'prev_day_low', 'prev_day_range']],
            on='date',
            how='left'
        )

        # 당일 첫 캔들의 시가 가져오기 (일별 그룹)
        df['day_open'] = df.groupby('date')['open'].transform('first')

        # target_price 계산
        df['target_price'] = df['day_open'] + (df['prev_day_range'] * k)

        # breakout_signal 계산 (종가 > target_price)
        df['breakout_signal'] = (df['close'] > df['target_price']).astype(int)

        # DB 업데이트
        updated = 0
        for _, row in df.iterrows():
            if pd.notna(row['prev_day_high']):
                try:
                    self.conn.execute(f'''
                        UPDATE {table_name}
                        SET prev_day_high = ?,
                            prev_day_low = ?,
                            prev_day_range = ?,
                            target_price = ?,
                            breakout_signal = ?
                        WHERE timestamp = ?
                    ''', (
                        row['prev_day_high'],
                        row['prev_day_low'],
                        row['prev_day_range'],
                        row['target_price'],
                        int(row['breakout_signal']),
                        row['timestamp']
                    ))
                    updated += 1
                except Exception as e:
                    print(f"  업데이트 오류: {e}")

            if updated % 10000 == 0:
                print(f"  처리 중: {updated:,}개", end='\r')

        self.conn.commit()
        print(f"  ✅ {updated:,}개 행 업데이트 완료")
        return updated

    def add_scaled_columns(
        self,
        timeframe: str = 'minute60',
        rolling_window: int = 720,
        exclude_cols: Optional[List[str]] = None
    ) -> int:
        """LSTM용 스케일링 컬럼 추가

        모든 숫자형 컬럼에 대해:
        - {col}_scaled: 전체 데이터 기준 MinMax (0~1)
        - {col}_scaled_rolling: 최근 N기간 Rolling MinMax

        Args:
            timeframe: 대상 타임프레임 (기본: minute60)
            rolling_window: Rolling 윈도우 크기 (기본: 720 = 30일 시간봉)
            exclude_cols: 스케일링 제외 컬럼 목록

        Returns:
            추가된 컬럼 수
        """
        if exclude_cols is None:
            exclude_cols = ['timestamp', 'breakout_signal']

        table_name = f"binance_{timeframe}"

        print(f"\n🔢 LSTM 스케일링 컬럼 추가 (window={rolling_window})")

        # 데이터 로드
        df = pd.read_sql_query(f"SELECT * FROM {table_name} ORDER BY timestamp", self.conn)

        if df.empty:
            print("  데이터 없음")
            return 0

        # 숫자형 컬럼만 선택
        numeric_cols = df.select_dtypes(include=[np.number]).columns.tolist()
        scale_cols = [c for c in numeric_cols if c not in exclude_cols and not c.endswith('_scaled')]

        print(f"  대상 컬럼: {len(scale_cols)}개")

        added_cols = 0
        now_str = datetime.now().strftime('%Y-%m-%dT%H:%M:%S')

        for col in scale_cols:
            col_data = df[col].dropna()
            if col_data.empty:
                continue

            # 전체 MinMax
            min_val = col_data.min()
            max_val = col_data.max()
            range_val = max_val - min_val

            if range_val > 0:
                scaled_col = f"{col}_scaled"
                df[scaled_col] = (df[col] - min_val) / range_val

                # 스케일링 파라미터 저장
                self.conn.execute('''
                    INSERT OR REPLACE INTO scaling_params
                    (column_name, min_value, max_value, rolling_window, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                ''', (col, float(min_val), float(max_val), None, now_str))

                # Rolling MinMax
                rolling_col = f"{col}_scaled_rolling"
                rolling_min = df[col].rolling(window=rolling_window, min_periods=1).min()
                rolling_max = df[col].rolling(window=rolling_window, min_periods=1).max()
                rolling_range = rolling_max - rolling_min
                df[rolling_col] = (df[col] - rolling_min) / rolling_range.replace(0, 1)

                added_cols += 2

        # 새 컬럼들을 DB에 추가
        for col in df.columns:
            if col.endswith('_scaled') or col.endswith('_scaled_rolling'):
                self._add_column_if_not_exists(table_name, col, "REAL")

        # DB 업데이트 (배치)
        print(f"  DB 업데이트 중...")
        scaled_cols = [c for c in df.columns if '_scaled' in c]

        for idx, row in df.iterrows():
            set_clause = ", ".join([f"{c} = ?" for c in scaled_cols])
            values = [float(row[c]) if pd.notna(row[c]) else None for c in scaled_cols]
            values.append(row['timestamp'])

            try:
                self.conn.execute(f'''
                    UPDATE {table_name}
                    SET {set_clause}
                    WHERE timestamp = ?
                ''', values)
            except Exception as e:
                print(f"  업데이트 오류: {e}")
                break

            if idx % 10000 == 0:
                print(f"  처리 중: {idx:,}개", end='\r')

        self.conn.commit()
        print(f"  ✅ {added_cols}개 스케일링 컬럼 추가 완료")
        return added_cols

    def collect_with_features(
        self,
        start_date: str,
        end_date: str,
        k: float = 0.5,
        rolling_window: int = 720
    ):
        """데이터 수집 + 피처 계산 통합 파이프라인

        1. 일봉 수집 (변동성 돌파용)
        2. 시간봉 수집
        3. 변동성 돌파 지표 추가
        4. LSTM 스케일링 추가

        Args:
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
            k: 변동성 돌파 k값 (기본: 0.5)
            rolling_window: 스케일링 윈도우 (기본: 720)
        """
        print(f"\n{'='*60}")
        print(f"🚀 데이터 수집 + 피처 계산 파이프라인")
        print(f"   기간: {start_date} ~ {end_date}")
        print(f"   k값: {k}, Rolling Window: {rolling_window}")
        print(f"{'='*60}")

        # 1. 일봉 먼저 수집 (변동성 돌파 의존성)
        print("\n[1/4] 일봉 수집...")
        self.collect_timeframe('day', start_date, end_date)

        # 2. 시간봉 수집
        print("\n[2/4] 시간봉 수집...")
        self.collect_timeframe('minute60', start_date, end_date)

        # 3. 변동성 돌파 지표
        print("\n[3/4] 변동성 돌파 지표 계산...")
        self.add_volatility_breakout(timeframe='minute60', k=k)

        # 4. LSTM 스케일링
        print("\n[4/4] LSTM 스케일링...")
        self.add_scaled_columns(timeframe='minute60', rolling_window=rolling_window)

        print(f"\n{'='*60}")
        print(f"✅ 전체 파이프라인 완료!")
        self.show_stats()


def main():
    """메인 실행"""
    import argparse

    parser = argparse.ArgumentParser(description='Binance BTCUSDT 데이터 수집기')
    parser.add_argument('--start', type=str, default='2020-01-01', help='시작일 (YYYY-MM-DD)')
    parser.add_argument('--end', type=str, default=None, help='종료일 (YYYY-MM-DD)')
    parser.add_argument('--timeframe', type=str, default=None, help='특정 타임프레임만 수집')
    parser.add_argument('--stats', action='store_true', help='통계만 출력')

    # 변동성 돌파 & 스케일링 옵션
    parser.add_argument('--with-features', action='store_true',
                        help='수집 후 변동성 돌파 + 스케일링 피처 추가')
    parser.add_argument('--k', type=float, default=0.5,
                        help='변동성 돌파 k값 (기본: 0.5)')
    parser.add_argument('--add-features', action='store_true',
                        help='기존 데이터에 피처만 추가 (수집 없이)')
    parser.add_argument('--add-breakout', action='store_true',
                        help='변동성 돌파 지표만 추가')
    parser.add_argument('--add-scaling', action='store_true',
                        help='스케일링 컬럼만 추가')
    parser.add_argument('--rolling-window', type=int, default=720,
                        help='Rolling 스케일링 윈도우 (기본: 720)')

    args = parser.parse_args()

    collector = BinanceSQLiteCollector()

    try:
        if args.stats:
            collector.show_stats()

        elif args.add_features:
            # 기존 데이터에 피처만 추가
            print("📊 기존 데이터에 피처 추가...")
            collector.add_volatility_breakout(k=args.k)
            collector.add_scaled_columns(rolling_window=args.rolling_window)
            collector.show_stats()

        elif args.add_breakout:
            # 변동성 돌파만 추가
            collector.add_volatility_breakout(k=args.k)
            collector.show_stats()

        elif args.add_scaling:
            # 스케일링만 추가
            collector.add_scaled_columns(rolling_window=args.rolling_window)
            collector.show_stats()

        elif args.with_features:
            # 수집 + 피처 계산
            end_date = args.end or datetime.now().strftime('%Y-%m-%d')
            collector.collect_with_features(
                args.start, end_date,
                k=args.k,
                rolling_window=args.rolling_window
            )

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
