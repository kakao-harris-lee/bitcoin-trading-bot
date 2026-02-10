#!/usr/bin/env python3
"""
data_loader.py
Binance 가격 데이터를 읽어오는 공통 모듈

지원 DB:
- binance_bitcoin.db: Binance BTCUSDT 데이터
"""

import sqlite3
import pandas as pd
from pathlib import Path
from typing import Optional, List, Tuple, Literal
from datetime import datetime

# 프로젝트 루트 기준 기본 DB 경로
_PROJECT_ROOT = Path(__file__).parent.parent
_DB_DIR = _PROJECT_ROOT / "data"
_BINANCE_DB_PATH = _DB_DIR / "binance_bitcoin.db"


class DataLoader:
    """Binance 데이터 로더"""

    TIMEFRAMES = [
        "minute1", "minute3", "minute5", "minute10",
        "minute15", "minute30", "minute60", "minute240",
        "day", "week", "month"
    ]

    # Binance 테이블명 매핑
    BINANCE_TABLE_MAP = {
        "minute1": "binance_minute1",
        "minute5": "binance_minute5",
        "minute15": "binance_minute15",
        "minute30": "binance_minute30",
        "minute60": "binance_minute60",
        "minute240": "binance_minute240",
        "day": "binance_day",
    }

    # 하위 호환성을 위한 별칭
    TABLE_MAP = BINANCE_TABLE_MAP

    def __init__(self, db_path: str = None, exchange: Literal["binance"] = "binance"):
        """
        Args:
            db_path: DB 경로 (기본: binance_bitcoin.db)
            exchange: 거래소 선택 ("binance")
        """
        self.exchange = exchange

        if db_path is None:
            self.db_path = _BINANCE_DB_PATH
        else:
            self.db_path = Path(db_path)

        if not self.db_path.exists():
            raise FileNotFoundError(f"DB 파일을 찾을 수 없습니다: {self.db_path}")

        self.conn = sqlite3.connect(str(self.db_path))

        # Auto-detect table prefix based on existing tables
        self._table_prefix = self._detect_table_prefix()

    def _detect_table_prefix(self) -> str:
        """Detect table prefix by checking which table has data.

        Returns:
            Table prefix (e.g., 'binance', 'solana', 'ethereum', 'btc')
        """
        cursor = self.conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = [row[0] for row in cursor.fetchall()]

        # Priority: Check minute240 tables for actual data (not just existence)
        # This handles databases with multiple prefix tables where only one has data
        prefixes = ['btc', 'bnb', 'binance', 'solana', 'ethereum', 'xrp']
        for prefix in prefixes:
            table_name = f"{prefix}_minute240"
            if table_name in tables:
                # Check if table has data
                cursor.execute(f"SELECT COUNT(*) FROM {table_name} LIMIT 1")
                count = cursor.fetchone()[0]
                if count > 0:
                    return prefix

        # Fallback: check for any table with known prefix that has data
        for prefix in prefixes:
            matching_tables = [t for t in tables if t.startswith(f"{prefix}_")]
            for table_name in matching_tables:
                cursor.execute(f"SELECT COUNT(*) FROM {table_name} LIMIT 1")
                count = cursor.fetchone()[0]
                if count > 0:
                    return prefix

        # Default to binance
        return 'binance'

    def _get_table_name(self, timeframe: str) -> str:
        """Get actual table name for the timeframe using detected prefix."""
        # Map timeframe to suffix
        suffix_map = {
            "minute1": "minute1",
            "minute5": "minute5",
            "minute15": "minute15",
            "minute30": "minute30",
            "minute60": "minute60",
            "minute240": "minute240",
            "day": "day",
        }
        if timeframe not in suffix_map:
            raise ValueError(f"지원하지 않는 타임프레임: {timeframe}")

        table_prefix = getattr(self, "_table_prefix", None) or "binance"
        return f"{table_prefix}_{suffix_map[timeframe]}"

    def load_timeframe(
        self,
        timeframe: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        exchange: Optional[str] = None,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """
        특정 타임프레임 데이터 로드

        Args:
            timeframe: minute1, minute5, day, ... (TIMEFRAMES 참고)
            start_date: 시작일 (YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS)
            end_date: 종료일 (YYYY-MM-DD 또는 YYYY-MM-DD HH:MM:SS)
            exchange: 거래소 지정 (None이면 인스턴스 설정 사용)
            columns: 반환할 컬럼 목록 (None이면 기본 OHLCV만 반환)

        Returns:
            DataFrame with columns: timestamp, open, high, low, close, volume
        """
        return self._load_binance_timeframe(timeframe, start_date, end_date, columns=columns)

    def _load_binance_timeframe(
        self,
        timeframe: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Binance 데이터 로드 with parameterized queries."""
        # Use auto-detected table name based on database
        table_name = self._get_table_name(timeframe)

        # Build query with parameterized placeholders
        params = []
        conditions = []

        if start_date:
            conditions.append("timestamp >= ?")
            params.append(start_date)
        if end_date:
            conditions.append("timestamp <= ?")
            params.append(end_date)

        # Table name is safe (from internal mapping), but dates use parameters
        query = f"SELECT * FROM {table_name}"
        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY timestamp ASC"

        df = pd.read_sql_query(query, self.conn, params=params)

        # Binance 컬럼명은 이미 표준 형식
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        if columns is None:
            # 필요한 컬럼만 선택 (funding_rate 등 추가 컬럼 제외)
            cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
            df = df[[c for c in cols if c in df.columns]]
        else:
            cols = [c for c in columns if c in df.columns]
            if 'timestamp' in df.columns and 'timestamp' not in cols:
                cols = ['timestamp'] + cols
            df = df[cols]

        return df

    def load_binance(
        self,
        timeframe: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        columns: Optional[List[str]] = None,
    ) -> pd.DataFrame:
        """Binance 데이터 로드 (편의 메서드)"""
        return self._load_binance_timeframe(timeframe, start_date, end_date, columns=columns)

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
