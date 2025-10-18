#!/usr/bin/env python3
"""
parabolic_sar.py
Category: Trend Following
Purpose: Parabolic SAR (Stop and Reverse) 지표 및 신호 생성

Parabolic SAR:
  - 추세 추종 및 청산 지점 표시
  - SAR이 가격 아래 → 상승 추세 (매수)
  - SAR이 가격 위 → 하락 추세 (매도)
  - Acceleration Factor (AF)가 SAR 속도 조절

전략:
  - SAR이 가격 아래로 전환 → 매수
  - SAR이 가격 위로 전환 → 매도
"""

import pandas as pd
import numpy as np


class ParabolicSAR:
    def __init__(self, af_start=0.02, af_increment=0.02, af_max=0.20):
        """
        Args:
            af_start: 초기 Acceleration Factor (기본 0.02)
            af_increment: AF 증가량 (기본 0.02)
            af_max: 최대 AF (기본 0.20)
        """
        self.af_start = af_start
        self.af_increment = af_increment
        self.af_max = af_max

    def calculate(self, df):
        """
        Parabolic SAR 계산

        Args:
            df: DataFrame with 'high', 'low', 'close'

        Returns:
            DataFrame with added columns:
                - psar: Parabolic SAR 값
                - psar_trend: 1 (상승), -1 (하락)
                - psar_af: 현재 AF 값
        """
        df = df.copy()
        n = len(df)

        # Initialize
        psar = np.zeros(n)
        trend = np.zeros(n)
        af = np.zeros(n)
        ep = np.zeros(n)  # Extreme Point (High or Low)

        # 첫 2개 캔들로 초기값 설정
        if n < 2:
            df['psar'] = np.nan
            df['psar_trend'] = 0
            df['psar_af'] = np.nan
            return df

        # 초기 추세 판단 (첫 캔들 < 두번째 캔들 → 상승)
        if df.iloc[1]['close'] > df.iloc[0]['close']:
            trend[0] = 1
            psar[0] = df.iloc[0]['low']
            ep[0] = df.iloc[1]['high']
        else:
            trend[0] = -1
            psar[0] = df.iloc[0]['high']
            ep[0] = df.iloc[1]['low']

        af[0] = self.af_start

        # SAR 계산 (2번째 캔들부터)
        for i in range(1, n):
            # 이전 SAR + AF × (EP - 이전 SAR)
            psar[i] = psar[i-1] + af[i-1] * (ep[i-1] - psar[i-1])

            # 현재 추세 유지 여부 확인
            reverse = False

            if trend[i-1] == 1:  # 상승 추세
                # SAR이 현재 low 위로 올라가면 반전
                if psar[i] > df.iloc[i]['low']:
                    reverse = True
                    trend[i] = -1
                    psar[i] = ep[i-1]  # EP를 SAR로
                    ep[i] = df.iloc[i]['low']
                    af[i] = self.af_start
                else:
                    trend[i] = 1
                    # EP 업데이트 (새 고점 발견 시)
                    if df.iloc[i]['high'] > ep[i-1]:
                        ep[i] = df.iloc[i]['high']
                        af[i] = min(af[i-1] + self.af_increment, self.af_max)
                    else:
                        ep[i] = ep[i-1]
                        af[i] = af[i-1]

                    # SAR이 이전 2개 캔들의 low보다 높으면 조정
                    if i >= 2:
                        psar[i] = min(psar[i], df.iloc[i-1]['low'], df.iloc[i-2]['low'])

            else:  # 하락 추세
                # SAR이 현재 high 아래로 내려가면 반전
                if psar[i] < df.iloc[i]['high']:
                    reverse = True
                    trend[i] = 1
                    psar[i] = ep[i-1]
                    ep[i] = df.iloc[i]['high']
                    af[i] = self.af_start
                else:
                    trend[i] = -1
                    # EP 업데이트 (새 저점 발견 시)
                    if df.iloc[i]['low'] < ep[i-1]:
                        ep[i] = df.iloc[i]['low']
                        af[i] = min(af[i-1] + self.af_increment, self.af_max)
                    else:
                        ep[i] = ep[i-1]
                        af[i] = af[i-1]

                    # SAR이 이전 2개 캔들의 high보다 낮으면 조정
                    if i >= 2:
                        psar[i] = max(psar[i], df.iloc[i-1]['high'], df.iloc[i-2]['high'])

        df['psar'] = psar
        df['psar_trend'] = trend
        df['psar_af'] = af

        return df

    def detect_signals(self, df, i):
        """
        Parabolic SAR 매매 신호 감지

        Args:
            df: DataFrame with Parabolic SAR indicators
            i: 현재 인덱스

        Returns:
            dict: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, 'psar': float}
        """
        if i < 2:
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        psar = current['psar']
        trend = current['psar_trend']
        prev_trend = prev['psar_trend']

        # 추세 전환 감지
        if prev_trend == -1 and trend == 1:
            # 하락 → 상승 전환 (매수)
            return {
                'signal': 'BUY',
                'reason': 'PSAR_BULLISH_REVERSAL',
                'psar': psar,
                'af': current['psar_af'],
                'confidence': min(1.0, current['psar_af'] / self.af_max)
            }

        if prev_trend == 1 and trend == -1:
            # 상승 → 하락 전환 (매도)
            return {
                'signal': 'SELL',
                'reason': 'PSAR_BEARISH_REVERSAL',
                'psar': psar,
                'af': current['psar_af'],
                'confidence': 0.8
            }

        return {'signal': 'HOLD', 'reason': 'NO_REVERSAL', 'psar': psar}

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

    # Parabolic SAR 계산
    psar = ParabolicSAR(af_start=0.02, af_increment=0.02, af_max=0.20)
    df = psar.calculate(df)

    print("Parabolic SAR 지표 추가 완료:")
    print(df[['timestamp', 'close', 'psar', 'psar_trend', 'psar_af']].tail(10))

    # 신호 생성
    signals = psar.generate_signals(df)
    print(f"\n발견된 Parabolic SAR 신호: {len(signals)}개")
    for sig in signals[:10]:
        print(f"  {sig['timestamp']}: {sig['reason']} (SAR={sig['psar']:,.0f}, AF={sig['af']:.2f})")

    # AlgorithmTester로 자동 테스트
    print("\n" + "="*80)
    print("AlgorithmTester로 자동 테스트")
    print("="*80)

    class ParabolicSARTester(AlgorithmTester):
        def _generate_signals(self, df, params):
            psar = ParabolicSAR(**(params or {}))
            return psar.generate_signals(df)

    tester = ParabolicSARTester('parabolic_sar')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={'af_start': 0.02, 'af_increment': 0.02, 'af_max': 0.20},
        trailing_stop=0.20,
        stop_loss=0.10
    )
