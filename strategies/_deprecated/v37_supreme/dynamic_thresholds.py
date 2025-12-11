#!/usr/bin/env python3
"""
Dynamic Thresholds Module
시장 상태에 따른 동적 임계값 조정

핵심 아이디어:
  - 고정 임계값 → 동적 quantile 기반 임계값
  - RSI 30 → 최근 20일 RSI의 하위 20%
  - Volume 2.0x → 최근 20일 Volume의 상위 20%
  - Volatility 기반 조정 (변동성 높을 때 완화)

목표:
  - 진입 빈도 증가 (3-9회/년 → 15-30회/년)
  - BULL 시장 거래 활성화
  - 오버피팅 방지 (rolling window 사용)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class DynamicThresholds:
    """동적 임계값 관리자"""

    def __init__(self, config: Dict):
        """
        Args:
            config: 기본 설정 (fallback용)
        """
        self.config = config

        # Rolling window 크기
        self.lookback_period = config.get('threshold_lookback_period', 60)  # 60일

        # Quantile 설정
        self.rsi_oversold_quantile = config.get('rsi_oversold_quantile', 0.30)  # 하위 30%
        self.rsi_overbought_quantile = config.get('rsi_overbought_quantile', 0.70)  # 상위 30%
        self.volume_high_quantile = config.get('volume_high_quantile', 0.80)  # 상위 20%
        self.volatility_high_quantile = config.get('volatility_high_quantile', 0.70)

        # Fallback 고정값 (데이터 부족 시)
        self.fallback_rsi_oversold = 30
        self.fallback_rsi_overbought = 70
        self.fallback_volume_mult = 2.0

    def get_dynamic_rsi_thresholds(self, df_recent: pd.DataFrame) -> Dict:
        """
        RSI 동적 임계값 계산

        Args:
            df_recent: 최근 N일 데이터 (lookback_period)

        Returns:
            {'oversold': float, 'overbought': float}
        """

        if len(df_recent) < 20:
            return {
                'oversold': self.fallback_rsi_oversold,
                'overbought': self.fallback_rsi_overbought
            }

        rsi_values = df_recent['rsi'].dropna()

        if len(rsi_values) < 10:
            return {
                'oversold': self.fallback_rsi_oversold,
                'overbought': self.fallback_rsi_overbought
            }

        oversold = rsi_values.quantile(self.rsi_oversold_quantile)
        overbought = rsi_values.quantile(self.rsi_overbought_quantile)

        # 너무 극단적인 값 방지
        oversold = max(20, min(40, oversold))
        overbought = max(60, min(80, overbought))

        return {
            'oversold': oversold,
            'overbought': overbought
        }

    def get_dynamic_volume_threshold(self, df_recent: pd.DataFrame) -> float:
        """
        Volume 동적 임계값 계산

        Args:
            df_recent: 최근 N일 데이터

        Returns:
            volume_threshold (평균 대비 배수)
        """

        if len(df_recent) < 20:
            return self.fallback_volume_mult

        volume_values = df_recent['volume'].dropna()

        if len(volume_values) < 10:
            return self.fallback_volume_mult

        avg_volume = volume_values.mean()
        high_volume = volume_values.quantile(self.volume_high_quantile)

        # 평균 대비 배수 계산
        volume_mult = high_volume / avg_volume if avg_volume > 0 else self.fallback_volume_mult

        # 1.5 ~ 3.0 범위로 제한
        volume_mult = max(1.5, min(3.0, volume_mult))

        return volume_mult

    def get_dynamic_bb_thresholds(self, df_recent: pd.DataFrame) -> Dict:
        """
        Bollinger Bands 동적 임계값

        Returns:
            {'lower_penetration': float, 'upper_penetration': float}
        """

        if len(df_recent) < 20:
            return {'lower_penetration': 1.0, 'upper_penetration': 1.0}

        # BB 하단 이탈 정도 (가격이 BB_lower보다 얼마나 낮은지)
        bb_lower = df_recent['bb_lower'].dropna()
        close = df_recent['close'].dropna()

        if len(bb_lower) < 10 or len(close) < 10:
            return {'lower_penetration': 1.0, 'upper_penetration': 1.0}

        # 최근 변동성 기반 조정
        volatility = close.pct_change().std()

        # 변동성 높을 때 이탈 조건 완화
        if volatility > 0.03:  # 3% 이상
            lower_penetration = 1.02  # BB_lower의 102% 이하 (완화)
            upper_penetration = 0.98
        elif volatility > 0.02:
            lower_penetration = 1.01
            upper_penetration = 0.99
        else:
            lower_penetration = 1.0  # 정확히 이탈
            upper_penetration = 1.0

        return {
            'lower_penetration': lower_penetration,
            'upper_penetration': upper_penetration
        }

    def adjust_entry_conditions_by_volatility(self, df_recent: pd.DataFrame) -> Dict:
        """
        변동성 기반 진입 조건 조정

        변동성 높을 때 → 조건 완화
        변동성 낮을 때 → 조건 강화

        Returns:
            {
                'rsi_adjustment': float,  # RSI 임계값 조정폭
                'macd_simplify': bool,    # MACD 조건 단순화 여부
                'volume_relax': bool      # Volume 조건 완화 여부
            }
        """

        if len(df_recent) < 20:
            return {
                'rsi_adjustment': 0,
                'macd_simplify': False,
                'volume_relax': False
            }

        close = df_recent['close'].dropna()

        if len(close) < 10:
            return {
                'rsi_adjustment': 0,
                'macd_simplify': False,
                'volume_relax': False
            }

        # 변동성 계산 (20일 일일 수익률 표준편차)
        volatility = close.pct_change().std()

        # 변동성 quantile
        if len(df_recent) >= 60:
            recent_60 = df_recent.iloc[-60:]
            volatility_60 = recent_60['close'].pct_change().rolling(20).std().dropna()
            if len(volatility_60) > 0:
                volatility_quantile = (volatility_60 < volatility).mean()
            else:
                volatility_quantile = 0.5
        else:
            volatility_quantile = 0.5

        # 고변동성 (상위 30%)
        if volatility_quantile >= 0.70:
            return {
                'rsi_adjustment': +5,      # RSI 30 → 35
                'macd_simplify': True,     # 골든크로스 불필요
                'volume_relax': True       # Volume 조건 완화
            }

        # 중변동성
        elif volatility_quantile >= 0.40:
            return {
                'rsi_adjustment': +2,
                'macd_simplify': False,
                'volume_relax': False
            }

        # 저변동성 (하위 40%)
        else:
            return {
                'rsi_adjustment': -2,      # RSI 30 → 28 (더 빡빡)
                'macd_simplify': False,
                'volume_relax': False
            }

    def get_all_dynamic_thresholds(self, df_recent: pd.DataFrame, current_row: pd.Series) -> Dict:
        """
        모든 동적 임계값 한번에 계산

        Args:
            df_recent: 최근 lookback_period일 데이터
            current_row: 현재 캔들

        Returns:
            전체 동적 임계값 딕셔너리
        """

        rsi_thresholds = self.get_dynamic_rsi_thresholds(df_recent)
        volume_threshold = self.get_dynamic_volume_threshold(df_recent)
        bb_thresholds = self.get_dynamic_bb_thresholds(df_recent)
        volatility_adjustments = self.adjust_entry_conditions_by_volatility(df_recent)

        # RSI 임계값에 변동성 조정 적용
        rsi_oversold_adjusted = rsi_thresholds['oversold'] + volatility_adjustments['rsi_adjustment']
        rsi_overbought_adjusted = rsi_thresholds['overbought'] - volatility_adjustments['rsi_adjustment']

        # 범위 제한
        rsi_oversold_adjusted = max(20, min(45, rsi_oversold_adjusted))
        rsi_overbought_adjusted = max(60, min(85, rsi_overbought_adjusted))

        return {
            'rsi_oversold': rsi_oversold_adjusted,
            'rsi_overbought': rsi_overbought_adjusted,
            'volume_mult': volume_threshold,
            'bb_lower_penetration': bb_thresholds['lower_penetration'],
            'bb_upper_penetration': bb_thresholds['upper_penetration'],
            'macd_simplify': volatility_adjustments['macd_simplify'],
            'volume_relax': volatility_adjustments['volume_relax']
        }


if __name__ == '__main__':
    """테스트"""
    print("="*70)
    print("  Dynamic Thresholds - 테스트")
    print("="*70)

    # 시뮬레이션 데이터 (고변동성 → 저변동성)
    dates = pd.date_range('2024-01-01', periods=100, freq='D')

    # 고변동성 구간 (0-40)
    high_vol_prices = 100000 + np.random.randn(40).cumsum() * 5000

    # 저변동성 구간 (41-100)
    low_vol_prices = high_vol_prices[-1] + np.random.randn(60).cumsum() * 500

    prices = np.concatenate([high_vol_prices, low_vol_prices])

    # RSI 시뮬레이션
    rsi_values = 50 + np.random.randn(100) * 15
    rsi_values = np.clip(rsi_values, 10, 90)

    # Volume
    volumes = np.random.uniform(1000, 5000, 100)
    volumes[20] = 10000  # 급등
    volumes[80] = 8000

    # BB
    bb_middle = prices
    bb_upper = bb_middle + 2000
    bb_lower = bb_middle - 2000

    df = pd.DataFrame({
        'close': prices,
        'rsi': rsi_values,
        'volume': volumes,
        'bb_upper': bb_upper,
        'bb_middle': bb_middle,
        'bb_lower': bb_lower
    }, index=dates)

    config = {
        'threshold_lookback_period': 60,
        'rsi_oversold_quantile': 0.30,
        'rsi_overbought_quantile': 0.70,
        'volume_high_quantile': 0.80,
        'volatility_high_quantile': 0.70
    }

    dt = DynamicThresholds(config)

    # 고변동성 구간 테스트 (i=30)
    i = 30
    df_recent = df.iloc[max(0, i-60):i+1]
    thresholds = dt.get_all_dynamic_thresholds(df_recent, df.iloc[i])

    print(f"\n[고변동성 구간 (i={i})]")
    print(f"  RSI Oversold: {thresholds['rsi_oversold']:.1f} (기본 30)")
    print(f"  RSI Overbought: {thresholds['rsi_overbought']:.1f} (기본 70)")
    print(f"  Volume Mult: {thresholds['volume_mult']:.2f}x (기본 2.0x)")
    print(f"  MACD 단순화: {thresholds['macd_simplify']}")
    print(f"  Volume 완화: {thresholds['volume_relax']}")

    # 저변동성 구간 테스트 (i=80)
    i = 80
    df_recent = df.iloc[max(0, i-60):i+1]
    thresholds = dt.get_all_dynamic_thresholds(df_recent, df.iloc[i])

    print(f"\n[저변동성 구간 (i={i})]")
    print(f"  RSI Oversold: {thresholds['rsi_oversold']:.1f} (기본 30)")
    print(f"  RSI Overbought: {thresholds['rsi_overbought']:.1f} (기본 70)")
    print(f"  Volume Mult: {thresholds['volume_mult']:.2f}x (기본 2.0x)")
    print(f"  MACD 단순화: {thresholds['macd_simplify']}")
    print(f"  Volume 완화: {thresholds['volume_relax']}")

    print(f"\n테스트 완료!")
    print(f"\n핵심:")
    print(f"  - 고변동성 → RSI 완화 (30→35), MACD 단순화")
    print(f"  - 저변동성 → RSI 강화 (30→28), 조건 엄격")
    print(f"  - 시장 적응형 임계값 ✅")
