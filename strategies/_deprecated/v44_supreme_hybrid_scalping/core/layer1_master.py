#!/usr/bin/env python3
"""
Layer 1: Master Signal (v43 Day Score 40 복제)
- v43와 동일한 Entry/Exit 조건
- 메인 포지션 (40% 자본)
- Layer 2 활성화 트리거
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../v42_ultimate_scalping/core'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class Layer1Master:
    """Layer 1: Day 타임프레임 메인 전략 (v43 복제)"""

    def __init__(self, config):
        self.config = config['layer1_master']
        self.timeframe = self.config['timeframe']
        self.min_score = self.config['min_score']
        self.min_tier = self.config['min_tier']

        # Exit 조건
        self.take_profit = self.config['exit']['take_profit']
        self.stop_loss = self.config['exit']['stop_loss']
        self.max_hold_hours = self.config['exit']['max_hold_hours']

        # Position Sizing (Kelly는 Layer 3에서 계산)
        self.kelly_range = self.config['kelly_range']

        # 상태
        self.current_position = None
        self.trade_history = []

    def check_entry_signal(self, scored_data):
        """
        Entry 시그널 체크

        Args:
            scored_data: ScoreEngine에서 점수 계산된 데이터

        Returns:
            signal dict 또는 None
        """
        df = scored_data[self.timeframe]

        if df is None or len(df) == 0:
            return None

        # 최신 캔들
        latest = df.iloc[-1]

        # v43 조건: S-Tier & Score >= 40
        if latest['tier'] == self.min_tier and latest['score'] >= self.min_score:
            return {
                'action': 'BUY',
                'timeframe': self.timeframe,
                'timestamp': latest['timestamp'],
                'price': latest['close'],
                'score': latest['score'],
                'tier': latest['tier'],
                'layer': 1
            }

        return None

    def check_exit_signal(self, current_data):
        """
        Exit 시그널 체크

        Args:
            current_data: 현재 데이터

        Returns:
            exit signal dict 또는 None
        """
        if not self.current_position:
            return None

        pos = self.current_position
        df = current_data[self.timeframe]

        if df is None or len(df) == 0:
            return None

        latest = df.iloc[-1]
        current_price = latest['close']
        current_time = latest['timestamp']

        # 수익률 계산
        return_pct = (current_price - pos['buy_price']) / pos['buy_price']

        # 보유 시간
        if isinstance(current_time, str):
            current_time = pd.to_datetime(current_time)
        if isinstance(pos['buy_time'], str):
            buy_time = pd.to_datetime(pos['buy_time'])
        else:
            buy_time = pos['buy_time']

        hold_hours = (current_time - buy_time).total_seconds() / 3600

        # 1. 익절
        if return_pct >= self.take_profit:
            return {
                'action': 'SELL',
                'reason': f'take_profit_{return_pct*100:.2f}%',
                'timestamp': current_time,
                'price': current_price,
                'return': return_pct,
                'hold_hours': hold_hours,
                'layer': 1
            }

        # 2. 손절
        if return_pct <= self.stop_loss:
            return {
                'action': 'SELL',
                'reason': f'stop_loss_{return_pct*100:.2f}%',
                'timestamp': current_time,
                'price': current_price,
                'return': return_pct,
                'hold_hours': hold_hours,
                'layer': 1
            }

        # 3. 시간 초과
        if hold_hours >= self.max_hold_hours:
            return {
                'action': 'SELL',
                'reason': f'timeout_{hold_hours:.1f}h',
                'timestamp': current_time,
                'price': current_price,
                'return': return_pct,
                'hold_hours': hold_hours,
                'layer': 1
            }

        return None

    def execute_entry(self, signal, position_size):
        """
        Entry 실행

        Args:
            signal: Entry 시그널
            position_size: Kelly에서 계산된 포지션 크기 (0.0-1.0)
        """
        self.current_position = {
            'layer': 1,
            'timeframe': signal['timeframe'],
            'buy_time': signal['timestamp'],
            'buy_price': signal['price'],
            'score': signal['score'],
            'tier': signal['tier'],
            'position_size': position_size,
            'amount': None  # 실제 수량은 Coordinator에서 계산
        }

    def execute_exit(self, exit_signal):
        """
        Exit 실행

        Args:
            exit_signal: Exit 시그널
        """
        if not self.current_position:
            return None

        pos = self.current_position

        # 거래 기록
        trade = {
            'layer': 1,
            'timeframe': pos['timeframe'],
            'buy_time': pos['buy_time'],
            'buy_price': pos['buy_price'],
            'sell_time': exit_signal['timestamp'],
            'sell_price': exit_signal['price'],
            'return': exit_signal['return'],
            'hold_hours': exit_signal['hold_hours'],
            'reason': exit_signal['reason'],
            'score': pos['score'],
            'position_size': pos['position_size']
        }

        self.trade_history.append(trade)
        self.current_position = None

        return trade

    def is_active(self):
        """Layer 1 포지션이 활성화되어 있는지"""
        return self.current_position is not None

    def get_statistics(self):
        """통계 계산"""
        if not self.trade_history:
            return {
                'total_trades': 0,
                'win_rate': 0.0,
                'avg_return': 0.0,
                'avg_win': 0.0,
                'avg_loss': 0.0
            }

        trades = self.trade_history
        returns = [t['return'] for t in trades]
        wins = [r for r in returns if r > 0]
        losses = [r for r in returns if r < 0]

        return {
            'total_trades': len(trades),
            'wins': len(wins),
            'losses': len(losses),
            'win_rate': len(wins) / len(trades) if trades else 0.0,
            'avg_return': np.mean(returns) if returns else 0.0,
            'avg_win': np.mean(wins) if wins else 0.0,
            'avg_loss': np.mean(losses) if losses else 0.0
        }
