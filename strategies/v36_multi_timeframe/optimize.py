#!/usr/bin/env python3
"""
v36 Multi-Timeframe Hyperparameter Optimization
Optuna 베이지안 최적화 (2020-2024 학습, 2025 검증)

최적화 대상:
- M240: RSI threshold, TP, SL, Trailing Stop
- M60: RSI oversold/overbought, TP, SL
- 자본 배분 비율 (Day/M240/M60)

목표: 2025년 +25-30% 달성
"""

import sys
sys.path.append('../..')

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategies.v35_optimized.strategy import V35OptimizedStrategy
from strategies.v36_multi_timeframe.strategies.minute240_strategy import Minute240SwingStrategy
from strategies.v36_multi_timeframe.strategies.minute60_strategy import Minute60ScalpingStrategy
from strategies.v36_multi_timeframe.ensemble_manager import EnsembleManager
from strategies.v36_multi_timeframe.backtest import MultiTimeframeBacktester

import optuna
import json
import pandas as pd
import numpy as np
from datetime import datetime
from typing import Dict


class V36Optimizer:
    """v36 Multi-Timeframe 최적화"""

    def __init__(self, train_df_dict: Dict[str, pd.DataFrame], v35_config: Dict):
        """
        Args:
            train_df_dict: {'day': day_df, 'minute240': m240_df, 'minute60': m60_df}
            v35_config: v35 전략 config (Day용)
        """
        self.train_df_dict = train_df_dict
        self.v35_config = v35_config
        self.best_params = None
        self.best_score = -np.inf

    def create_trial_params(self, trial: optuna.Trial) -> Dict:
        """Trial 파라미터 생성"""

        # M240 파라미터
        m240_rsi_threshold = trial.suggest_int('m240_rsi_threshold', 45, 60)
        m240_take_profit = trial.suggest_float('m240_take_profit', 0.03, 0.08)
        m240_stop_loss = trial.suggest_float('m240_stop_loss', -0.03, -0.01)
        m240_trailing_stop = trial.suggest_float('m240_trailing_stop', 0.01, 0.03)
        m240_position_size = trial.suggest_float('m240_position_size', 0.2, 0.4)

        # M60 파라미터
        m60_rsi_oversold = trial.suggest_int('m60_rsi_oversold', 25, 35)
        m60_rsi_overbought = trial.suggest_int('m60_rsi_overbought', 65, 75)
        m60_take_profit = trial.suggest_float('m60_take_profit', 0.015, 0.04)
        m60_stop_loss = trial.suggest_float('m60_stop_loss', -0.025, -0.01)
        m60_position_size = trial.suggest_float('m60_position_size', 0.2, 0.4)

        # 자본 배분
        day_capital = trial.suggest_float('day_capital', 0.3, 0.5)
        m240_capital = trial.suggest_float('m240_capital', 0.2, 0.4)
        # m60_capital = 1.0 - day_capital - m240_capital
        m60_capital = max(0.1, 1.0 - day_capital - m240_capital)

        return {
            'strategy_name': 'multi_timeframe',
            'version': 'v36',

            'capital_allocation': {
                'day_capital': day_capital,
                'm240_capital': m240_capital,
                'm60_capital': m60_capital
            },

            'day_strategy': {
                'use_v35': True,
                'position_size': 0.5
            },

            'minute240_strategy': {
                'm240_rsi_threshold': m240_rsi_threshold,
                'm240_position_size': m240_position_size,
                'm240_take_profit': m240_take_profit,
                'm240_stop_loss': m240_stop_loss,
                'm240_trailing_stop': m240_trailing_stop
            },

            'minute60_strategy': {
                'm60_rsi_oversold': m60_rsi_oversold,
                'm60_rsi_overbought': m60_rsi_overbought,
                'm60_position_size': m60_position_size,
                'm60_take_profit': m60_take_profit,
                'm60_stop_loss': m60_stop_loss
            },

            'backtesting': {
                'initial_capital': 10000000,
                'fee_rate': 0.0005,
                'slippage': 0.0002
            },

            # v35 config 추가
            'market_classifier': self.v35_config.get('market_classifier', {}),
            'entry_conditions': self.v35_config.get('entry_conditions', {}),
            'exit_conditions': self.v35_config.get('exit_conditions', {}),
            'position_sizing': self.v35_config.get('position_sizing', {}),
            'sideways_strategies': self.v35_config.get('sideways_strategies', {})
        }

    def backtest_with_params(self, params: Dict) -> Dict:
        """파라미터로 백테스팅 실행 (2020-2024 학습 데이터)"""

        # 전략 초기화
        v35_strategy = V35OptimizedStrategy({
            'market_classifier': params.get('market_classifier', {}),
            'entry_conditions': params.get('entry_conditions', {}),
            'exit_conditions': params.get('exit_conditions', {}),
            'position_sizing': params.get('position_sizing', {}),
            'sideways_strategies': params.get('sideways_strategies', {})
        })

        m240_strategy = Minute240SwingStrategy(params.get('minute240_strategy', {}))
        m60_strategy = Minute60ScalpingStrategy(params.get('minute60_strategy', {}))
        ensemble_manager = EnsembleManager(params['capital_allocation'])

        # 백테스팅
        backtester = MultiTimeframeBacktester(params)
        results = backtester.run(
            self.train_df_dict['day'],
            self.train_df_dict['minute240'],
            self.train_df_dict['minute60'],
            v35_strategy,
            m240_strategy,
            m60_strategy,
            ensemble_manager
        )

        return results

    def objective(self, trial: optuna.Trial) -> float:
        """Optuna 목표 함수"""

        # 파라미터 생성
        params = self.create_trial_params(trial)

        # 백테스팅
        try:
            results = self.backtest_with_params(params)
        except Exception as e:
            print(f"  Trial {trial.number} 실패: {e}")
            return -1e10

        # 성과 지표
        total_return = results['total_return']
        sharpe_ratio = results['sharpe_ratio']
        max_drawdown = abs(results['max_drawdown'])

        # 목표 함수 계산
        # 수익률 60%, Sharpe 30%, MDD 10%
        return_score = total_return / 25.0  # 목표 25% 대비
        sharpe_score = sharpe_ratio / 2.0    # 목표 2.0 대비
        mdd_score = 1 - (max_drawdown / 20.0)  # MDD 20% 이하 목표

        score = 0.6 * return_score + 0.3 * sharpe_score + 0.1 * mdd_score

        # 출력
        print(f"  Trial {trial.number:3d}: Return={total_return:>7.2f}% | Sharpe={sharpe_ratio:>5.2f} | MDD={max_drawdown:>6.2f}% | Score={score:>6.3f}")

        # 제약 조건: 최소 수익률 10%
        if total_return < 10.0:
            return -1e10

        return score

    def optimize(self, n_trials: int = 200) -> Dict:
        """최적화 실행"""

        print("\n" + "="*80)
        print("  v36 Multi-Timeframe Hyperparameter Optimization")
        print("  학습 기간: 2020-2024")
        print(f"  Trials: {n_trials}")
        print("="*80)

        study = optuna.create_study(
            direction='maximize',
            sampler=optuna.samplers.TPESampler(seed=42)
        )

        study.optimize(self.objective, n_trials=n_trials, show_progress_bar=True)

        # 최적 파라미터
        self.best_params = self.create_trial_params(study.best_trial)
        self.best_score = study.best_value

        print("\n" + "="*80)
        print("  최적화 완료!")
        print("="*80)
        print(f"  Best Score: {self.best_score:.4f}")
        print(f"\n  최적 파라미터:")
        print(f"    자본 배분:")
        print(f"      Day: {self.best_params['capital_allocation']['day_capital']:.2%}")
        print(f"      M240: {self.best_params['capital_allocation']['m240_capital']:.2%}")
        print(f"      M60: {self.best_params['capital_allocation']['m60_capital']:.2%}")
        print(f"\n    M240:")
        m240 = self.best_params['minute240_strategy']
        print(f"      RSI Threshold: {m240['m240_rsi_threshold']}")
        print(f"      Position Size: {m240['m240_position_size']:.2%}")
        print(f"      Take Profit: {m240['m240_take_profit']:.2%}")
        print(f"      Stop Loss: {m240['m240_stop_loss']:.2%}")
        print(f"      Trailing Stop: {m240['m240_trailing_stop']:.2%}")
        print(f"\n    M60:")
        m60 = self.best_params['minute60_strategy']
        print(f"      RSI Oversold: {m60['m60_rsi_oversold']}")
        print(f"      RSI Overbought: {m60['m60_rsi_overbought']}")
        print(f"      Position Size: {m60['m60_position_size']:.2%}")
        print(f"      Take Profit: {m60['m60_take_profit']:.2%}")
        print(f"      Stop Loss: {m60['m60_stop_loss']:.2%}")

        return self.best_params


