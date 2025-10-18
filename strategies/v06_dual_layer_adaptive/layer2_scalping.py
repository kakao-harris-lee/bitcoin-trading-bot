#!/usr/bin/env python3
"""
layer2_scalping.py
v06 Layer 2: 적응형 Scalping 전략

전략 A (minute60): 단타, 8-15% 목표
전략 B (minute240): 스윙, 15-30% 목표
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta


class AdaptiveScalpingStrategy:
    """적응형 Scalping 전략 (minute60 or minute240)"""

    def __init__(self, config: dict, strategy_type: str = 'A'):
        """
        Args:
            config: strategy_a_scalping or strategy_b_swing
            strategy_type: 'A' (scalping) or 'B' (swing)
        """
        self.strategy_type = strategy_type
        self.config = config

        # 진입/청산 조건
        self.entry = config.get('entry_conditions', {})
        self.exit = config.get('exit_conditions', {})
        self.risk = config.get('risk_management', {})

        # 포지션 상태
        self.position = None
        self.entry_price = 0.0
        self.entry_time = None
        self.highest_price = 0.0
        self.filled_fraction = 0.0  # 현재까지 진입한 비율
        self.exited_fraction = 0.0  # 현재까지 청산한 비율

        # 분할 익절 상태
        self.partial_exits = self.exit.get('partial_exits', [])
        self.exit_triggered = [False] * len(self.partial_exits)

        # 리스크 관리
        self.daily_trades = 0
        self.weekly_trades = 0
        self.consecutive_losses = 0
        self.last_trade_date = None
        self.pause_until = None

    def reset_counters(self, current_time):
        """일일/주간 카운터 리셋"""
        if self.last_trade_date is None:
            self.last_trade_date = current_time
            return

        # 일일 리셋
        if current_time.date() > self.last_trade_date.date():
            self.daily_trades = 0

        # 주간 리셋
        if (current_time - self.last_trade_date).days >= 7:
            self.weekly_trades = 0

        self.last_trade_date = current_time

    def can_trade(self, current_time) -> bool:
        """거래 가능 여부 체크"""
        # 일시 정지 중인지
        if self.pause_until and current_time < self.pause_until:
            return False

        # 일일 제한
        if self.daily_trades >= self.risk.get('max_daily_trades', 3):
            return False

        # 주간 제한
        if self.weekly_trades >= self.risk.get('max_weekly_trades', 10):
            return False

        return True

    def generate_signal(
        self,
        df: pd.DataFrame,
        i: int,
        current_capital: float,
        current_time
    ) -> Dict:
        """
        신호 생성

        Args:
            df: minute60 or minute240 데이터
            i: 현재 인덱스
            current_capital: Layer 2 사용 가능 자본
            current_time: 현재 시각

        Returns:
            {'action': 'buy'|'sell'|'hold', 'fraction': float, 'reason': str}
        """
        if i < 30:
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'insufficient_data'}

        # 거래 가능 체크
        if not self.can_trade(current_time):
            return {'action': 'hold', 'fraction': 0.0, 'reason': 'trading_paused'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]
        price = current['close']

        # === 포지션 없을 때: 진입 신호 ===
        if self.position is None:
            if self._check_entry_conditions(df, i):
                return {
                    'action': 'buy',
                    'fraction': 1.0,  # 할당된 자본 전액
                    'reason': f'{self.strategy_type}_entry'
                }

        # === 포지션 있을 때: 청산 신호 ===
        else:
            # 최고가 갱신
            if price > self.highest_price:
                self.highest_price = price

            pnl_ratio = (price - self.entry_price) / self.entry_price
            drop_from_high = (self.highest_price - price) / self.highest_price

            # 보유 시간 체크
            if self.strategy_type == 'A':
                max_hours = self.exit.get('max_holding_hours', 48)
                holding_hours = (current_time - self.entry_time).total_seconds() / 3600
            else:  # B
                max_days = self.exit.get('max_holding_days', 10)
                holding_hours = (current_time - self.entry_time).total_seconds() / 3600
                max_hours = max_days * 24

            # === 청산 조건 체크 ===

            # 1. 분할 익절
            for idx, exit_config in enumerate(self.partial_exits):
                if not self.exit_triggered[idx]:
                    target_profit = exit_config['profit_pct']
                    if pnl_ratio >= target_profit:
                        self.exit_triggered[idx] = True
                        self.exited_fraction += exit_config['fraction']
                        return {
                            'action': 'sell',
                            'fraction': exit_config['fraction'],
                            'reason': f'partial_exit_{idx+1} profit={pnl_ratio:.2%}'
                        }

            # 2. Trailing Stop
            trailing_pct = self.exit.get('trailing_stop_pct', 0.10)
            if drop_from_high >= trailing_pct:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'trailing_stop drop={drop_from_high:.2%}'
                }

            # 3. Stop Loss (기본)
            stop_loss = self.exit.get('stop_loss_base', 0.05)
            if pnl_ratio <= -stop_loss:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'stop_loss pnl={pnl_ratio:.2%}'
                }

            # 4. Quick Stop Loss (전략 A only)
            if self.strategy_type == 'A':
                quick_config = self.exit.get('quick_stop_loss', {})
                if holding_hours <= quick_config.get('time_hours', 1):
                    if pnl_ratio <= -quick_config.get('loss_pct', 0.03):
                        return {
                            'action': 'sell',
                            'fraction': 1.0,
                            'reason': 'quick_stop_loss'
                        }

            # 5. 데드크로스 (전략 B only)
            if self.strategy_type == 'B' and self.exit.get('dead_cross_immediate', False):
                ema12 = current.get('ema_12', price)
                ema26 = current.get('ema_26', price)
                prev_ema12 = prev.get('ema_12', price)
                prev_ema26 = prev.get('ema_26', price)

                dead_cross = (prev_ema12 >= prev_ema26) and (ema12 < ema26)
                if dead_cross:
                    return {
                        'action': 'sell',
                        'fraction': 1.0,
                        'reason': 'dead_cross'
                    }

            # 6. 최대 보유 시간 초과
            if holding_hours >= max_hours:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'max_holding_time {holding_hours:.1f}h'
                }

        return {'action': 'hold', 'fraction': 0.0, 'reason': 'no_signal'}

    def _check_entry_conditions(self, df: pd.DataFrame, i: int) -> bool:
        """진입 조건 체크"""
        current = df.iloc[i]
        prev = df.iloc[i - 1]
        price = current['close']

        # EMA 골든크로스
        if self.entry.get('golden_cross', False):
            ema12 = current.get('ema_12', price)
            ema26 = current.get('ema_26', price)
            prev_ema12 = prev.get('ema_12', price)
            prev_ema26 = prev.get('ema_26', price)

            if pd.isna(ema12) or pd.isna(ema26):
                return False

            golden_cross = (prev_ema12 <= prev_ema26) and (ema12 > ema26)
            if not golden_cross and not (ema12 > ema26):
                return False

        # RSI 조건
        rsi = current.get('rsi', 50)
        if not pd.isna(rsi):
            rsi_min = self.entry.get('rsi_min', 0)
            rsi_max = self.entry.get('rsi_max', 100)
            if not (rsi_min <= rsi <= rsi_max):
                return False

        # MACD 조건 (전략 B)
        if self.strategy_type == 'B' and self.entry.get('macd_bullish', False):
            macd = current.get('macd', 0)
            macd_signal = current.get('macd_signal', 0)
            if pd.isna(macd) or pd.isna(macd_signal):
                return False
            if macd <= macd_signal:
                return False

        # ADX 조건 (전략 B)
        if self.strategy_type == 'B':
            adx_min = self.entry.get('adx_min', 0)
            if adx_min > 0:
                adx = current.get('adx', 0)
                if pd.isna(adx) or adx < adx_min:
                    return False

        return True

    def on_buy(self, timestamp, price: float):
        """매수 체결"""
        self.position = 'long'
        self.entry_price = price
        self.entry_time = timestamp
        self.highest_price = price
        self.filled_fraction = 1.0
        self.exited_fraction = 0.0
        self.exit_triggered = [False] * len(self.partial_exits)

        # 거래 카운터 증가
        self.daily_trades += 1
        self.weekly_trades += 1

    def on_sell(self, pnl: float):
        """매도 체결"""
        # 손실 처리
        if pnl < 0:
            self.consecutive_losses += 1

            # 연속 손실 시 일시 정지
            max_losses = self.risk.get('max_consecutive_losses', 3)
            if self.consecutive_losses >= max_losses:
                pause_hours = self.risk.get('consecutive_loss_pause_hours', 24)
                self.pause_until = self.entry_time + timedelta(hours=pause_hours)
        else:
            self.consecutive_losses = 0

        # 포지션 초기화
        self.position = None
        self.entry_price = 0.0
        self.entry_time = None
        self.highest_price = 0.0
        self.filled_fraction = 0.0
        self.exited_fraction = 0.0
