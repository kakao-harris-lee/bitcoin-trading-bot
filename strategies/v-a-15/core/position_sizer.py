#!/usr/bin/env python3
"""
Position Sizer - Kelly Criterion 기반 동적 포지션 사이징

v-a-15 핵심 모듈 1/3
"""

import numpy as np
from typing import Dict, Optional


class KellyPositionSizer:
    """
    Kelly Criterion 기반 포지션 사이징

    Kelly % = W - (1 - W) / R
    W = 승률
    R = 평균 이익 / 평균 손실 비율

    Half Kelly 적용으로 안전성 확보
    신뢰도 점수 (0-100)로 추가 조정
    """

    def __init__(self, config: Dict):
        self.config = config

        # Kelly Criterion 파라미터
        self.win_rate = config.get('kelly_win_rate', 0.467)  # v-a-11 2025 실적
        self.win_loss_ratio = config.get('kelly_win_loss_ratio', 1.97)  # 6.51 / 3.31
        self.use_half_kelly = config.get('kelly_use_half', True)
        self.kelly_multiplier = config.get('kelly_multiplier', 0.5) if self.use_half_kelly else 1.0

        # 포지션 제한
        self.min_position = config.get('min_position_pct', 0.10)  # 10%
        self.max_position = config.get('max_position_pct', 0.80)  # 80%

        # Kelly 계산
        self.kelly_pct = self._calculate_kelly()

    def _calculate_kelly(self) -> float:
        """
        Kelly % 계산

        Kelly % = W - (1 - W) / R

        Returns:
            Kelly percentage (0-1)
        """
        W = self.win_rate
        R = self.win_loss_ratio

        if R <= 0:
            return 0.0

        kelly = W - (1 - W) / R

        # Half Kelly 적용
        kelly *= self.kelly_multiplier

        # 음수 방지
        kelly = max(0, kelly)

        return kelly

    def calculate_position_size(
        self,
        confidence_score: float,
        capital: float,
        strategy: str = 'default'
    ) -> float:
        """
        신뢰도 점수 기반 포지션 크기 계산

        Args:
            confidence_score: 신뢰도 점수 (0-100)
            capital: 현재 자본
            strategy: 전략 이름 (grid/trend/sideways)

        Returns:
            포지션 크기 (원)
        """
        # 신뢰도 비율 (0-1)
        confidence_ratio = confidence_score / 100.0

        # 전략별 기본 배율
        strategy_multiplier = self._get_strategy_multiplier(strategy)

        # 포지션 비율 계산
        # Kelly를 기준값으로, 신뢰도로 조정
        # confidence_ratio가 0.5이면 50% 사용, 1.0이면 100% 사용
        position_pct = self.kelly_pct * strategy_multiplier * (1 + confidence_ratio)

        # 제한 적용
        position_pct = np.clip(position_pct, self.min_position, self.max_position)

        # 자본 적용
        position_size = capital * position_pct

        return position_size

    def _get_strategy_multiplier(self, strategy: str) -> float:
        """
        전략별 기본 배율

        Args:
            strategy: 전략 이름

        Returns:
            배율 (1.0 = 기본)
        """
        multipliers = {
            'trend_following': 3.0,   # Trend는 승률 48%, 기여도 69.6% → 적극적
            'grid': 2.0,              # Grid는 안정적 → 중간
            'sideways': 1.5,          # Sideways는 승률 40% → 보수적
            'defensive': 0.5,         # Defensive는 실패 전략 → 최소
            'default': 2.0
        }

        return multipliers.get(strategy, multipliers['default'])

    def get_kelly_info(self) -> Dict:
        """
        Kelly Criterion 정보 반환

        Returns:
            Kelly 계산 정보
        """
        return {
            'win_rate': self.win_rate,
            'win_loss_ratio': self.win_loss_ratio,
            'kelly_pct': self.kelly_pct,
            'half_kelly': self.use_half_kelly,
            'kelly_multiplier': self.kelly_multiplier,
            'min_position': self.min_position,
            'max_position': self.max_position
        }


