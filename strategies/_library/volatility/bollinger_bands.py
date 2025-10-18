#!/usr/bin/env python3
"""
bollinger_bands.py
Category: Volatility
Purpose: Bollinger Bands 지표 생성 및 매매 신호 감지

Bollinger Bands 구조:
  - Upper Band: MA + (Std × N)
  - Middle Band: MA (보통 SMA 20)
  - Lower Band: MA - (Std × N)

전략:
  - Bounce: 하단 밴드 터치 → 매수, 중심선/상단 → 매도
  - Squeeze: 밴드 폭 축소 → 변동성 증가 예상
  - Breakout: 상단 돌파 → 강한 상승
"""

import pandas as pd
import numpy as np


class BollingerBands:
    def __init__(self, window=20, num_std=2.0):
        """
        Args:
            window: 이동평균 기간 (기본 20일)
            num_std: 표준편차 배수 (기본 2.0)
        """
        self.window = window
        self.num_std = num_std

    def calculate(self, df):
        """
        Bollinger Bands 지표 계산

        Args:
            df: DataFrame with 'close' column

        Returns:
            DataFrame with added columns:
                - bb_middle: 중심선 (SMA)
                - bb_upper: 상단 밴드
                - bb_lower: 하단 밴드
                - bb_width: 밴드 폭 (상단 - 하단)
                - bb_pctb: %B (현재가의 밴드 내 위치, 0~1)
        """
        df = df.copy()

        # 중심선 (SMA)
        df['bb_middle'] = df['close'].rolling(window=self.window).mean()

        # 표준편차
        rolling_std = df['close'].rolling(window=self.window).std()

        # 상단/하단 밴드
        df['bb_upper'] = df['bb_middle'] + (rolling_std * self.num_std)
        df['bb_lower'] = df['bb_middle'] - (rolling_std * self.num_std)

        # 밴드 폭
        df['bb_width'] = df['bb_upper'] - df['bb_lower']

        # %B (Percent B): 현재가가 밴드 내 어디에 위치하는지
        # 0: 하단, 0.5: 중심, 1.0: 상단
        df['bb_pctb'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        return df

    def detect_bounce(self, df, i, touch_threshold=0.05):
        """
        Bollinger Band Bounce 신호 감지

        하단 밴드 근처에서 반등 → 매수 신호

        Args:
            df: DataFrame with BB indicators
            i: 현재 인덱스
            touch_threshold: 하단 밴드 접촉 판정 기준 (기본 5%)

        Returns:
            dict: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, 'confidence': float}
        """
        if i < self.window:
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA', 'confidence': 0.0}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        # %B 값으로 판단
        pctb = current['bb_pctb']
        prev_pctb = prev['bb_pctb']

        # 매수 신호: 하단 밴드 터치 (pctb <= touch_threshold) 후 반등
        if prev_pctb <= touch_threshold and pctb > touch_threshold:
            confidence = min(1.0, (pctb - prev_pctb) * 10)  # 반등 강도
            return {
                'signal': 'BUY',
                'reason': 'BB_LOWER_BOUNCE',
                'confidence': confidence,
                'pctb': pctb
            }

        # 매도 신호 1: 중심선 도달 (평균 회귀 목표)
        if pctb >= 0.45 and pctb <= 0.55 and prev_pctb < 0.45:
            return {
                'signal': 'SELL',
                'reason': 'BB_MIDDLE_REACHED',
                'confidence': 0.6,
                'pctb': pctb
            }

        # 매도 신호 2: 상단 밴드 근처 (과열)
        if pctb >= 0.95:
            return {
                'signal': 'SELL',
                'reason': 'BB_UPPER_OVERBOUGHT',
                'confidence': 0.8,
                'pctb': pctb
            }

        return {'signal': 'HOLD', 'reason': 'NO_SIGNAL', 'confidence': 0.0}

    def detect_squeeze(self, df, i, lookback=20, percentile=20):
        """
        Bollinger Band Squeeze 감지

        밴드 폭이 좁아지면 곧 변동성 증가 예상

        Args:
            df: DataFrame with BB indicators
            i: 현재 인덱스
            lookback: 비교 기간
            percentile: Squeeze 판정 기준 (하위 몇 %?)

        Returns:
            bool: True if squeeze detected
        """
        if i < self.window + lookback:
            return False

        current_width = df.iloc[i]['bb_width']
        historical_widths = df.iloc[i - lookback:i]['bb_width']

        # 현재 밴드 폭이 과거 lookback 기간 중 하위 percentile 이하
        threshold = np.percentile(historical_widths, percentile)

        return current_width <= threshold

    def detect_breakout(self, df, i):
        """
        Bollinger Band Breakout 감지

        가격이 상단 밴드를 돌파 → 강한 상승 신호

        Args:
            df: DataFrame with BB indicators
            i: 현재 인덱스

        Returns:
            dict: {'signal': 'BUY'/'HOLD', 'reason': str}
        """
        if i < self.window + 1:
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        # 상단 돌파
        if prev['close'] <= prev['bb_upper'] and current['close'] > current['bb_upper']:
            # 거래량 확인 (있으면)
            volume_confirmed = True
            if 'volume' in df.columns:
                avg_volume = df.iloc[i - 20:i]['volume'].mean()
                volume_confirmed = current['volume'] > avg_volume * 1.2

            if volume_confirmed:
                return {
                    'signal': 'BUY',
                    'reason': 'BB_UPPER_BREAKOUT',
                    'confidence': 0.7
                }

        return {'signal': 'HOLD', 'reason': 'NO_BREAKOUT'}

    def generate_signals(self, df, strategy='bounce'):
        """
        전체 DataFrame에 대해 신호 생성

        Args:
            df: OHLCV DataFrame
            strategy: 'bounce', 'squeeze', 'breakout'

        Returns:
            List of signals with timestamps
        """
        df = self.calculate(df)
        signals = []

        for i in range(len(df)):
            if strategy == 'bounce':
                signal = self.detect_bounce(df, i)
            elif strategy == 'breakout':
                signal = self.detect_breakout(df, i)
            else:
                raise ValueError(f"Unknown strategy: {strategy}")

            if signal['signal'] != 'HOLD':
                signals.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'] if 'timestamp' in df.columns else i,
                    'price': df.iloc[i]['close'],
                    **signal
                })

        return signals


# 사용 예시
if __name__ == '__main__':
    import sys
    sys.path.append('../../..')
    from core.data_loader import DataLoader

    # 데이터 로드
    with DataLoader('../../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    # Bollinger Bands 생성
    bb = BollingerBands(window=20, num_std=2.0)
    df = bb.calculate(df)

    print("Bollinger Bands 지표 추가 완료:")
    print(df[['timestamp', 'close', 'bb_lower', 'bb_middle', 'bb_upper', 'bb_pctb']].tail(10))

    # Bounce 신호 생성
    signals = bb.generate_signals(df, strategy='bounce')
    print(f"\n발견된 Bounce 신호: {len(signals)}개")
    for sig in signals[:5]:
        print(f"  {sig['timestamp']}: {sig['signal']} ({sig['reason']}, conf={sig['confidence']:.2f})")
