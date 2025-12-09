-- trading_results.db 초기화 스크립트
-- Bitcoin Trading Bot Dashboard

-- 전략 테이블
CREATE TABLE IF NOT EXISTS strategies (
    strategy_id INTEGER PRIMARY KEY AUTOINCREMENT,
    version TEXT NOT NULL,
    name TEXT NOT NULL,
    description TEXT,
    timeframe TEXT,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- 백테스팅 결과 테이블
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
);

-- 실시간 거래 내역 테이블
CREATE TABLE IF NOT EXISTS trades (
    trade_id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL,
    action TEXT NOT NULL,  -- 'BUY' or 'SELL'
    price REAL NOT NULL,
    volume REAL NOT NULL,
    profit REAL,
    profit_pct REAL,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
);

-- 인덱스 생성
CREATE INDEX IF NOT EXISTS idx_strategies_version ON strategies(version);
CREATE INDEX IF NOT EXISTS idx_backtest_strategy ON backtest_results(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_strategy ON trades(strategy_id);
CREATE INDEX IF NOT EXISTS idx_trades_timestamp ON trades(timestamp);
