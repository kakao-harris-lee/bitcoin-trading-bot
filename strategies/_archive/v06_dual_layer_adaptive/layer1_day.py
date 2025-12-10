#!/usr/bin/env python3
"""
layer1_day.py
v06 Layer 1: DAY 전략 (v05 최적 파라미터 사용)

역할:
- 주요 트렌드 포착 (연 4회 거래)
- 기본 수익 확보 (293.38%)
- Layer 2 활성화 신호 제공
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict, Optional


class DayStrategy:
    """v05 검증된 DAY 전략"""

    def __init__(self, config: dict):
        """
        Args:
            config: layer1_day 설정
        """
        params = config.get('params', {})
        self.position_fraction = params.get('position_fraction', 0.98)
        self.trailing_stop_pct = params.get('trailing_stop_pct', 0.21)
        self.stop_loss_pct = params.get('stop_loss_pct', 0.10)

        # 포지션 상태
        self.position = None  # None or 'long'
        self.entry_price = 0.0
        self.entry_time = None
        self.highest_price = 0.0
        self.current_price = 0.0

    def generate_signal(
        self,
        df: pd.DataFrame,
        i: int,
        current_capital: float
    ) -> Dict:
        """
        DAY 신호 생성

        Args:
            df: DAY 타임프레임 데이터
            i: 현재 인덱스
            current_capital: 현재 자본

        Returns:
            {'action': 'buy'|'sell'|'hold', 'fraction': float, 'reason': str}
        """
        if i < 26:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        price = current['close']
        self.current_price = price

        ema12 = current.get('ema_12', price)
        ema26 = current.get('ema_26', price)
        prev_ema12 = prev.get('ema_12', price)
        prev_ema26 = prev.get('ema_26', price)

        if pd.isna(ema12) or pd.isna(ema26):
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'missing_ema'}

        # === 포지션 없을 때: 진입 ===
        if self.position is None:
            golden_cross = (prev_ema12 <= prev_ema26) and (ema12 > ema26)
            already_golden = (ema12 > ema26)

            if golden_cross or already_golden:
                return {
                    'action': 'buy',
                    'fraction': self.position_fraction,
                    'reason': f'golden_cross EMA12({ema12:.0f}) > EMA26({ema26:.0f})'
                }

        # === 포지션 있을 때: 청산 ===
        else:
            # 최고가 갱신
            if price > self.highest_price:
                self.highest_price = price

            # 수익률
            pnl_ratio = (price - self.entry_price) / self.entry_price
            drop_from_high = (self.highest_price - price) / self.highest_price

            # 데드크로스
            dead_cross = (prev_ema12 >= prev_ema26) and (ema12 < ema26)
            if dead_cross:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'dead_cross EMA12({ema12:.0f}) < EMA26({ema26:.0f}), PnL={pnl_ratio:.2%}'
                }

            # Trailing Stop
            if drop_from_high >= self.trailing_stop_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'trailing_stop drop={drop_from_high:.2%}, PnL={pnl_ratio:.2%}'
                }

            # Stop Loss
            if pnl_ratio <= -self.stop_loss_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'stop_loss PnL={pnl_ratio:.2%}'
                }

        return {'action': 'hold', 'fraction': 0.0, 'reason': 'no_signal'}

    def on_buy(self, timestamp, price: float):
        """매수 체결"""
        self.position = 'long'
        self.entry_price = price
        self.entry_time = timestamp
        self.highest_price = price
        self.current_price = price

    def on_sell(self):
        """매도 체결"""
        self.position = None
        self.entry_price = 0.0
        self.entry_time = None
        self.highest_price = 0.0

    def get_unrealized_profit(self) -> float:
        """미실현 이익 계산"""
        if self.position is None or self.entry_price == 0:
            return 0.0

        profit_pct = (self.current_price - self.entry_price) / self.entry_price
        return profit_pct

    def is_active(self) -> bool:
        """포지션 활성 여부"""
        return self.position is not None

    def meets_layer2_activation(self, threshold: float = 0.15) -> bool:
        """Layer 2 활성화 조건 충족 여부"""
        if not self.is_active():
            return False

        profit = self.get_unrealized_profit()
        return profit >= threshold
