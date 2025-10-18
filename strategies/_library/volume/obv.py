#!/usr/bin/env python3
"""
obv.py
Category: Volume
Purpose: On-Balance Volume (OBV) 지표 및 신호 생성

OBV (On-Balance Volume):
  - 가격 상승 시 거래량 누적, 하락 시 차감
  - OBV 추세가 가격 추세와 일치하면 강한 신호
  - OBV 다이버전스 (가격↑ OBV↓) → 반전 신호

전략:
  - OBV가 20일 이평선 돌파 + 가격 상승 → 매수
  - OBV가 20일 이평선 하향 돌파 + 가격 하락 → 매도
  - OBV 다이버전스 감지
"""

import pandas as pd
import numpy as np


class OBV:
    def __init__(self, ma_period=20):
        """
        Args:
            ma_period: OBV 이동평균 기간 (기본 20)
        """
        self.ma_period = ma_period

    def calculate(self, df):
        """
        OBV 계산

        Args:
            df: DataFrame with 'close', 'volume'

        Returns:
            DataFrame with added columns:
                - obv: On-Balance Volume
                - obv_ma: OBV 이동평균
        """
        df = df.copy()

        # OBV 계산
        obv = [0]
        for i in range(1, len(df)):
            if df.iloc[i]['close'] > df.iloc[i-1]['close']:
                obv.append(obv[-1] + df.iloc[i]['volume'])
            elif df.iloc[i]['close'] < df.iloc[i-1]['close']:
                obv.append(obv[-1] - df.iloc[i]['volume'])
            else:
                obv.append(obv[-1])

        df['obv'] = obv

        # OBV 이동평균
        df['obv_ma'] = df['obv'].rolling(window=self.ma_period).mean()

        return df

    def detect_divergence(self, df, i, lookback=20):
        """
        OBV 다이버전스 감지

        Args:
            df: DataFrame with OBV
            i: 현재 인덱스
            lookback: 과거 몇 캔들을 볼지

        Returns:
            'bullish' / 'bearish' / None
        """
        if i < lookback + 1:
            return None

        # 최근 lookback 기간의 가격/OBV 추세
        price_slice = df.iloc[i-lookback:i+1]['close']
        obv_slice = df.iloc[i-lookback:i+1]['obv']

        # 선형 회귀 기울기 계산 (간단히)
        price_trend = (price_slice.iloc[-1] - price_slice.iloc[0]) / price_slice.iloc[0]
        obv_trend = (obv_slice.iloc[-1] - obv_slice.iloc[0]) / abs(obv_slice.iloc[0] + 1)

        # Bullish Divergence: 가격↓ OBV↑
        if price_trend < -0.05 and obv_trend > 0.05:
            return 'bullish'

        # Bearish Divergence: 가격↑ OBV↓
        if price_trend > 0.05 and obv_trend < -0.05:
            return 'bearish'

        return None

    def detect_signals(self, df, i):
        """
        OBV 매매 신호 감지

        Args:
            df: DataFrame with OBV indicators
            i: 현재 인덱스

        Returns:
            dict: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, 'obv': float}
        """
        if i < self.ma_period:
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        obv = current['obv']
        obv_ma = current['obv_ma']
        prev_obv = prev['obv']
        prev_obv_ma = prev['obv_ma']

        # 1. OBV 골든크로스 + 가격 상승
        golden_cross = (prev_obv <= prev_obv_ma) and (obv > obv_ma)
        price_rising = current['close'] > prev['close']

        if golden_cross and price_rising:
            return {
                'signal': 'BUY',
                'reason': 'OBV_GOLDEN_CROSS',
                'obv': obv,
                'obv_ma': obv_ma,
                'confidence': 0.75
            }

        # 2. OBV 데드크로스 + 가격 하락
        dead_cross = (prev_obv >= prev_obv_ma) and (obv < obv_ma)
        price_falling = current['close'] < prev['close']

        if dead_cross and price_falling:
            return {
                'signal': 'SELL',
                'reason': 'OBV_DEAD_CROSS',
                'obv': obv,
                'obv_ma': obv_ma,
                'confidence': 0.7
            }

        # 3. OBV Bullish Divergence
        divergence = self.detect_divergence(df, i, lookback=20)
        if divergence == 'bullish':
            return {
                'signal': 'BUY',
                'reason': 'OBV_BULLISH_DIVERGENCE',
                'obv': obv,
                'confidence': 0.65
            }

        # 4. OBV Bearish Divergence
        if divergence == 'bearish':
            return {
                'signal': 'SELL',
                'reason': 'OBV_BEARISH_DIVERGENCE',
                'obv': obv,
                'confidence': 0.6
            }

        return {'signal': 'HOLD', 'reason': 'NO_SIGNAL', 'obv': obv}

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

    # OBV 계산
    obv = OBV(ma_period=20)
    df = obv.calculate(df)

    print("OBV 지표 추가 완료:")
    print(df[['timestamp', 'close', 'volume', 'obv', 'obv_ma']].tail(10))

    # 신호 생성
    signals = obv.generate_signals(df)
    print(f"\n발견된 OBV 신호: {len(signals)}개")
    for sig in signals[:10]:
        print(f"  {sig['timestamp']}: {sig['reason']}")

    # AlgorithmTester로 자동 테스트
    print("\n" + "="*80)
    print("AlgorithmTester로 자동 테스트")
    print("="*80)

    class OBVTester(AlgorithmTester):
        def _generate_signals(self, df, params):
            obv = OBV(**(params or {}))
            return obv.generate_signals(df)

    tester = OBVTester('obv')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={'ma_period': 20},
        trailing_stop=0.20,
        stop_loss=0.10
    )
