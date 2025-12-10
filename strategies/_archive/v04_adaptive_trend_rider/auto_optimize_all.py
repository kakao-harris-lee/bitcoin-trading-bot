#!/usr/bin/env python3
"""
auto_optimize_all.py
모든 타임프레임별 자동 최적화

각 타임프레임의 특성에 맞는 최적 파라미터를 Optuna로 자동 탐색
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


def optimize_timeframe(timeframe: str, n_trials: int = 50):
    """
    특정 타임프레임 최적화

    Args:
        timeframe: 타임프레임 (minute5, minute240, day 등)
        n_trials: Optuna 시행 횟수

    Returns:
        최적 파라미터 및 성과
    """
    print(f"\n{'='*80}")
    print(f"Optimizing {timeframe.upper()}")
    print(f"{'='*80}")

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            timeframe,
            start_date='2024-01-01',
            end_date='2024-12-30'
        )

    df = MarketAnalyzer.add_indicators(df, indicators=['ema'])
    print(f"Loaded {len(df):,} candles")

    # Buy&Hold 계산
    start_price = df.iloc[0]['close']
    end_price = df.iloc[-1]['close']
    buyhold_return = ((end_price - start_price) / start_price) * 100
    print(f"Buy&Hold: {buyhold_return:.2f}%\n")

    def objective(trial: optuna.Trial) -> float:
        """Optuna objective 함수"""

        # 파라미터 제안
        position_fraction = trial.suggest_float('position_fraction', 0.60, 0.95, step=0.05)
        trailing_stop_pct = trial.suggest_float('trailing_stop_pct', 0.10, 0.40, step=0.05)
        stop_loss_pct = trial.suggest_float('stop_loss_pct', 0.10, 0.30, step=0.05)

        config = {
            'strategy_name': 'simple_trend_following',
            'version': 'v04_simple_opt',
            'timeframe': timeframe,
            'position_fraction': position_fraction,
            'trailing_stop_pct': trailing_stop_pct,
            'stop_loss_pct': stop_loss_pct,
            'initial_capital': 10000000,
            'fee_rate': 0.0005,
            'slippage': 0.0002
        }

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

            results = backtester.run(df, simple_strategy_wrapper, strategy_params)
            metrics = Evaluator.calculate_all_metrics(results)

            total_return = metrics['total_return']
            sharpe_ratio = metrics['sharpe_ratio']
            max_drawdown = metrics['max_drawdown']
            total_trades = metrics['total_trades']

            # 스코어 계산
            return_score = total_return / 170.0
            sharpe_score = min(max(sharpe_ratio, 0), 2.0) / 2.0
            mdd_score = max(0, (35.0 - max_drawdown) / 35.0)

            # 거래 횟수 페널티
            trade_penalty = 1.0
            if total_trades < 3:
                trade_penalty = 0.6  # 너무 적으면 페널티
            elif total_trades > 500:
                trade_penalty = 0.7  # 너무 많으면 페널티

            score = (
                0.65 * return_score +
                0.20 * sharpe_score +
                0.15 * mdd_score
            ) * trade_penalty

            return score

        except Exception as e:
            return 0.0

    # Optuna 최적화 실행
    study = optuna.create_study(
        direction='maximize',
        sampler=TPESampler(seed=42)
    )

    optuna.logging.set_verbosity(optuna.logging.WARNING)  # 로그 줄이기
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)

    # 최적 파라미터
    best_params = study.best_trial.params

    # 최적 파라미터로 최종 백테스팅
    config = {
        'strategy_name': 'simple_trend_following',
        'version': 'v04_simple_optimized',
        'timeframe': timeframe,
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

    results = backtester.run(df, simple_strategy_wrapper, strategy_params)
    metrics = Evaluator.calculate_all_metrics(results)

    # 결과 출력
    print(f"\n=== Best Parameters ===")
    print(f"position_fraction:  {best_params['position_fraction']:.2f}")
    print(f"trailing_stop_pct:  {best_params['trailing_stop_pct']:.2f}")
    print(f"stop_loss_pct:      {best_params['stop_loss_pct']:.2f}")

    print(f"\n=== Performance ===")
    print(f"Buy&Hold:     {buyhold_return:7.2f}%")
    print(f"Strategy:     {metrics['total_return']:7.2f}% (vs BH: {metrics['total_return'] - buyhold_return:+.2f}%p)")
    print(f"Sharpe:       {metrics['sharpe_ratio']:7.2f}")
    print(f"MDD:          {metrics['max_drawdown']:7.2f}%")
    print(f"Trades:       {metrics['total_trades']:7d} (Win rate: {metrics['win_rate']:.1%})")

    achieved = "✅" if metrics['total_return'] >= 170.0 else "❌"
    print(f"170% Target:  {achieved} ({metrics['total_return']:.2f}% vs 170%)")

    return {
        'timeframe': timeframe,
        'best_params': best_params,
        'buyhold_return': buyhold_return,
        'strategy_return': metrics['total_return'],
        'sharpe_ratio': metrics['sharpe_ratio'],
        'max_drawdown': metrics['max_drawdown'],
        'total_trades': metrics['total_trades'],
        'win_rate': metrics['win_rate'],
        'profit_factor': metrics.get('profit_factor', 0),
        'achieved_170': metrics['total_return'] >= 170.0
    }


def main():
    """모든 타임프레임 자동 최적화"""

    print("="*80)
    print("v04 Simple Strategy - Auto Optimization for All Timeframes")
    print("="*80)

    # 타임프레임별 시행 횟수 (짧은 프레임은 더 많이)
    timeframe_trials = {
        'minute5': 30,    # 너무 많아서 빠른 탐색
        'minute15': 30,
        'minute30': 40,
        'minute60': 50,
        'minute240': 50,
        'day': 50
    }

    results = []

    for timeframe, n_trials in timeframe_trials.items():
        try:
            result = optimize_timeframe(timeframe, n_trials)
            results.append(result)
        except Exception as e:
            print(f"\n❌ Error optimizing {timeframe}: {e}")
            continue

    # 종합 결과
    print("\n" + "="*80)
    print("SUMMARY - OPTIMIZED PARAMETERS FOR ALL TIMEFRAMES")
    print("="*80)
    print()

    for r in results:
        print(f"\n{r['timeframe'].upper()}:")
        print(f"  Parameters: pos={r['best_params']['position_fraction']:.2f}, "
              f"trail={r['best_params']['trailing_stop_pct']:.2f}, "
              f"stop={r['best_params']['stop_loss_pct']:.2f}")
        print(f"  Performance: {r['strategy_return']:.2f}% | "
              f"Sharpe={r['sharpe_ratio']:.2f} | MDD={r['max_drawdown']:.2f}% | "
              f"Trades={r['total_trades']} | Win={r['win_rate']:.1%}")
        achieved = "✅" if r['achieved_170'] else "❌"
        print(f"  170% Target: {achieved}")

    # 최고 성과
    best = max(results, key=lambda x: x['strategy_return'])
    print(f"\n🏆 Best Timeframe: {best['timeframe'].upper()} with {best['strategy_return']:.2f}% return")

    # 170% 달성
    achieved_170 = [r for r in results if r['achieved_170']]
    if achieved_170:
        print(f"\n✅ 170% Target Achieved:")
        for r in achieved_170:
            print(f"   - {r['timeframe']}: {r['strategy_return']:.2f}%")
    else:
        print(f"\n❌ No timeframe achieved 170% target")

    # 결과 저장
    with open('auto_optimized_all_timeframes.json', 'w') as f:
        json.dump(results, f, indent=2, default=str)

    print(f"\n\nResults saved to: auto_optimized_all_timeframes.json")
    print("="*80)


if __name__ == '__main__':
    main()
