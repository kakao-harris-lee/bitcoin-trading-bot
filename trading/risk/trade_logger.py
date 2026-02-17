#!/usr/bin/env python3
"""
거래 로거 - DB에 거래 내역 기록
"""

# pylint: disable=broad-exception-caught,redefined-outer-name

import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, date
from pathlib import Path
from typing import Optional, List, Dict, Any, Generator


class TradeLogger:
    """거래 내역을 DB에 기록하는 클래스

    Uses thread-local connections for thread safety.
    """

    def __init__(self, db_path: Optional[str] = None, strategy_name: Optional[str] = None):
        """
        Args:
            db_path: DB file path (default: data/trading_results.db)
            strategy_name: Strategy name to use (default: multi_exchange)
        """
        if db_path is None:
            project_root = Path(__file__).parent.parent.parent
            db_path = str(project_root / "data" / "trading_results.db")

        self.db_path = db_path
        self.strategy_id: Optional[int] = None
        self.strategy_name = strategy_name or "multi_exchange"
        # Thread-local storage for connections
        self._local = threading.local()

        # Initialize database schema
        self._init_schema()

        # 전략 ID 조회 또는 생성
        self._ensure_strategy_exists()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get thread-local database connection with context manager.

        Yields:
            SQLite connection for the current thread.
        """
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
            self._local.connection = sqlite3.connect(self.db_path)
            self._local.connection.row_factory = sqlite3.Row
        try:
            yield self._local.connection
        except Exception:
            self._local.connection.rollback()
            raise

    def close(self) -> None:
        """Close the thread-local connection if open."""
        if hasattr(self._local, 'connection') and self._local.connection is not None:
            self._local.connection.close()
            self._local.connection = None

    def _init_schema(self):
        """Initialize database schema if tables don't exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Create strategies table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS strategies (
                    strategy_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    version TEXT NOT NULL,
                    name TEXT NOT NULL,
                    description TEXT,
                    timeframe TEXT,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Create trades table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS trades (
                    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    strategy_id INTEGER NOT NULL,
                    symbol TEXT DEFAULT 'BTC',
                    action TEXT NOT NULL,
                    price REAL NOT NULL,
                    volume REAL NOT NULL,
                    profit REAL,
                    profit_pct REAL,
                    exchange TEXT DEFAULT 'binance',
                    market TEXT DEFAULT 'spot',
                    paper INTEGER DEFAULT 1,
                    timestamp TEXT NOT NULL,
                    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
                )
            """)

            # Create indexes for faster queries
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_timestamp
                ON trades(timestamp DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_strategy
                ON trades(strategy_id)
            """)
            # Composite index for common query pattern
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_trades_strategy_exchange
                ON trades(strategy_id, exchange)
            """)

            conn.commit()

    def _ensure_strategy_exists(self):
        """Ensure strategy exists in DB, create if not."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # Query for strategy by name
            cursor.execute("""
                SELECT strategy_id FROM strategies
                WHERE name = ?
            """, (self.strategy_name,))

            result = cursor.fetchone()

            if result:
                self.strategy_id = result[0]
            else:
                # Create strategy
                cursor.execute("""
                    INSERT INTO strategies (version, name, description, timeframe)
                    VALUES (?, ?, ?, ?)
                """, (
                    'paper',
                    self.strategy_name,
                    f'Paper trading - {self.strategy_name}',
                    'realtime'
                ))
                self.strategy_id = cursor.lastrowid
                conn.commit()

    def log_trade(self, action: str, price: float, volume: float,
                  profit: Optional[float] = None, profit_pct: Optional[float] = None,
                  exchange: str = 'binance', symbol: str = 'BTC',
                  market: str = 'futures', paper: bool = True):
        """
        거래 내역 기록

        Args:
            action: 'BUY' or 'SELL'
            price: Fill price
            volume: Trade volume
            profit: Realized profit (for exits)
            profit_pct: Profit percentage (for exits)
            exchange: Exchange name ('binance')
            symbol: Trading symbol ('BTC', 'ETH', etc.)
            market: Market type ('spot' or 'futures')
            paper: Whether this is paper trading
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    INSERT INTO trades
                    (strategy_id, symbol, action, price, volume, profit, profit_pct, exchange, market, paper, timestamp)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    self.strategy_id,
                    symbol,
                    action.upper(),
                    price,
                    volume,
                    profit,
                    profit_pct,
                    exchange,
                    market,
                    1 if paper else 0,
                    datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                ))

                conn.commit()

            print(f"✅ Trade logged: {action} {volume:.8f} {symbol} @ {price:,.2f}")

        except Exception as e:
            print(f"❌ 거래 기록 실패: {e}")

    def log_position_open(self, price: float, volume: float, exchange: str = 'binance'):
        """포지션 진입 기록"""
        self.log_trade('BUY', price, volume, exchange=exchange)

    def log_position_close(self, price: float, volume: float,
                          entry_price: float, exchange: str = 'binance',
                          is_short: bool = True):
        """포지션 청산 기록 (손익 계산 포함)"""

        # 손익 계산
        if is_short:
            # 숏 포지션: 진입가보다 낮으면 이익
            profit = (entry_price - price) * volume
            profit_pct = ((entry_price - price) / entry_price) * 100
        else:
            # 롱 포지션: 진입가보다 높으면 이익
            profit = (price - entry_price) * volume
            profit_pct = ((price - entry_price) / entry_price) * 100

        self.log_trade('SELL', price, volume, profit, profit_pct, exchange)

    def get_today_trades(self):
        """오늘의 거래 내역 조회"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute("""
                    SELECT action, price, volume, profit, profit_pct, exchange, timestamp
                    FROM trades
                    WHERE strategy_id = ?
                    AND date(timestamp) = date('now')
                    ORDER BY timestamp DESC
                """, (self.strategy_id,))

                trades = cursor.fetchall()
                return trades

        except Exception as e:
            print(f"❌ 거래 내역 조회 실패: {e}")
            return []

    def get_recent_trades(self, limit: int = 5, exchange: Optional[str] = None):
        """최근 거래 내역 조회

        Args:
            limit: 조회할 최대 거래 수
            exchange: 거래소 필터 ('binance', None이면 전체)

        Returns:
            List of dicts with trade info
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                if exchange:
                    cursor.execute("""
                        SELECT action, price, volume, profit, profit_pct, exchange, timestamp
                        FROM trades
                        WHERE strategy_id = ? AND exchange = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (self.strategy_id, exchange, limit))
                else:
                    cursor.execute("""
                        SELECT action, price, volume, profit, profit_pct, exchange, timestamp
                        FROM trades
                        WHERE strategy_id = ?
                        ORDER BY timestamp DESC
                        LIMIT ?
                    """, (self.strategy_id, limit))

                rows = cursor.fetchall()

                trades = []
                for row in rows:
                    trades.append({
                        'action': row[0],
                        'price': row[1],
                        'volume': row[2],
                        'profit': row[3],
                        'profit_pct': row[4],
                        'exchange': row[5],
                        'timestamp': row[6]
                    })
                return trades

        except Exception as e:
            print(f"❌ 최근 거래 조회 실패: {e}")
            return []

    def get_trades_for_date(
        self,
        target_date: date,
        strategy_name: Optional[str] = None,
        exchange: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        특정 날짜의 거래 내역 조회 (비교 리포트용)

        Args:
            target_date: 조회할 날짜
            strategy_name: 전략 이름 필터 (None이면 현재 strategy_id 사용)
            exchange: 거래소 필터 ('binance', None이면 전체)

        Returns:
            List of dicts with trade info including timestamp, action, price, volume, profit, profit_pct, exchange
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                date_str = target_date.strftime('%Y-%m-%d')

                # Build query based on filters
                base_query = """
                    SELECT action, price, volume, profit, profit_pct, exchange, timestamp
                    FROM trades
                    WHERE date(timestamp) = ?
                """
                params: List[Any] = [date_str]

                # Filter by strategy
                if strategy_name:
                    base_query += """
                        AND strategy_id IN (
                            SELECT strategy_id FROM strategies WHERE name = ? OR version = ?
                        )
                    """
                    params.extend([strategy_name, strategy_name])
                else:
                    base_query += " AND strategy_id = ?"
                    params.append(self.strategy_id)

                # Filter by exchange
                if exchange:
                    base_query += " AND exchange = ?"
                    params.append(exchange)

                base_query += " ORDER BY timestamp ASC"

                cursor.execute(base_query, params)
                rows = cursor.fetchall()

                trades = []
                for row in rows:
                    trades.append({
                        'action': row[0],
                        'price': row[1],
                        'volume': row[2],
                        'profit': row[3],
                        'profit_pct': row[4],
                        'exchange': row[5],
                        'timestamp': datetime.strptime(row[6], '%Y-%m-%d %H:%M:%S')
                    })
                return trades

        except Exception as e:
            print(f"❌ 날짜별 거래 조회 실패: {e}")
            return []

    def get_trades_for_date_range(
        self,
        start_date: date,
        end_date: date,
        strategy_name: Optional[str] = None,
        exchange: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        날짜 범위의 거래 내역 조회

        Args:
            start_date: 시작 날짜 (포함)
            end_date: 종료 날짜 (포함)
            strategy_name: 전략 이름 필터
            exchange: 거래소 필터

        Returns:
            List of dicts with trade info
        """
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                start_str = start_date.strftime('%Y-%m-%d')
                end_str = end_date.strftime('%Y-%m-%d')

                base_query = """
                    SELECT action, price, volume, profit, profit_pct, exchange, timestamp
                    FROM trades
                    WHERE date(timestamp) >= ? AND date(timestamp) <= ?
                """
                params: List[Any] = [start_str, end_str]

                if strategy_name:
                    base_query += """
                        AND strategy_id IN (
                            SELECT strategy_id FROM strategies WHERE name = ? OR version = ?
                        )
                    """
                    params.extend([strategy_name, strategy_name])
                else:
                    base_query += " AND strategy_id = ?"
                    params.append(self.strategy_id)

                if exchange:
                    base_query += " AND exchange = ?"
                    params.append(exchange)

                base_query += " ORDER BY timestamp ASC"

                cursor.execute(base_query, params)
                rows = cursor.fetchall()

                trades = []
                for row in rows:
                    trades.append({
                        'action': row[0],
                        'price': row[1],
                        'volume': row[2],
                        'profit': row[3],
                        'profit_pct': row[4],
                        'exchange': row[5],
                        'timestamp': datetime.strptime(row[6], '%Y-%m-%d %H:%M:%S')
                    })
                return trades

        except Exception as e:
            print(f"❌ 날짜 범위 거래 조회 실패: {e}")
            return []

    def get_statistics(self):
        """전체 거래 통계"""
        try:
            with self._get_connection() as conn:
                cursor = conn.cursor()

                # 총 거래 수
                cursor.execute("""
                    SELECT COUNT(*) FROM trades
                    WHERE strategy_id = ?
                """, (self.strategy_id,))
                total_trades = cursor.fetchone()[0]

                # 총 손익
                cursor.execute("""
                    SELECT SUM(profit) FROM trades
                    WHERE strategy_id = ? AND profit IS NOT NULL
                """, (self.strategy_id,))
                result = cursor.fetchone()
                total_profit = result[0] if result[0] else 0

                # 승률
                cursor.execute("""
                    SELECT
                        SUM(CASE WHEN profit > 0 THEN 1 ELSE 0 END) as wins,
                        COUNT(*) as total
                    FROM trades
                    WHERE strategy_id = ? AND profit IS NOT NULL
                """, (self.strategy_id,))
                result = cursor.fetchone()
                win_rate = (result[0] / result[1] * 100) if result[1] > 0 else 0

                return {
                    'total_trades': total_trades,
                    'total_profit': total_profit,
                    'win_rate': win_rate
                }

        except Exception as e:
            print(f"❌ 통계 조회 실패: {e}")
            return {
                'total_trades': 0,
                'total_profit': 0,
                'win_rate': 0
            }


# DB 스키마에 exchange 컬럼 추가
def add_exchange_column_if_not_exists(db_path: str):
    """trades 테이블에 exchange 컬럼 추가 (없으면)"""
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # 컬럼 존재 확인
        cursor.execute("PRAGMA table_info(trades)")
        columns = [row[1] for row in cursor.fetchall()]

        if 'exchange' not in columns:
            cursor.execute("""
                ALTER TABLE trades
                ADD COLUMN exchange TEXT DEFAULT 'binance'
            """)
            conn.commit()
            print("✅ trades 테이블에 exchange 컬럼 추가 완료")

        conn.close()

    except Exception as e:
        print(f"⚠️  컬럼 추가 실패: {e}")


if __name__ == "__main__":
    # DB 경로
    project_root = Path(__file__).parent.parent
    db_path = project_root / "trading_results.db"

    # exchange 컬럼 추가
    add_exchange_column_if_not_exists(str(db_path))

    # 로거 생성
    logger = TradeLogger(str(db_path))

    print("=" * 70)
    print("📊 거래 로거 테스트")
    print("=" * 70)
    print(f"전략 ID: {logger.strategy_id}")
    print()

    # 테스트 거래 기록
    print("✅ 1. 테스트 거래 기록...")
    logger.log_position_open(50000.0, 0.001, 'binance')
    logger.log_position_close(49000.0, 0.001, 50000.0, 'binance', is_short=True)

    print()

    # 오늘의 거래 내역
    print("✅ 2. 오늘의 거래 내역...")
    trades = logger.get_today_trades()
    for trade in trades:
        print(f"   {trade}")

    print()

    # 통계
    print("✅ 3. 거래 통계...")
    stats = logger.get_statistics()
    print(f"   총 거래: {stats['total_trades']}회")
    print(f"   총 손익: {stats['total_profit']:,.0f}원")
    print(f"   승률: {stats['win_rate']:.1f}%")

    print()
    print("=" * 70)
    print("✅ 테스트 완료!")
    print("=" * 70)
