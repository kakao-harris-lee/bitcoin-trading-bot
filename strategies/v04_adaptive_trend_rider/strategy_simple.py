#!/usr/bin/env python3
"""
strategy_simple.py
v04: 초단순 추세 추종 전략

핵심 철학: "추세는 친구다. 단순하게 따라간다."

진입: EMA12 > EMA26 (골든크로스 또는 이미 골든 상태)
청산: Trailing Stop 20% OR EMA 데드크로스 OR Stop Loss 15%
포지션: 80% 고정
"""

import pandas as pd
import numpy as np
from typing import Dict


class SimpleTrendFollowing:
    """초단순 추세 추종 전략"""

    def __init__(self, config: dict):
        """
        Args:
            config: 설정 딕셔너리
        """
        self.position_fraction = config.get('position_fraction', 0.80)
        self.trailing_stop_pct = config.get('trailing_stop_pct', 0.20)
        self.stop_loss_pct = config.get('stop_loss_pct', 0.15)

        # 포지션 상태
        self.position = None  # None or 'long'
        self.entry_price = 0.0
        self.entry_idx = 0
        self.highest_price = 0.0

    def generate_signal(
        self,
        df: pd.DataFrame,
        i: int,
        current_capital: float
    ) -> Dict:
        """
        매 캔들마다 호출되는 신호 생성

        Args:
            df: 데이터프레임 (EMA 포함)
            i: 현재 인덱스
            current_capital: 현재 자본

        Returns:
            {'action': 'buy'|'sell'|'hold', 'fraction': float, 'reason': str}
        """
        # 최소 데이터 확보
        if i < 26:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        price = current['close']
        ema12 = current.get('ema_12', price)
        ema26 = current.get('ema_26', price)
        prev_ema12 = prev.get('ema_12', price)
        prev_ema26 = prev.get('ema_26', price)

        # NaN 처리
        if pd.isna(ema12) or pd.isna(ema26):
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'missing_ema'}

        # === 포지션 없을 때: 진입 신호 ===
        if self.position is None:
            # 골든크로스 감지
            golden_cross = (prev_ema12 <= prev_ema26) and (ema12 > ema26)

            # 이미 골든크로스 상태 (추세 합류)
            already_golden = (ema12 > ema26)

            if golden_cross:
                return {
                    'action': 'buy',
                    'fraction': self.position_fraction,
                    'reason': f'golden_cross EMA12({ema12:.0f}) > EMA26({ema26:.0f})'
                }
            elif already_golden:
                return {
                    'action': 'buy',
                    'fraction': self.position_fraction,
                    'reason': f'trend_following EMA12({ema12:.0f}) > EMA26({ema26:.0f})'
                }

        # === 포지션 있을 때: 청산 신호 ===
        else:
            # 최고가 갱신
            if price > self.highest_price:
                self.highest_price = price

            # 수익률
            pnl_ratio = (price - self.entry_price) / self.entry_price

            # 최고가 대비 하락률
            drop_from_high = (self.highest_price - price) / self.highest_price

            # === 청산 조건 1: 데드크로스 ===
            dead_cross = (prev_ema12 >= prev_ema26) and (ema12 < ema26)

            if dead_cross:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'dead_cross EMA12({ema12:.0f}) < EMA26({ema26:.0f}), PnL={pnl_ratio:.2%}'
                }

            # === 청산 조건 2: Trailing Stop ===
            if drop_from_high >= self.trailing_stop_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'trailing_stop high={self.highest_price:.0f}, drop={drop_from_high:.2%}, PnL={pnl_ratio:.2%}'
                }

            # === 청산 조건 3: Stop Loss ===
            if pnl_ratio <= -self.stop_loss_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'stop_loss PnL={pnl_ratio:.2%} <= -{self.stop_loss_pct:.2%}'
                }

        # 홀드
        return {
            'action': 'hold',
            'fraction': 0.0,
            'reason': f'holding PnL={pnl_ratio:.2%}, high={self.highest_price:.0f}' if self.position else 'no_signal'
        }

    def on_buy(self, idx: int, price: float):
        """매수 체결 시 호출"""
        self.position = 'long'
        self.entry_price = price
        self.entry_idx = idx
        self.highest_price = price

    def on_sell(self):
        """매도 체결 시 호출"""
        self.position = None
        self.entry_price = 0.0
        self.entry_idx = 0
        self.highest_price = 0.0


def simple_strategy_wrapper(df, i, params):
    """
    Backtester 호환 래퍼 함수

    Args:
        df: 데이터프레임
        i: 현재 인덱스
        params: {'strategy_instance': SimpleTrendFollowing, 'backtester': Backtester}

    Returns:
        {'action': 'buy'|'sell'|'hold', 'fraction': float}
    """
    strategy = params['strategy_instance']
    backtester = params['backtester']

    # 현재 자본
    current_capital = backtester.cash + backtester.position_value

    # 신호 생성
    signal = strategy.generate_signal(df, i, current_capital)

    # 상태 업데이트
    if signal['action'] == 'buy':
        strategy.on_buy(i, df.iloc[i]['close'])
    elif signal['action'] == 'sell':
        strategy.on_sell()

    return signal
