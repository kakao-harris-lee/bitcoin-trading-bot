#!/usr/bin/env python3
"""
v37 Supreme - Optuna Hyperparameter Optimization

최적화 목표:
  - 2020-2024 평균 수익률 최대화
  - 2024 강한 상승장 대응 개선 (목표: 60-70%)
  - Sharpe Ratio >= 1.0
  - Max Drawdown <= 20%

최적화 파라미터:
  1. 시장 분류: MA20 slope, ADX 임계값
  2. BULL 전략: RSI, MACD, TP/SL
  3. SIDEWAYS 전략: RSI, BB, Volume
  4. BEAR 전략: RSI, TP
"""

import sys
sys.path.append('../..')

import json
import optuna
import pandas as pd
from datetime import datetime
from typing import Dict

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from core.backtester import Backtester
from core.evaluator import Evaluator

from strategies.v37_supreme.strategy import V37SupremeStrategy


def load_training_data(db_path='../../upbit_bitcoin.db', timeframe='day'):
    """
    학습 데이터 로드 (2020-2024)

    Returns:
        Dict[int, pd.DataFrame]: {year: dataframe}
    """

    data_by_year = {}

    for year in [2020, 2021, 2022, 2023, 2024]:
        with DataLoader(db_path) as loader:
            df = loader.load_timeframe(
                timeframe,
                start_date=f"{year}-01-01",
                end_date=f"{year}-12-31"
            )

        if df is not None and len(df) > 0:
            df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'adx', 'atr', 'bb', 'stoch', 'mfi'])
            data_by_year[year] = df

    return data_by_year


