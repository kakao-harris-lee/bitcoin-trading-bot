#!/usr/bin/env python3
"""
breakout.py
Category: Trend Following
Purpose: High Breakout (고가 돌파) 전략

Breakout Strategy:
  - N일 최고가 돌파 시 매수
  - 추세 추종 전략의 기본
  - 강한 모멘텀 포착

전략:
  - 현재 가격이 N일 최고가 돌파 → 매수
  - Trailing Stop으로 청산
"""

import pandas as pd
import numpy as np


class Breakout:
    def __init__(self, period=20):
        """
        Args:
            period: 최고가 계산 기간 (기본 20)
        """
        self.period = period

    def calculate(self, df):
        """
        Breakout 지표 계산

        Args:
            df: DataFrame with 'high', 'low', 'close'

        Returns:
            DataFrame with added columns:
                - highest_high: N일 최고가
                - lowest_low: N일 최저가 (참고용)
        """
        df = df.copy()

        # N일 최고가/최저가
        df['highest_high'] = df['high'].rolling(window=self.period).max()
        df['lowest_low'] = df['low'].rolling(window=self.period).min()

        return df

    def detect_signals(self, df, i):
        """
        Breakout 매매 신호 감지

        Args:
            df: DataFrame with Breakout indicators
            i: 현재 인덱스

        Returns:
            dict: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, ...}
        """
        if i < self.period + 1:
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        close = current['close']
        prev_close = prev['close']
        prev_highest = prev['highest_high']

        # NaN 체크
        if pd.isna(prev_highest):
            return {'signal': 'HOLD', 'reason': 'INCOMPLETE_DATA'}

        # 1. N일 최고가 돌파
        breakout_up = (prev_close <= prev_highest) and (close > prev_highest)

        if breakout_up:
            return {
                'signal': 'BUY',
                'reason': 'BREAKOUT_HIGH',
                'highest_high': prev_highest,
                'breakout_pct': ((close - prev_highest) / prev_highest) * 100,
                'confidence': 0.85
            }

        return {'signal': 'HOLD', 'reason': 'NO_SIGNAL'}

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

    # Breakout 계산
    breakout = Breakout(period=20)
    df = breakout.calculate(df)

    print("Breakout 지표 추가 완료:")
    print(df[['timestamp', 'close', 'highest_high', 'lowest_low']].tail(10))

    # 신호 생성
    signals = breakout.generate_signals(df)
    print(f"\n발견된 Breakout 신호: {len(signals)}개")
    for sig in signals[:10]:
        print(f"  {sig['timestamp']}: {sig['reason']} (돌파율 +{sig['breakout_pct']:.2f}%)")

    # AlgorithmTester로 자동 테스트
    print("\n" + "="*80)
    print("AlgorithmTester로 자동 테스트")
    print("="*80)

    class BreakoutTester(AlgorithmTester):
        def _generate_signals(self, df, params):
            breakout = Breakout(**(params or {}))
            return breakout.generate_signals(df)

    tester = BreakoutTester('breakout')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={'period': 20},
        trailing_stop=0.20,
        stop_loss=0.10
    )
