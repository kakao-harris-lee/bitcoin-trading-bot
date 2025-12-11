#!/usr/bin/env python3
"""
SHORT_V1 - Optuna 하이퍼파라미터 최적화
EMA 기간, ADX 임계값, R:R 비율 등 최적화
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional
import pandas as pd
import numpy as np

try:
    import optuna
    from optuna.samplers import TPESampler
except ImportError:
    print("optuna 라이브러리가 필요합니다: pip install optuna")
    sys.exit(1)

sys.path.insert(0, str(Path(__file__).parent))
from backtest import FuturesBacktester


class ShortV1Optimizer:
    """SHORT_V1 하이퍼파라미터 최적화"""

    def __init__(self, df: pd.DataFrame, base_config: Dict):
        """
        초기화

        Args:
            df: OHLCV 데이터프레임
            base_config: 기본 설정
        """
        self.df = df
        self.base_config = base_config
        self.best_params = None
        self.best_score = float('-inf')

    def objective(self, trial: optuna.Trial) -> float:
        """
        최적화 목적 함수

        Args:
            trial: Optuna trial 객체

        Returns:
            최적화 점수 (높을수록 좋음)
        """
        # 하이퍼파라미터 샘플링
        config = self.base_config.copy()

        # 지표 파라미터
        config['indicators'] = {
            'ema_fast': trial.suggest_int('ema_fast', 20, 100),
            'ema_slow': trial.suggest_int('ema_slow', 100, 300),
            'adx_period': trial.suggest_int('adx_period', 10, 20),
            'adx_threshold': trial.suggest_int('adx_threshold', 20, 35),
        }

        # EMA fast < EMA slow 제약
        if config['indicators']['ema_fast'] >= config['indicators']['ema_slow']:
            return float('-inf')

        # 진입 조건
        config['entry'] = {
            'require_death_cross': True,
            'adx_min': config['indicators']['adx_threshold'],
            'di_negative_dominant': True,
            'require_bearish_candle': trial.suggest_categorical('require_bearish_candle', [True, False]),
        }

        # 청산 조건
        config['exit'] = {
            'stop_loss_pct': trial.suggest_float('stop_loss_pct', 2.0, 5.0),
            'max_stop_loss_pct': trial.suggest_float('max_stop_loss_pct', 4.0, 8.0),
            'risk_reward_ratio': trial.suggest_float('risk_reward_ratio', 1.5, 4.0),
            'exit_on_golden_cross': True,
        }

        # 리스크 관리
        config['risk_management'] = {
            'margin_type': 'ISOLATED',
            'max_leverage': trial.suggest_int('max_leverage', 1, 5),
            'position_risk_pct': trial.suggest_float('position_risk_pct', 0.5, 2.0),
            'max_drawdown_pct': 20.0,
            'emergency_stop_pct': 25.0,
        }

        # 백테스트 실행
        try:
            backtester = FuturesBacktester(config)
            results = backtester.run(self.df.copy(), verbose=False)
        except Exception as e:
            print(f"백테스트 오류: {e}")
            return float('-inf')

        # 최소 거래 수 체크
        if results['total_trades'] < 10:
            return float('-inf')

        # MDD 제한 체크
        if results['max_drawdown'] > 20:
            return float('-inf')

        # 복합 점수 계산
        # Profit Factor × Sharpe × (1 - MDD/100) × sqrt(trades)
        profit_factor = results.get('profit_factor', 0)
        sharpe = results.get('sharpe_ratio', 0)
        mdd = results.get('max_drawdown', 100)
        trades = results.get('total_trades', 0)
        expectancy = results.get('expectancy', 0)

        # 음수 Sharpe는 페널티
        if sharpe < 0:
            return float('-inf')

        # 복합 점수
        score = (
            profit_factor *
            max(sharpe, 0.1) *
            (1 - mdd / 100) *
            np.sqrt(trades) *
            max(expectancy + 1, 0.1)
        )

        # 수익률 보너스
        total_return = results.get('total_return', 0)
        if total_return > 0:
            score *= (1 + total_return / 100)

        # 결과 기록
        trial.set_user_attr('total_return', results['total_return'])
        trial.set_user_attr('sharpe_ratio', results['sharpe_ratio'])
        trial.set_user_attr('max_drawdown', results['max_drawdown'])
        trial.set_user_attr('profit_factor', profit_factor)
        trial.set_user_attr('total_trades', trades)
        trial.set_user_attr('win_rate', results.get('win_rate', 0))
        trial.set_user_attr('expectancy', expectancy)

        return score

    def optimize(
        self,
        n_trials: int = 100,
        timeout: Optional[int] = None,
        n_jobs: int = 1
    ) -> Dict:
        """
        최적화 실행

        Args:
            n_trials: 시도 횟수
            timeout: 시간 제한 (초)
            n_jobs: 병렬 작업 수

        Returns:
            최적화 결과
        """
        study = optuna.create_study(
            direction='maximize',
            sampler=TPESampler(seed=42),
            study_name='SHORT_V1_optimization'
        )

        study.optimize(
            self.objective,
            n_trials=n_trials,
            timeout=timeout,
            n_jobs=n_jobs,
            show_progress_bar=True
        )

        # 최적 파라미터
        self.best_params = study.best_params
        self.best_score = study.best_value

        # 최적 trial의 속성
        best_trial = study.best_trial
        best_attrs = {
            'total_return': best_trial.user_attrs.get('total_return', 0),
            'sharpe_ratio': best_trial.user_attrs.get('sharpe_ratio', 0),
            'max_drawdown': best_trial.user_attrs.get('max_drawdown', 0),
            'profit_factor': best_trial.user_attrs.get('profit_factor', 0),
            'total_trades': best_trial.user_attrs.get('total_trades', 0),
            'win_rate': best_trial.user_attrs.get('win_rate', 0),
            'expectancy': best_trial.user_attrs.get('expectancy', 0),
        }

        return {
            'best_params': self.best_params,
            'best_score': self.best_score,
            'best_results': best_attrs,
            'n_trials': len(study.trials),
            'completed_trials': len([t for t in study.trials if t.value is not None and t.value > float('-inf')]),
        }

    def get_optimized_config(self) -> Dict:
        """최적화된 설정 생성"""
        if self.best_params is None:
            raise ValueError("최적화가 실행되지 않았습니다")

        config = self.base_config.copy()

        config['indicators'] = {
            'ema_fast': self.best_params['ema_fast'],
            'ema_slow': self.best_params['ema_slow'],
            'adx_period': self.best_params['adx_period'],
            'adx_threshold': self.best_params['adx_threshold'],
        }

        config['entry'] = {
            'require_death_cross': True,
            'adx_min': self.best_params['adx_threshold'],
            'di_negative_dominant': True,
            'require_bearish_candle': self.best_params['require_bearish_candle'],
        }

        config['exit'] = {
            'stop_loss_pct': self.best_params['stop_loss_pct'],
            'max_stop_loss_pct': self.best_params['max_stop_loss_pct'],
            'risk_reward_ratio': self.best_params['risk_reward_ratio'],
            'exit_on_golden_cross': True,
        }

        config['risk_management'] = {
            'margin_type': 'ISOLATED',
            'max_leverage': self.best_params['max_leverage'],
            'position_risk_pct': self.best_params['position_risk_pct'],
            'max_drawdown_pct': 20.0,
            'emergency_stop_pct': 25.0,
        }

        return config


def run_optimization(
    data_path: Optional[str] = None,
    n_trials: int = 100,
    save_config: bool = True
) -> Dict:
    """
    최적화 실행 편의 함수

    Args:
        data_path: 데이터 파일 경로
        n_trials: 시도 횟수
        save_config: 최적화된 설정 저장 여부

    Returns:
        최적화 결과
    """
    # 기본 설정 로드
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        base_config = json.load(f)

    # 데이터 로드
    if data_path and Path(data_path).exists():
        df = pd.read_csv(data_path, index_col=0, parse_dates=True)
        print(f"데이터 로드: {data_path}")
    else:
        from data_collector import collect_all_data
        df = collect_all_data('2022-01-01', '2024-12-31', '4h')

    print(f"\n{'='*70}")
    print(f"  SHORT_V1 하이퍼파라미터 최적화")
    print(f"  시도 횟수: {n_trials}")
    print(f"{'='*70}\n")

    # 최적화 실행
    optimizer = ShortV1Optimizer(df, base_config)
    results = optimizer.optimize(n_trials=n_trials)

    # 결과 출력
    print(f"\n{'='*70}")
    print(f"  최적화 결과")
    print(f"{'='*70}")
    print(f"\n최적 점수: {results['best_score']:.4f}")
    print(f"완료된 시도: {results['completed_trials']}/{results['n_trials']}")

    print(f"\n📊 최적 성과:")
    print(f"  총 수익률: {results['best_results']['total_return']:+.2f}%")
    print(f"  Sharpe Ratio: {results['best_results']['sharpe_ratio']:.2f}")
    print(f"  Max Drawdown: {results['best_results']['max_drawdown']:.2f}%")
    print(f"  Profit Factor: {results['best_results']['profit_factor']:.2f}")
    print(f"  거래 수: {results['best_results']['total_trades']}")
    print(f"  승률: {results['best_results']['win_rate']:.1f}%")
    print(f"  Expectancy: {results['best_results']['expectancy']:.2f}")

    print(f"\n🔧 최적 파라미터:")
    for param, value in results['best_params'].items():
        print(f"  {param}: {value}")

    # 최적화된 설정 저장
    if save_config:
        optimized_config = optimizer.get_optimized_config()
        output_path = Path(__file__).parent / 'config_optimized.json'
        with open(output_path, 'w') as f:
            json.dump(optimized_config, f, indent=2)
        print(f"\n최적화된 설정 저장: {output_path}")

    return results


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(description='SHORT_V1 최적화')
    parser.add_argument('--data', type=str, help='데이터 파일 경로')
    parser.add_argument('--trials', type=int, default=100, help='시도 횟수')
    parser.add_argument('--no-save', action='store_true', help='설정 저장 비활성화')

    args = parser.parse_args()

    results = run_optimization(
        data_path=args.data,
        n_trials=args.trials,
        save_config=not args.no_save
    )
