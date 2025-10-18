#!/usr/bin/env python3
"""
position_sizer.py
변동성 기반 포지션 사이징

핵심 로직:
1. ATR (Average True Range) 기반 리스크 계산
2. Kelly Criterion 조합
3. 시장 상태별 조정 (Strong Bull → 공격적, Neutral-Bear → 보수적)
"""

import pandas as pd
import numpy as np
from typing import Dict


class PositionSizer:
    """변동성 기반 포지션 사이징"""

    def __init__(
        self,
        base_kelly_fraction: float = 0.25,
        min_fraction: float = 0.1,
        max_fraction: float = 0.5,
        risk_per_trade: float = 0.02  # 거래당 최대 리스크 (자본의 2%)
    ):
        """
        Args:
            base_kelly_fraction: 기본 Kelly 비율 (기본: 25%)
            min_fraction: 최소 투자 비율 (기본: 10%)
            max_fraction: 최대 투자 비율 (기본: 50%)
            risk_per_trade: 거래당 최대 리스크 (기본: 2%)
        """
        self.base_kelly_fraction = base_kelly_fraction
        self.min_fraction = min_fraction
        self.max_fraction = max_fraction
        self.risk_per_trade = risk_per_trade

    def calculate_position_size(
        self,
        df: pd.DataFrame,
        i: int,
        regime: str,
        current_capital: float,
        stop_loss_pct: float
    ) -> Dict:
        """
        포지션 크기 계산

        Args:
            df: 거래 타임프레임 데이터
            i: 현재 인덱스
            regime: 시장 상태 ('strong_bull', 'moderate_bull', 'neutral_bear')
            current_capital: 현재 자본
            stop_loss_pct: 손절 비율 (예: -0.03 = -3%)

        Returns:
            {
                'fraction': float,  # 투자 비율 (0~1)
                'position_size': float,  # 투자 금액 (원)
                'shares': float,  # 매수 수량 (BTC)
                'reason': str
            }
        """
        # ATR 기반 변동성 계산
        atr = df.iloc[i]['atr']
        price = df.iloc[i]['close']

        # ATR 비율 (가격 대비 변동성)
        atr_pct = atr / price

        # === 1. ATR 기반 리스크 조정 ===
        # 변동성이 높을수록 포지션 축소
        # ATR 2% → 100% 비율, ATR 4% → 50% 비율
        volatility_multiplier = min(0.02 / atr_pct, 1.0) if atr_pct > 0 else 1.0

        # === 2. Kelly Criterion 조정 ===
        # 시장 상태별 Kelly 배율
        regime_multipliers = {
            'strong_bull': 1.5,      # 공격적 (150%)
            'moderate_bull': 1.0,    # 기본 (100%)
            'neutral_bear': 0.5      # 보수적 (50%)
        }
        kelly_multiplier = regime_multipliers.get(regime, 1.0)

        # 조정된 Kelly 비율
        adjusted_kelly = self.base_kelly_fraction * kelly_multiplier * volatility_multiplier

        # === 3. 리스크 기반 포지션 크기 ===
        # 거래당 최대 손실 금액
        max_risk_amount = current_capital * self.risk_per_trade

        # 손절 비율 기반 최대 투자 금액
        # 예: 자본 1000만원, 리스크 2%, 손절 -3%
        # → 최대 손실 20만원 / 3% = 최대 투자 666만원 (66.6%)
        risk_based_position = max_risk_amount / abs(stop_loss_pct)

        # 비율로 변환
        risk_based_fraction = min(risk_based_position / current_capital, 1.0)

        # === 4. 최종 포지션 크기 (Kelly와 Risk 중 작은 값) ===
        final_fraction = min(adjusted_kelly, risk_based_fraction)

        # 최소/최대 제한
        final_fraction = max(self.min_fraction, min(final_fraction, self.max_fraction))

        # 투자 금액 및 수량
        position_size = current_capital * final_fraction
        shares = position_size / price

        reason = (
            f"Kelly({adjusted_kelly:.2%}) × Vol({volatility_multiplier:.2f}) "
            f"vs Risk({risk_based_fraction:.2%}) → {final_fraction:.2%}"
        )

        return {
            'fraction': final_fraction,
            'position_size': position_size,
            'shares': shares,
            'reason': reason
        }

    def calculate_pyramid_size(
        self,
        df: pd.DataFrame,
        i: int,
        current_capital: float,
        existing_position_size: float,
        profit_ratio: float
    ) -> Dict:
        """
        피라미딩 (추가 매수) 포지션 크기 계산

        Args:
            df: 거래 타임프레임 데이터
            i: 현재 인덱스
            current_capital: 현재 자본
            existing_position_size: 기존 포지션 크기 (원)
            profit_ratio: 현재 수익률

        Returns:
            {
                'should_pyramid': bool,
                'fraction': float,
                'position_size': float,
                'reason': str
            }
        """
        # === 피라미딩 조건 ===
        # 1. 수익률 >= 10%
        # 2. 기존 포지션의 50% 이하만 추가
        # 3. 최대 1회만 추가

        if profit_ratio < 0.10:
            return {
                'should_pyramid': False,
                'fraction': 0.0,
                'position_size': 0.0,
                'reason': f'profit({profit_ratio:.2%}) < 10%'
            }

        # 추가 포지션 크기: 기존의 50%
        additional_size = existing_position_size * 0.5

        # 자본 제한 확인
        available_capital = current_capital - existing_position_size
        if additional_size > available_capital:
            additional_size = available_capital * 0.5  # 여유 자본의 50%만

        if additional_size < 10000:  # 최소 주문 금액
            return {
                'should_pyramid': False,
                'fraction': 0.0,
                'position_size': 0.0,
                'reason': 'insufficient_capital'
            }

        fraction = additional_size / current_capital
        price = df.iloc[i]['close']
        shares = additional_size / price

        return {
            'should_pyramid': True,
            'fraction': fraction,
            'position_size': additional_size,
            'shares': shares,
            'reason': f'pyramid at {profit_ratio:.2%} profit'
        }
