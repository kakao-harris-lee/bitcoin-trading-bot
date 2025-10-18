#!/usr/bin/env python3
"""
stochastic.py
Category: Momentum
Purpose: Stochastic Oscillator (스토캐스틱) 지표 및 신호 생성

Stochastic Oscillator:
  - %K = ((Current - Lowest Low) / (Highest High - Lowest Low)) × 100
  - %D = %K의 3일 이동평균
  - 범위: 0~100
  - 80 이상: 과매수, 20 이하: 과매도

전략:
  - %K가 20 이하에서 %D를 상향 돌파 → 매수
  - %K가 80 이상에서 %D를 하향 돌파 → 매도
"""

import pandas as pd
import numpy as np


class StochasticOscillator:
    def __init__(self, k_period=14, d_period=3, overbought=80, oversold=20):
        """
        Args:
            k_period: %K 계산 기간 (기본 14)
            d_period: %D 이동평균 기간 (기본 3)
            overbought: 과매수 기준 (기본 80)
            oversold: 과매도 기준 (기본 20)
        """
        self.k_period = k_period
        self.d_period = d_period
        self.overbought = overbought
        self.oversold = oversold

    def calculate(self, df):
        """
        Stochastic Oscillator 계산

        Args:
            df: DataFrame with 'high', 'low', 'close'

        Returns:
            DataFrame with added columns:
                - stoch_k: %K
                - stoch_d: %D
        """
        df = df.copy()

        # Lowest Low, Highest High
        lowest_low = df['low'].rolling(window=self.k_period).min()
        highest_high = df['high'].rolling(window=self.k_period).max()

        # %K 계산
        df['stoch_k'] = ((df['close'] - lowest_low) / (highest_high - lowest_low)) * 100

        # %D 계산 (%K의 이동평균)
        df['stoch_d'] = df['stoch_k'].rolling(window=self.d_period).mean()

        return df

    def detect_signals(self, df, i):
        """
        Stochastic 매매 신호 감지

        Args:
            df: DataFrame with Stochastic indicators
            i: 현재 인덱스

        Returns:
            dict: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, 'k': float, 'd': float}
        """
        if i < self.k_period + self.d_period:
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        k = current['stoch_k']
        d = current['stoch_d']
        prev_k = prev['stoch_k']
        prev_d = prev['stoch_d']

        # 매수 신호: %K가 과매도 영역(20 이하)에서 %D를 상향 돌파
        if prev_k <= self.oversold and k > self.oversold:
            if prev_k <= prev_d and k > d:
                return {
                    'signal': 'BUY',
                    'reason': 'STOCH_OVERSOLD_CROSS',
                    'k': k,
                    'd': d,
                    'confidence': min(1.0, (k - prev_k) / 10)
                }

        # 매수 신호 2: 과매도 반등 (단순 버전)
        if k <= self.oversold and prev_k < k:
            return {
                'signal': 'BUY',
                'reason': 'STOCH_OVERSOLD_BOUNCE',
                'k': k,
                'd': d,
                'confidence': 0.6
            }

        # 매도 신호: %K가 과매수 영역(80 이상)에서 %D를 하향 돌파
        if prev_k >= self.overbought and k < self.overbought:
            if prev_k >= prev_d and k < d:
                return {
                    'signal': 'SELL',
                    'reason': 'STOCH_OVERBOUGHT_CROSS',
                    'k': k,
                    'd': d,
                    'confidence': 0.8
                }

        # 매도 신호 2: 과매수 (단순 버전)
        if k >= self.overbought:
            return {
                'signal': 'SELL',
                'reason': 'STOCH_OVERBOUGHT',
                'k': k,
                'd': d,
                'confidence': 0.5
            }

        return {'signal': 'HOLD', 'reason': 'NO_SIGNAL', 'k': k, 'd': d}

    def generate_signals(self, df):
        """
        전체 DataFrame에 대해 신호 생성

        Args:
            df: OHLCV DataFrame

        Returns:
            List of signals
        """
        df = self.calculate(df)
        signals = []

        for i in range(len(df)):
            signal = self.detect_signals(df, i)

            if signal['signal'] == 'BUY':
                signals.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'] if 'timestamp' in df.columns else i,
                    'price': df.iloc[i]['close'],
                    **signal
                })

        return signals


# 사용 예시 및 테스트
if __name__ == '__main__':
    import sys
    import os

    # 프로젝트 루트로 이동
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '../../..'))
    os.chdir(project_root)
    sys.path.insert(0, project_root)

    from core.data_loader import DataLoader
    from automation.test_algorithm import AlgorithmTester

    # 데이터 로드
    with DataLoader('upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    # Stochastic 계산
    stoch = StochasticOscillator(k_period=14, d_period=3)
    df = stoch.calculate(df)

    print("Stochastic Oscillator 지표 추가 완료:")
    print(df[['timestamp', 'close', 'stoch_k', 'stoch_d']].tail(10))

    # 신호 생성
    signals = stoch.generate_signals(df)
    print(f"\n발견된 Stochastic 신호: {len(signals)}개")
    for sig in signals[:10]:
        print(f"  {sig['timestamp']}: {sig['reason']} (K={sig['k']:.1f}, D={sig['d']:.1f})")

    # AlgorithmTester로 자동 테스트
    print("\n" + "="*80)
    print("AlgorithmTester로 자동 테스트")
    print("="*80)

    class StochasticTester(AlgorithmTester):
        def _generate_signals(self, df, params):
            stoch = StochasticOscillator(**(params or {}))
            return stoch.generate_signals(df)

    tester = StochasticTester('stochastic')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={'k_period': 14, 'd_period': 3, 'oversold': 20, 'overbought': 80},
        trailing_stop=0.20,
        stop_loss=0.10
    )
