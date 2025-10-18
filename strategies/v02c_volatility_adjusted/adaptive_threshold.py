#!/usr/bin/env python3
"""
adaptive_threshold.py
Bufi's Adaptive Threshold (BAT) 구현
최근 30개 캔들의 추세와 변동성을 기반으로 RSI 임계값을 동적으로 조정
"""

import numpy as np
from scipy import stats


class AdaptiveThreshold:
    """동적 RSI 임계값 계산기"""

    def __init__(
        self,
        window: int = 30,
        base_oversold: int = 30,
        base_overbought: int = 70,
        adjustment_range: int = 20,
        volatility_threshold_high: float = 0.03,
        volatility_threshold_low: float = 0.01
    ):
        """
        Args:
            window: 분석할 최근 캔들 수
            base_oversold: 기본 과매도 임계값
            base_overbought: 기본 과매수 임계값
            adjustment_range: 최대 조정 범위 (±20)
            volatility_threshold_high: 높은 변동성 기준
            volatility_threshold_low: 낮은 변동성 기준
        """
        self.window = window
        self.base_oversold = base_oversold
        self.base_overbought = base_overbought
        self.adjustment_range = adjustment_range
        self.vol_high = volatility_threshold_high
        self.vol_low = volatility_threshold_low

    def calculate_thresholds(self, df, current_idx: int) -> dict:
        """
        현재 시점의 적응형 RSI 임계값 계산

        Args:
            df: OHLCV 데이터프레임
            current_idx: 현재 인덱스

        Returns:
            {
                'oversold': 과매도 임계값 (20~50 범위),
                'overbought': 과매수 임계값 (50~90 범위),
                'slope': 추세 기울기,
                'volatility': 변동성 (normalized std)
            }
        """
        # 최소 window 크기 확보
        if current_idx < self.window:
            return {
                'oversold': self.base_oversold,
                'overbought': self.base_overbought,
                'slope': 0.0,
                'volatility': 0.0
            }

        # 최근 window 개 캔들 추출
        start_idx = current_idx - self.window + 1
        recent = df.iloc[start_idx:current_idx + 1].copy()

        # 1. 추세 강도 계산 (선형회귀 기울기)
        slope = self._calculate_trend_slope(recent['close'].values)

        # 2. 변동성 계산 (정규화된 표준편차)
        volatility = self._calculate_volatility(recent['close'].values)

        # 3. 임계값 조정
        oversold_adj = 0
        overbought_adj = 0

        # 강한 상승 추세
        if slope > 0.02:
            if volatility > self.vol_high:
                # 강한 상승 + 높은 변동성: 매수 완화, 매도 강화
                oversold_adj = +10
                overbought_adj = +10
            elif volatility < self.vol_low:
                # 강한 상승 + 낮은 변동성: 소폭 완화
                oversold_adj = +5
                overbought_adj = +5

        # 강한 하락 추세
        elif slope < -0.02:
            if volatility > self.vol_high:
                # 강한 하락 + 높은 변동성: 매수 강화, 매도 완화
                oversold_adj = -10
                overbought_adj = -10
            elif volatility < self.vol_low:
                # 강한 하락 + 낮은 변동성: 소폭 강화
                oversold_adj = -5
                overbought_adj = -5

        # 횡보장
        else:
            if volatility > self.vol_high:
                # 횡보 + 높은 변동성: 범위 확장
                oversold_adj = -5
                overbought_adj = +5
            # 낮은 변동성은 기본값 유지

        # 조정 범위 제한
        oversold_adj = np.clip(oversold_adj, -self.adjustment_range, self.adjustment_range)
        overbought_adj = np.clip(overbought_adj, -self.adjustment_range, self.adjustment_range)

        # 최종 임계값
        oversold = self.base_oversold + oversold_adj
        overbought = self.base_overbought + overbought_adj

        # 범위 보정 (oversold: 10~50, overbought: 50~90)
        oversold = np.clip(oversold, 10, 50)
        overbought = np.clip(overbought, 50, 90)

        return {
            'oversold': oversold,
            'overbought': overbought,
            'slope': slope,
            'volatility': volatility
        }

    def _calculate_trend_slope(self, prices: np.ndarray) -> float:
        """
        선형회귀로 추세 기울기 계산

        Returns:
            정규화된 기울기 (-1 ~ +1 범위로 변환)
        """
        x = np.arange(len(prices))
        slope, intercept, r_value, p_value, std_err = stats.linregress(x, prices)

        # 기울기를 가격 대비 비율로 정규화
        mean_price = np.mean(prices)
        normalized_slope = (slope * len(prices)) / mean_price if mean_price > 0 else 0

        return normalized_slope

    def _calculate_volatility(self, prices: np.ndarray) -> float:
        """
        정규화된 변동성 계산 (CV: Coefficient of Variation)

        Returns:
            표준편차 / 평균 (0 ~ 1+ 범위)
        """
        mean_price = np.mean(prices)
        std_price = np.std(prices)

        if mean_price == 0:
            return 0.0

        cv = std_price / mean_price
        return cv
