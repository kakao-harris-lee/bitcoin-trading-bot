#!/usr/bin/env python3
"""
Optuna Hyperparameter Optimization for v07

최적화 대상:
  - Trailing Stop %
  - Stop Loss %
  - MACD 파라미터
  - 분할 익절 임계값 (선택적)
"""

import sys
sys.path.append('../..')

import json
import optuna
import pandas as pd
import numpy as np
from datetime import datetime
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.evaluator import Evaluator
from simple_backtester import SimpleBacktester
from strategy import v07_strategy


# Global data
df_global = None


def load_data():
    """데이터 로드 (1회만)"""
    global df_global

    if df_global is not None:
        return df_global

    print("데이터 로드 중...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-30')

    print(f"로드 완료: {len(df)}개 캔들")
    df_global = df
    return df


def objective(trial):
    """
    Optuna objective function

    최적화 목표: 수익률 최대화 (제약: Sharpe >= 0.8, MDD <= 35%)
    """
    global df_global

    # Suggest parameters
    trailing_stop_pct = trial.suggest_float('trailing_stop_pct', 0.10, 0.30, step=0.01)
    stop_loss_pct = trial.suggest_float('stop_loss_pct', 0.05, 0.15, step=0.01)
    macd_fast = trial.suggest_int('macd_fast', 8, 16)
    macd_slow = trial.suggest_int('macd_slow', 20, 32)
    macd_signal = trial.suggest_int('macd_signal', 7, 11)

    # macd_slow must be > macd_fast
    if macd_slow <= macd_fast:
        return -999  # Invalid configuration

    # Add indicators with trial parameters
    df = df_global.copy()

    # EMA
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['prev_ema12'] = df['ema12'].shift(1)
    df['prev_ema26'] = df['ema26'].shift(1)

    # MACD with trial parameters
    exp1 = df['close'].ewm(span=macd_fast, adjust=False).mean()
    exp2 = df['close'].ewm(span=macd_slow, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=macd_signal, adjust=False).mean()
    df['prev_macd'] = df['macd'].shift(1)
    df['prev_macd_signal'] = df['macd_signal'].shift(1)

    # Reset strategy state
    v07_strategy.in_position = False
    v07_strategy.entry_price = None
    v07_strategy.highest_price = None

    # Backtester
    backtester = SimpleBacktester(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0002
    )

    params = {
        'trailing_stop_pct': trailing_stop_pct,
        'stop_loss_pct': stop_loss_pct,
        'position_fraction': 0.95
    }

    # Run backtest
    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = row['timestamp']
        price = row['close']

        decision = v07_strategy(df, i, params)
        action = decision['action']

        if action == 'buy':
            backtester.execute_buy(timestamp, price, decision['fraction'])
        elif action == 'sell':
            backtester.execute_sell(timestamp, price, decision['fraction'])

        backtester.record_equity(timestamp, price)

    # Final liquidation
    if backtester.position > 0:
        final_time = df.iloc[-1]['timestamp']
        final_price = df.iloc[-1]['close']
        backtester.execute_sell(final_time, final_price, 1.0)
        backtester.record_equity(final_time, final_price)

    # Evaluate
    results = backtester.get_results()

    try:
        metrics = Evaluator.calculate_all_metrics(results)
    except Exception as e:
        print(f"  Evaluation error: {e}")
        return -999

    total_return = metrics['total_return']
    sharpe = metrics['sharpe_ratio']
    mdd = metrics['max_drawdown']
    total_trades = metrics['total_trades']

    # Constraints
    if sharpe < 0.8:
        return -999  # Too low Sharpe
    if mdd > 35.0:
        return -999  # Too high drawdown
    if total_trades < 2:
        return -999  # Too few trades

    # Objective: maximize return
    return total_return


def optimize(n_trials=200):
    """Optuna 최적화 실행"""
    print("="*80)
    print("v07 Hyperparameter Optimization (Optuna)")
    print("="*80)

    # Load data
    load_data()

    # Create study
    print(f"\nOptuna 최적화 시작 ({n_trials} trials)...")
    print("목표: 수익률 최대화")
    print("제약: Sharpe >= 0.8, MDD <= 35%, 거래 >= 2회")
    print()

    study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=42)
    )

    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # Results
    print("\n" + "="*80)
    print("최적화 완료")
    print("="*80)

    print(f"\n최고 수익률: {study.best_value:.2f}%")
    print("\n최적 파라미터:")
    for key, value in study.best_params.items():
        print(f"  {key}: {value}")

    # Save results
    output = {
        'timestamp': datetime.now().isoformat(),
        'n_trials': n_trials,
        'best_value': study.best_value,
        'best_params': study.best_params,
        'all_trials': [
            {
                'number': t.number,
                'value': t.value,
                'params': t.params
            }
            for t in study.trials if t.value is not None and t.value > -999
        ]
    }

    with open('optuna_results.json', 'w') as f:
        json.dump(output, f, indent=2)

    print("\n결과 저장: optuna_results.json")

    # Test best params
    print("\n" + "="*80)
    print("최적 파라미터로 백테스팅")
    print("="*80)

    test_backtest(study.best_params)


