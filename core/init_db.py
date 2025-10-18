#!/usr/bin/env python3
"""
trading_results.db 초기화 스크립트
모든 버전의 백테스팅 결과를 저장하는 통합 DB 생성
"""

import sqlite3
from pathlib import Path

def init_trading_results_db(db_path: str = "trading_results.db"):
    """trading_results.db 스키마 초기화"""

    # 이미 존재하면 백업
    db_file = Path(db_path)
    if db_file.exists():
        backup_path = db_path.replace(".db", "_backup.db")
        print(f"⚠️  기존 DB 발견. 백업: {backup_path}")
        import shutil
        shutil.copy2(db_path, backup_path)

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # 1. strategies 테이블 - 전략 메타데이터
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS strategies (
        strategy_id INTEGER PRIMARY KEY AUTOINCREMENT,
        version TEXT NOT NULL UNIQUE,
        name TEXT NOT NULL,
        type TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'testing',
        description TEXT
    )
    """)

    # 2. backtest_results 테이블 - 백테스팅 결과
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS backtest_results (
        result_id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id INTEGER NOT NULL,
        timeframe TEXT NOT NULL,
        start_date TEXT NOT NULL,
        end_date TEXT NOT NULL,
        initial_capital REAL NOT NULL,
        final_capital REAL NOT NULL,
        total_return REAL,
        sharpe_ratio REAL,
        max_drawdown REAL,
        win_rate REAL,
        profit_factor REAL,
        total_trades INTEGER,
        winning_trades INTEGER,
        losing_trades INTEGER,
        avg_profit REAL,
        avg_loss REAL,
        kelly_criterion REAL,
        executed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
    )
    """)

    # 3. trades 테이블 - 개별 거래 기록
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS trades (
        trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
        result_id INTEGER NOT NULL,
        entry_time TIMESTAMP NOT NULL,
        exit_time TIMESTAMP,
        entry_price REAL NOT NULL,
        exit_price REAL,
        quantity REAL NOT NULL,
        side TEXT NOT NULL,
        profit_loss REAL,
        profit_loss_pct REAL,
        reason TEXT,
        FOREIGN KEY (result_id) REFERENCES backtest_results(result_id)
    )
    """)

    # 4. hyperparameters 테이블 - 하이퍼파라미터 기록
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS hyperparameters (
        param_id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id INTEGER NOT NULL,
        param_name TEXT NOT NULL,
        param_value TEXT NOT NULL,
        param_type TEXT,
        FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
    )
    """)

    # 5. realtime_performance 테이블 - 실시간 거래 성과
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS realtime_performance (
        perf_id INTEGER PRIMARY KEY AUTOINCREMENT,
        strategy_id INTEGER NOT NULL,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        current_capital REAL NOT NULL,
        open_positions TEXT,
        daily_pnl REAL,
        cumulative_pnl REAL,
        FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
    )
    """)

    # 인덱스 생성 (성능 최적화)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_strategy_version ON strategies(version)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_backtest_timeframe ON backtest_results(timeframe)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_result ON trades(result_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_trades_time ON trades(entry_time)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_realtime_strategy ON realtime_performance(strategy_id)")

    conn.commit()
    conn.close()

    print(f"✅ trading_results.db 초기화 완료: {db_path}")
    print(f"   - strategies 테이블")
    print(f"   - backtest_results 테이블")
    print(f"   - trades 테이블")
    print(f"   - hyperparameters 테이블")
    print(f"   - realtime_performance 테이블")

if __name__ == "__main__":
    init_trading_results_db()
