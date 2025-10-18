#!/usr/bin/env python3
"""
cci.py
Category: Momentum
Purpose: CCI (Commodity Channel Index) 지표 및 신호 생성

CCI (Commodity Channel Index):
  - 가격이 평균에서 얼마나 벗어났는지 측정
  - 일반적으로 -100 ~ +100 범위
  - +100 이상: 과매수 (매도 고려)
  - -100 이하: 과매도 (매수 고려)

전략:
  - CCI < -100 → 과매도 → 매수
  - CCI > +100 → 과매수 → 매도
  - CCI 제로라인 크로스 (추세 전환)
"""

import pandas as pd
import numpy as np


class CCI:
    def __init__(self, period=20, constant=0.015):
        """
        Args:
            period: CCI 계산 기간 (기본 20)
            constant: 상수 (기본 0.015, Lambert가 제안한 값)
        """
        self.period = period
        self.constant = constant

    def calculate(self, df):
        """
        CCI 계산

        Args:
            df: DataFrame with 'high', 'low', 'close'

        Returns:
            DataFrame with added columns:
                - tp: Typical Price (H+L+C)/3
                - cci: Commodity Channel Index
        """
        df = df.copy()

        # Typical Price
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3

        # SMA of Typical Price
        df['sma_tp'] = df['tp'].rolling(window=self.period).mean()

        # Mean Absolute Deviation
        df['mad'] = df['tp'].rolling(window=self.period).apply(
            lambda x: np.mean(np.abs(x - x.mean())), raw=True
        )

        # CCI = (TP - SMA(TP)) / (constant × MAD)
        df['cci'] = (df['tp'] - df['sma_tp']) / (self.constant * df['mad'])

        return df

    def detect_signals(self, df, i, oversold=-100, overbought=100):
        """
        CCI 매매 신호 감지

        Args:
            df: DataFrame with CCI indicator
            i: 현재 인덱스
            oversold: 과매도 기준선 (기본 -100)
            overbought: 과매수 기준선 (기본 +100)

        Returns:
            dict: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, 'cci': float}
        """
        if i < self.period:
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        cci = current['cci']
        prev_cci = prev['cci']

        # 1. CCI 과매도 영역에서 반등
        if prev_cci < oversold and cci >= oversold:
            return {
                'signal': 'BUY',
                'reason': 'CCI_OVERSOLD_BOUNCE',
                'cci': cci,
                'confidence': min(1.0, abs(prev_cci) / 200)
            }

        # 2. CCI 제로라인 상향 돌파 (추세 전환)
        if prev_cci < 0 and cci >= 0:
            return {
                'signal': 'BUY',
                'reason': 'CCI_ZERO_CROSS_UP',
                'cci': cci,
                'confidence': 0.6
            }

        # 3. CCI 과매수 영역 진입
        if prev_cci < overbought and cci >= overbought:
            return {
                'signal': 'SELL',
                'reason': 'CCI_OVERBOUGHT',
                'cci': cci,
                'confidence': 0.7
            }

        # 4. CCI 제로라인 하향 돌파
        if prev_cci > 0 and cci <= 0:
            return {
                'signal': 'SELL',
                'reason': 'CCI_ZERO_CROSS_DOWN',
                'cci': cci,
                'confidence': 0.5
            }

        return {'signal': 'HOLD', 'reason': 'NO_SIGNAL', 'cci': cci}

    def generate_signals(self, df, oversold=-100, overbought=100):
        """
        전체 DataFrame에 대해 신호 생성

        Args:
            df: OHLCV DataFrame
            oversold: 과매도 기준선
            overbought: 과매수 기준선

        Returns:
            List of signals
        """
        df = self.calculate(df)
        signals = []

        for i in range(len(df)):
            signal = self.detect_signals(df, i, oversold=oversold, overbought=overbought)

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

    # CCI 계산
    cci = CCI(period=20, constant=0.015)
    df = cci.calculate(df)

    print("CCI 지표 추가 완료:")
    print(df[['timestamp', 'close', 'tp', 'cci']].tail(10))

    # 신호 생성
    signals = cci.generate_signals(df, oversold=-100, overbought=100)
    print(f"\n발견된 CCI 신호: {len(signals)}개")
    for sig in signals[:10]:
        print(f"  {sig['timestamp']}: {sig['reason']} (CCI={sig['cci']:.1f})")

    # AlgorithmTester로 자동 테스트
    print("\n" + "="*80)
    print("AlgorithmTester로 자동 테스트")
    print("="*80)

    class CCITester(AlgorithmTester):
        def _generate_signals(self, df, params):
            cci = CCI(period=params.get('period', 20), constant=params.get('constant', 0.015))
            return cci.generate_signals(df,
                                        oversold=params.get('oversold', -100),
                                        overbought=params.get('overbought', 100))

    tester = CCITester('cci')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={'period': 20, 'constant': 0.015, 'oversold': -100, 'overbought': 100},
        trailing_stop=0.20,
        stop_loss=0.10
    )
