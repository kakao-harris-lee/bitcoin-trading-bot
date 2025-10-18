#!/usr/bin/env python3
"""
williams_r.py
Category: Momentum
Purpose: Williams %R 지표 및 신호 생성

Williams %R:
  - 현재 가격이 일정 기간의 최고가-최저가 범위 어디에 있는지 표시
  - 0 ~ -100 범위 (주의: 음수)
  - -20 이상: 과매수 (매도 고려)
  - -80 이하: 과매도 (매수 고려)
  - Stochastic과 유사하지만 음수 범위 사용

전략:
  - %R < -80 (과매도) → 매수
  - %R > -20 (과매수) → 매도
  - %R이 -50 크로스 → 추세 전환
"""

import pandas as pd
import numpy as np


class WilliamsR:
    def __init__(self, period=14, overbought=-20, oversold=-80):
        """
        Args:
            period: 계산 기간 (기본 14)
            overbought: 과매수 기준선 (기본 -20)
            oversold: 과매도 기준선 (기본 -80)
        """
        self.period = period
        self.overbought = overbought
        self.oversold = oversold

    def calculate(self, df):
        """
        Williams %R 계산

        Args:
            df: DataFrame with 'high', 'low', 'close'

        Returns:
            DataFrame with added column:
                - williams_r: Williams %R 값
        """
        df = df.copy()

        # Highest High와 Lowest Low
        highest_high = df['high'].rolling(window=self.period).max()
        lowest_low = df['low'].rolling(window=self.period).min()

        # Williams %R = ((HH - Close) / (HH - LL)) × -100
        df['williams_r'] = ((highest_high - df['close']) / (highest_high - lowest_low)) * -100

        return df

    def detect_signals(self, df, i):
        """
        Williams %R 매매 신호 감지

        Args:
            df: DataFrame with Williams %R indicator
            i: 현재 인덱스

        Returns:
            dict: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, 'williams_r': float}
        """
        if i < self.period:
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        wr = current['williams_r']
        prev_wr = prev['williams_r']

        # 1. Williams %R 과매도에서 반등
        if prev_wr <= self.oversold and wr > self.oversold:
            return {
                'signal': 'BUY',
                'reason': 'WILLIAMS_R_OVERSOLD_BOUNCE',
                'williams_r': wr,
                'confidence': min(1.0, abs(prev_wr) / 100)
            }

        # 2. Williams %R -50 상향 돌파 (중립선)
        if prev_wr < -50 and wr >= -50:
            return {
                'signal': 'BUY',
                'reason': 'WILLIAMS_R_CROSS_UP_50',
                'williams_r': wr,
                'confidence': 0.6
            }

        # 3. Williams %R 과매수 영역 진입
        if prev_wr < self.overbought and wr >= self.overbought:
            return {
                'signal': 'SELL',
                'reason': 'WILLIAMS_R_OVERBOUGHT',
                'williams_r': wr,
                'confidence': 0.7
            }

        # 4. Williams %R -50 하향 돌파
        if prev_wr > -50 and wr <= -50:
            return {
                'signal': 'SELL',
                'reason': 'WILLIAMS_R_CROSS_DOWN_50',
                'williams_r': wr,
                'confidence': 0.5
            }

        return {'signal': 'HOLD', 'reason': 'NO_SIGNAL', 'williams_r': wr}

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

    # Williams %R 계산
    williams = WilliamsR(period=14, overbought=-20, oversold=-80)
    df = williams.calculate(df)

    print("Williams %R 지표 추가 완료:")
    print(df[['timestamp', 'close', 'williams_r']].tail(10))

    # 신호 생성
    signals = williams.generate_signals(df)
    print(f"\n발견된 Williams %R 신호: {len(signals)}개")
    for sig in signals[:10]:
        print(f"  {sig['timestamp']}: {sig['reason']} (Williams %R={sig['williams_r']:.1f})")

    # AlgorithmTester로 자동 테스트
    print("\n" + "="*80)
    print("AlgorithmTester로 자동 테스트")
    print("="*80)

    class WilliamsRTester(AlgorithmTester):
        def _generate_signals(self, df, params):
            williams = WilliamsR(**(params or {}))
            return williams.generate_signals(df)

    tester = WilliamsRTester('williams_r')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={'period': 14, 'overbought': -20, 'oversold': -80},
        trailing_stop=0.20,
        stop_loss=0.10
    )
