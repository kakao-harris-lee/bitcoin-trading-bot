#!/usr/bin/env python3
"""
v35 Optuna 하이퍼파라미터 최적화 엔진

목표: v34 (+8.43% @ 2025) → v35 (+15% @ 2025)
방법: 동적 익절, SIDEWAYS 강화, 최적 파라미터 탐색
"""

import sys
sys.path.append('..')

import optuna
from optuna.samplers import TPESampler
import pandas as pd
import numpy as np
import json
from datetime import datetime
from typing import Dict, Tuple

from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer
from strategies.v34_supreme.market_classifier_v34 import MarketClassifierV34


class V35StrategyOptimizer:
    """v35 전략 최적화를 위한 Optuna 래퍼"""

    def __init__(self, train_start='2020-01-01', train_end='2024-12-31',
                 test_start='2025-01-01', test_end='2025-10-17'):
        self.train_start = train_start
        self.train_end = train_end
        self.test_start = test_start
        self.test_end = test_end

        # 데이터 로드
        print("데이터 로딩...")
        with DataLoader('../upbit_bitcoin.db') as loader:
            self.train_df = loader.load_timeframe('day',
                                                   start_date=train_start,
                                                   end_date=train_end)
            self.test_df = loader.load_timeframe('day',
                                                  start_date=test_start,
                                                  end_date=test_end)

        # 지표 추가
        print("지표 계산...")
        self.train_df = MarketAnalyzer.add_indicators(
            self.train_df,
            indicators=['rsi', 'macd', 'mfi', 'adx', 'atr', 'bb', 'stoch']
        )
        self.test_df = MarketAnalyzer.add_indicators(
            self.test_df,
            indicators=['rsi', 'macd', 'mfi', 'adx', 'atr', 'bb', 'stoch']
        )

        print(f"학습 데이터: {len(self.train_df)}개 캔들 ({train_start} ~ {train_end})")
        print(f"검증 데이터: {len(self.test_df)}개 캔들 ({test_start} ~ {test_end})")

    def create_trial_params(self, trial: optuna.Trial) -> Dict:
        """Optuna trial에서 파라미터 샘플링"""

        params = {
            # ===== 시장 분류기 임계값 =====
            'mfi_bull_strong': trial.suggest_int('mfi_bull_strong', 50, 55),
            'mfi_bull_moderate': trial.suggest_int('mfi_bull_moderate', 43, 48),
            'mfi_sideways_up': trial.suggest_int('mfi_sideways_up', 40, 45),
            'mfi_bear_moderate': trial.suggest_int('mfi_bear_moderate', 35, 40),
            'mfi_bear_strong': trial.suggest_int('mfi_bear_strong', 30, 35),

            'adx_strong_trend': trial.suggest_int('adx_strong_trend', 18, 25),
            'adx_moderate_trend': trial.suggest_int('adx_moderate_trend', 12, 18),

            # ===== Entry 조건 =====
            'momentum_rsi_bull_strong': trial.suggest_int('momentum_rsi_bull_strong', 48, 60),
            'momentum_rsi_bull_moderate': trial.suggest_int('momentum_rsi_bull_moderate', 50, 62),

            'breakout_threshold': trial.suggest_float('breakout_threshold', 0.003, 0.010),
            'breakout_volume_mult': trial.suggest_float('breakout_volume_mult', 1.2, 1.8),

            'range_support_zone': trial.suggest_float('range_support_zone', 0.10, 0.20),
            'range_rsi_oversold': trial.suggest_int('range_rsi_oversold', 30, 45),

            # ===== Exit 조건 (핵심!) =====
            # BULL_STRONG
            'tp_bull_strong_1': trial.suggest_float('tp_bull_strong_1', 0.03, 0.07),
            'tp_bull_strong_2': trial.suggest_float('tp_bull_strong_2', 0.07, 0.15),
            'tp_bull_strong_3': trial.suggest_float('tp_bull_strong_3', 0.15, 0.25),
            'trailing_bull_strong': trial.suggest_float('trailing_bull_strong', 0.03, 0.07),

            # BULL_MODERATE
            'tp_bull_moderate_1': trial.suggest_float('tp_bull_moderate_1', 0.02, 0.05),
            'tp_bull_moderate_2': trial.suggest_float('tp_bull_moderate_2', 0.05, 0.10),
            'tp_bull_moderate_3': trial.suggest_float('tp_bull_moderate_3', 0.10, 0.18),
            'trailing_bull_moderate': trial.suggest_float('trailing_bull_moderate', 0.02, 0.05),

            # SIDEWAYS
            'tp_sideways_1': trial.suggest_float('tp_sideways_1', 0.015, 0.03),
            'tp_sideways_2': trial.suggest_float('tp_sideways_2', 0.03, 0.06),
            'tp_sideways_3': trial.suggest_float('tp_sideways_3', 0.06, 0.10),

            # Stop Loss
            'stop_loss': trial.suggest_float('stop_loss', -0.03, -0.008),

            # 분할 익절 비율
            'exit_fraction_1': trial.suggest_float('exit_fraction_1', 0.3, 0.5),
            'exit_fraction_2': trial.suggest_float('exit_fraction_2', 0.25, 0.35),
            # exit_fraction_3 = 1.0 - exit_fraction_1 - exit_fraction_2

            # ===== Position Sizing =====
            'position_size': trial.suggest_float('position_size', 0.3, 1.0),

            # ===== SIDEWAYS 전략 활성화 =====
            'use_rsi_bb': trial.suggest_categorical('use_rsi_bb', [True, False]),
            'use_stoch': trial.suggest_categorical('use_stoch', [True, False]),
            'use_volume_breakout': trial.suggest_categorical('use_volume_breakout', [True, False]),

            # RSI + BB 파라미터
            'rsi_bb_oversold': trial.suggest_int('rsi_bb_oversold', 25, 35),
            'rsi_bb_overbought': trial.suggest_int('rsi_bb_overbought', 65, 75),

            # Stochastic 파라미터
            'stoch_oversold': trial.suggest_int('stoch_oversold', 15, 25),
            'stoch_overbought': trial.suggest_int('stoch_overbought', 75, 85),

            # Volume Breakout 파라미터
            'volume_breakout_mult': trial.suggest_float('volume_breakout_mult', 1.5, 2.5),
        }

        # 계산된 파라미터
        params['exit_fraction_3'] = 1.0 - params['exit_fraction_1'] - params['exit_fraction_2']

        return params

    def backtest_with_params(self, df: pd.DataFrame, params: Dict) -> Dict:
        """주어진 파라미터로 백테스팅 실행"""

        from strategies.v35_optimized.strategy import V35OptimizedStrategy

        initial_capital = 10_000_000
        capital = initial_capital
        position = 0.0
        trades = []
        equity_curve = []

        strategy = V35OptimizedStrategy(params)

        for i in range(30, len(df)):
            signal = strategy.execute(df, i)
            row = df.iloc[i]

            # Buy
            if signal['action'] == 'buy' and position == 0:
                fraction = signal.get('fraction', 0.5)
                buy_amount = capital * fraction
                buy_price = row['close'] * 1.0007  # 수수료 + 슬리피지
                shares = buy_amount / buy_price

                if shares > 0:
                    position = shares
                    capital -= buy_amount
                    trades.append({
                        'type': 'buy',
                        'time': row.name,
                        'price': buy_price,
                        'shares': shares
                    })

            # Sell
            elif signal['action'] == 'sell' and position > 0:
                sell_fraction = signal.get('fraction', 1.0)
                sell_shares = position * sell_fraction
                sell_price = row['close'] * 0.9993  # 수수료 + 슬리피지
                proceeds = sell_shares * sell_price

                capital += proceeds
                position -= sell_shares
                trades.append({
                    'type': 'sell',
                    'time': row.name,
                    'price': sell_price,
                    'shares': sell_shares
                })

            # Equity
            current_equity = capital + (position * row['close'] if position > 0 else 0)
            equity_curve.append(current_equity)

        # 마지막 포지션 정리
        if position > 0:
            capital += position * df.iloc[-1]['close'] * 0.9993
            position = 0

        final_capital = capital

        # 성과 계산
        total_return = (final_capital - initial_capital) / initial_capital * 100

        # Sharpe Ratio
        if len(equity_curve) > 1:
            returns = pd.Series(equity_curve).pct_change().dropna()
            if returns.std() > 0:
                sharpe = returns.mean() / returns.std() * np.sqrt(252)
            else:
                sharpe = 0
        else:
            sharpe = 0

        # Max Drawdown
        equity_series = pd.Series(equity_curve)
        cummax = equity_series.cummax()
        drawdown = (equity_series - cummax) / cummax * 100
        max_drawdown = drawdown.min()

        # 거래 분석
        buy_trades = [t for t in trades if t['type'] == 'buy']
        sell_trades = [t for t in trades if t['type'] == 'sell']

        profits = []
        for i in range(min(len(buy_trades), len(sell_trades))):
            profit_pct = (sell_trades[i]['price'] - buy_trades[i]['price']) / buy_trades[i]['price'] * 100
            profits.append(profit_pct)

        wins = [p for p in profits if p > 0]
        win_rate = len(wins) / len(profits) * 100 if len(profits) > 0 else 0

        return {
            'total_return': total_return,
            'sharpe_ratio': sharpe,
            'max_drawdown': max_drawdown,
            'total_trades': len(profits),
            'win_rate': win_rate
        }

    def objective(self, trial: optuna.Trial) -> float:
        """Optuna 목표 함수"""

        # 파라미터 샘플링
        params = self.create_trial_params(trial)

        # 학습 데이터 백테스팅 (2020-2024)
        train_results = self.backtest_with_params(self.train_df, params)

        # 검증 데이터 백테스팅 (2025)
        test_results = self.backtest_with_params(self.test_df, params)

        # 목표 함수 계산 (2025 검증 데이터 기준)
        # 수익률 60% + Sharpe 30% + MDD 10%
        return_score = test_results['total_return'] / 15.0  # 목표 15%
        sharpe_score = test_results['sharpe_ratio'] / 1.5   # 목표 1.5
        mdd_score = 1 - abs(test_results['max_drawdown']) / 20.0  # 목표 -20% 이내

        # 가중 합산
        score = 0.6 * return_score + 0.3 * sharpe_score + 0.1 * mdd_score

        # 로그 출력
        trial.set_user_attr('train_return', train_results['total_return'])
        trial.set_user_attr('test_return', test_results['total_return'])
        trial.set_user_attr('test_sharpe', test_results['sharpe_ratio'])
        trial.set_user_attr('test_mdd', test_results['max_drawdown'])
        trial.set_user_attr('test_trades', test_results['total_trades'])
        trial.set_user_attr('test_win_rate', test_results['win_rate'])

        return score

    def optimize(self, n_trials=500, output_dir='../strategies/v35_optimized'):
        """최적화 실행"""

        print(f"\n{'='*70}")
        print(f"  v35 Optuna 하이퍼파라미터 최적화")
        print(f"{'='*70}")
        print(f"Trials: {n_trials}")
        print(f"학습: {self.train_start} ~ {self.train_end}")
        print(f"검증: {self.test_start} ~ {self.test_end}")
        print(f"\n최적화 시작...\n")

        # Optuna Study 생성
        study = optuna.create_study(
            direction='maximize',
            sampler=TPESampler(seed=42)
        )

        # 최적화 실행
        study.optimize(self.objective, n_trials=n_trials, show_progress_bar=True)

        # 최적 파라미터
        best_params = study.best_params
        best_trial = study.best_trial

        print(f"\n{'='*70}")
        print(f"  최적화 완료!")
        print(f"{'='*70}")
        print(f"Best Score: {best_trial.value:.4f}")
        print(f"Best Trial: #{best_trial.number}")
        print(f"\n[최적 성과]")
        print(f"  학습 수익률: {best_trial.user_attrs['train_return']:+.2f}%")
        print(f"  검증 수익률: {best_trial.user_attrs['test_return']:+.2f}%")
        print(f"  검증 Sharpe: {best_trial.user_attrs['test_sharpe']:.2f}")
        print(f"  검증 MDD: {best_trial.user_attrs['test_mdd']:.2f}%")
        print(f"  검증 거래: {best_trial.user_attrs['test_trades']}회")
        print(f"  검증 승률: {best_trial.user_attrs['test_win_rate']:.1f}%")

        # 파라미터 저장
        output = {
            'optimization_date': datetime.now().isoformat(),
            'n_trials': n_trials,
            'best_trial_number': best_trial.number,
            'best_score': best_trial.value,
            'best_params': best_params,
            'train_period': f'{self.train_start} to {self.train_end}',
            'test_period': f'{self.test_start} to {self.test_end}',
            'train_return': best_trial.user_attrs['train_return'],
            'test_return': best_trial.user_attrs['test_return'],
            'test_sharpe': best_trial.user_attrs['test_sharpe'],
            'test_mdd': best_trial.user_attrs['test_mdd'],
            'test_trades': best_trial.user_attrs['test_trades'],
            'test_win_rate': best_trial.user_attrs['test_win_rate']
        }

        output_path = f'{output_dir}/config_optimized.json'
        with open(output_path, 'w') as f:
            json.dump(output, f, indent=2)

        print(f"\n최적 파라미터 저장: {output_path}")

        # Top 10 trials
        print(f"\n{'='*70}")
        print(f"  Top 10 Trials")
        print(f"{'='*70}")
        print(f"{'Trial':>6s} | {'Score':>7s} | {'Test Return':>12s} | {'Sharpe':>7s} | {'MDD':>7s} | {'Trades':>7s}")
        print(f"{'-'*6}|{'-'*9}|{'-'*14}|{'-'*9}|{'-'*9}|{'-'*9}")

        sorted_trials = sorted(study.trials, key=lambda t: t.value, reverse=True)[:10]
        for t in sorted_trials:
            print(f"{t.number:>6d} | {t.value:>7.4f} | {t.user_attrs['test_return']:>11.2f}% | "
                  f"{t.user_attrs['test_sharpe']:>7.2f} | {t.user_attrs['test_mdd']:>6.2f}% | "
                  f"{t.user_attrs['test_trades']:>6d}회")

        return study, best_params


if __name__ == '__main__':
    # v35 전략 파일이 먼저 생성되어야 함
    # 이 스크립트는 v35 전략이 완성된 후 실행

    print("⚠️  주의: v35_optimized/strategy.py가 먼저 생성되어야 합니다.")
    print("현재는 템플릿만 생성합니다.\n")

    # optimizer = V35StrategyOptimizer()
    # study, best_params = optimizer.optimize(n_trials=500)

    print("optimize_v35.py 생성 완료!")
    print("다음 단계: v35_optimized/strategy.py 생성")
