#!/usr/bin/env python3
"""
optimize_simple.py
v04 Simple 전략 Optuna 최적화

목표: 170% 수익률 달성
"""

import sys
sys.path.append('../..')

import json
import optuna
from optuna.samplers import TPESampler

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.backtester import Backtester
from core.evaluator import Evaluator

from strategy_simple import SimpleTrendFollowing, simple_strategy_wrapper


# 전역 데이터 (한번만 로드)
print("Loading data...")
with DataLoader('../../upbit_bitcoin.db') as loader:
    DF_GLOBAL = loader.load_timeframe(
        'minute240',
        start_date='2024-01-01',
        end_date='2024-12-30'
    )

DF_GLOBAL = MarketAnalyzer.add_indicators(DF_GLOBAL, indicators=['ema'])
print(f"Loaded {len(DF_GLOBAL):,} candles")

# Buy&Hold 기준
START_PRICE = DF_GLOBAL.iloc[0]['close']
END_PRICE = DF_GLOBAL.iloc[-1]['close']
BUYHOLD_RETURN = ((END_PRICE - START_PRICE) / START_PRICE) * 100
print(f"Buy&Hold: {BUYHOLD_RETURN:.2f}%\n")


def objective(trial: optuna.Trial) -> float:
    """
    Optuna objective 함수

    최적화 목표:
    1. 수익률 최대화 (목표 170%)
    2. Sharpe Ratio >= 1.0
    3. MDD <= 20%

    Returns:
        score: 높을수록 좋음
    """
    # === 파라미터 제안 ===
    position_fraction = trial.suggest_float('position_fraction', 0.70, 0.95, step=0.05)
    trailing_stop_pct = trial.suggest_float('trailing_stop_pct', 0.15, 0.30, step=0.05)
    stop_loss_pct = trial.suggest_float('stop_loss_pct', 0.10, 0.25, step=0.05)

    # Config 생성
    config = {
        'strategy_name': 'simple_trend_following',
        'version': 'v04_simple_opt',
        'timeframe': 'minute240',
        'position_fraction': position_fraction,
        'trailing_stop_pct': trailing_stop_pct,
        'stop_loss_pct': stop_loss_pct,
        'initial_capital': 10000000,
        'fee_rate': 0.0005,
        'slippage': 0.0002
    }

    # === 백테스팅 실행 ===
    try:
        strategy = SimpleTrendFollowing(config)
        backtester = Backtester(
            initial_capital=config['initial_capital'],
            fee_rate=config['fee_rate'],
            slippage=config['slippage']
        )

        strategy_params = {
            'strategy_instance': strategy,
            'backtester': backtester
        }

        results = backtester.run(
            DF_GLOBAL,
            simple_strategy_wrapper,
            strategy_params
        )

        # 성과 계산
        metrics = Evaluator.calculate_all_metrics(results)

        total_return = metrics['total_return']
        sharpe_ratio = metrics['sharpe_ratio']
        max_drawdown = metrics['max_drawdown']
        total_trades = metrics['total_trades']

        # === 스코어 계산 ===

        # 1. 수익률 스코어 (목표 170%)
        return_score = total_return / 170.0

        # 2. Sharpe 스코어 (목표 >= 1.0)
        sharpe_score = min(sharpe_ratio, 2.0) / 2.0  # 최대 2.0까지만 인정

        # 3. MDD 스코어 (목표 <= 20%)
        mdd_score = max(0, (30.0 - max_drawdown) / 30.0)  # MDD 낮을수록 좋음

        # 4. 거래 횟수 페널티 (너무 많으면 안 좋음)
        trade_penalty = 1.0
        if total_trades < 5:
            trade_penalty = 0.5  # 너무 적으면 페널티
        elif total_trades > 100:
            trade_penalty = 0.8  # 너무 많으면 약간 페널티

        # 가중 합산 (수익률 60%, Sharpe 20%, MDD 20%)
        score = (
            0.60 * return_score +
            0.20 * sharpe_score +
            0.20 * mdd_score
        ) * trade_penalty

        # 로그 출력
        print(f"Trial {trial.number:3d}: Return={total_return:6.2f}% | "
              f"Sharpe={sharpe_ratio:4.2f} | MDD={max_drawdown:5.2f}% | "
              f"Trades={total_trades:2d} | Score={score:.4f} | "
              f"Params: pos={position_fraction:.2f}, trail={trailing_stop_pct:.2f}, stop={stop_loss_pct:.2f}")

        return score

    except Exception as e:
        print(f"Trial {trial.number} failed: {e}")
        return 0.0


def main():
    """메인 최적화 실행"""
    print("="*80)
    print("v04 Simple Strategy Optuna Optimization")
    print("="*80)
    print(f"Target: 170% return")
    print(f"Buy&Hold: {BUYHOLD_RETURN:.2f}%")
    print(f"Trials: 100")
    print("="*80)
    print()

    # Optuna Study 생성
    study = optuna.create_study(
        direction='maximize',
        sampler=TPESampler(seed=42)
    )

    # 최적화 실행
    study.optimize(objective, n_trials=100, show_progress_bar=True)

    # === 결과 출력 ===
    print("\n" + "="*80)
    print("OPTIMIZATION RESULTS")
    print("="*80)

    best_trial = study.best_trial
    best_params = best_trial.params

    print(f"\nBest Score: {best_trial.value:.4f}")
    print(f"\nBest Parameters:")
    print(f"  - position_fraction: {best_params['position_fraction']:.2f}")
    print(f"  - trailing_stop_pct: {best_params['trailing_stop_pct']:.2f}")
    print(f"  - stop_loss_pct: {best_params['stop_loss_pct']:.2f}")

    # 최적 파라미터로 재실행
    print(f"\n{'='*80}")
    print("BEST TRIAL BACKTEST")
    print("="*80)

    config = {
        'strategy_name': 'simple_trend_following',
        'version': 'v04_simple_optimized',
        'timeframe': 'minute240',
        'position_fraction': best_params['position_fraction'],
        'trailing_stop_pct': best_params['trailing_stop_pct'],
        'stop_loss_pct': best_params['stop_loss_pct'],
        'initial_capital': 10000000,
        'fee_rate': 0.0005,
        'slippage': 0.0002
    }

    strategy = SimpleTrendFollowing(config)
    backtester = Backtester(
        initial_capital=config['initial_capital'],
        fee_rate=config['fee_rate'],
        slippage=config['slippage']
    )

    strategy_params = {
        'strategy_instance': strategy,
        'backtester': backtester
    }

    results = backtester.run(DF_GLOBAL, simple_strategy_wrapper, strategy_params)
    metrics = Evaluator.calculate_all_metrics(results)

    print(f"\n=== 최종 성과 ===")
    print(f"수익률: {metrics['total_return']:+.2f}% (vs Buy&Hold: {metrics['total_return'] - BUYHOLD_RETURN:+.2f}%p)")
    print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"Max Drawdown: {metrics['max_drawdown']:.2f}%")
    print(f"총 거래: {metrics['total_trades']}회 | 승률: {metrics['win_rate']:.1%}")
    print(f"Profit Factor: {metrics.get('profit_factor', 0):.2f}")

    target_170 = 170.0
    achieved = "✅" if metrics['total_return'] >= target_170 else "❌"
    print(f"\n170% 목표 달성: {achieved} ({metrics['total_return']:.2f}% vs 170%)")

    # 최적 config 저장
    with open('config_optimized.json', 'w') as f:
        json.dump(config, f, indent=2)

    print(f"\nOptimized config saved to: config_optimized.json")
    print("="*80)


if __name__ == '__main__':
    main()