def main():
    """메인 실행"""

    # 학습 데이터 로드 (2020-2024)
    print("\n데이터 로딩 중...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        day_df = loader.load_timeframe('day', start_date='2020-01-01', end_date='2024-12-31')
        m240_df = loader.load_timeframe('minute240', start_date='2020-01-01', end_date='2024-12-31')
        m60_df = loader.load_timeframe('minute60', start_date='2020-01-01', end_date='2024-12-31')

    print(f"  Day: {len(day_df)} 캔들")
    print(f"  M240: {len(m240_df)} 캔들")
    print(f"  M60: {len(m60_df)} 캔들")

    # 지표 추가
    print("\n지표 계산 중...")
    day_df = MarketAnalyzer.add_indicators(day_df, indicators=['all'])
    m240_df = MarketAnalyzer.add_indicators(m240_df, indicators=['rsi', 'macd', 'bb', 'adx'])
    m60_df = MarketAnalyzer.add_indicators(m60_df, indicators=['rsi', 'macd', 'bb'])

    train_df_dict = {
        'day': day_df,
        'minute240': m240_df,
        'minute60': m60_df
    }

    # v35 config 로드
    with open('../v35_optimized/config.json', 'r') as f:
        v35_config = json.load(f)

    # 최적화 실행
    optimizer = V36Optimizer(train_df_dict, v35_config)
    best_params = optimizer.optimize(n_trials=200)

    # 결과 저장
    output = {
        'optimization_date': datetime.now().isoformat(),
        'train_period': '2020-2024',
        'n_trials': 200,
        'best_score': optimizer.best_score,
        'best_params': best_params
    }

    with open('optimized_config.json', 'w') as f:
        json.dump(output, f, indent=2)

    print("\n최적 파라미터 저장: optimized_config.json")


if __name__ == '__main__':
    main()
