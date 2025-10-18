#!/usr/bin/env python3
"""
optimize_hyperparameters.py

Optuna를 사용한 하이퍼파라미터 자동 최적화 시스템
- 베이지안 최적화로 효율적인 파라미터 탐색
- 다중 목표 최적화 (수익률, Sharpe, MDD)
- Walk-Forward 방식 지원
"""

import sys
sys.path.append('..')

import json
import argparse
from pathlib import Path
from datetime import datetime
import optuna
from optuna.visualization import (
    plot_optimization_history,
    plot_param_importances,
    plot_parallel_coordinate
)
import numpy as np

from core.data_loader import DataLoader
from core.backtester import Backtester
from core.evaluator import Evaluator


class HyperparameterOptimizer:
    """하이퍼파라미터 최적화기"""

    def __init__(self, strategy_path: str, target_return: float = 170.0,
                 max_drawdown: float = 15.0, target_sharpe: float = 1.5):
        """
        Args:
            strategy_path: 전략 디렉토리 경로
            target_return: 목표 수익률 (%)
            max_drawdown: 최대 허용 MDD (%)
            target_sharpe: 목표 Sharpe Ratio
        """
        self.strategy_path = Path(strategy_path)
        self.target_return = target_return
        self.max_drawdown = max_drawdown
        self.target_sharpe = target_sharpe

        # 원본 config 로드
        config_path = self.strategy_path / 'config.json'
        with open(config_path) as f:
            self.base_config = json.load(f)

        # 백테스터 초기화
        self.db_path = Path('upbit_bitcoin.db')

    def objective(self, trial: optuna.Trial) -> float:
        """
        Optuna objective function

        다중 목표:
        1. 수익률 최대화 (목표: 170%)
        2. Sharpe Ratio 최대화 (목표: 1.5)
        3. Max Drawdown 최소화 (목표: < 15%)
        """

        # 파라미터 샘플링
        params = self.suggest_parameters(trial)

        # Config 업데이트
        config = self.base_config.copy()
        config.update(params)

        try:
            # 백테스팅 실행
            results = self.run_backtest(config)

            # 목표 미달 시 페널티
            if results['total_return'] < 0:
                return -1000.0
            if results['max_drawdown'] > self.max_drawdown:
                return -500.0

            # 다중 목표 스코어 계산
            return_score = results['total_return'] / self.target_return
            sharpe_score = max(results['sharpe_ratio'], 0) / self.target_sharpe
            mdd_score = (self.max_drawdown - results['max_drawdown']) / self.max_drawdown

            # 가중 합산
            # 수익률 50%, Sharpe 30%, MDD 20%
            score = (0.5 * return_score +
                    0.3 * sharpe_score +
                    0.2 * mdd_score)

            return score

        except Exception as e:
            print(f"  ✗ Trial 실패: {e}")
            return -1000.0

    def suggest_parameters(self, trial: optuna.Trial) -> dict:
        """파라미터 제안"""
        params = {}

        # RSI 설정
        if 'rsi_period' in self.base_config:
            params['rsi_period'] = trial.suggest_int('rsi_period', 10, 30)

        if 'adaptive_rsi' in self.base_config:
            params['adaptive_rsi'] = {
                'base_oversold': trial.suggest_int('rsi_oversold', 20, 40),
                'base_overbought': trial.suggest_int('rsi_overbought', 60, 80),
                'adjustment_range': trial.suggest_int('rsi_adjustment', 10, 30)
            }

        # 리스크 관리
        if 'risk_management' in self.base_config:
            params['risk_management'] = {
                'take_profit_1': trial.suggest_float('tp1', 0.03, 0.10),
                'take_profit_2': trial.suggest_float('tp2', 0.08, 0.20),
                'stop_loss': trial.suggest_float('sl', -0.05, -0.01)
            }

            # v02b, v02c의 3단계 익절
            if 'take_profit_3' in self.base_config.get('risk_management', {}):
                params['risk_management']['take_profit_3'] = trial.suggest_float('tp3', 0.15, 0.30)

        # Kelly Fraction
        if 'kelly_fraction' in self.base_config:
            params['kelly_fraction'] = trial.suggest_float('kelly', 0.1, 0.5)
        elif 'kelly_settings' in self.base_config:
            params['kelly_settings'] = {
                'initial_fraction': trial.suggest_float('kelly_initial', 0.1, 0.5),
                'max_fraction': trial.suggest_float('kelly_max', 0.3, 0.7),
                'min_fraction': trial.suggest_float('kelly_min', 0.05, 0.2)
            }

        # Rolling window
        if 'rolling_window' in self.base_config:
            params['rolling_window'] = trial.suggest_int('rolling_window', 20, 50)

        # ADX
        if 'adx_threshold' in self.base_config:
            params['adx_threshold'] = trial.suggest_int('adx_threshold', 15, 30)

        # Volatility
        if 'volatility_threshold' in self.base_config:
            params['volatility_threshold'] = {
                'high': trial.suggest_float('vol_high', 0.02, 0.05),
                'low': trial.suggest_float('vol_low', 0.005, 0.02)
            }

        return params

    def run_backtest(self, config: dict) -> dict:
        """백테스팅 실행"""
        # 전략 로드 (동적 import)
        strategy_module = __import__(
            f"strategies.{self.strategy_path.name}.strategy",
            fromlist=['']
        )

        # 데이터 로드
        with DataLoader(str(self.db_path)) as loader:
            df = loader.load_timeframe(
                config['timeframe'],
                start_date='2024-01-01',
                end_date='2024-12-30'
            )

        # 전략별 indicator 추가 (필요 시)
        # TODO: 각 전략의 add_indicators 함수 호출

        # 백테스팅 실행
        backtester = Backtester(
            initial_capital=config['initial_capital'],
            fee_rate=config['fee_rate'],
            slippage=config['slippage']
        )

        # 전략 함수 찾기 (v01_strategy, v02b_strategy_wrapper 등)
        strategy_func = None
        for attr in dir(strategy_module):
            if 'strategy' in attr.lower() and callable(getattr(strategy_module, attr)):
                strategy_func = getattr(strategy_module, attr)
                break

        if not strategy_func:
            raise ValueError(f"전략 함수를 찾을 수 없습니다: {self.strategy_path.name}")

        results = backtester.run(df, strategy_func, config)

        # 평가 지표 계산
        metrics = Evaluator.calculate_all_metrics(results)

        return metrics

    def optimize(self, n_trials: int = 200, n_jobs: int = 1) -> optuna.Study:
        """최적화 실행"""
        print(f"\n{'='*70}")
        print(f"하이퍼파라미터 최적화 시작")
        print(f"{'='*70}")
        print(f"전략: {self.strategy_path.name}")
        print(f"목표 수익률: {self.target_return}%")
        print(f"목표 Sharpe: {self.target_sharpe}")
        print(f"최대 MDD: {self.max_drawdown}%")
        print(f"Trial 횟수: {n_trials}")
        print(f"{'='*70}\n")

        # Optuna study 생성
        study = optuna.create_study(
            direction='maximize',
            study_name=f"{self.strategy_path.name}_optimization",
            sampler=optuna.samplers.TPESampler(seed=42)
        )

        # 최적화 실행
        study.optimize(
            self.objective,
            n_trials=n_trials,
            n_jobs=n_jobs,
            show_progress_bar=True
        )

        # 결과 출력
        self.print_results(study)

        # 결과 저장
        self.save_results(study)

        return study

    def print_results(self, study: optuna.Study):
        """결과 출력"""
        print(f"\n{'='*70}")
        print(f"최적화 완료")
        print(f"{'='*70}")
        print(f"Best Score: {study.best_value:.4f}")
        print(f"\nBest Parameters:")
        for key, value in study.best_params.items():
            print(f"  {key}: {value}")
        print(f"{'='*70}\n")

    def save_results(self, study: optuna.Study):
        """결과 저장"""
        timestamp = datetime.now().strftime('%y%m%d_%H%M%S')

        # 1. 최적 파라미터를 config_optimized.json에 저장
        optimized_config = self.base_config.copy()

        # best_params를 config 구조에 맞게 병합
        for key, value in study.best_params.items():
            if 'rsi_' in key:
                if 'adaptive_rsi' not in optimized_config:
                    optimized_config['adaptive_rsi'] = {}
                if key == 'rsi_oversold':
                    optimized_config['adaptive_rsi']['base_oversold'] = value
                elif key == 'rsi_overbought':
                    optimized_config['adaptive_rsi']['base_overbought'] = value
                elif key == 'rsi_adjustment':
                    optimized_config['adaptive_rsi']['adjustment_range'] = value
                elif key == 'rsi_period':
                    optimized_config['rsi_period'] = value
            elif key in ['tp1', 'tp2', 'tp3', 'sl']:
                if 'risk_management' not in optimized_config:
                    optimized_config['risk_management'] = {}
                if key == 'tp1':
                    optimized_config['risk_management']['take_profit_1'] = value
                elif key == 'tp2':
                    optimized_config['risk_management']['take_profit_2'] = value
                elif key == 'tp3':
                    optimized_config['risk_management']['take_profit_3'] = value
                elif key == 'sl':
                    optimized_config['risk_management']['stop_loss'] = value
            elif 'kelly' in key:
                if key == 'kelly':
                    optimized_config['kelly_fraction'] = value
                else:
                    if 'kelly_settings' not in optimized_config:
                        optimized_config['kelly_settings'] = {}
                    if key == 'kelly_initial':
                        optimized_config['kelly_settings']['initial_fraction'] = value
                    elif key == 'kelly_max':
                        optimized_config['kelly_settings']['max_fraction'] = value
                    elif key == 'kelly_min':
                        optimized_config['kelly_settings']['min_fraction'] = value
            else:
                optimized_config[key] = value

        config_path = self.strategy_path / 'config_optimized.json'
        with open(config_path, 'w') as f:
            json.dump(optimized_config, f, indent=2, ensure_ascii=False)
        print(f"✓ 최적 config 저장: {config_path}")

        # 2. 최적화 리포트 생성
        report_path = self.strategy_path / f'optimization_report_{timestamp}.md'
        with open(report_path, 'w') as f:
            f.write(f"# 하이퍼파라미터 최적화 리포트\n\n")
            f.write(f"**전략**: {self.strategy_path.name}\n")
            f.write(f"**시간**: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
            f.write(f"**Trial 횟수**: {len(study.trials)}\n\n")
            f.write(f"## 최적 스코어\n\n")
            f.write(f"{study.best_value:.4f}\n\n")
            f.write(f"## 최적 파라미터\n\n")
            f.write("```yaml\n")
            for key, value in study.best_params.items():
                f.write(f"{key}: {value}\n")
            f.write("```\n\n")
            f.write(f"## 목표\n\n")
            f.write(f"- 수익률: {self.target_return}%\n")
            f.write(f"- Sharpe Ratio: {self.target_sharpe}\n")
            f.write(f"- Max Drawdown: < {self.max_drawdown}%\n")
        print(f"✓ 최적화 리포트 저장: {report_path}")

        # 3. Study 객체 저장 (시각화용)
        study_path = self.strategy_path / f'optuna_study_{timestamp}.pkl'
        import pickle
        with open(study_path, 'wb') as f:
            pickle.dump(study, f)
        print(f"✓ Optuna study 저장: {study_path}")


def main():
    """메인 실행"""
    parser = argparse.ArgumentParser(description='하이퍼파라미터 최적화')
    parser.add_argument('--strategy', required=True, help='전략 디렉토리 (예: strategies/v02b_split_exit)')
    parser.add_argument('--n-trials', type=int, default=200, help='Trial 횟수')
    parser.add_argument('--target-return', type=float, default=170.0, help='목표 수익률 (%)')
    parser.add_argument('--max-drawdown', type=float, default=15.0, help='최대 허용 MDD (%)')
    parser.add_argument('--target-sharpe', type=float, default=1.5, help='목표 Sharpe Ratio')
    parser.add_argument('--n-jobs', type=int, default=1, help='병렬 실행 프로세스 수')

    args = parser.parse_args()

    # 최적화기 생성
    optimizer = HyperparameterOptimizer(
        strategy_path=args.strategy,
        target_return=args.target_return,
        max_drawdown=args.max_drawdown,
        target_sharpe=args.target_sharpe
    )

    # 최적화 실행
    study = optimizer.optimize(
        n_trials=args.n_trials,
        n_jobs=args.n_jobs
    )


if __name__ == '__main__':
    main()
