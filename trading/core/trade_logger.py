#!/usr/bin/env python3
"""
거래 로거 - DB에 거래 내역 기록
"""

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional


class TradeLogger:
    """거래 내역을 DB에 기록하는 클래스"""

    def __init__(self, db_path: Optional[str] = None):
        """
        Args:
            db_path: DB 파일 경로 (기본: 프로젝트 루트의 trading_results.db)
        """
        if db_path is None:
            project_root = Path(__file__).parent.parent
            db_path = project_root / "trading_results.db"

        self.db_path = str(db_path)
        self.strategy_id = None

        # 전략 ID 조회 또는 생성
        self._ensure_strategy_exists()

    def _ensure_strategy_exists(self):
        """v35 듀얼 전략이 DB에 있는지 확인하고 없으면 생성"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # v35-dual 전략 조회
        cursor.execute("""
            SELECT strategy_id FROM strategies
            WHERE version = 'v35-dual' AND name = 'upbit_binance_hedge'
        """)

        result = cursor.fetchone()

        if result:
            self.strategy_id = result[0]
        else:
            # 전략 생성
            cursor.execute("""
                INSERT INTO strategies (version, name, description, timeframe)
                VALUES ('v35-dual', 'upbit_binance_hedge',
                        'v35 Optimized + 바이넨스 선물 헤지 (실시간)', 'day')
            """)
            self.strategy_id = cursor.lastrowid
            conn.commit()

        conn.close()

    def log_trade(self, action: str, price: float, volume: float,
                  profit: Optional[float] = None, profit_pct: Optional[float] = None,
                  exchange: str = 'upbit'):
        """
        거래 내역 기록

        Args:
            action: 'BUY' 또는 'SELL'
            price: 체결 가격
            volume: 거래량 (BTC)
            profit: 실현 손익 (원) - SELL 시
            profit_pct: 손익률 (%) - SELL 시
            exchange: 거래소 ('upbit' 또는 'binance')
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                INSERT INTO trades
                (strategy_id, action, price, volume, profit, profit_pct, exchange, timestamp)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                self.strategy_id,
                action.upper(),
                price,
                volume,
                profit,
                profit_pct,
                exchange,
                datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            ))

            conn.commit()
            conn.close()

            print(f"✅ 거래 기록 저장: {action} {volume:.8f} BTC @ {price:,.0f}원")

        except Exception as e:
            print(f"❌ 거래 기록 실패: {e}")

    def log_position_open(self, price: float, volume: float, exchange: str = 'upbit'):
        """포지션 진입 기록"""
        self.log_trade('BUY', price, volume, exchange=exchange)

    def log_position_close(self, price: float, volume: float,
                          entry_price: float, exchange: str = 'upbit'):
        """포지션 청산 기록 (손익 계산 포함)"""

        # 손익 계산
        if exchange == 'upbit':
            # 업비트: 원화 기준
            profit = (price - entry_price) * volume
            profit_pct = ((price - entry_price) / entry_price) * 100
        else:
            # 바이넨스: 숏 포지션
            profit = (entry_price - price) * volume
            profit_pct = ((entry_price - price) / entry_price) * 100

        self.log_trade('SELL', price, volume, profit, profit_pct, exchange)

    def get_today_trades(self):
        """오늘의 거래 내역 조회"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()

            cursor.execute("""
                SELECT action, price, volume, profit, profit_pct, exchange, timestamp
                FROM trades
                WHERE strategy_id = ?
                AND date(timestamp) = date('now')
                ORDER BY timestamp DESC
            """, (self.strategy_id,))

            trades = cursor.fetchall()
            conn.close()

            return trades

        except Exception as e:
            print(f"❌ 거래 내역 조회 실패: {e}")
            return []

    def get_statistics(self):
        """전체 거래 통계"""
        try:
            conn = sqlite3.connect(self.db_path)
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

            conn.close()

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
                ADD COLUMN exchange TEXT DEFAULT 'upbit'
            """)
            conn.commit()
            print("✅ trades 테이블에 exchange 컬럼 추가 완료")

        conn.close()

    except Exception as e:
        print(f"⚠️  컬럼 추가 실패: {e}")


if __name__ == "__main__":
    """테스트"""

    # DB 경로
    import os
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
    logger.log_position_open(100_000_000, 0.001, 'upbit')
    logger.log_position_close(102_000_000, 0.001, 100_000_000, 'upbit')

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