class SignalConfidenceScorer:
    """
    시그널 신뢰도 점수 계산 (0-100점)

    다양한 지표 조건을 평가하여 종합 점수 산출
    """

    def __init__(self, config: Dict):
        self.config = config

        # 점수 가중치
        self.weights = {
            'adx_strong': 20,         # ADX > 25
            'adx_very_strong': 10,    # ADX > 30 (추가)
            'volume_high': 15,        # Volume > 2.0x
            'volume_very_high': 10,   # Volume > 3.0x (추가)
            'rsi_extreme': 25,        # RSI < 20 or > 80
            'stoch_signal': 20,       # Stochastic 골든/데드크로스
            'bb_extreme': 10,         # Bollinger Band 상하단
            'support_resistance': 10  # Support/Resistance 접근
        }

    def calculate_confidence(
        self,
        adx: float,
        volume_ratio: float,
        rsi: float,
        stoch_k: float,
        stoch_d: float,
        bb_position: float,
        near_support: bool = False,
        near_resistance: bool = False
    ) -> float:
        """
        신뢰도 점수 계산

        Args:
            adx: ADX 값
            volume_ratio: 거래량 비율 (평균 대비)
            rsi: RSI 값
            stoch_k: Stochastic %K
            stoch_d: Stochastic %D
            bb_position: Bollinger Band 위치 (0-1)
            near_support: Support 접근 여부
            near_resistance: Resistance 접근 여부

        Returns:
            신뢰도 점수 (0-100)
        """
        score = 0

        # 1. ADX (추세 강도)
        if adx > 30:
            score += self.weights['adx_strong'] + self.weights['adx_very_strong']
        elif adx > 25:
            score += self.weights['adx_strong']

        # 2. Volume (거래량)
        if volume_ratio > 3.0:
            score += self.weights['volume_high'] + self.weights['volume_very_high']
        elif volume_ratio > 2.0:
            score += self.weights['volume_high']

        # 3. RSI (극단 과매도/과매수)
        if rsi < 20 or rsi > 80:
            score += self.weights['rsi_extreme']
        elif rsi < 25 or rsi > 75:
            score += self.weights['rsi_extreme'] * 0.6  # 부분 점수

        # 4. Stochastic (골든/데드크로스)
        if self._is_golden_cross(stoch_k, stoch_d):
            score += self.weights['stoch_signal']
        elif self._is_dead_cross(stoch_k, stoch_d):
            score += self.weights['stoch_signal']

        # 5. Bollinger Band (상하단 접근)
        if bb_position < 0.1 or bb_position > 0.9:
            score += self.weights['bb_extreme']

        # 6. Support/Resistance
        if near_support or near_resistance:
            score += self.weights['support_resistance']

        # 최대 100점 제한
        score = min(score, 100)

        return score

    def _is_golden_cross(self, k: float, d: float) -> bool:
        """Stochastic 골든크로스 판정"""
        return k > d and k < 30  # K가 D를 상향 돌파, 과매도 구간

    def _is_dead_cross(self, k: float, d: float) -> bool:
        """Stochastic 데드크로스 판정"""
        return k < d and k > 70  # K가 D를 하향 돌파, 과매수 구간


# 테스트 코드
if __name__ == '__main__':
    # Kelly Criterion 테스트
    config = {
        'kelly_win_rate': 0.467,
        'kelly_win_loss_ratio': 1.97,
        'kelly_use_half': True,
        'min_position_pct': 0.10,
        'max_position_pct': 0.80
    }

    sizer = KellyPositionSizer(config)
    print("="*80)
    print("Kelly Position Sizer 테스트")
    print("="*80)
    print(f"\nKelly 정보:")
    info = sizer.get_kelly_info()
    for key, value in info.items():
        print(f"  {key}: {value}")

    print(f"\n포지션 크기 계산 (자본 10,000,000원):")
    capital = 10_000_000

    test_cases = [
        ('trend_following', 100, '최고 신뢰도 Trend'),
        ('trend_following', 60, '중간 신뢰도 Trend'),
        ('sideways', 80, '높은 신뢰도 Sideways'),
        ('sideways', 40, '낮은 신뢰도 Sideways'),
        ('grid', 70, '중간 신뢰도 Grid')
    ]

    for strategy, confidence, desc in test_cases:
        position = sizer.calculate_position_size(confidence, capital, strategy)
        pct = position / capital * 100
        print(f"  {desc}: {position:,.0f}원 ({pct:.1f}%)")

    # SignalConfidenceScorer 테스트
    print("\n" + "="*80)
    print("Signal Confidence Scorer 테스트")
    print("="*80)

    scorer = SignalConfidenceScorer(config)

    test_signals = [
        {
            'desc': '강한 BULL Trend',
            'adx': 35, 'volume_ratio': 3.5, 'rsi': 45,
            'stoch_k': 25, 'stoch_d': 20, 'bb_position': 0.3,
            'near_support': False, 'near_resistance': False
        },
        {
            'desc': '극단 과매도 SIDEWAYS',
            'adx': 12, 'volume_ratio': 2.2, 'rsi': 18,
            'stoch_k': 15, 'stoch_d': 20, 'bb_position': 0.05,
            'near_support': True, 'near_resistance': False
        },
        {
            'desc': '약한 시그널',
            'adx': 15, 'volume_ratio': 1.0, 'rsi': 50,
            'stoch_k': 50, 'stoch_d': 48, 'bb_position': 0.5,
            'near_support': False, 'near_resistance': False
        }
    ]

    for signal in test_signals:
        desc = signal.pop('desc')
        confidence = scorer.calculate_confidence(**signal)
        print(f"\n{desc}:")
        print(f"  신뢰도 점수: {confidence:.1f}점")
        print(f"  → Trend 포지션: {sizer.calculate_position_size(confidence, capital, 'trend_following')/capital*100:.1f}%")
        print(f"  → Sideways 포지션: {sizer.calculate_position_size(confidence, capital, 'sideways')/capital*100:.1f}%")
