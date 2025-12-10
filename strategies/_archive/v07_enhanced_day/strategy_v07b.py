#!/usr/bin/env python3
"""
v07b Enhanced DAY Strategy with Partial Profit Taking

진입:
  - EMA Golden Cross OR MACD Golden Cross

청산:
  - 분할 익절: +10% (1/3), +20% (1/2), +30% (전량)
  - Trailing Stop: 15%
  - Stop Loss: 8%
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from datetime import datetime


# Global state for standalone function
class V07bState:
    def __init__(self):
        self.in_position = False
        self.entry_price = None
        self.highest_price = None
        self.current_position_fraction = 0.0  # 현재 보유 비율 (0.0 ~ 1.0)
        self.profit_level_reached = 0  # 도달한 익절 레벨 (0, 1, 2, 3)


_state = V07bState()


def v07b_strategy(df, i, params):
    """
    v07b 전략 함수

    Args:
        df: DataFrame with indicators
        i: current index
        params: strategy parameters

    Returns:
        dict: {'action': 'buy'/'sell'/'hold', 'fraction': float, 'reason': str}
    """
    global _state

    # Params
    trailing_stop_pct = params.get('trailing_stop_pct', 0.15)
    stop_loss_pct = params.get('stop_loss_pct', 0.08)
    position_fraction = params.get('position_fraction', 0.95)
    profit_targets = params.get('profit_targets', [
        {'threshold': 0.10, 'fraction': 0.33},
        {'threshold': 0.20, 'fraction': 0.50},
        {'threshold': 0.30, 'fraction': 1.00}
    ])

    # Not enough data
    if i < 27:
        return {'action': 'hold'}

    row = df.iloc[i]
    prev_row = df.iloc[i - 1]
    current_price = row['close']

    # === EXIT CHECK ===
    if _state.in_position:
        # Update highest price
        if current_price > _state.highest_price:
            _state.highest_price = current_price

        # Calculate profit
        profit_pct = ((current_price - _state.entry_price) / _state.entry_price)

        # 1. Partial Profit Taking
        for level, target in enumerate(profit_targets):
            if level <= _state.profit_level_reached:
                continue  # Already taken

            if profit_pct >= target['threshold']:
                sell_fraction = target['fraction']
                _state.profit_level_reached = level + 1
                _state.current_position_fraction *= (1 - sell_fraction)

                # 전량 청산이면 상태 초기화
                if _state.current_position_fraction <= 0.01:
                    _state.in_position = False
                    _state.entry_price = None
                    _state.highest_price = None
                    _state.current_position_fraction = 0.0
                    _state.profit_level_reached = 0

                return {
                    'action': 'sell',
                    'fraction': sell_fraction,
                    'reason': f'PARTIAL_PROFIT_{int(target["threshold"]*100)}pct'
                }

        # 2. Trailing Stop
        trailing_stop_price = _state.highest_price * (1 - trailing_stop_pct)
        if current_price <= trailing_stop_price:
            _state.in_position = False
            _state.entry_price = None
            _state.highest_price = None
            _state.current_position_fraction = 0.0
            _state.profit_level_reached = 0
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'TRAILING_STOP'}

        # 3. Stop Loss
        stop_loss_price = _state.entry_price * (1 - stop_loss_pct)
        if current_price <= stop_loss_price:
            _state.in_position = False
            _state.entry_price = None
            _state.highest_price = None
            _state.current_position_fraction = 0.0
            _state.profit_level_reached = 0
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'STOP_LOSS'}

    # === ENTRY CHECK ===
    if not _state.in_position:
        # EMA Golden Cross
        ema_golden = (
            prev_row['ema12'] <= prev_row['ema26'] and
            row['ema12'] > row['ema26']
        )

        # MACD Golden Cross
        macd_golden = (
            prev_row['macd'] <= prev_row['macd_signal'] and
            row['macd'] > row['macd_signal']
        )

        if ema_golden or macd_golden:
            _state.in_position = True
            _state.entry_price = current_price
            _state.highest_price = current_price
            _state.current_position_fraction = 1.0
            _state.profit_level_reached = 0

            reason = []
            if ema_golden:
                reason.append('EMA_GOLDEN')
            if macd_golden:
                reason.append('MACD_GOLDEN')

            return {
                'action': 'buy',
                'fraction': position_fraction,
                'reason': '+'.join(reason)
            }

    return {'action': 'hold'}


def reset_state():
    """상태 초기화"""
    global _state
    _state = V07bState()
