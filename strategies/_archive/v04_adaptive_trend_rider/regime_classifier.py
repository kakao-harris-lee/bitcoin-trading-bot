#!/usr/bin/env python3
"""
regime_classifier.py
시장 상태 분류기 - 3단계 (Strong Bull / Moderate Bull / Neutral-Bear)

핵심 로직:
- ADX로 추세 강도 측정
- Day 타임프레임 수익률로 방향 판단
- 동적 임계값 조정
"""

import pandas as pd
import numpy as np
from typing import Dict, Literal

MarketRegime = Literal['strong_bull', 'moderate_bull', 'neutral_bear']


class RegimeClassifier:
    """시장 상태 분류기"""

    def __init__(
        self,
        strong_bull_adx: float = 30.0,
        moderate_bull_adx: float = 20.0,
        bull_return_threshold: float = 0.10,
        recent_period: int = 20
    ):
        """
        Args:
            strong_bull_adx: 강한 상승장 ADX 임계값 (기본: 30)
            moderate_bull_adx: 중간 상승장 ADX 임계값 (기본: 20)
            bull_return_threshold: 상승장 수익률 임계값 (기본: 10%)
            recent_period: 최근 수익률 계산 기간 (기본: 20 캔들)
        """
        self.strong_bull_adx = strong_bull_adx
        self.moderate_bull_adx = moderate_bull_adx
        self.bull_return_threshold = bull_return_threshold
        self.recent_period = recent_period

    def classify(self, df_day: pd.DataFrame, i_day: int) -> Dict:
        """
        현재 시장 상태 분류

        Args:
            df_day: Day 타임프레임 데이터프레임 (지표 포함)
            i_day: 현재 Day 인덱스

        Returns:
            {
                'regime': 'strong_bull' | 'moderate_bull' | 'neutral_bear',
                'adx': float,
                'recent_return': float,
                'ema_trend': 'up' | 'down' | 'sideways'
            }
        """
        # 최소 데이터 확보
        if i_day < self.recent_period:
            return {
                'regime': 'neutral_bear',
                'adx': 0.0,
                'recent_return': 0.0,
                'ema_trend': 'sideways',
                'reason': 'insufficient_data'
            }

        # 현재 캔들 데이터
        current = df_day.iloc[i_day]
        adx = current['adx']

        # 최근 N일 수익률
        start_price = df_day.iloc[i_day - self.recent_period]['close']
        current_price = current['close']
        recent_return = (current_price - start_price) / start_price

        # EMA 추세 판단 (20일, 50일)
        ema20 = current['ema_20']
        ema50 = current['ema_50']
        price = current['close']

        if price > ema20 > ema50:
            ema_trend = 'up'
        elif price < ema20 < ema50:
            ema_trend = 'down'
        else:
            ema_trend = 'sideways'

        # === 시장 상태 분류 ===

        # 1. Strong Bull: 강한 추세 + 높은 수익률 + 상승 추세
        if (adx >= self.strong_bull_adx and
            recent_return >= self.bull_return_threshold and
            ema_trend == 'up'):
            regime = 'strong_bull'
            reason = f"ADX({adx:.1f})≥{self.strong_bull_adx}, Return({recent_return:.1%})≥{self.bull_return_threshold:.1%}, EMA↑"

        # 2. Moderate Bull: 중간 추세 + 양수 수익률 + 상승 추세
        elif (adx >= self.moderate_bull_adx and
              recent_return >= 0.03 and  # 최소 3% 상승
              ema_trend == 'up'):
            regime = 'moderate_bull'
            reason = f"ADX({adx:.1f})≥{self.moderate_bull_adx}, Return({recent_return:.1%})≥3%, EMA↑"

        # 3. Neutral-Bear: 나머지 모든 경우
        else:
            regime = 'neutral_bear'
            reason = f"ADX({adx:.1f}), Return({recent_return:.1%}), EMA={ema_trend}"

        return {
            'regime': regime,
            'adx': adx,
            'recent_return': recent_return,
            'ema_trend': ema_trend,
            'reason': reason
        }

    def get_regime_params(self, regime: MarketRegime) -> Dict:
        """
        시장 상태별 전략 파라미터 반환

        Returns:
            {
                'take_profit': float,        # 익절 목표
                'trailing_stop_pct': float,  # 트레일링 스탑 거리
                'stop_loss': float,          # 손절 임계값
                'max_holding_days': int,     # 최대 보유 기간
                'pyramid_enabled': bool      # 피라미딩 활성화
            }
        """
        if regime == 'strong_bull':
            return {
                'take_profit': 0.50,         # 50% 익절 (큰 수익 노림)
                'trailing_stop_pct': 0.15,   # 15% 트레일링 스탑
                'stop_loss': -0.10,          # -10% 손절 (여유)
                'max_holding_days': 60,      # 60일 장기 보유
                'pyramid_enabled': True,     # 피라미딩 활성화
                'entry_signals_needed': 3    # 4개 중 3개 신호 (적극)
            }

        elif regime == 'moderate_bull':
            return {
                'take_profit': 0.25,         # 25% 익절 (중간)
                'trailing_stop_pct': 0.10,   # 10% 트레일링 스탑
                'stop_loss': -0.05,          # -5% 손절
                'max_holding_days': 30,      # 30일 보유
                'pyramid_enabled': False,    # 피라미딩 비활성화
                'entry_signals_needed': 3    # 4개 중 3개 신호
            }

        else:  # neutral_bear
            return {
                'take_profit': 0.08,         # 8% 익절 (빠른 청산)
                'trailing_stop_pct': 0.05,   # 5% 트레일링 스탑
                'stop_loss': -0.03,          # -3% 손절 (빠른 손절)
                'max_holding_days': 14,      # 14일 단기 보유
                'pyramid_enabled': False,    # 피라미딩 비활성화
                'entry_signals_needed': 4    # 4개 전부 신호 (보수적)
            }
