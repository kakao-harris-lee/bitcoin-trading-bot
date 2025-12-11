#!/usr/bin/env python3
"""
exit_manager_v2.py
적응형 청산 관리자 v2 - 시장 상태 기반 동적 청산

추세 강도에 따라 청산 규칙 자동 조정:
- 강한 추세 (ADX >= 30): 공격적 (Trailing 15%, 익절 50%)
- 중간 추세 (ADX 20-30): 중립적 (Trailing 10%, 익절 25%)
- 약한 추세 (ADX < 20): 보수적 (빠른 청산 8%)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class ExitManagerV2:
    """적응형 청산 관리자 v2"""

    def __init__(self):
        """초기화"""
        # 포지션 정보
        self.entry_price = 0.0
        self.entry_idx = 0
        self.entry_track = None  # 'trend_following' or 'mean_reversion'
        self.highest_price = 0.0  # 진입 후 최고가

    def on_entry(
        self,
        idx: int,
        price: float,
        track: str
    ):
        """
        진입 시 호출

        Args:
            idx: 진입 인덱스
            price: 진입 가격
            track: 진입 트랙 ('trend_following' or 'mean_reversion')
        """
        self.entry_price = price
        self.entry_idx = idx
        self.entry_track = track
        self.highest_price = price

    def get_exit_rules(self, market_state: Dict) -> Dict:
        """
        현재 시장 상태에 따른 청산 규칙 반환

        Args:
            market_state: 시장 상태 (DynamicMarketAnalyzer.analyze() 결과)

        Returns:
            {
                'method': 'trailing_stop' | 'quick_exit',
                'trailing_distance': float,
                'take_profit': float,
                'stop_loss': float,
                'max_hold_candles': int
            }
        """
        trend_strength = market_state['trend']['strength']

        # === 강한 추세 (ADX >= 25) - 공격적 ===
        if trend_strength >= 25:
            return {
                'method': 'trailing_stop',
                'trailing_distance': 0.20,  # 20% trailing (더 여유있게)
                'take_profit': 1.00,  # 100% 익절 (매우 느슨)
                'stop_loss': -0.12,  # -12% 손절
                'max_hold_candles': 999999  # 무제한
            }

        # === 중간 추세 (ADX 15-25) - 균형 ===
        elif trend_strength >= 15:
            return {
                'method': 'trailing_stop',
                'trailing_distance': 0.15,  # 15% trailing
                'take_profit': 0.50,  # 50% 익절
                'stop_loss': -0.08,  # -8% 손절
                'max_hold_candles': 999999  # 무제한
            }

        # === 약한 추세 (ADX < 15) - 보수적 ===
        else:
            return {
                'method': 'trailing_stop',
                'trailing_distance': 0.10,  # 10% trailing
                'take_profit': 0.20,  # 20% 익절
                'stop_loss': -0.05,  # -5% 손절
                'max_hold_candles': 200  # 여유있게
            }

    def check_exit(
        self,
        df: pd.DataFrame,
        i: int,
        market_state: Dict,
        signal_exit: Dict
    ) -> Dict:
        """
        매도 여부 판단

        Args:
            df: 데이터프레임
            i: 현재 인덱스
            market_state: 시장 상태
            signal_exit: 신호 기반 매도 (HybridSignalGenerator.generate_exit_signal)

        Returns:
            {
                'should_exit': bool,
                'reason': str,
                'fraction': float  # 청산 비율 (1.0 = 전량)
            }
        """
        if self.entry_price == 0.0:
            return {'should_exit': False, 'reason': 'no_position', 'fraction': 0.0}

        current_price = df.iloc[i]['close']

        # 최고가 갱신
        if current_price > self.highest_price:
            self.highest_price = current_price

        # 현재 수익률
        pnl_ratio = (current_price - self.entry_price) / self.entry_price

        # 현재 청산 규칙
        rules = self.get_exit_rules(market_state)

        # === 1. Stop Loss (최우선) ===
        if pnl_ratio <= rules['stop_loss']:
            return {
                'should_exit': True,
                'reason': f"stop_loss ({pnl_ratio:.2%} <= {rules['stop_loss']:.2%})",
                'fraction': 1.0
            }

        # === 2. Take Profit (고정 익절) ===
        if pnl_ratio >= rules['take_profit']:
            return {
                'should_exit': True,
                'reason': f"take_profit ({pnl_ratio:.2%} >= {rules['take_profit']:.2%})",
                'fraction': 1.0
            }

        # === 3. Trailing Stop ===
        drop_from_high = (self.highest_price - current_price) / self.highest_price

        if drop_from_high >= rules['trailing_distance']:
            return {
                'should_exit': True,
                'reason': f"trailing_stop (high={self.highest_price:.0f}, drop={drop_from_high:.2%})",
                'fraction': 1.0
            }

        # === 4. 최대 보유 기간 (약한 추세만) ===
        holding_candles = i - self.entry_idx
        max_candles = rules['max_hold_candles']

        if holding_candles >= max_candles:
            return {
                'should_exit': True,
                'reason': f"max_holding ({holding_candles} >= {max_candles} candles, {pnl_ratio:.2%})",
                'fraction': 1.0
            }

        # === 5. 신호 기반 매도 (추세 전환 등) ===
        if signal_exit['should_exit']:
            # 수익 중일 때만 신호 매도 (손실 중이면 규칙 우선)
            if pnl_ratio > 0.02:  # 2% 이상 수익
                return {
                    'should_exit': True,
                    'reason': f"signal_exit ({signal_exit['reason']}, {pnl_ratio:.2%})",
                    'fraction': 1.0
                }

        # === 6. 추세 방향 전환 (강제 청산) ===
        # 추세 추종 진입 → 추세가 down으로 전환
        if self.entry_track == 'trend_following':
            if market_state['trend']['direction'] == 'down' and pnl_ratio > 0:
                return {
                    'should_exit': True,
                    'reason': f"trend_reversal (up→down, {pnl_ratio:.2%})",
                    'fraction': 1.0
                }

        # 보유 유지
        return {
            'should_exit': False,
            'reason': f'holding ({pnl_ratio:.2%}, high={self.highest_price:.0f}, method={rules["method"]})',
            'fraction': 0.0
        }

    def on_exit(self):
        """청산 시 호출 (상태 초기화)"""
        self.entry_price = 0.0
        self.entry_idx = 0
        self.entry_track = None
        self.highest_price = 0.0

    def get_position_info(self) -> Dict:
        """
        현재 포지션 정보 반환

        Returns:
            {
                'has_position': bool,
                'entry_price': float,
                'entry_track': str,
                'highest_price': float
            }
        """
        return {
            'has_position': (self.entry_price > 0.0),
            'entry_price': self.entry_price,
            'entry_track': self.entry_track,
            'highest_price': self.highest_price
        }
