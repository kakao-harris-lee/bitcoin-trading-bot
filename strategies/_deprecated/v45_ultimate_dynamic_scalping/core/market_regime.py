#!/usr/bin/env python3
"""
Market Regime Detector
7-Level 시장 상태 분류 (v34 기준)
"""

import numpy as np
import pandas as pd
from typing import Dict, Optional


class MarketRegimeDetector:
    """
    시장 상태 감지기
    - 7-Level 분류: BULL_STRONG/MODERATE, SIDEWAYS_UP/FLAT/DOWN, BEAR_MODERATE/STRONG
    - MFI + MACD + Trend 기반
    """

    def __init__(self, config: Dict):
        """
        Args:
            config: 설정 dict
        """
        # YAML에서 trend를 trend_pct로 변환
        thresholds_config = config.get('thresholds', {})
        if 'trend' in thresholds_config and 'trend_pct' not in thresholds_config:
            trend_cfg = thresholds_config['trend']
            strong = trend_cfg.get('strong', 0.02)
            moderate = trend_cfg.get('moderate', 0.01)
            thresholds_config['trend_pct'] = {
                'strong_up': strong,
                'moderate_up': moderate,
                'moderate_down': -moderate,
                'strong_down': -strong
            }

        self.thresholds = thresholds_config if thresholds_config else {
            'mfi': {'bull_strong': 60, 'bull_moderate': 52, 'bear_moderate': 48, 'bear_strong': 40},
            'macd_signal_ratio': {'bull': 1.05, 'bear': 0.95},
            'trend_pct': {'strong_up': 0.05, 'moderate_up': 0.02, 'moderate_down': -0.02, 'strong_down': -0.05}
        }

        self.lookback_days = config.get('lookback_days', 14)
        self.cache = {}  # timestamp → regime 캐시

    def detect_regime(self, market_data: pd.DataFrame) -> str:
        """
        현재 시장 상태 감지

        Args:
            market_data: 시장 데이터 (MFI, MACD, Signal 포함)

        Returns:
            시장 상태 문자열
        """
        if len(market_data) < self.lookback_days:
            return 'SIDEWAYS_FLAT'  # Default

        latest = market_data.iloc[-1]
        timestamp = latest['timestamp']

        # 캐시 확인
        if timestamp in self.cache:
            return self.cache[timestamp]

        # 1. MFI 레벨
        mfi = latest.get('mfi', 50)
        mfi_level = self._classify_mfi(mfi)

        # 2. MACD vs Signal
        macd = latest.get('macd', 0)
        signal = latest.get('signal', 0)
        macd_signal = self._classify_macd_signal(macd, signal)

        # 3. Trend (최근 14일)
        trend_pct = self._calculate_trend(market_data)
        trend_level = self._classify_trend(trend_pct)

        # 4. 종합 판단
        regime = self._combine_signals(mfi_level, macd_signal, trend_level)

        # 캐시 저장
        self.cache[timestamp] = regime

        return regime

    def get_regime_characteristics(self, regime: str) -> Dict:
        """
        시장 상태별 특성 반환

        Args:
            regime: 시장 상태

        Returns:
            특성 dict (aggression, risk_tolerance, expected_duration)
        """
        characteristics = {
            'BULL_STRONG': {
                'aggression': 1.5,
                'risk_tolerance': 1.2,
                'expected_duration_hours': 168,  # 1주
                'preferred_timeframes': ['day', 'minute240']
            },
            'BULL_MODERATE': {
                'aggression': 1.2,
                'risk_tolerance': 1.0,
                'expected_duration_hours': 72,  # 3일
                'preferred_timeframes': ['minute240', 'minute60']
            },
            'SIDEWAYS_UP': {
                'aggression': 1.0,
                'risk_tolerance': 0.9,
                'expected_duration_hours': 48,  # 2일
                'preferred_timeframes': ['minute60', 'minute15']
            },
            'SIDEWAYS_FLAT': {
                'aggression': 0.8,
                'risk_tolerance': 0.8,
                'expected_duration_hours': 24,  # 1일
                'preferred_timeframes': ['minute60', 'minute15']
            },
            'SIDEWAYS_DOWN': {
                'aggression': 0.6,
                'risk_tolerance': 0.7,
                'expected_duration_hours': 48,  # 2일
                'preferred_timeframes': ['minute60']
            },
            'BEAR_MODERATE': {
                'aggression': 0.4,
                'risk_tolerance': 0.6,
                'expected_duration_hours': 72,  # 3일
                'preferred_timeframes': []  # 거래 자제
            },
            'BEAR_STRONG': {
                'aggression': 0.0,
                'risk_tolerance': 0.5,
                'expected_duration_hours': 168,  # 1주
                'preferred_timeframes': []  # 거래 중단
            }
        }
        return characteristics.get(regime, characteristics['SIDEWAYS_FLAT'])

    def _classify_mfi(self, mfi: float) -> str:
        """MFI 레벨 분류"""
        t = self.thresholds['mfi']
        if mfi >= t['bull_strong']:
            return 'BULL_STRONG'
        elif mfi >= t['bull_moderate']:
            return 'BULL_MODERATE'
        elif mfi <= t['bear_strong']:
            return 'BEAR_STRONG'
        elif mfi <= t['bear_moderate']:
            return 'BEAR_MODERATE'
        else:
            return 'NEUTRAL'

    def _classify_macd_signal(self, macd: float, signal: float) -> str:
        """MACD vs Signal 분류"""
        if signal == 0:
            return 'NEUTRAL'

        ratio = macd / signal
        t = self.thresholds['macd_signal_ratio']

        if ratio >= t['bull']:
            return 'BULL'
        elif ratio <= t['bear']:
            return 'BEAR'
        else:
            return 'NEUTRAL'

    def _calculate_trend(self, market_data: pd.DataFrame) -> float:
        """최근 14일 추세 계산"""
        recent = market_data.tail(self.lookback_days)
        if len(recent) < 2:
            return 0.0

        start_price = recent.iloc[0]['close']
        end_price = recent.iloc[-1]['close']

        return (end_price - start_price) / start_price

    def _classify_trend(self, trend_pct: float) -> str:
        """추세 레벨 분류"""
        t = self.thresholds['trend_pct']
        if trend_pct >= t['strong_up']:
            return 'STRONG_UP'
        elif trend_pct >= t['moderate_up']:
            return 'MODERATE_UP'
        elif trend_pct <= t['strong_down']:
            return 'STRONG_DOWN'
        elif trend_pct <= t['moderate_down']:
            return 'MODERATE_DOWN'
        else:
            return 'FLAT'

    def _combine_signals(self, mfi_level: str, macd_signal: str, trend_level: str) -> str:
        """
        3가지 신호 종합 판단
        우선순위: Trend > MFI > MACD
        """
        # BULL_STRONG 조건
        if (trend_level == 'STRONG_UP' and
            mfi_level in ['BULL_STRONG', 'BULL_MODERATE'] and
            macd_signal == 'BULL'):
            return 'BULL_STRONG'

        # BULL_MODERATE 조건
        if (trend_level in ['STRONG_UP', 'MODERATE_UP'] and
            mfi_level in ['BULL_MODERATE', 'NEUTRAL'] and
            macd_signal == 'BULL'):
            return 'BULL_MODERATE'

        # BEAR_STRONG 조건
        if (trend_level == 'STRONG_DOWN' and
            mfi_level in ['BEAR_STRONG', 'BEAR_MODERATE'] and
            macd_signal == 'BEAR'):
            return 'BEAR_STRONG'

        # BEAR_MODERATE 조건
        if (trend_level in ['STRONG_DOWN', 'MODERATE_DOWN'] and
            mfi_level in ['BEAR_MODERATE', 'NEUTRAL'] and
            macd_signal == 'BEAR'):
            return 'BEAR_MODERATE'

        # SIDEWAYS 세부 분류
        if trend_level == 'MODERATE_UP':
            return 'SIDEWAYS_UP'
        elif trend_level == 'MODERATE_DOWN':
            return 'SIDEWAYS_DOWN'
        else:
            return 'SIDEWAYS_FLAT'

    def clear_cache(self):
        """캐시 초기화"""
        self.cache.clear()


