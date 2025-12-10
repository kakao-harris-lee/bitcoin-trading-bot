#!/usr/bin/env python3
"""
trend_detector.py
상승장/하락장/횡보장 판단 모듈
"""

import pandas as pd
import numpy as np


class TrendDetector:
    """시장 추세 감지기"""

    def __init__(
        self,
        adx_threshold: float = 25,
        recent_period: int = 10,
        trend_threshold: float = 0.10
    ):
        """
        Args:
            adx_threshold: ADX 기준값 (강한 추세 판단)
            recent_period: 최근 수익률 계산 기간 (캔들 수)
            trend_threshold: 상승장 판단 수익률 (10% = 0.10)
        """
        self.adx_threshold = adx_threshold
        self.recent_period = recent_period
        self.trend_threshold = trend_threshold

    def detect_trend(self, df: pd.DataFrame, idx: int) -> dict:
        """
        현재 시장 추세 판단

        Returns:
            {
                'trend': 'bull' | 'bear' | 'sideways',
                'adx': float,
                'macd_signal': 'golden' | 'dead' | 'neutral',
                'recent_return': float (% 수익률),
                'strength': float (0~1, 추세 강도)
            }
        """
        if idx < self.recent_period:
            return {
                'trend': 'sideways',
                'adx': 0.0,
                'macd_signal': 'neutral',
                'recent_return': 0.0,
                'strength': 0.0
            }

        row = df.iloc[idx]
        adx = row['adx']
        macd = row['macd']
        macd_signal = row['macd_signal']

        # 최근 N일 수익률 계산
        past_price = df.iloc[idx - self.recent_period]['close']
        current_price = row['close']
        recent_return = (current_price - past_price) / past_price

        # MACD 신호
        if macd > macd_signal:
            macd_status = 'golden'
        elif macd < macd_signal:
            macd_status = 'dead'
        else:
            macd_status = 'neutral'

        # 추세 판단
        trend = 'sideways'
        strength = 0.0

        # 상승장 조건
        if (adx > self.adx_threshold and
            macd_status == 'golden' and
            recent_return > self.trend_threshold):
            trend = 'bull'
            # 강도 = ADX 정규화 (25~50 → 0~1)
            strength = min((adx - self.adx_threshold) / 25, 1.0)

        # 하락장 조건
        elif (adx > self.adx_threshold and
              macd_status == 'dead' and
              recent_return < -self.trend_threshold):
            trend = 'bear'
            strength = min((adx - self.adx_threshold) / 25, 1.0)

        # 횡보장 (약한 추세)
        else:
            trend = 'sideways'
            strength = 0.0

        return {
            'trend': trend,
            'adx': adx,
            'macd_signal': macd_status,
            'recent_return': recent_return,
            'strength': strength
        }

    def is_bull_market(self, df: pd.DataFrame, idx: int) -> bool:
        """상승장 여부 (간단 체크)"""
        result = self.detect_trend(df, idx)
        return result['trend'] == 'bull'

    def is_bear_market(self, df: pd.DataFrame, idx: int) -> bool:
        """하락장 여부 (간단 체크)"""
        result = self.detect_trend(df, idx)
        return result['trend'] == 'bear'


# 사용 예제
if __name__ == "__main__":
    import sys
    sys.path.append('../..')

    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('minute5', start_date='2024-08-26')

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['macd', 'adx'])

    # 추세 감지
    detector = TrendDetector()

    print("✅ 최근 10개 캔들 추세 감지 결과:\n")
    for i in range(len(df) - 10, len(df)):
        result = detector.detect_trend(df, i)
        timestamp = df.iloc[i]['timestamp']
        print(f"{timestamp}: {result['trend']:8s} | ADX={result['adx']:.1f} | "
              f"Return={result['recent_return']:+.2%} | Strength={result['strength']:.2f}")