def objective(trial: optuna.Trial, data_by_year: Dict[int, pd.DataFrame]) -> float:
    """
    Optuna 목적 함수

    최적화 목표:
      - 2020-2024 평균 수익률 (가중치 60%)
      - Sharpe Ratio (가중치 20%)
      - 2024년 수익률 (가중치 20%, 중요!)

    Returns:
        종합 점수 (높을수록 좋음)
    """

    # 1. 시장 분류 파라미터
    ma20_slope_bull_strong = trial.suggest_float('ma20_slope_bull_strong', 0.005, 0.020)
    ma20_slope_bull_moderate = trial.suggest_float('ma20_slope_bull_moderate', 0.001, 0.010)
    adx_strong_trend = trial.suggest_int('adx_strong_trend', 15, 30)
    adx_moderate_trend = trial.suggest_int('adx_moderate_trend', 10, 25)

    # 2. Trend Following (BULL_STRONG)
    trend_adx_threshold = trial.suggest_int('trend_adx_threshold', 15, 30)
    trend_stop_loss = trial.suggest_float('trend_stop_loss', -0.15, -0.05)
    trend_trailing_stop = trial.suggest_float('trend_trailing_stop', -0.10, -0.03)
    trend_trailing_trigger = trial.suggest_float('trend_trailing_trigger', 0.10, 0.30)
    trend_max_hold_days = trial.suggest_int('trend_max_hold_days', 60, 120)

    # 3. Swing Trading (BULL_MODERATE)
    swing_rsi_oversold = trial.suggest_int('swing_rsi_oversold', 30, 50)
    swing_tp_1 = trial.suggest_float('swing_tp_1', 0.05, 0.15)
    swing_tp_2 = trial.suggest_float('swing_tp_2', 0.10, 0.25)
    swing_stop_loss = trial.suggest_float('swing_stop_loss', -0.05, -0.01)
    swing_max_hold_days = trial.suggest_int('swing_max_hold_days', 20, 60)

    # 4. SIDEWAYS
    rsi_bb_oversold = trial.suggest_int('rsi_bb_oversold', 20, 40)
    rsi_bb_overbought = trial.suggest_int('rsi_bb_overbought', 60, 80)
    volume_breakout_mult = trial.suggest_float('volume_breakout_mult', 1.5, 3.0)
    sideways_tp_1 = trial.suggest_float('sideways_tp_1', 0.01, 0.04)
    sideways_tp_2 = trial.suggest_float('sideways_tp_2', 0.02, 0.06)
    sideways_tp_3 = trial.suggest_float('sideways_tp_3', 0.04, 0.10)
    sideways_stop_loss = trial.suggest_float('sideways_stop_loss', -0.03, -0.01)

    # 5. Defensive (BEAR)
    defensive_rsi_oversold = trial.suggest_int('defensive_rsi_oversold', 15, 30)
    defensive_tp_1 = trial.suggest_float('defensive_tp_1', 0.03, 0.08)
    defensive_tp_2 = trial.suggest_float('defensive_tp_2', 0.05, 0.15)

    # 설정 구성
    config = {
        # Market Classifier
        'ma20_slope_bull_strong': ma20_slope_bull_strong,
        'ma20_slope_bull_moderate': ma20_slope_bull_moderate,
        'ma20_slope_sideways': 0.001,
        'ma20_slope_bear_moderate': -ma20_slope_bull_moderate,
        'ma20_slope_bear_strong': -ma20_slope_bull_strong,
        'adx_strong_trend': adx_strong_trend,
        'adx_moderate_trend': adx_moderate_trend,
        'adx_weak_trend': max(10, adx_moderate_trend - 5),

        # Dynamic Thresholds
        'threshold_lookback_period': 60,
        'rsi_oversold_quantile': 0.30,
        'rsi_overbought_quantile': 0.70,
        'volume_high_quantile': 0.80,
        'volatility_high_quantile': 0.70,

        # Trend Following
        'trend_adx_threshold': trend_adx_threshold,
        'trend_stop_loss': trend_stop_loss,
        'trend_trailing_stop': trend_trailing_stop,
        'trend_trailing_trigger': trend_trailing_trigger,
        'trend_max_hold_days': trend_max_hold_days,

        # Swing Trading
        'swing_rsi_oversold': swing_rsi_oversold,
        'swing_rsi_extreme': max(20, swing_rsi_oversold - 10),
        'swing_tp_1': swing_tp_1,
        'swing_tp_2': swing_tp_2,
        'swing_stop_loss': swing_stop_loss,
        'swing_max_hold_days': swing_max_hold_days,

        # SIDEWAYS
        'use_rsi_bb': True,
        'use_stoch': True,
        'use_volume_breakout': True,
        'rsi_bb_oversold': rsi_bb_oversold,
        'rsi_bb_overbought': rsi_bb_overbought,
        'stoch_oversold': 20,
        'stoch_overbought': 80,
        'volume_breakout_mult': volume_breakout_mult,
        'sideways_position_size': 0.4,
        'sideways_tp_1': sideways_tp_1,
        'sideways_tp_2': sideways_tp_2,
        'sideways_tp_3': sideways_tp_3,
        'sideways_stop_loss': sideways_stop_loss,
        'sideways_max_hold_days': 20,

        # Defensive
        'defensive_rsi_oversold': defensive_rsi_oversold,
        'defensive_position_size': 0.2,
        'defensive_bear_strong_size': 0.1,
        'defensive_take_profit_1': defensive_tp_1,
        'defensive_take_profit_2': defensive_tp_2,
        'defensive_stop_loss': -0.05,
        'defensive_tp_bear_strong': 0.03,
        'defensive_max_hold_days': 20
    }

    # 연도별 백테스팅
    yearly_returns = []
    yearly_sharpes = []

    backtester = Backtester(
        initial_capital=10000000,
        fee_rate=0.0005,
        slippage=0.0002
    )

    for year, df in data_by_year.items():
        strategy = V37SupremeStrategy(config)

        def strategy_wrapper(df, i, params):
            return strategy.execute(df, i)

        results = backtester.run(df, strategy_wrapper, {})
        metrics = Evaluator.calculate_all_metrics(results)

        yearly_returns.append(metrics['total_return'])
        yearly_sharpes.append(metrics['sharpe_ratio'])

    # 평균 수익률
    avg_return = sum(yearly_returns) / len(yearly_returns)

    # 평균 Sharpe
    avg_sharpe = sum(yearly_sharpes) / len(yearly_sharpes)

    # 2024년 수익률 (가장 중요)
    return_2024 = yearly_returns[4] if len(yearly_returns) > 4 else 0

    # 종합 점수 계산
    # 목표: 2024년 60%+, 평균 30%+, Sharpe 1.0+

    score = (
        0.40 * (return_2024 / 70.0) +      # 2024년 중요도 40% (목표 70%)
        0.40 * (avg_return / 40.0) +        # 평균 수익률 40% (목표 40%)
        0.20 * (avg_sharpe / 1.0)           # Sharpe 20% (목표 1.0)
    )

    # 제약 조건 (페널티)
    if avg_sharpe < 0:
        score *= 0.5  # Sharpe 음수면 50% 페널티

    if return_2024 < 10:
        score *= 0.7  # 2024년 10% 미만이면 30% 페널티

    return score


