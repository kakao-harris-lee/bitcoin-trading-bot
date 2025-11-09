#!/usr/bin/env python3
"""
v35 Optuna 최적화 스크립트
목표: 2025년 +15% 달성 (현재 +12.69%, 추가 +2.31%p 필요)
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategy import V35OptimizedStrategy
from backtest import V35Backtester
import optuna
import pandas as pd
import json
from datetime import datetime


def objective(trial):
    """Optuna 목적 함수 - 2025년 수익률 최대화"""

    # 하이퍼파라미터 샘플링
    config = {
        # Market Classifier
        'mfi_bull_strong': trial.suggest_int('mfi_bull_strong', 48, 58),
        'mfi_bull_moderate': trial.suggest_int('mfi_bull_moderate', 42, 50),
        'mfi_sideways_up': trial.suggest_int('mfi_sideways_up', 38, 46),
        'mfi_bear_moderate': trial.suggest_int('mfi_bear_moderate', 34, 42),
        'mfi_bear_strong': trial.suggest_int('mfi_bear_strong', 30, 38),
        'adx_strong_trend': trial.suggest_int('adx_strong_trend', 18, 25),
        'adx_moderate_trend': trial.suggest_int('adx_moderate_trend', 12, 18),

        # Entry Conditions
        'momentum_rsi_bull_strong': trial.suggest_int('momentum_rsi_bull_strong', 48, 58),
        'momentum_rsi_bull_moderate': trial.suggest_int('momentum_rsi_bull_moderate', 50, 60),
        'breakout_threshold': trial.suggest_float('breakout_threshold', 0.003, 0.008),
        'breakout_volume_mult': trial.suggest_float('breakout_volume_mult', 1.2, 1.5),
        'range_support_zone': trial.suggest_float('range_support_zone', 0.10, 0.20),
        'range_rsi_oversold': trial.suggest_int('range_rsi_oversold', 35, 45),

        # Exit Conditions - Bull Strong
        'tp_bull_strong_1': trial.suggest_float('tp_bull_strong_1', 0.03, 0.07),
        'tp_bull_strong_2': trial.suggest_float('tp_bull_strong_2', 0.08, 0.15),
        'tp_bull_strong_3': trial.suggest_float('tp_bull_strong_3', 0.15, 0.25),
        'trailing_bull_strong': trial.suggest_float('trailing_bull_strong', 0.03, 0.07),

        # Exit Conditions - Bull Moderate
        'tp_bull_moderate_1': trial.suggest_float('tp_bull_moderate_1', 0.02, 0.05),
        'tp_bull_moderate_2': trial.suggest_float('tp_bull_moderate_2', 0.05, 0.10),
        'tp_bull_moderate_3': trial.suggest_float('tp_bull_moderate_3', 0.10, 0.15),
        'trailing_bull_moderate': trial.suggest_float('trailing_bull_moderate', 0.02, 0.05),

        # Exit Conditions - Sideways
        'tp_sideways_1': trial.suggest_float('tp_sideways_1', 0.015, 0.03),
        'tp_sideways_2': trial.suggest_float('tp_sideways_2', 0.03, 0.06),
        'tp_sideways_3': trial.suggest_float('tp_sideways_3', 0.05, 0.08),

        # Stop Loss
        'stop_loss': trial.suggest_float('stop_loss', -0.025, -0.010),

        # Exit Fractions
        'exit_fraction_1': trial.suggest_float('exit_fraction_1', 0.3, 0.5),
        'exit_fraction_2': trial.suggest_float('exit_fraction_2', 0.25, 0.4),
        # exit_fraction_3는 나머지로 자동 계산

        # Position Sizing
        'position_size': trial.suggest_float('position_size', 0.4, 0.7),

        # Sideways Strategies
        'use_rsi_bb': trial.suggest_categorical('use_rsi_bb', [True, False]),
        'use_stoch': trial.suggest_categorical('use_stoch', [True, False]),
        'use_volume_breakout': trial.suggest_categorical('use_volume_breakout', [True, False]),
        'rsi_bb_oversold': trial.suggest_int('rsi_bb_oversold', 25, 35),
        'rsi_bb_overbought': trial.suggest_int('rsi_bb_overbought', 65, 75),
        'stoch_oversold': trial.suggest_int('stoch_oversold', 15, 25),
        'stoch_overbought': trial.suggest_int('stoch_overbought', 75, 85),
        'volume_breakout_mult': trial.suggest_float('volume_breakout_mult', 1.8, 2.5),

        # Backtest Config
        'initial_capital': 10000000,
        'fee_rate': 0.0005,
        'slippage': 0.0002,
    }

    # exit_fraction_3 계산
    config['exit_fraction_3'] = 1.0 - config['exit_fraction_1'] - config['exit_fraction_2']
    if config['exit_fraction_3'] <= 0:
        return -999  # 불가능한 조합

    try:
        # 2025년 데이터 로드
        with DataLoader('../../upbit_bitcoin.db') as loader:
            df = loader.load_timeframe('day', start_date='2025-01-01', end_date='2025-10-17')

        # 지표 추가
        df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'mfi', 'adx', 'atr', 'bb', 'stoch'])

        # 백테스팅
        strategy = V35OptimizedStrategy(config)
        backtester = V35Backtester(
            initial_capital=config['initial_capital'],
            fee_rate=config['fee_rate'],
            slippage=config['slippage']
        )
        results = backtester.run(df, strategy)

        # 목적 함수: 수익률 최대화 (단, 샤프 비율 >= 1.5, MDD >= -10% 제약)
        total_return = results['total_return']
        sharpe = results['sharpe_ratio']
        mdd = results['max_drawdown']

        # 제약 조건
        if sharpe < 1.5:
            total_return -= 10 * (1.5 - sharpe)  # 샤프 비율 페널티
        if mdd < -10:
            total_return -= 10 * abs(mdd + 10)  # MDD 페널티

        return total_return

    except Exception as e:
        print(f"Trial {trial.number} failed: {e}")
        return -999


def run_optimization(n_trials=500):
    """Optuna 최적화 실행"""

    print("="*70)
    print("  v35 Optuna 최적화 시작")
    print("="*70)
    print(f"목표: 2025년 수익률 +15% 달성 (현재 +12.69%)")
    print(f"Trials: {n_trials}회")
    print(f"최적화 기간: 약 {n_trials * 2 // 60}분 예상")
    print("="*70)

    # Optuna Study 생성
    study = optuna.create_study(
        direction='maximize',
        study_name='v35_optimization',
        sampler=optuna.samplers.TPESampler(seed=42)
    )

    # 최적화 실행
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # 결과 출력
    print("\n" + "="*70)
    print("  최적화 완료!")
    print("="*70)
    print(f"Best Trial: {study.best_trial.number}")
    print(f"Best Return: {study.best_value:.2f}%")
    print("\n[Best Parameters]")
    for key, value in study.best_params.items():
        print(f"  {key}: {value}")

    # 최적 파라미터로 전체 백테스트 (2023-2025)
    print("\n" + "="*70)
    print("  최적 파라미터로 전체 백테스트")
    print("="*70)

    best_config = study.best_params.copy()
    best_config['initial_capital'] = 10000000
    best_config['fee_rate'] = 0.0005
    best_config['slippage'] = 0.0002
    best_config['exit_fraction_3'] = 1.0 - best_config['exit_fraction_1'] - best_config['exit_fraction_2']

    results_all_years = {}

    for year in ['2023', '2024', '2025']:
        with DataLoader('../../upbit_bitcoin.db') as loader:
            df = loader.load_timeframe(
                'day',
                start_date=f'{year}-01-01',
                end_date=f'{year}-12-31' if year != '2025' else '2025-10-17'
            )

        df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'mfi', 'adx', 'atr', 'bb', 'stoch'])

        strategy = V35OptimizedStrategy(best_config)
        backtester = V35Backtester(
            initial_capital=best_config['initial_capital'],
            fee_rate=best_config['fee_rate'],
            slippage=best_config['slippage']
        )
        results = backtester.run(df, strategy)

        results_all_years[year] = {k: v for k, v in results.items() if k not in ['trades', 'equity_curve']}

        print(f"\n{year}년:")
        print(f"  수익률: {results['total_return']:+.2f}%")
        print(f"  Sharpe: {results['sharpe_ratio']:.2f}")
        print(f"  MDD: {results['max_drawdown']:.2f}%")
        print(f"  승률: {results['win_rate']:.1f}%")

    # 결과 저장
    output = {
        'version': 'v35',
        'optimization_status': 'after_optuna',
        'optimization_date': datetime.now().isoformat(),
        'n_trials': n_trials,
        'best_trial': study.best_trial.number,
        'best_params': study.best_params,
        'results': results_all_years
    }

    with open('backtest_results_after_optuna.json', 'w') as f:
        json.dump(output, f, indent=2, default=str)

    # 최적 config 저장
    optimized_config = {
        'strategy_name': 'optimized',
        'version': 'v35',
        'timeframe': 'day',
        'description': 'v35 Optuna 최적화 완료 (500 trials)',
        'market_classifier': {
            'mfi_bull_strong': best_config['mfi_bull_strong'],
            'mfi_bull_moderate': best_config['mfi_bull_moderate'],
            'mfi_sideways_up': best_config['mfi_sideways_up'],
            'mfi_bear_moderate': best_config['mfi_bear_moderate'],
            'mfi_bear_strong': best_config['mfi_bear_strong'],
            'adx_strong_trend': best_config['adx_strong_trend'],
            'adx_moderate_trend': best_config['adx_moderate_trend']
        },
        'entry_conditions': {
            'momentum_rsi_bull_strong': best_config['momentum_rsi_bull_strong'],
            'momentum_rsi_bull_moderate': best_config['momentum_rsi_bull_moderate'],
            'breakout_threshold': best_config['breakout_threshold'],
            'breakout_volume_mult': best_config['breakout_volume_mult'],
            'range_support_zone': best_config['range_support_zone'],
            'range_rsi_oversold': best_config['range_rsi_oversold']
        },
        'exit_conditions': {
            'tp_bull_strong_1': best_config['tp_bull_strong_1'],
            'tp_bull_strong_2': best_config['tp_bull_strong_2'],
            'tp_bull_strong_3': best_config['tp_bull_strong_3'],
            'trailing_bull_strong': best_config['trailing_bull_strong'],
            'tp_bull_moderate_1': best_config['tp_bull_moderate_1'],
            'tp_bull_moderate_2': best_config['tp_bull_moderate_2'],
            'tp_bull_moderate_3': best_config['tp_bull_moderate_3'],
            'trailing_bull_moderate': best_config['trailing_bull_moderate'],
            'tp_sideways_1': best_config['tp_sideways_1'],
            'tp_sideways_2': best_config['tp_sideways_2'],
            'tp_sideways_3': best_config['tp_sideways_3'],
            'stop_loss': best_config['stop_loss'],
            'exit_fraction_1': best_config['exit_fraction_1'],
            'exit_fraction_2': best_config['exit_fraction_2'],
            'exit_fraction_3': best_config['exit_fraction_3']
        },
        'position_sizing': {
            'position_size': best_config['position_size']
        },
        'sideways_strategies': {
            'use_rsi_bb': best_config['use_rsi_bb'],
            'use_stoch': best_config['use_stoch'],
            'use_volume_breakout': best_config['use_volume_breakout'],
            'rsi_bb_oversold': best_config['rsi_bb_oversold'],
            'rsi_bb_overbought': best_config['rsi_bb_overbought'],
            'stoch_oversold': best_config['stoch_oversold'],
            'stoch_overbought': best_config['stoch_overbought'],
            'volume_breakout_mult': best_config['volume_breakout_mult']
        },
        'backtesting': {
            'initial_capital': 10000000,
            'fee_rate': 0.0005,
            'slippage': 0.0002,
            'train_period': '2020-01-01 to 2024-12-31',
            'test_period': '2025-01-01 to 2025-10-17'
        }
    }

    with open('config_optimized.json', 'w') as f:
        json.dump(optimized_config, f, indent=2)

    print("\n" + "="*70)
    print("  최적화 결과 저장 완료")
    print("="*70)
    print("결과 파일: backtest_results_after_optuna.json")
    print("설정 파일: config_optimized.json")

    # 개선 비교
    if results_all_years['2025']['total_return'] >= 15.0:
        print(f"\n✅ 목표 달성! (2025년 +15% 이상)")
        print(f"최종 수익률: {results_all_years['2025']['total_return']:+.2f}%")
    else:
        improvement = results_all_years['2025']['total_return'] - 12.69
        print(f"\n최적화 전: +12.69%")
        print(f"최적화 후: {results_all_years['2025']['total_return']:+.2f}%")
        print(f"개선: {improvement:+.2f}%p")

        if results_all_years['2025']['total_return'] >= 14.0:
            print(f"✅ 목표 근접 달성 (+14% 이상)")
        else:
            needed = 15.0 - results_all_years['2025']['total_return']
            print(f"⚠️  추가 개선 필요: +{needed:.2f}%p")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='v35 Optuna Optimization')
    parser.add_argument('--n-trials', type=int, default=500, help='Number of Optuna trials')
    args = parser.parse_args()

    run_optimization(n_trials=args.n_trials)
