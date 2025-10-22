#!/usr/bin/env python3
"""
Position Sizing Plugins
========================
포지션 크기 결정 플러그인 모음

작성일: 2025-10-21
버전: 1.0

플러그인:
- FixedPositionPlugin: 고정 비율 (v30-v40 대부분)
- KellyPositionPlugin: Kelly Criterion (v02a)
- ScoreBasedPositionPlugin: 점수 기반 (v41)
"""

from typing import Dict, Any


# ========================================
# Base Position Plugin
# ========================================

class BasePositionPlugin:
    """포지션 크기 플러그인 베이스 클래스"""

    def calculate_position_size(
        self,
        signal: Any,
        capital: float,
        config: Dict
    ) -> float:
        """
        포지션 크기 계산

        Args:
            signal: Signal 객체
            capital: 현재 자본
            config: 포지션 설정

        Returns:
            fraction (0.0-1.0): 자본의 몇 %를 사용할지
        """
        raise NotImplementedError


# ========================================
# Fixed Position Plugin
# ========================================

class FixedPositionPlugin(BasePositionPlugin):
    """
    고정 비율 포지션

    기존 전략: v30-v40 대부분
    설정 예시:
    {
        "type": "fixed",
        "fraction": 0.5  # 50%
    }
    """

    def calculate_position_size(
        self,
        signal,
        capital,
        config
    ) -> float:
        fraction = config.get('fraction', 0.5)
        return min(max(fraction, 0.0), 1.0)  # 0-1 범위로 제한


# ========================================
# Kelly Criterion Plugin
# ========================================

class KellyPositionPlugin(BasePositionPlugin):
    """
    Kelly Criterion 포지션 크기

    기존 전략: v02a Dynamic Kelly
    설정 예시:
    {
        "type": "kelly",
        "win_rate": 0.55,
        "avg_win": 0.03,
        "avg_loss": 0.015,
        "max_fraction": 0.8,
        "kelly_fraction": 0.5  # Half Kelly
    }
    """

    def calculate_position_size(
        self,
        signal,
        capital,
        config
    ) -> float:
        win_rate = config.get('win_rate', 0.5)
        avg_win = config.get('avg_win', 0.02)
        avg_loss = config.get('avg_loss', 0.01)
        max_fraction = config.get('max_fraction', 0.8)
        kelly_fraction = config.get('kelly_fraction', 0.5)  # Half Kelly (보수적)

        # Kelly Formula: f = (p * b - q) / b
        # p = win_rate, q = 1 - p, b = avg_win / avg_loss
        if avg_loss == 0:
            return max_fraction

        b = avg_win / avg_loss
        q = 1 - win_rate

        kelly_f = (win_rate * b - q) / b

        # Kelly fraction 적용 (Half Kelly 등)
        kelly_f *= kelly_fraction

        # 범위 제한
        kelly_f = max(0.0, min(kelly_f, max_fraction))

        return kelly_f


# ========================================
# Score-Based Position Plugin
# ========================================

class ScoreBasedPositionPlugin(BasePositionPlugin):
    """
    점수 기반 포지션 크기

    기존 전략: v41 Voting System
    설정 예시:
    {
        "type": "score_based",
        "min_score": 25,
        "score_to_fraction": {
            "25-40": 0.3,
            "40-60": 0.5,
            "60-100": 0.7
        }
    }
    """

    def calculate_position_size(
        self,
        signal,
        capital,
        config
    ) -> float:
        score = getattr(signal, 'score', None)

        if score is None:
            # score 없으면 기본값
            return config.get('default_fraction', 0.5)

        score_to_fraction = config.get('score_to_fraction', {
            "0-40": 0.3,
            "40-60": 0.5,
            "60-100": 0.7
        })

        # Score 범위 매칭
        for range_str, fraction in score_to_fraction.items():
            min_score, max_score = map(int, range_str.split('-'))
            if min_score <= score <= max_score:
                return fraction

        # 매칭 실패 시 기본값
        return config.get('default_fraction', 0.5)


# ========================================
# Confidence-Based Position Plugin
# ========================================

class ConfidenceBasedPositionPlugin(BasePositionPlugin):
    """
    신뢰도 기반 포지션 크기 (ML 전략용)

    설정 예시:
    {
        "type": "confidence_based",
        "min_confidence": 0.5,
        "max_fraction": 0.8,
        "min_fraction": 0.2
    }
    """

    def calculate_position_size(
        self,
        signal,
        capital,
        config
    ) -> float:
        confidence = getattr(signal, 'confidence', None)

        if confidence is None:
            return config.get('default_fraction', 0.5)

        min_confidence = config.get('min_confidence', 0.5)
        max_fraction = config.get('max_fraction', 0.8)
        min_fraction = config.get('min_fraction', 0.2)

        # 신뢰도가 최소 기준 이하면 진입 안 함
        if confidence < min_confidence:
            return 0.0

        # 선형 스케일링: confidence 0.5-1.0 → fraction 0.2-0.8
        fraction = min_fraction + (confidence - min_confidence) / (1.0 - min_confidence) * (max_fraction - min_fraction)

        return min(max(fraction, 0.0), 1.0)


# ========================================
# Tier-Based Position Plugin
# ========================================

class TierBasedPositionPlugin(BasePositionPlugin):
    """
    Tier 기반 포지션 크기 (v41 스타일)

    설정 예시:
    {
        "type": "tier_based",
        "tier_fractions": {
            "S": 0.8,
            "A": 0.6,
            "B": 0.4,
            "C": 0.2,
            "D": 0.0
        }
    }
    """

    def calculate_position_size(
        self,
        signal,
        capital,
        config
    ) -> float:
        metadata = getattr(signal, 'metadata', {})
        tier = metadata.get('tier', 'C')

        tier_fractions = config.get('tier_fractions', {
            "S": 0.8,
            "A": 0.6,
            "B": 0.4,
            "C": 0.2,
            "D": 0.0
        })

        return tier_fractions.get(tier, 0.5)


# ========================================
# 플러그인 레지스트리
# ========================================

def get_default_position_plugins():
    """기본 포지션 플러그인 세트 반환"""
    return {
        'fixed': FixedPositionPlugin(),
        'kelly': KellyPositionPlugin(),
        'score_based': ScoreBasedPositionPlugin(),
        'confidence_based': ConfidenceBasedPositionPlugin(),
        'tier_based': TierBasedPositionPlugin()
    }
