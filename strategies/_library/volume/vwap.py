#!/usr/bin/env python3
"""
vwap.py
Category: Volume
Purpose: VWAP (Volume Weighted Average Price) 지표 및 신호 생성

VWAP:
  - 거래량 가중 평균 가격
  - 주로 일중 거래에서 사용 (intraday)
  - VWAP 위 → 상승 추세 (매수 유리)
  - VWAP 아래 → 하락 추세 (매도 유리)

전략:
  - 가격이 VWAP 상향 돌파 → 매수
  - 가격이 VWAP 하향 돌파 → 매도
  - VWAP 대비 +2% 이상 → 과매수
  - VWAP 대비 -2% 이하 → 과매도
"""

import pandas as pd
import numpy as np


class VWAP:
    def __init__(self, deviation_threshold=0.02):
        """
        Args:
            deviation_threshold: VWAP 대비 괴리율 임계값 (기본 2%)
        """
        self.deviation_threshold = deviation_threshold

    def calculate(self, df, reset_period='D'):
        """
        VWAP 계산

        Args:
            df: DataFrame with 'high', 'low', 'close', 'volume', 'timestamp'
            reset_period: VWAP 리셋 주기 ('D'=일별, None=누적)

        Returns:
            DataFrame with added columns:
                - vwap: Volume Weighted Average Price
                - vwap_deviation: VWAP 대비 괴리율 (%)
        """
        df = df.copy()

        # Typical Price
        df['tp'] = (df['high'] + df['low'] + df['close']) / 3

        # TP × Volume
        df['tp_volume'] = df['tp'] * df['volume']

        if reset_period and 'timestamp' in df.columns:
            # 일별 리셋 (day 타임프레임에서는 누적 사용)
            df['date'] = pd.to_datetime(df['timestamp']).dt.date
            df['cum_tp_volume'] = df.groupby('date')['tp_volume'].cumsum()
            df['cum_volume'] = df.groupby('date')['volume'].cumsum()
        else:
            # 누적 (전체 기간)
            df['cum_tp_volume'] = df['tp_volume'].cumsum()
            df['cum_volume'] = df['volume'].cumsum()

        # VWAP = Σ(TP × Volume) / Σ(Volume)
        df['vwap'] = df['cum_tp_volume'] / df['cum_volume']

        # VWAP 대비 괴리율
        df['vwap_deviation'] = (df['close'] - df['vwap']) / df['vwap']

        return df

    def detect_signals(self, df, i):
        """
        VWAP 매매 신호 감지

        Args:
            df: DataFrame with VWAP indicators
            i: 현재 인덱스

        Returns:
            dict: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, 'vwap': float}
        """
        if i < 2:
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        close = current['close']
        vwap = current['vwap']
        prev_close = prev['close']
        prev_vwap = prev['vwap']
        deviation = current['vwap_deviation']

        # NaN 체크
        if pd.isna(vwap) or pd.isna(deviation):
            return {'signal': 'HOLD', 'reason': 'INCOMPLETE_DATA'}

        # 1. 가격이 VWAP 상향 돌파 + 거래량 증가
        vwap_cross_up = (prev_close <= prev_vwap) and (close > vwap)
        volume_increase = current['volume'] > prev['volume']

        if vwap_cross_up and volume_increase:
            return {
                'signal': 'BUY',
                'reason': 'VWAP_CROSS_UP_VOLUME',
                'vwap': vwap,
                'deviation': deviation,
                'confidence': 0.8
            }

        # 2. 가격이 VWAP 상향 돌파 (거래량 무관)
        if vwap_cross_up:
            return {
                'signal': 'BUY',
                'reason': 'VWAP_CROSS_UP',
                'vwap': vwap,
                'deviation': deviation,
                'confidence': 0.65
            }

        # 3. VWAP 대비 과매도 (2% 이하)
        if deviation <= -self.deviation_threshold:
            return {
                'signal': 'BUY',
                'reason': 'VWAP_OVERSOLD',
                'vwap': vwap,
                'deviation': deviation,
                'confidence': 0.6
            }

        # 4. 가격이 VWAP 하향 돌파
        vwap_cross_down = (prev_close >= prev_vwap) and (close < vwap)

        if vwap_cross_down:
            return {
                'signal': 'SELL',
                'reason': 'VWAP_CROSS_DOWN',
                'vwap': vwap,
                'deviation': deviation,
                'confidence': 0.7
            }

        # 5. VWAP 대비 과매수 (2% 이상)
        if deviation >= self.deviation_threshold:
            return {
                'signal': 'SELL',
                'reason': 'VWAP_OVERBOUGHT',
                'vwap': vwap,
                'deviation': deviation,
                'confidence': 0.5
            }

        return {'signal': 'HOLD', 'reason': 'NO_SIGNAL', 'vwap': vwap}

    def generate_signals(self, df):
        """
        전체 DataFrame에 대해 신호 생성

        Args:
            df: OHLCV DataFrame

        Returns:
            List of signals
        """
        df = self.calculate(df, reset_period=None)  # day 타임프레임은 누적
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

    # VWAP 계산
    vwap = VWAP(deviation_threshold=0.02)
    df = vwap.calculate(df, reset_period=None)

    print("VWAP 지표 추가 완료:")
    print(df[['timestamp', 'close', 'vwap', 'vwap_deviation']].tail(10))

    # 신호 생성
    signals = vwap.generate_signals(df)
    print(f"\n발견된 VWAP 신호: {len(signals)}개")
    for sig in signals[:10]:
        print(f"  {sig['timestamp']}: {sig['reason']} (deviation={sig['deviation']:.2%})")

    # AlgorithmTester로 자동 테스트
    print("\n" + "="*80)
    print("AlgorithmTester로 자동 테스트")
    print("="*80)

    class VWAPTester(AlgorithmTester):
        def _generate_signals(self, df, params):
            vwap = VWAP(**(params or {}))
            return vwap.generate_signals(df)

    tester = VWAPTester('vwap')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={'deviation_threshold': 0.02},
        trailing_stop=0.20,
        stop_loss=0.10
    )