def test_backtest(best_params):
    """최적 파라미터로 백테스팅"""
    global df_global

    df = df_global.copy()

    # Add indicators
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['prev_ema12'] = df['ema12'].shift(1)
    df['prev_ema26'] = df['ema26'].shift(1)

    macd_fast = best_params['macd_fast']
    macd_slow = best_params['macd_slow']
    macd_signal = best_params['macd_signal']

    exp1 = df['close'].ewm(span=macd_fast, adjust=False).mean()
    exp2 = df['close'].ewm(span=macd_slow, adjust=False).mean()
    df['macd'] = exp1 - exp2
    df['macd_signal'] = df['macd'].ewm(span=macd_signal, adjust=False).mean()
    df['prev_macd'] = df['macd'].shift(1)
    df['prev_macd_signal'] = df['macd_signal'].shift(1)

    # Reset
    v07_strategy.in_position = False
    v07_strategy.entry_price = None
    v07_strategy.highest_price = None

    backtester = SimpleBacktester(10_000_000, 0.0005, 0.0002)

    params = {
        'trailing_stop_pct': best_params['trailing_stop_pct'],
        'stop_loss_pct': best_params['stop_loss_pct'],
        'position_fraction': 0.95
    }

    for i in range(len(df)):
        row = df.iloc[i]
        timestamp = row['timestamp']
        price = row['close']

        decision = v07_strategy(df, i, params)
        if decision['action'] == 'buy':
            backtester.execute_buy(timestamp, price, decision['fraction'])
        elif decision['action'] == 'sell':
            backtester.execute_sell(timestamp, price, decision['fraction'])

        backtester.record_equity(timestamp, price)

    if backtester.position > 0:
        final_time = df.iloc[-1]['timestamp']
        final_price = df.iloc[-1]['close']
        backtester.execute_sell(final_time, final_price, 1.0)
        backtester.record_equity(final_time, final_price)

    results = backtester.get_results()
    metrics = Evaluator.calculate_all_metrics(results)

    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buy_hold = ((end_price - start_price) / start_price) * 100

    print(f"\n수익률:         {metrics['total_return']:>14.2f}%")
    print(f"Buy&Hold:       {buy_hold:>14.2f}%")
    print(f"차이:           {metrics['total_return'] - buy_hold:>14.2f}%p")
    print(f"\nSharpe Ratio:   {metrics['sharpe_ratio']:>14.2f}")
    print(f"Max Drawdown:   {metrics['max_drawdown']:>14.2f}%")
    print(f"\n총 거래:        {metrics['total_trades']:>15}회")
    print(f"승률:           {metrics['win_rate']:>14.1%}")


if __name__ == '__main__':
    import sys
    n_trials = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    optimize(n_trials)
