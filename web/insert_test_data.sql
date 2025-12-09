-- 테스트 데이터 삽입
-- v35, v34, v31 전략 결과 (CLAUDE.md 기준)

-- v35 Optimized (현재 최고)
INSERT INTO strategies (version, name, description, timeframe)
VALUES ('v35', 'optimized', 'Optuna 최적화 + 동적 익절 + SIDEWAYS 강화', 'day');

INSERT INTO backtest_results (
    strategy_id, total_return, sharpe_ratio, max_drawdown, win_rate,
    total_trades, start_date, end_date, initial_capital, final_capital
)
VALUES (
    1, 14.20, 2.24, -2.33, 0.25,
    8, '2025-01-01', '2025-10-20', 10000000, 11420000
);

-- v34 Supreme
INSERT INTO strategies (version, name, description, timeframe)
VALUES ('v34', 'supreme', '7-Level 시장 분류 + Multi-Strategy', 'day');

INSERT INTO backtest_results (
    strategy_id, total_return, sharpe_ratio, max_drawdown, win_rate,
    total_trades, start_date, end_date, initial_capital, final_capital
)
VALUES (
    2, 8.43, 1.34, -2.83, 0.60,
    15, '2025-01-01', '2025-10-19', 10000000, 10843000
);

-- v31 Scalping
INSERT INTO strategies (version, name, description, timeframe)
VALUES ('v31', 'scalping_with_classifier', 'Minute60 + Day 필터', 'minute60');

INSERT INTO backtest_results (
    strategy_id, total_return, sharpe_ratio, max_drawdown, win_rate,
    total_trades, start_date, end_date, initial_capital, final_capital
)
VALUES (
    3, 6.33, 1.94, -8.96, 0.45,
    124, '2024-01-01', '2024-12-31', 10000000, 10633000
);

-- v-a-02 (Perfect Signal Reproduction)
INSERT INTO strategies (version, name, description, timeframe)
VALUES ('v-a-02', 'multi_indicator_score', 'v42 Score Engine (7차원 지표)', 'day');

INSERT INTO backtest_results (
    strategy_id, total_return, sharpe_ratio, max_drawdown, win_rate,
    total_trades, start_date, end_date, initial_capital, final_capital
)
VALUES (
    4, 11.28, 1.85, -3.50, 0.75,
    192, '2024-01-01', '2024-12-31', 10000000, 11128000
);
