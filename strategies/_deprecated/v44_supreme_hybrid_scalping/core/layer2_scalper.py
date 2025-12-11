#!/usr/bin/env python3
"""
Layer 2: Scalping Enhancer (Minute60 + Minute240)
- Layer 1 활성화 시에만 동작
- 추가 스캘핑으로 복리 효과 극대화
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../v42_ultimate_scalping/core'))

import pandas as pd
import numpy as np
from datetime import datetime, timedelta


class Layer2Scalper:
    """Layer 2: Minute60/240 스캘핑 전략"""

    def __init__(self, config, timeframe):
        """
        Args:
            config: 전체 설정
            timeframe: 'minute60' 또는 'minute240'
        """
        self.timeframe = timeframe
        self.config = config['layer2_scalping'][timeframe]

        # Entry 조건
        self.min_score = self.config['min_score']
        self.min_tier = self.config['min_tier']
        self.additional_filters = self.config['additional_filters']

        # Exit 조건
        self.take_profit = self.config['exit']['take_profit']
        self.stop_loss = self.config['exit']['stop_loss']
        self.max_hold_hours = self.config['exit']['max_hold_hours']

        # Trailing Stop
        self.trailing_enabled = self.config['exit']['trailing_stop']['enabled']
        self.trailing_activation = self.config['exit']['trailing_stop']['activation_profit']
        self.trailing_percent = self.config['exit']['trailing_stop']['trail_percent']

        # Kelly
        self.kelly_range = self.config['kelly_range']

        # 상태
        self.current_position = None
        self.trade_history = []
        self.peak_profit = 0.0  # Trailing Stop용

    def check_entry_signal(self, scored_data, layer1_active):
        """
        Entry 시그널 체크

        Args:
            scored_data: ScoreEngine에서 점수 계산된 데이터
            layer1_active: Layer 1이 활성화되어 있는지

        Returns:
            signal dict 또는 None
        """
        # Layer 1이 비활성화되면 진입 불가
        if not layer1_active:
            return None

        # 이미 포지션이 있으면 진입 불가
        if self.current_position:
            return None

        df = scored_data[self.timeframe]

        if df is None or len(df) == 0:
            return None

        # 최신 캔들
        latest = df.iloc[-1]

        # 기본 조건: Score & Tier
        if latest['tier'] != self.min_tier and latest['score'] < self.min_score:
            return None

        # 추가 필터
        if 'rsi_max' in self.additional_filters:
            if latest['rsi'] > self.additional_filters['rsi_max']:
                return None

        if 'rsi_min' in self.additional_filters:
            if latest['rsi'] < self.additional_filters['rsi_min']:
                return None

        if 'mfi_min' in self.additional_filters:
            if latest['mfi'] < self.additional_filters['mfi_min']:
                return None

        if 'mfi_max' in self.additional_filters:
            if latest['mfi'] > self.additional_filters['mfi_max']:
                return None

        if 'volume_ratio_min' in self.additional_filters:
            if latest['volume_ratio'] < self.additional_filters['volume_ratio_min']:
                return None

        # 모든 조건 통과
        return {
            'action': 'BUY',
            'timeframe': self.timeframe,
            'timestamp': latest['timestamp'],
            'price': latest['close'],
            'score': latest['score'],
            'tier': latest['tier'],
            'rsi': latest['rsi'],
            'mfi': latest['mfi'],
            'layer': 2
        }

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

        # Peak 업데이트 (Trailing용)
        if return_pct > self.peak_profit:
            self.peak_profit = return_pct

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
            self._reset_trailing()
            return {
                'action': 'SELL',
                'reason': f'take_profit_{return_pct*100:.2f}%',
                'timestamp': current_time,
                'price': current_price,
                'return': return_pct,
                'hold_hours': hold_hours,
                'layer': 2
            }

        # 2. Trailing Stop
        if self.trailing_enabled and self.peak_profit >= self.trailing_activation:
            trail_threshold = self.peak_profit - self.trailing_percent
            if return_pct <= trail_threshold:
                self._reset_trailing()
                return {
                    'action': 'SELL',
                    'reason': f'trailing_stop_{return_pct*100:.2f}%_peak_{self.peak_profit*100:.2f}%',
                    'timestamp': current_time,
                    'price': current_price,
                    'return': return_pct,
                    'hold_hours': hold_hours,
                    'layer': 2
                }

        # 3. 손절
        if return_pct <= self.stop_loss:
            self._reset_trailing()
            return {
                'action': 'SELL',
                'reason': f'stop_loss_{return_pct*100:.2f}%',
                'timestamp': current_time,
                'price': current_price,
                'return': return_pct,
                'hold_hours': hold_hours,
                'layer': 2
            }

        # 4. 시간 초과
        if hold_hours >= self.max_hold_hours:
            self._reset_trailing()
            return {
                'action': 'SELL',
                'reason': f'timeout_{hold_hours:.1f}h',
                'timestamp': current_time,
                'price': current_price,
                'return': return_pct,
                'hold_hours': hold_hours,
                'layer': 2
            }

        return None

    def execute_entry(self, signal, position_size):
        """Entry 실행"""
        self.current_position = {
            'layer': 2,
            'timeframe': signal['timeframe'],
            'buy_time': signal['timestamp'],
            'buy_price': signal['price'],
            'score': signal['score'],
            'tier': signal['tier'],
            'position_size': position_size,
            'amount': None
        }
        self.peak_profit = 0.0

    def execute_exit(self, exit_signal):
        """Exit 실행"""
        if not self.current_position:
            return None

        pos = self.current_position

        trade = {
            'layer': 2,
            'timeframe': pos['timeframe'],
            'buy_time': pos['buy_time'],
            'buy_price': pos['buy_price'],
            'sell_time': exit_signal['timestamp'],
            'sell_price': exit_signal['price'],
            'return': exit_signal['return'],
            'hold_hours': exit_signal['hold_hours'],
            'reason': exit_signal['reason'],
            'score': pos['score'],
            'position_size': pos['position_size'],
            'peak_profit': self.peak_profit
        }

        self.trade_history.append(trade)
        self.current_position = None
        self.peak_profit = 0.0

        return trade

    def _reset_trailing(self):
        """Trailing Stop 상태 초기화"""
        self.peak_profit = 0.0

    def is_active(self):
        """Layer 2 포지션이 활성화되어 있는지"""
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
            'avg_loss': np.mean(losses) if losses else 0.0,
            'avg_peak_profit': np.mean([t['peak_profit'] for t in trades]) if trades else 0.0
        }
