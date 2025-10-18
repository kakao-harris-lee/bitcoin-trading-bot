#!/usr/bin/env python3
"""
evaluator.py
성과 평가 모듈 - 모든 KPI 계산
"""

import pandas as pd
import numpy as np
from typing import Dict, List
from datetime import datetime

class Evaluator:
    """백테스팅 결과 평가기"""

    @staticmethod
    def calculate_all_metrics(backtest_results: Dict) -> Dict:
        """
        모든 KPI 계산

        Args:
            backtest_results: Backtester.run() 결과

        Returns:
            모든 평가 지표 포함된 딕셔너리
        """
        equity_curve = backtest_results['equity_curve']
        trades = backtest_results.get('trades', [])

        # 기본 지표
        initial_capital = backtest_results['initial_capital']
        final_capital = backtest_results['final_capital']
        total_return = backtest_results['total_return']

        # Sharpe Ratio
        sharpe_ratio = Evaluator._calculate_sharpe_ratio(equity_curve)

        # Max Drawdown (MDD)
        max_drawdown = Evaluator._calculate_max_drawdown(equity_curve)

        # 거래 통계
        if trades:
            win_rate = backtest_results['win_rate']
            profit_factor = backtest_results['profit_factor']
            avg_profit = backtest_results['avg_profit']
            avg_loss = backtest_results['avg_loss']
            total_trades = backtest_results['total_trades']
            winning_trades = backtest_results['winning_trades']
            losing_trades = backtest_results['losing_trades']

            # Kelly Criterion
            kelly = Evaluator._calculate_kelly(win_rate, avg_profit, avg_loss)
        else:
            win_rate = 0
            profit_factor = 0
            avg_profit = 0
            avg_loss = 0
            total_trades = 0
            winning_trades = 0
            losing_trades = 0
            kelly = 0

        return {
            # 수익성
            'initial_capital': initial_capital,
            'final_capital': final_capital,
            'total_return': total_return,

            # 리스크 조정 수익
            'sharpe_ratio': sharpe_ratio,
            'max_drawdown': max_drawdown,

            # 거래 통계
            'total_trades': total_trades,
            'winning_trades': winning_trades,
            'losing_trades': losing_trades,
            'win_rate': win_rate,
            'avg_profit': avg_profit,
            'avg_loss': avg_loss,
            'profit_factor': profit_factor,

            # 포지션 사이징
            'kelly_criterion': kelly,
            'kelly_quarter': kelly * 0.25,
            'kelly_half': kelly * 0.5,

            # 원본 데이터
            'equity_curve': equity_curve,
            'trades': trades
        }

    @staticmethod
    def _calculate_sharpe_ratio(equity_curve: pd.DataFrame, risk_free_rate: float = 0.0) -> float:
        """
        Sharpe Ratio 계산

        Args:
            equity_curve: Equity curve DataFrame
            risk_free_rate: 무위험 이자율 (연율, 기본 0%)

        Returns:
            Sharpe Ratio
        """
        if len(equity_curve) < 2:
            return 0.0

        # 일일 수익률 계산
        equity_curve = equity_curve.copy()
        equity_curve['returns'] = equity_curve['total_equity'].pct_change()

        # NaN 제거
        daily_returns = equity_curve['returns'].dropna()

        if len(daily_returns) == 0 or daily_returns.std() == 0:
            return 0.0

        # Sharpe Ratio = (평균 수익률 - 무위험 이자율) / 표준편차
        mean_return = daily_returns.mean()
        std_return = daily_returns.std()

        sharpe = (mean_return - risk_free_rate) / std_return

        # 연율화 (가정: 1년 = 252 거래일)
        sharpe_annualized = sharpe * np.sqrt(252)

        return sharpe_annualized

    @staticmethod
    def _calculate_max_drawdown(equity_curve: pd.DataFrame) -> float:
        """
        Maximum Drawdown (MDD) 계산

        Args:
            equity_curve: Equity curve DataFrame

        Returns:
            MDD (%)
        """
        if len(equity_curve) < 2:
            return 0.0

        equity = equity_curve['total_equity'].values
        running_max = np.maximum.accumulate(equity)
        drawdown = (equity - running_max) / running_max * 100

        max_drawdown = abs(drawdown.min())

        return max_drawdown

    @staticmethod
    def _calculate_kelly(win_rate: float, avg_profit: float, avg_loss: float) -> float:
        """
        Kelly Criterion 계산

        Args:
            win_rate: 승률 (0~1)
            avg_profit: 평균 수익
            avg_loss: 평균 손실 (양수)

        Returns:
            Kelly 비율
        """
        if avg_loss == 0 or win_rate <= 0 or win_rate >= 1:
            return 0.0

        p = win_rate
        q = 1 - p
        b = avg_profit / avg_loss

        kelly = (p * b - q) / b
        return max(0.0, min(kelly, 1.0))

    @staticmethod
    def analyze_by_market_condition(
        equity_curve: pd.DataFrame,
        df: pd.DataFrame,
        window: int = 20
    ) -> Dict:
        """
        시장 조건별 성과 분석

        Args:
            equity_curve: Equity curve
            df: 가격 데이터
            window: 시장 조건 판단 윈도우

        Returns:
            시장 조건별 성과
        """
        # 시장 조건 분류
        df = df.copy()
        df['sma'] = df['close'].rolling(window=window).mean()
        df['market_condition'] = 'sideways'

        # 상승장: 현재가 > SMA + 2%
        df.loc[df['close'] > df['sma'] * 1.02, 'market_condition'] = 'bull'

        # 하락장: 현재가 < SMA - 2%
        df.loc[df['close'] < df['sma'] * 0.98, 'market_condition'] = 'bear'

        # Equity curve와 병합
        merged = equity_curve.merge(
            df[['timestamp', 'market_condition']],
            on='timestamp',
            how='left'
        )

        # 조건별 수익률 계산
        results = {}
        for condition in ['bull', 'bear', 'sideways']:
            condition_data = merged[merged['market_condition'] == condition]

            if len(condition_data) > 1:
                start_equity = condition_data.iloc[0]['total_equity']
                end_equity = condition_data.iloc[-1]['total_equity']
                return_pct = ((end_equity - start_equity) / start_equity) * 100

                results[condition] = {
                    'count': len(condition_data),
                    'return_pct': return_pct
                }
            else:
                results[condition] = {
                    'count': 0,
                    'return_pct': 0.0
                }

        return results

    @staticmethod
    def check_overfitting(
        in_sample_metrics: Dict,
        out_sample_metrics: Dict,
        threshold: float = 0.8
    ) -> Dict:
        """
        오버피팅 검증

        Args:
            in_sample_metrics: In-sample 성과
            out_sample_metrics: Out-of-sample 성과
            threshold: 허용 비율 (Out / In >= threshold)

        Returns:
            오버피팅 판정 결과
        """
        in_return = in_sample_metrics['total_return']
        out_return = out_sample_metrics['total_return']

        if in_return <= 0:
            return {
                'overfitting': True,
                'reason': 'In-sample 수익률이 0% 이하',
                'ratio': 0.0
            }

        ratio = out_return / in_return

        overfitting = ratio < threshold

        return {
            'overfitting': overfitting,
            'in_sample_return': in_return,
            'out_sample_return': out_return,
            'ratio': ratio,
            'threshold': threshold,
            'status': 'FAIL' if overfitting else 'PASS'
        }


