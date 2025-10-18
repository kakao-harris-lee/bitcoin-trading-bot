#!/usr/bin/env python3
"""
data_loader.py
upbit_bitcoin.db에서 가격 데이터를 읽어오는 공통 모듈
"""

import sqlite3
import pandas as pd
from pathlib import Path
from typing import Optional, List, Tuple
from datetime import datetime

class DataLoader:
    """upbit_bitcoin.db 데이터 로더"""

    TIMEFRAMES = [
        "minute1", "minute3", "minute5", "minute10",
        "minute15", "minute30", "minute60", "minute240",
        "day", "week", "month"
    ]

    # 실제 테이블명 매핑 (bitcoin_ 접두사)
    TABLE_MAP = {
        "minute1": "bitcoin_minute1",
        "minute3": "bitcoin_minute3",
        "minute5": "bitcoin_minute5",
        "minute10": "bitcoin_minute10",
        "minute15": "bitcoin_minute15",
        "minute30": "bitcoin_minute30",
        "minute60": "bitcoin_minute60",
        "minute240": "bitcoin_minute240",
        "day": "bitcoin_day",
        "week": "bitcoin_week",
        "month": "bitcoin_month"
    }

    def __init__(self, db_path: str = "upbit_bitcoin.db"):
        """
        Args:
            db_path: upbit_bitcoin.db 경로
        """
        self.db_path = Path(db_path)
        if not self.db_path.exists():
            raise FileNotFoundError(f"DB 파일을 찾을 수 없습니다: {db_path}")

        self.conn = sqlite3.connect(str(self.db_path))

    def load_timeframe(
        self,
        timeframe: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None
    ) -> pd.DataFrame:
        """
        특정 타임프레임 데이터 로드

        Args:
            timeframe: minute1, minute5, day, ... (TIMEFRAMES 참고)
            start_date: 시작일 (YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS)
            end_date: 종료일 (YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        if timeframe not in self.TIMEFRAMES:
            raise ValueError(f"지원하지 않는 타임프레임: {timeframe}")

        # 실제 테이블명 가져오기
        table_name = self.TABLE_MAP[timeframe]
        query = f"SELECT * FROM {table_name}"
        conditions = []

        if start_date:
            conditions.append(f"timestamp >= '{start_date}'")
        if end_date:
            conditions.append(f"timestamp <= '{end_date}'")

        if conditions:
            query += " WHERE " + " AND ".join(conditions)

        query += " ORDER BY timestamp ASC"

        df = pd.read_sql_query(query, self.conn)

        # 컬럼명 정리 (이미 timestamp 컬럼 존재)
        df = df.rename(columns={
            'opening_price': 'open',
            'high_price': 'high',
            'low_price': 'low',
            'trade_price': 'close',
            'candle_acc_trade_volume': 'volume'
        })

        # timestamp를 datetime으로 변환
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        # 필요한 컬럼만 선택
        df = df[['timestamp', 'open', 'high', 'low', 'close', 'volume']]

        return df

    def get_date_range(self, timeframe: str) -> Tuple[str, str]:
        """
        특정 타임프레임의 데이터 기간 조회

        Args:
            timeframe: minute1, minute5, day, ...

        Returns:
            (시작일, 종료일) 튜플
        """
        table_name = self.TABLE_MAP[timeframe]
        query = f"""
        SELECT
            MIN(timestamp) as start_date,
            MAX(timestamp) as end_date
        FROM {table_name}
        """
        result = pd.read_sql_query(query, self.conn)
        return result.iloc[0]['start_date'], result.iloc[0]['end_date']

    def get_record_count(self, timeframe: str) -> int:
        """
        특정 타임프레임의 레코드 수 조회

        Args:
            timeframe: minute1, minute5, day, ...

        Returns:
            레코드 수
        """
        table_name = self.TABLE_MAP[timeframe]
        query = f"SELECT COUNT(*) as count FROM {table_name}"
        result = pd.read_sql_query(query, self.conn)
        return result.iloc[0]['count']

    def split_data(
        self,
        df: pd.DataFrame,
        train_ratio: float = 0.7,
        val_ratio: float = 0.15,
        test_ratio: float = 0.15
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        데이터를 학습/검증/테스트로 분할

        Args:
            df: 분할할 DataFrame
            train_ratio: 학습 데이터 비율
            val_ratio: 검증 데이터 비율
            test_ratio: 테스트 데이터 비율

        Returns:
            (train_df, val_df, test_df) 튜플
        """
        assert abs(train_ratio + val_ratio + test_ratio - 1.0) < 1e-6, \
            "비율의 합이 1.0이 아닙니다"

        n = len(df)
        train_end = int(n * train_ratio)
        val_end = int(n * (train_ratio + val_ratio))

        train_df = df.iloc[:train_end].copy()
        val_df = df.iloc[train_end:val_end].copy()
        test_df = df.iloc[val_end:].copy()

        return train_df, val_df, test_df

    def split_by_date(
        self,
        df: pd.DataFrame,
        train_end: str,
        val_end: str
    ) -> Tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
        """
        날짜 기준으로 데이터 분할

        Args:
            df: 분할할 DataFrame
            train_end: 학습 데이터 종료일 (YYYY-MM-DD)
            val_end: 검증 데이터 종료일 (YYYY-MM-DD)

        Returns:
            (train_df, val_df, test_df) 튜플
        """
        train_df = df[df['timestamp'] <= train_end].copy()
        val_df = df[(df['timestamp'] > train_end) & (df['timestamp'] <= val_end)].copy()
        test_df = df[df['timestamp'] > val_end].copy()

        return train_df, val_df, test_df

    def close(self):
        """DB 연결 종료"""
        if self.conn:
            self.conn.close()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()


# 사용 예제
if __name__ == "__main__":
    with DataLoader() as loader:
        # 5분봉 데이터 로드
        df = loader.load_timeframe("minute5", start_date="2024-01-01")
        print(f"✅ 5분봉 데이터: {len(df)} 레코드")
        print(df.head())

        # 데이터 분할
        train, val, test = loader.split_by_date(
            df,
            train_end="2023-12-31",
            val_end="2024-06-30"
        )
        print(f"\n✅ 학습: {len(train)}, 검증: {len(val)}, 테스트: {len(test)}")
