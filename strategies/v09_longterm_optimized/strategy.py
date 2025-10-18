#!/usr/bin/env python3
"""
v07 Enhanced DAY Strategy with MACD Entry

진입 조건:
  - Condition A: EMA(12) Golden Cross over EMA(26)
  - Condition B: MACD Golden Cross (MACD > Signal)
  - Either A or B triggers entry

청산 조건:
  - Trailing Stop: 21%
  - Stop Loss: 10%
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from datetime import datetime
from core.market_analyzer import MarketAnalyzer


class V07Strategy:
    """v07 Enhanced DAY Strategy"""

    def __init__(self, config):
        """초기화"""
        self.config = config

        # Indicators
        self.ema_fast = config['indicators']['ema_fast']
        self.ema_slow = config['indicators']['ema_slow']
        self.macd_fast = config['indicators']['macd_fast']
        self.macd_slow = config['indicators']['macd_slow']
        self.macd_signal = config['indicators']['macd_signal']

        # Entry
        self.use_ema_golden = config['entry']['use_ema_golden_cross']
        self.use_macd_golden = config['entry']['use_macd_golden_cross']
        self.allow_multiple = config['entry']['allow_multiple_positions']

        # Exit
        self.trailing_stop_pct = config['exit']['trailing_stop_pct']
        self.stop_loss_pct = config['exit']['stop_loss_pct']

        # Position
        self.position_fraction = config['position']['position_fraction']

        # State
        self.in_position = False
        self.entry_price = None
        self.highest_price = None

    def add_indicators(self, df):
        """기술 지표 추가"""
        # EMA
        df['ema12'] = df['close'].ewm(span=self.ema_fast, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=self.ema_slow, adjust=False).mean()
        df['prev_ema12'] = df['ema12'].shift(1)
        df['prev_ema26'] = df['ema26'].shift(1)

        # MACD
        df = MarketAnalyzer.add_indicators(df, indicators=['macd'])
        df['prev_macd'] = df['macd'].shift(1)
        df['prev_macd_signal'] = df['macd_signal'].shift(1)

        return df

    def check_entry_signals(self, row, prev_row):
        """진입 신호 확인"""
        signals = []

        # EMA Golden Cross
        if self.use_ema_golden:
            ema_golden = (
                prev_row['ema12'] <= prev_row['ema26'] and
                row['ema12'] > row['ema26']
            )
            if ema_golden:
                signals.append('EMA_GOLDEN')

        # MACD Golden Cross
        if self.use_macd_golden:
            macd_golden = (
                prev_row['macd'] <= prev_row['macd_signal'] and
                row['macd'] > row['macd_signal']
            )
            if macd_golden:
                signals.append('MACD_GOLDEN')

        return signals

    def check_exit_signals(self, row):
        """청산 신호 확인"""
        if not self.in_position:
            return None, None

        current_price = row['close']

        # Update highest price
        if current_price > self.highest_price:
            self.highest_price = current_price

        # Trailing Stop
        trailing_stop_price = self.highest_price * (1 - self.trailing_stop_pct)
        if current_price <= trailing_stop_price:
            return 'TRAILING_STOP', trailing_stop_price

        # Stop Loss
        stop_loss_price = self.entry_price * (1 - self.stop_loss_pct)
        if current_price <= stop_loss_price:
            return 'STOP_LOSS', stop_loss_price

        return None, None

    def decide(self, df, i):
        """
        전략 결정 함수

        Args:
            df: DataFrame with indicators
            i: current index

        Returns:
            dict: {'action': 'buy'/'sell'/'hold', 'fraction': 0.0~1.0, 'reason': str}
        """
        if i < max(self.ema_slow, self.macd_slow) + 1:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}

        row = df.iloc[i]
        prev_row = df.iloc[i - 1]

        # Check exit first
        if self.in_position:
            exit_reason, exit_price = self.check_exit_signals(row)
            if exit_reason:
                self.in_position = False
                self.entry_price = None
                self.highest_price = None
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': exit_reason,
                    'exit_price': exit_price
                }

        # Check entry
        if not self.in_position or self.allow_multiple:
            entry_signals = self.check_entry_signals(row, prev_row)

            if entry_signals:
                self.in_position = True
                self.entry_price = row['close']
                self.highest_price = row['close']

                return {
                    'action': 'buy',
                    'fraction': self.position_fraction,
                    'reason': '+'.join(entry_signals),
                    'entry_price': row['close']
                }

        return {'action': 'hold', 'fraction': 0.0, 'reason': 'no_signal'}

    def reset_state(self):
        """상태 초기화 (백테스팅용)"""
        self.in_position = False
        self.entry_price = None
        self.highest_price = None


def create_strategy(config):
    """전략 인스턴스 생성"""
    return V07Strategy(config)


# Standalone function for simple backtester compatibility
def v07_strategy(df, i, params):
    """
    Simple backtester용 전략 함수

    Args:
        df: DataFrame with indicators
        i: current index
        params: strategy parameters (dict)

    Returns:
        dict: {'action': 'buy'/'sell'/'hold', 'fraction': 0.0~1.0}
    """
    # State tracking (global)
    if not hasattr(v07_strategy, 'in_position'):
        v07_strategy.in_position = False
        v07_strategy.entry_price = None
        v07_strategy.highest_price = None

    # Params
    trailing_stop_pct = params.get('trailing_stop_pct', 0.21)
    stop_loss_pct = params.get('stop_loss_pct', 0.10)
    position_fraction = params.get('position_fraction', 0.95)

    # Not enough data
    if i < 27:
        return {'action': 'hold'}

    row = df.iloc[i]
    prev_row = df.iloc[i - 1]

    # Exit check
    if v07_strategy.in_position:
        current_price = row['close']

        # Update highest
        if current_price > v07_strategy.highest_price:
            v07_strategy.highest_price = current_price

        # Trailing Stop
        trailing_stop_price = v07_strategy.highest_price * (1 - trailing_stop_pct)
        if current_price <= trailing_stop_price:
            v07_strategy.in_position = False
            v07_strategy.entry_price = None
            v07_strategy.highest_price = None
            return {'action': 'sell', 'fraction': 1.0}

        # Stop Loss
        stop_loss_price = v07_strategy.entry_price * (1 - stop_loss_pct)
        if current_price <= stop_loss_price:
            v07_strategy.in_position = False
            v07_strategy.entry_price = None
            v07_strategy.highest_price = None
            return {'action': 'sell', 'fraction': 1.0}

    # Entry check
    if not v07_strategy.in_position:
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
            v07_strategy.in_position = True
            v07_strategy.entry_price = row['close']
            v07_strategy.highest_price = row['close']
            return {'action': 'buy', 'fraction': position_fraction}

    return {'action': 'hold'}