# 사용 예제
if __name__ == "__main__":
    from data_loader import DataLoader
    from backtester import Backtester

    # 간단한 전략
    def simple_strategy(df, i, params):
        if i < 14:
            return {'action': 'hold'}
        if i % 10 == 0:
            return {'action': 'buy', 'fraction': 0.5}
        elif i % 20 == 0:
            return {'action': 'sell', 'fraction': 1.0}
        return {'action': 'hold'}

    # 데이터 로드
    with DataLoader() as loader:
        df = loader.load_timeframe("minute5", start_date="2024-01-01", end_date="2024-02-29")

    # 백테스팅
    backtester = Backtester()
    results = backtester.run(df, simple_strategy)

    # 평가
    metrics = Evaluator.calculate_all_metrics(results)

    print("✅ 평가 결과:")
    print(f"   총 수익률: {metrics['total_return']:.2f}%")
    print(f"   Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
    print(f"   Max Drawdown: {metrics['max_drawdown']:.2f}%")
    print(f"   승률: {metrics['win_rate']:.1%}")
    print(f"   Profit Factor: {metrics['profit_factor']:.2f}")
    print(f"   Kelly (Quarter): {metrics['kelly_quarter']:.1%}")

    # 시장 조건별 성과
    market_perf = Evaluator.analyze_by_market_condition(
        metrics['equity_curve'],
        df
    )
    print("\n✅ 시장 조건별 성과:")
    for condition, perf in market_perf.items():
        print(f"   {condition}: {perf['return_pct']:.2f}% ({perf['count']}건)")
