#!/usr/bin/env python3
"""
exit_manager.py
적응형 청산 관리자

핵심 로직:
1. Trailing Stop (시장 상태별 거리 조정)
2. Take Profit (시장 상태별 목표 조정)
3. Stop Loss (시장 상태별 임계값 조정)
4. 최대 보유 기간 (강제 청산)
5. Exit 신호 (RSI, MACD 등)
"""

import pandas as pd
import numpy as np
from typing import Dict, Optional


class ExitManager:
    """적응형 청산 관리자"""

    def __init__(self):
        """초기화"""
        # 포지션 정보 (진입 시 설정됨)
        self.entry_price = 0.0
        self.entry_idx = 0
        self.highest_price = 0.0  # 진입 후 최고가 (Trailing Stop용)

        # 현재 시장 상태별 파라미터 (regime_classifier에서 받음)
        self.current_regime_params = None

    def on_entry(self, idx: int, price: float, regime_params: Dict):
        """
        진입 시 호출

        Args:
            idx: 진입 인덱스
            price: 진입 가격
            regime_params: 시장 상태별 파라미터
                {
                    'take_profit': float,
                    'trailing_stop_pct': float,
                    'stop_loss': float,
                    'max_holding_days': int
                }
        """
        self.entry_price = price
        self.entry_idx = idx
        self.highest_price = price
        self.current_regime_params = regime_params

    def check_exit(
        self,
        df: pd.DataFrame,
        i: int,
        regime_params: Dict,
        exit_signals: Dict
    ) -> Dict:
        """
        매도 여부 판단

        Args:
            df: 거래 타임프레임 데이터
            i: 현재 인덱스
            regime_params: 현재 시장 상태별 파라미터
            exit_signals: 매도 신호 (signal_ensemble.generate_exit_signals)

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

        # === 1. Stop Loss (고정 손절) ===
        if pnl_ratio <= regime_params['stop_loss']:
            return {
                'should_exit': True,
                'reason': f"stop_loss ({pnl_ratio:.2%} <= {regime_params['stop_loss']:.2%})",
                'fraction': 1.0
            }

        # === 2. Take Profit (고정 익절) ===
        if pnl_ratio >= regime_params['take_profit']:
            return {
                'should_exit': True,
                'reason': f"take_profit ({pnl_ratio:.2%} >= {regime_params['take_profit']:.2%})",
                'fraction': 1.0
            }

        # === 3. Trailing Stop (추적 손절) ===
        # 최고가 대비 현재가 하락률
        drop_from_high = (self.highest_price - current_price) / self.highest_price

        if drop_from_high >= regime_params['trailing_stop_pct']:
            return {
                'should_exit': True,
                'reason': f"trailing_stop (high={self.highest_price:.0f}, drop={drop_from_high:.2%})",
                'fraction': 1.0
            }

        # === 4. 최대 보유 기간 (타임프레임별 캔들 수) ===
        holding_candles = i - self.entry_idx
        max_candles = self._get_max_holding_candles(
            df,
            regime_params['max_holding_days']
        )

        if holding_candles >= max_candles:
            return {
                'should_exit': True,
                'reason': f"max_holding ({holding_candles} >= {max_candles} candles, {pnl_ratio:.2%})",
                'fraction': 1.0
            }

        # === 5. Exit 신호 (2개 이상) ===
        if exit_signals['exit_vote_count'] >= 2:
            return {
                'should_exit': True,
                'reason': f"exit_signals ({exit_signals['exit_vote_count']}/3, {pnl_ratio:.2%})",
                'fraction': 1.0
            }

        # 보유 유지
        return {
            'should_exit': False,
            'reason': f'holding ({pnl_ratio:.2%}, high={self.highest_price:.0f})',
            'fraction': 0.0
        }

    def _get_max_holding_candles(
        self,
        df: pd.DataFrame,
        max_holding_days: int
    ) -> int:
        """
        타임프레임별 최대 보유 캔들 수 계산

        Args:
            df: 데이터프레임 (타임프레임 정보 포함)
            max_holding_days: 최대 보유 일수

        Returns:
            int: 최대 보유 캔들 수
        """
        # 타임프레임 추정 (연속된 두 캔들의 시간 차이)
        if len(df) < 2:
            return 100  # 기본값

        t1 = pd.to_datetime(df.iloc[0]['timestamp'])
        t2 = pd.to_datetime(df.iloc[1]['timestamp'])
        candle_minutes = (t2 - t1).total_seconds() / 60

        # 하루 캔들 수
        candles_per_day = 1440 / candle_minutes  # 1440분 = 24시간

        # 최대 보유 캔들 수
        max_candles = int(candles_per_day * max_holding_days)

        return max_candles

    def on_exit(self):
        """청산 시 호출 (상태 초기화)"""
        self.entry_price = 0.0
        self.entry_idx = 0
        self.highest_price = 0.0
        self.current_regime_params = None

    def get_position_info(self) -> Dict:
        """
        현재 포지션 정보 반환

        Returns:
            {
                'has_position': bool,
                'entry_price': float,
                'highest_price': float,
                'holding_candles': int (현재 인덱스 필요)
            }
        """
        return {
            'has_position': (self.entry_price > 0.0),
            'entry_price': self.entry_price,
            'highest_price': self.highest_price
        }
