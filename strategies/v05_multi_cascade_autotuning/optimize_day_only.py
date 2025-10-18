#!/usr/bin/env python3
"""
optimize_day_only.py
v05: v04 DAY 전략 파라미터 재최적화

목표: 288.67% → 320%+ 달성
방법: Optuna로 position, trailing_stop, stop_loss 미세 조정
"""

import sys
sys.path.append('../..')

import optuna
import json
from core.data_loader import DataLoader
from core.backtester import Backtester
from core.evaluator import Evaluator
from core.market_analyzer import MarketAnalyzer

# v04 전략 import
sys.path.append('../v04_adaptive_trend_rider')
from strategy_simple import SimpleTrendFollowing, simple_strategy_wrapper


def objective(trial: optuna.Trial) -> float:
    """Optuna 목적 함수"""

    # 파라미터 샘플링 (v04 최적값 기준 미세 조정)
    position_fraction = trial.suggest_float('position_fraction', 0.90, 0.98, step=0.01)
    trailing_stop_pct = trial.suggest_float('trailing_stop_pct', 0.15, 0.25, step=0.01)
    stop_loss_pct = trial.suggest_float('stop_loss_pct', 0.08, 0.15, step=0.01)

    # Config
    config = {
        'position_fraction': position_fraction,
        'trailing_stop_pct': trailing_stop_pct,
        'stop_loss_pct': stop_loss_pct
    }

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    df = MarketAnalyzer.add_indicators(df, indicators=['ema'])

    # 전략 생성
    strategy = SimpleTrendFollowing(config)

    # 백테스팅
    backtester = Backtester(
        initial_capital=10_000_000,
        fee_rate=0.0005,
        slippage=0.0002
    )

    results = backtester.run(
        df=df,
        strategy_func=simple_strategy_wrapper,
        strategy_params={
            'strategy_instance': strategy,
            'backtester': backtester
        }
    )

    # 지표 계산
    metrics = Evaluator.calculate_all_metrics(results)

    total_return = results['total_return']
    sharpe = metrics['sharpe_ratio']
    mdd = metrics['max_drawdown']
    trades = results['total_trades']

    # 거래 횟수 페널티 (너무 많으면 감점)
    if trades > 10:
        trade_penalty = 0.9
    elif trades < 3:
        trade_penalty = 0.9
    else:
        trade_penalty = 1.0

    # MDD 페널티
    if mdd > 30:
        mdd_penalty = 0.8
    else:
        mdd_penalty = 1.0

    # Sharpe 보너스
    if sharpe >= 1.8:
        sharpe_bonus = 1.1
    else:
        sharpe_bonus = 1.0

    # 종합 스코어 (수익률 위주)
    score = total_return * trade_penalty * mdd_penalty * sharpe_bonus

    # 로그 출력
    print(f"Trial {trial.number}: pos={position_fraction:.2f}, trail={trailing_stop_pct:.2f}, stop={stop_loss_pct:.2f} "
          f"→ Return={total_return:.2f}%, Sharpe={sharpe:.2f}, MDD={mdd:.2f}%, Trades={trades}, Score={score:.2f}")

    return score


def main():
    print("=" * 80)
    print("v05: DAY Strategy Parameter Re-Optimization")
    print("=" * 80)
    print(f"\nBaseline (v04 DAY): 288.67%")
    print(f"Target (v05): 320%+\n")

    # Optuna 스터디 생성
    study = optuna.create_study(
        direction='maximize',
        sampler=optuna.samplers.TPESampler(seed=42)
    )

    # 최적화 실행
    print("Starting optimization (200 trials)...\n")
    study.optimize(objective, n_trials=200, show_progress_bar=True)

    # 최적 파라미터
    print("\n" + "=" * 80)
    print("BEST PARAMETERS")
    print("=" * 80)
    print(f"\nBest Score: {study.best_value:.2f}")
    print(f"\nParameters:")
    for key, value in study.best_params.items():
        print(f"  {key}: {value:.2f}")

    # 최적 파라미터로 재실행
    print("\n" + "=" * 80)
    print("FINAL BACKTEST WITH BEST PARAMETERS")
    print("=" * 80)

    best_params = study.best_params

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    df = MarketAnalyzer.add_indicators(df, indicators=['ema'])

    strategy = SimpleTrendFollowing(best_params)
    backtester = Backtester()

    results = backtester.run(
        df=df,
        strategy_func=simple_strategy_wrapper,
        strategy_params={'strategy_instance': strategy, 'backtester': backtester}
    )

    metrics = Evaluator.calculate_all_metrics(results)

    print(f"\nReturn: {results['total_return']:.2f}%")
    print(f"Sharpe: {metrics['sharpe_ratio']:.2f}")
    print(f"MDD: {metrics['max_drawdown']:.2f}%")
    print(f"Trades: {results['total_trades']}")
    print(f"Win Rate: {results['win_rate']:.1%}")

    # 목표 달성 여부
    achieved = results['total_return'] >= 320.0
    print(f"\n{'✅ TARGET ACHIEVED!' if achieved else '⚠️  Target not met (but may be improved)'}")

    # 저장
    with open('optimized_day_params.json', 'w') as f:
        json.dump({
            'best_params': best_params,
            'return': results['total_return'],
            'sharpe': metrics['sharpe_ratio'],
            'mdd': metrics['max_drawdown'],
            'trades': results['total_trades'],
            'win_rate': results['win_rate']
        }, f, indent=2)

    print(f"\n✅ Saved to: optimized_day_params.json")
    print("=" * 80 + "\n")


if __name__ == "__main__":
    main()
