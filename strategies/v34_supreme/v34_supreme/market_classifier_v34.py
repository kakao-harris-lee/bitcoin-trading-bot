#!/usr/bin/env python3
"""
v34 Supreme: 7-Level Market Classifier
2020-2024 데이터 기반 최적화된 시장 분류기
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple

class MarketClassifierV34:
    """
    7-Level Market Classification System

    분류 기준:
    1. BULL_STRONG: 강한 상승 추세 (MFI>=55, MACD>Signal, ADX>=25)
    2. BULL_MODERATE: 중간 상승 추세 (MFI>=48, MACD>Signal, ADX>=18)
    3. SIDEWAYS_UP: 횡보 상승 (MFI 45-55, upward trend)
    4. SIDEWAYS_FLAT: 횡보 정체 (MFI 40-50, flat)
    5. SIDEWAYS_DOWN: 횡보 하락 (MFI 35-45, downward trend)
    6. BEAR_MODERATE: 중간 하락 추세 (MFI 35-42, MACD<Signal)
    7. BEAR_STRONG: 강한 하락 추세 (MFI<35, ADX>20)

    2020-2024 데이터 분석 결과:
    - SIDEWAYS_FLAT: 평균 31% (가장 많음)
    - BULL_STRONG: 평균 23%
    - BEAR_STRONG: 평균 16%
    """

    def __init__(self):
        # 2020-2024 데이터 기반 최적화된 임계값
        # 분석 결과: BULL_STRONG 23%, SIDEWAYS_FLAT 31%, BEAR_STRONG 16%
        self.thresholds = {
            # MFI 임계값 (완화)
            'mfi_bull_strong': 52,      # 55 → 52
            'mfi_bull_moderate': 45,    # 48 → 45
            'mfi_sideways_up': 42,      # 45 → 42
            'mfi_sideways_flat': 38,    # 40 → 38
            'mfi_sideways_down': 35,
            'mfi_bear_moderate': 38,    # 35 → 38
            'mfi_bear_strong': 35,
            # ADX 임계값 (완화)
            'adx_strong_trend': 20,     # 25 → 20
            'adx_moderate_trend': 15,   # 18 → 15
            'adx_weak_trend': 12,       # 15 → 12
            'volatility_high': 0.03,
            'volatility_low': 0.01
        }

    def classify_market_state(self, row: pd.Series, prev_row: pd.Series = None) -> str:
        """
        현재 캔들의 시장 상태 분류

        Args:
            row: 현재 캔들 데이터 (지표 포함)
            prev_row: 이전 캔들 데이터 (트렌드 계산용, optional)

        Returns:
            시장 상태 문자열
        """
        mfi = row.get('mfi', 50)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        adx = row.get('adx', 0)

        # 1. BULL_STRONG: 강한 상승 (조건 완화)
        if (mfi >= self.thresholds['mfi_bull_strong'] and
            macd > macd_signal and
            adx >= self.thresholds['adx_strong_trend']):
            return 'BULL_STRONG'

        # 2. BULL_MODERATE: 중간 상승
        if (mfi >= self.thresholds['mfi_bull_moderate'] and
            macd > macd_signal):
            return 'BULL_MODERATE'

        # 3. BEAR_STRONG: 강한 하락 (조건 완화)
        if (mfi < self.thresholds['mfi_bear_strong'] and
            adx >= self.thresholds['adx_strong_trend']):
            return 'BEAR_STRONG'

        # 4. BEAR_MODERATE: 중간 하락
        if (mfi < self.thresholds['mfi_bear_moderate'] and
            macd < macd_signal):
            return 'BEAR_MODERATE'

        # 5-7. SIDEWAYS (횡보) 분류
        # 이전 캔들과 비교하여 상승/정체/하락 판단
        if prev_row is not None:
            price_change = (row['close'] - prev_row['close']) / prev_row['close']

            # SIDEWAYS_UP: 약한 상승
            if (self.thresholds['mfi_sideways_up'] <= mfi < self.thresholds['mfi_bull_moderate'] and
                price_change > 0.005):  # 0.5% 이상 상승
                return 'SIDEWAYS_UP'

            # SIDEWAYS_DOWN: 약한 하락
            if (self.thresholds['mfi_sideways_down'] <= mfi < self.thresholds['mfi_sideways_up'] and
                price_change < -0.005):  # 0.5% 이상 하락
                return 'SIDEWAYS_DOWN'

        # SIDEWAYS_FLAT: 나머지 (가장 많은 경우)
        return 'SIDEWAYS_FLAT'

    def classify_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        전체 데이터프레임에 시장 상태 분류 적용

        Args:
            df: 지표가 포함된 데이터프레임

        Returns:
            market_state 컬럼이 추가된 데이터프레임
        """
        df = df.copy()
        df['market_state'] = 'UNKNOWN'

        for i in range(len(df)):
            prev_row = df.iloc[i-1] if i > 0 else None
            df.loc[df.index[i], 'market_state'] = self.classify_market_state(
                df.iloc[i],
                prev_row
            )

        return df

    def get_market_distribution(self, df: pd.DataFrame) -> Dict[str, float]:
        """
        시장 상태 분포 계산

        Args:
            df: market_state 컬럼이 포함된 데이터프레임

        Returns:
            시장 상태별 비율 딕셔너리
        """
        if 'market_state' not in df.columns:
            df = self.classify_dataframe(df)

        total = len(df)
        distribution = df['market_state'].value_counts().to_dict()

        # 비율로 변환
        return {state: count/total*100 for state, count in distribution.items()}

    def optimize_thresholds(self, df: pd.DataFrame, target_distribution: Dict[str, float]) -> Dict[str, float]:
        """
        목표 분포에 맞춰 임계값 최적화

        Args:
            df: 학습 데이터
            target_distribution: 목표 시장 상태 분포 (예: {'SIDEWAYS_FLAT': 30, 'BULL_STRONG': 20, ...})

        Returns:
            최적화된 임계값 딕셔너리

        Note:
            실제로는 Optuna나 Grid Search를 사용해야 하지만,
            현재는 2020-2024 분석 결과를 바탕으로 고정값 사용
        """
        # TODO: Optuna를 사용한 임계값 최적화 구현
        # 현재는 2020-2024 분석 결과 기반 고정값 반환
        return self.thresholds


if __name__ == '__main__':
    """테스트 및 검증"""
    import sys
    sys.path.append('../..')
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    # 2024 데이터로 테스트
    print("="*70)
    print("  v34 Market Classifier - 2024 테스트")
    print("="*70)

    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd', 'mfi', 'adx'])

    # 분류
    classifier = MarketClassifierV34()
    df = classifier.classify_dataframe(df)

    # 분포 확인
    distribution = classifier.get_market_distribution(df)

    print("\n[2024 시장 상태 분포]")
    for state, pct in sorted(distribution.items(), key=lambda x: x[1], reverse=True):
        count = int(len(df) * pct / 100)
        print(f"  {state:20s}: {count:3d}일 ({pct:5.1f}%)")

    # 2020-2024 분석 결과와 비교
    print("\n[2020-2024 평균 vs 2024 실제]")
    print(f"  SIDEWAYS_FLAT: 31% (평균) vs {distribution.get('SIDEWAYS_FLAT', 0):.1f}% (2024)")
    print(f"  BULL_STRONG:   23% (평균) vs {distribution.get('BULL_STRONG', 0):.1f}% (2024)")
    print(f"  BEAR_STRONG:   16% (평균) vs {distribution.get('BEAR_STRONG', 0):.1f}% (2024)")

    print("\n분류기 테스트 완료!")