# 테스트 코드
if __name__ == "__main__":
    print("=" * 80)
    print("Market Regime Detector 테스트")
    print("=" * 80)

    config = {
        'thresholds': {
            'mfi': {'bull_strong': 60, 'bull_moderate': 52, 'bear_moderate': 48, 'bear_strong': 40},
            'macd_signal_ratio': {'bull': 1.05, 'bear': 0.95},
            'trend_pct': {'strong_up': 0.05, 'moderate_up': 0.02, 'moderate_down': -0.02, 'strong_down': -0.05}
        },
        'lookback_days': 14
    }

    detector = MarketRegimeDetector(config)

    # 시뮬레이션 데이터 생성
    dates = pd.date_range('2024-01-01', periods=30, freq='D')
    np.random.seed(42)

    # 시나리오 1: BULL_STRONG
    print("\n시나리오 1: BULL_STRONG (MFI 65, MACD>Signal, +8% 추세)")
    print("-" * 80)
    data = pd.DataFrame({
        'timestamp': dates,
        'close': 100000 * (1 + np.linspace(0, 0.08, 30)),  # +8% 상승
        'mfi': 65,
        'macd': 1000,
        'signal': 900
    })
    regime = detector.detect_regime(data)
    print(f"감지된 상태: {regime}")
    char = detector.get_regime_characteristics(regime)
    print(f"특성: 공격성 {char['aggression']:.1f}x, 리스크 허용 {char['risk_tolerance']:.1f}x")
    print(f"선호 타임프레임: {', '.join(char['preferred_timeframes'])}")

    # 시나리오 2: SIDEWAYS_FLAT
    print("\n시나리오 2: SIDEWAYS_FLAT (MFI 50, MACD≈Signal, ±1% 추세)")
    print("-" * 80)
    data = pd.DataFrame({
        'timestamp': dates,
        'close': 100000 * (1 + np.random.uniform(-0.01, 0.01, 30)),  # ±1% 노이즈
        'mfi': 50,
        'macd': 100,
        'signal': 105
    })
    regime = detector.detect_regime(data)
    print(f"감지된 상태: {regime}")
    char = detector.get_regime_characteristics(regime)
    print(f"특성: 공격성 {char['aggression']:.1f}x, 리스크 허용 {char['risk_tolerance']:.1f}x")
    print(f"선호 타임프레임: {', '.join(char['preferred_timeframes'])}")

    # 시나리오 3: BEAR_STRONG
    print("\n시나리오 3: BEAR_STRONG (MFI 35, MACD<Signal, -10% 추세)")
    print("-" * 80)
    data = pd.DataFrame({
        'timestamp': dates,
        'close': 100000 * (1 + np.linspace(0, -0.10, 30)),  # -10% 하락
        'mfi': 35,
        'macd': 100,
        'signal': 150
    })
    regime = detector.detect_regime(data)
    print(f"감지된 상태: {regime}")
    char = detector.get_regime_characteristics(regime)
    print(f"특성: 공격성 {char['aggression']:.1f}x, 리스크 허용 {char['risk_tolerance']:.1f}x")
    print(f"선호 타임프레임: {', '.join(char['preferred_timeframes'])}")

    print("\n" + "=" * 80)
    print("테스트 완료")
    print("=" * 80)