def main():
    """메인 실행"""
    print("="*70)
    print("  v37 Supreme - Optuna Hyperparameter Optimization")
    print("="*70)

    # 학습 데이터 로드
    print("\n[데이터 로드 중...]")
    data_by_year = load_training_data()

    print(f"  로드 완료: {len(data_by_year)}개 연도")
    for year, df in data_by_year.items():
        print(f"    {year}: {len(df)}개 캔들")

    # Optuna Study 생성
    print("\n[Optuna 최적화 시작]")
    study = optuna.create_study(
        direction='maximize',
        study_name='v37_supreme_optimization',
        sampler=optuna.samplers.TPESampler(seed=42)
    )

    # 최적화 실행
    n_trials = 500
    print(f"  Trials: {n_trials}회")
    print(f"  목표: 2024년 60%+, 평균 30%+, Sharpe 1.0+")
    print(f"  예상 시간: {n_trials * 5 / 60:.0f}분")

    study.optimize(
        lambda trial: objective(trial, data_by_year),
        n_trials=n_trials,
        show_progress_bar=True
    )

    # 최적 파라미터
    print("\n" + "="*70)
    print("  최적화 완료!")
    print("="*70)

    best_params = study.best_params
    best_value = study.best_value

    print(f"\n[최적 점수: {best_value:.4f}]")

    print(f"\n[최적 파라미터]")
    print(f"\n시장 분류:")
    print(f"  MA20 slope BULL_STRONG: {best_params['ma20_slope_bull_strong']:.4f}")
    print(f"  MA20 slope BULL_MODERATE: {best_params['ma20_slope_bull_moderate']:.4f}")
    print(f"  ADX strong: {best_params['adx_strong_trend']}")
    print(f"  ADX moderate: {best_params['adx_moderate_trend']}")

    print(f"\nTrend Following (BULL_STRONG):")
    print(f"  ADX threshold: {best_params['trend_adx_threshold']}")
    print(f"  Stop Loss: {best_params['trend_stop_loss']:.2%}")
    print(f"  Trailing Stop: {best_params['trend_trailing_stop']:.2%}")
    print(f"  Trailing Trigger: {best_params['trend_trailing_trigger']:.2%}")
    print(f"  Max Hold: {best_params['trend_max_hold_days']}일")

    print(f"\nSwing Trading (BULL_MODERATE):")
    print(f"  RSI oversold: {best_params['swing_rsi_oversold']}")
    print(f"  TP 1: {best_params['swing_tp_1']:.2%}")
    print(f"  TP 2: {best_params['swing_tp_2']:.2%}")
    print(f"  Stop Loss: {best_params['swing_stop_loss']:.2%}")
    print(f"  Max Hold: {best_params['swing_max_hold_days']}일")

    print(f"\nSIDEWAYS:")
    print(f"  RSI oversold: {best_params['rsi_bb_oversold']}")
    print(f"  RSI overbought: {best_params['rsi_bb_overbought']}")
    print(f"  Volume mult: {best_params['volume_breakout_mult']:.2f}x")
    print(f"  TP 1/2/3: {best_params['sideways_tp_1']:.2%} / {best_params['sideways_tp_2']:.2%} / {best_params['sideways_tp_3']:.2%}")
    print(f"  Stop Loss: {best_params['sideways_stop_loss']:.2%}")

    print(f"\nDefensive (BEAR):")
    print(f"  RSI oversold: {best_params['defensive_rsi_oversold']}")
    print(f"  TP 1/2: {best_params['defensive_tp_1']:.2%} / {best_params['defensive_tp_2']:.2%}")

    # config_optimized.json 저장
    optimized_config = {
        "strategy_name": "supreme",
        "version": "v37",
        "timeframe": "day",
        "description": "Optuna Optimized (500 trials, 2020-2024)",

        "dynamic_thresholds": {
            "threshold_lookback_period": 60,
            "rsi_oversold_quantile": 0.30,
            "rsi_overbought_quantile": 0.70,
            "volume_high_quantile": 0.80,
            "volatility_high_quantile": 0.70
        },

        "market_classifier": {
            "ma20_slope_bull_strong": best_params['ma20_slope_bull_strong'],
            "ma20_slope_bull_moderate": best_params['ma20_slope_bull_moderate'],
            "ma20_slope_sideways": 0.001,
            "ma20_slope_bear_moderate": -best_params['ma20_slope_bull_moderate'],
            "ma20_slope_bear_strong": -best_params['ma20_slope_bull_strong'],
            "adx_strong_trend": best_params['adx_strong_trend'],
            "adx_moderate_trend": best_params['adx_moderate_trend'],
            "adx_weak_trend": max(10, best_params['adx_moderate_trend'] - 5),
            "volatility_high": 0.03,
            "volatility_low": 0.015,
            "rsi_overbought_ratio": 0.3,
            "rsi_oversold_ratio": 0.3
        },

        "trend_following": {
            "adx_threshold": best_params['trend_adx_threshold'],
            "stop_loss": best_params['trend_stop_loss'],
            "trailing_stop": best_params['trend_trailing_stop'],
            "trailing_trigger": best_params['trend_trailing_trigger'],
            "max_hold_days": best_params['trend_max_hold_days']
        },

        "swing_trading": {
            "rsi_oversold": best_params['swing_rsi_oversold'],
            "take_profit_1": best_params['swing_tp_1'],
            "take_profit_2": best_params['swing_tp_2'],
            "stop_loss": best_params['swing_stop_loss'],
            "max_hold_days": best_params['swing_max_hold_days']
        },

        "sideways": {
            "use_rsi_bb": True,
            "use_stoch": True,
            "use_volume_breakout": True,
            "rsi_bb_oversold": best_params['rsi_bb_oversold'],
            "rsi_bb_overbought": best_params['rsi_bb_overbought'],
            "stoch_oversold": 20,
            "stoch_overbought": 80,
            "volume_breakout_mult": best_params['volume_breakout_mult'],
            "position_size": 0.4,
            "take_profit_1": best_params['sideways_tp_1'],
            "take_profit_2": best_params['sideways_tp_2'],
            "take_profit_3": best_params['sideways_tp_3'],
            "stop_loss": best_params['sideways_stop_loss'],
            "max_hold_days": 20
        },

        "defensive": {
            "rsi_oversold": best_params['defensive_rsi_oversold'],
            "position_size": 0.2,
            "bear_strong_size": 0.1,
            "take_profit_1": best_params['defensive_tp_1'],
            "take_profit_2": best_params['defensive_tp_2'],
            "stop_loss": -0.05,
            "tp_bear_strong": 0.03,
            "max_hold_days": 20
        },

        "backtesting": {
            "initial_capital": 10000000,
            "fee_rate": 0.0005,
            "slippage": 0.0002,
            "train_period": "2020-01-01 to 2024-12-31",
            "test_period": "2025-01-01 to 2025-10-17"
        },

        "target_performance": {
            "annual_return_train": 0.60,
            "annual_return_test": 0.70,
            "sharpe_ratio": 1.5,
            "max_drawdown": 0.20,
            "win_rate": 0.50,
            "buyhold_ratio": 0.75
        },

        "optimization_info": {
            "date": datetime.now().isoformat(),
            "n_trials": n_trials,
            "best_score": best_value,
            "sampler": "TPE"
        }
    }

    with open('config_optimized.json', 'w', encoding='utf-8') as f:
        json.dump(optimized_config, f, indent=2, ensure_ascii=False)

    print(f"\n✅ 최적 설정 저장: config_optimized.json")
    print(f"\n다음 단계:")
    print(f"  1. python backtest.py 실행 (기본 config)")
    print(f"  2. config.json을 config_optimized.json으로 교체")
    print(f"  3. python backtest.py 재실행 (최적화 config)")
    print(f"  4. 2025 Out-of-Sample 검증")


if __name__ == '__main__':
    main()
