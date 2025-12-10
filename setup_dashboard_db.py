#!/usr/bin/env python3
"""
웹 대시보드용 데이터베이스 초기화 스크립트
"""

import sqlite3
from pathlib import Path

# DB 경로
DB_PATH = Path(__file__).parent / "trading_results.db"

print("=" * 70)
print("📊 웹 대시보드 데이터베이스 초기화")
print("=" * 70)
print(f"DB 경로: {DB_PATH}")
print()

# 기존 DB 삭제 (있으면)
if DB_PATH.exists():
    print("⚠️  기존 DB 파일 삭제 중...")
    DB_PATH.unlink()

# DB 연결 및 생성
conn = sqlite3.connect(str(DB_PATH))
cursor = conn.cursor()

print("✅ 1. 스키마 생성 중...")

# 전략 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS strategies (
    strategy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    timeframe TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
)
""")

# 백테스팅 결과 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS backtest_results (
    result_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL,
    total_return REAL,
    sharpe_ratio REAL,
    max_drawdown REAL,
    win_rate REAL,
    total_trades INTEGER,
    start_date TEXT,
    end_date TEXT,
    initial_capital REAL,
    final_capital REAL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
)
""")

# 실시간 거래 내역 테이블
cursor.execute("""
CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL,
    action TEXT NOT NULL,
    price REAL NOT NULL,
    volume REAL NOT NULL,
    profit REAL,
    profit_pct REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
)
""")

# 인덱스 생성
cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategies_version ON strategies(version)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_id)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id)")
cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp)")

print("✅ 스키마 생성 완료")
print()

print("✅ 2. 테스트 데이터 삽입 중...")

# v35 전략
cursor.execute("""
INSERT INTO strategies (version, name, description, timeframe)
VALUES ('v35', 'optimized', 'Optuna 최적화 + 동적 익절 + SIDEWAYS 강화', 'day')
""")
strategy_id_v35 = cursor.lastrowid

cursor.execute("""
INSERT INTO backtest_results
(strategy_id, total_return, sharpe_ratio, max_drawdown, win_rate,
 total_trades, start_date, end_date, initial_capital, final_capital)
VALUES (?, 0.1420, 2.24, -0.0233, 0.25, 16, '2025-01-01', '2025-12-31', 10000000, 11420000)
""", (strategy_id_v35,))

# v-a-02 전략
cursor.execute("""
INSERT INTO strategies (version, name, description, timeframe)
VALUES ('v-a-02', 'multi_indicator_score', 'v42 Score Engine (7차원 지표)', 'day')
""")
strategy_id_va02 = cursor.lastrowid

cursor.execute("""
INSERT INTO backtest_results
(strategy_id, total_return, sharpe_ratio, max_drawdown, win_rate,
 total_trades, start_date, end_date, initial_capital, final_capital)
VALUES (?, 0.1128, 1.85, -0.0350, 0.75, 200, '2024-01-01', '2024-12-31', 10000000, 11128000)
""", (strategy_id_va02,))

# v34 전략
cursor.execute("""
INSERT INTO strategies (version, name, description, timeframe)
VALUES ('v34', 'supreme', '7-Level 시장 분류 + Multi-Strategy', 'day')
""")
strategy_id_v34 = cursor.lastrowid

cursor.execute("""
INSERT INTO backtest_results
(strategy_id, total_return, sharpe_ratio, max_drawdown, win_rate,
 total_trades, start_date, end_date, initial_capital, final_capital)
VALUES (?, 0.0843, 1.34, -0.0283, 0.60, 25, '2025-01-01', '2025-12-31', 10000000, 10843000)
""", (strategy_id_v34,))

# v31 전략
cursor.execute("""
INSERT INTO strategies (version, name, description, timeframe)
VALUES ('v31', 'scalping_with_classifier', 'Minute60 + Day 필터', 'minute60')
""")
strategy_id_v31 = cursor.lastrowid

cursor.execute("""
INSERT INTO backtest_results
(strategy_id, total_return, sharpe_ratio, max_drawdown, win_rate,
 total_trades, start_date, end_date, initial_capital, final_capital)
VALUES (?, 0.0633, 1.94, -0.0896, 0.45, 50, '2024-01-01', '2024-12-31', 10000000, 10633000)
""", (strategy_id_v31,))

print("✅ 테스트 데이터 삽입 완료")
print()

# 변경사항 저장
conn.commit()

# 결과 확인
cursor.execute("SELECT COUNT(*) FROM strategies")
strategy_count = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM backtest_results")
result_count = cursor.fetchone()[0]

conn.close()

print("=" * 70)
print("✅ 데이터베이스 초기화 완료!")
print("=" * 70)
print(f"전략: {strategy_count}개")
print(f"백테스팅 결과: {result_count}개")
print()
print(f"DB 파일: {DB_PATH}")
print(f"DB 크기: {DB_PATH.stat().st_size / 1024:.1f} KB")
print()
