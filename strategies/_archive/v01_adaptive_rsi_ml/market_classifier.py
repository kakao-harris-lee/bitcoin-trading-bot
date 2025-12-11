#!/usr/bin/env python3
"""
market_classifier.py
시장 상태 분류기: 변동성 × 추세 × 모멘텀 → 9가지 상태
"""

import numpy as np
import talib
from typing import Literal


MarketState = Literal[
    "high_vol_strong_up", "high_vol_neutral", "high_vol_strong_down",
    "mid_vol_strong_up", "mid_vol_neutral", "mid_vol_strong_down",
    "low_vol_strong_up", "low_vol_neutral", "low_vol_strong_down"
]


class MarketClassifier:
    """시장 상태 9가지로 분류"""

    def __init__(
        self,
        window: int = 30,
        adx_period: int = 14,
        adx_threshold: int = 20,
        roc_period: int = 10,
        atr_period: int = 14,
        vol_high: float = 0.03,
        vol_low: float = 0.01
    ):
        """
        Args:
            window: 분석 윈도우
            adx_period: ADX 계산 기간
            adx_threshold: 추세 강도 임계값
            roc_period: Rate of Change 기간
            atr_period: ATR 계산 기간
            vol_high: 높은 변동성 기준
            vol_low: 낮은 변동성 기준
        """
        self.window = window
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        self.roc_period = roc_period
        self.atr_period = atr_period
        self.vol_high = vol_high
        self.vol_low = vol_low

    def classify(self, df, current_idx: int) -> dict:
        """
        현재 시점의 시장 상태 분류

        Returns:
            {
                'state': MarketState,
                'volatility': 'high' | 'mid' | 'low',
                'trend': 'strong_up' | 'neutral' | 'strong_down',
                'momentum': float,
                'adx': float,
                'atr_ratio': float
            }
        """
        if current_idx < max(self.window, self.adx_period, self.atr_period):
            return {
                'state': 'mid_vol_neutral',
                'volatility': 'mid',
                'trend': 'neutral',
                'momentum': 0.0,
                'adx': 0.0,
                'atr_ratio': 0.0
            }

        # 1. 변동성 측정 (ATR 기반)
        volatility = self._measure_volatility(df, current_idx)

        # 2. 추세 강도 측정 (ADX 기반)
        trend = self._measure_trend(df, current_idx)

        # 3. 모멘텀 측정 (ROC 기반)
        momentum = self._measure_momentum(df, current_idx)

        # 4. 상태 조합
        state = f"{volatility}_vol_{trend}"

        return {
            'state': state,
            'volatility': volatility,
            'trend': trend,
            'momentum': momentum,
            'adx': df.iloc[current_idx]['adx'],
            'atr_ratio': df.iloc[current_idx]['atr'] / df.iloc[current_idx]['close']
        }

    def _measure_volatility(self, df, idx: int) -> str:
        """
        ATR 기반 변동성 측정

        Returns:
            'high' | 'mid' | 'low'
        """
        close = df.iloc[idx]['close']
        atr = df.iloc[idx]['atr']

        # ATR을 가격 대비 비율로 정규화
        atr_ratio = atr / close if close > 0 else 0

        if atr_ratio > self.vol_high:
            return 'high'
        elif atr_ratio < self.vol_low:
            return 'low'
        else:
            return 'mid'

    def _measure_trend(self, df, idx: int) -> str:
        """
        ADX + MACD 기반 추세 강도 측정

        Returns:
            'strong_up' | 'neutral' | 'strong_down'
        """
        adx = df.iloc[idx]['adx']
        macd = df.iloc[idx]['macd']
        macd_signal = df.iloc[idx]['macd_signal']

        # ADX가 낮으면 무조건 중립
        if adx < self.adx_threshold:
            return 'neutral'

        # MACD로 방향 판단
        macd_diff = macd - macd_signal

        if macd_diff > 0:
            return 'strong_up'
        elif macd_diff < 0:
            return 'strong_down'
        else:
            return 'neutral'

    def _measure_momentum(self, df, idx: int) -> float:
        """
        ROC 기반 모멘텀 측정

        Returns:
            ROC 값 (백분율, -100 ~ +100)
        """
        if 'roc' in df.columns:
            return df.iloc[idx]['roc']

        # ROC가 없으면 직접 계산
        if idx < self.roc_period:
            return 0.0

        current_price = df.iloc[idx]['close']
        past_price = df.iloc[idx - self.roc_period]['close']

        if past_price == 0:
            return 0.0

        roc = ((current_price - past_price) / past_price) * 100
        return roc


def add_market_indicators(df):
    """
    시장 분류에 필요한 모든 지표 추가

    Args:
        df: OHLCV 데이터프레임

    Returns:
        지표가 추가된 데이터프레임
    """
    df = df.copy()

    # ADX (추세 강도)
    df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=14)

    # ATR (변동성)
    df['atr'] = talib.ATR(df['high'], df['low'], df['close'], timeperiod=14)

    # MACD (추세 방향)
    macd, macd_signal, macd_hist = talib.MACD(
        df['close'],
        fastperiod=12,
        slowperiod=26,
        signalperiod=9
    )
    df['macd'] = macd
    df['macd_signal'] = macd_signal
    df['macd_hist'] = macd_hist

    # ROC (모멘텀)
    df['roc'] = talib.ROC(df['close'], timeperiod=10)

    # RSI (과매수/과매도)
    df['rsi'] = talib.RSI(df['close'], timeperiod=14)

    return df
