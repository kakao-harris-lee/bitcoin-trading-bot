#!/usr/bin/env python3
"""
Market Meta Classifier for v38 Ensemble

v35 MFI + v37 MA20 Slope/ADX 통합 분류기
"""

import pandas as pd
import numpy as np
from typing import Dict


class MarketMetaClassifier:
    """
    v35와 v37 분류 로직을 통합한 Meta Classifier

    시장 상태:
    - BULL_STRONG: 강한 상승장 (장기 보유 전략)
    - BULL_MODERATE: 약한 상승장 (단기 스윙 전략)
    - SIDEWAYS: 횡보장 (v35 전략)
    - BEAR: 하락장 (방어 전략)
    """

    def __init__(self, config: Dict = None):
        """
        Args:
            config: 분류 임계값 설정
        """
        self.config = config or self._default_config()

    def _default_config(self) -> Dict:
        """기본 설정"""
        return {
            # v37 MA20 기울기 (일간 가격 변화율)
            'ma20_slope_bull_strong': 0.014,      # v37 최적화 값
            'ma20_slope_bull_moderate': 0.004,
            'ma20_slope_bear_moderate': -0.004,
            'ma20_slope_bear_strong': -0.014,

            # v35 MFI (Money Flow Index)
            'mfi_bull_strong': 52,                # v35 최적화 값
            'mfi_bull_moderate': 45,
            'mfi_bear_moderate': 38,
            'mfi_bear_strong': 35,

            # v37 ADX (추세 강도)
            'adx_strong_trend': 26,               # v37 최적화 값
            'adx_moderate_trend': 12,

            # 변동성
            'volatility_high': 0.03,
            'volatility_low': 0.015
        }

    def classify_market_state(
        self,
        current_row: pd.Series,
        df_recent: pd.DataFrame
    ) -> str:
        """
        현재 시장 상태 분류

        Args:
            current_row: 현재 캔들 데이터
            df_recent: 최근 60일 데이터 (MA20 계산용)

        Returns:
            'BULL_STRONG', 'BULL_MODERATE', 'SIDEWAYS', 'BEAR'
        """
        # 1. v37 MA20 기울기 계산 (선행 지표)
        ma20_slope = self._calculate_ma20_slope(df_recent)

        # 2. v35 MFI (모멘텀)
        mfi = current_row.get('mfi', 50)

        # 3. v37 ADX (추세 강도)
        adx = current_row.get('adx', 0)

        # 4. 변동성
        volatility = self._calculate_volatility(df_recent)

        # 5. 종합 판정
        return self._综合_classify(ma20_slope, mfi, adx, volatility)

    def _calculate_ma20_slope(self, df_recent: pd.DataFrame) -> float:
        """
        MA20 기울기 계산

        기울기 = (현재 MA20 - 20일 전 MA20) / 20일 전 MA20 / 20
        """
        if len(df_recent) < 40:
            return 0.0

        # MA20 계산
        ma20_current = df_recent['close'].iloc[-20:].mean()
        ma20_20days_ago = df_recent['close'].iloc[-40:-20].mean()

        # 기울기 (일간 변화율)
        if ma20_20days_ago == 0:
            return 0.0

        slope = (ma20_current - ma20_20days_ago) / ma20_20days_ago / 20

        return slope

    def _calculate_volatility(self, df_recent: pd.DataFrame) -> float:
        """변동성 계산 (20일 표준편차)"""
        if len(df_recent) < 20:
            return 0.02

        returns = df_recent['close'].pct_change().iloc[-20:]
        volatility = returns.std()

        return volatility

    def _综合_classify(
        self,
        ma20_slope: float,
        mfi: float,
        adx: float,
        volatility: float
    ) -> str:
        """
        종합 판정

        우선순위:
        1. MA20 기울기 (추세 방향)
        2. MFI (모멘텀 강도)
        3. ADX (추세 확실성)
        """
        cfg = self.config

        # === BULL_STRONG 조건 ===
        # MA20 강한 상승 + MFI 높음 + ADX 강한 추세
        if (ma20_slope > cfg['ma20_slope_bull_strong'] and
            mfi > cfg['mfi_bull_strong'] and
            adx > cfg['adx_strong_trend']):
            return 'BULL_STRONG'

        # === BULL_MODERATE 조건 ===
        # MA20 약한 상승 + MFI 중간
        if (ma20_slope > cfg['ma20_slope_bull_moderate'] and
            mfi > cfg['mfi_bull_moderate']):
            return 'BULL_MODERATE'

        # === BEAR 조건 ===
        # MA20 하락 또는 MFI 낮음
        if (ma20_slope < cfg['ma20_slope_bear_moderate'] or
            mfi < cfg['mfi_bear_moderate']):
            return 'BEAR'

        # === SIDEWAYS (기본) ===
        # 나머지 모든 경우
        return 'SIDEWAYS'

    def get_classification_details(
        self,
        current_row: pd.Series,
        df_recent: pd.DataFrame
    ) -> Dict:
        """
        분류 세부 정보 (디버깅용)

        Returns:
            {
                'market_state': str,
                'ma20_slope': float,
                'mfi': float,
                'adx': float,
                'volatility': float
            }
        """
        ma20_slope = self._calculate_ma20_slope(df_recent)
        mfi = current_row.get('mfi', 50)
        adx = current_row.get('adx', 0)
        volatility = self._calculate_volatility(df_recent)

        market_state = self._综合_classify(ma20_slope, mfi, adx, volatility)

        return {
            'market_state': market_state,
            'ma20_slope': ma20_slope,
            'mfi': mfi,
            'adx': adx,
            'volatility': volatility
        }


if __name__ == '__main__':
    print("Market Meta Classifier - v38 Ensemble")
    print("\n시장 분류:")
    print("  BULL_STRONG: MA20↑ + MFI>52 + ADX>26")
    print("  BULL_MODERATE: MA20↑ + MFI>45")
    print("  SIDEWAYS: 나머지")
    print("  BEAR: MA20↓ or MFI<38")
