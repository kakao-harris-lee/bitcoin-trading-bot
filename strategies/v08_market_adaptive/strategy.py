#!/usr/bin/env python3
"""
v08 Market-Adaptive Strategy

시장 상황(Bull/Sideways/Bear)을 감지하고 각 상황에 맞는 전략을 사용하는 적응형 전략

핵심 아이디어:
1. MarketRegimeDetector로 현재 시장 분류
2. Bull/Sideways/Bear별 독립적인 파라미터 사용
3. 시장 전환 시 기존 포지션 청산 (Hysteresis 적용)
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict
from market_regime_detector import MarketRegimeDetector


class V08Strategy:
    """Market-Adaptive Strategy"""

    def __init__(self, config: dict):
        """
        Args:
            config: strategy configuration from config.json
        """
        self.config = config
        self.detector = MarketRegimeDetector(config['market_detector'])

        # 현재 시장 상황
        self.current_regime = 'sideways'  # 초기값은 보수적으로 sideways
        self.regime_counter = 0  # 전환 카운터
        self.transition_days = config['market_detector']['transition_days']

        # 포지션 관리
        self.position_qty = 0.0
        self.entry_price = 0.0
        self.highest_price = 0.0

    def decide(self, df: pd.DataFrame, i: int, cash: float, position_value: float) -> Dict:
        """
        전략 결정 함수

        Args:
            df: 전체 데이터프레임 (지표 포함)
            i: 현재 인덱스
            cash: 현재 현금
            position_value: 현재 포지션 가치

        Returns:
            {'action': 'buy'|'sell'|'hold', 'fraction': float, 'reason': str}
        """
        if i < max(self.detector.momentum_window, 26):
            return {'action': 'hold', 'reason': 'insufficient_data'}

        row = df.iloc[i]
        current_price = row['close']

        # 1. 시장 상황 감지 (Hysteresis 적용)
        detected_regime = self.detector.detect(df, i)
        regime_changed = self._update_regime(detected_regime)

        # 2. 시장 전환 시 기존 포지션 청산
        if regime_changed and self.position_qty > 0:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'regime_change: {self.current_regime}'
            }

        # 3. 현재 시장 상황에 맞는 전략 실행
        if self.current_regime == 'bull':
            return self._bull_strategy(df, i, cash, current_price)
        elif self.current_regime == 'sideways':
            return self._sideways_strategy(df, i, cash, current_price)
        elif self.current_regime == 'bear':
            return self._bear_strategy(df, i, cash, current_price)
        else:
            return {'action': 'hold', 'reason': 'unknown_regime'}

    def _update_regime(self, detected_regime: str) -> bool:
        """
        시장 상황 업데이트 (Hysteresis 적용)

        Args:
            detected_regime: 감지된 시장 상황

        Returns:
            bool: 시장 전환 여부
        """
        if detected_regime == self.current_regime:
            self.regime_counter = 0
            return False

        self.regime_counter += 1

        if self.regime_counter >= self.transition_days:
            old_regime = self.current_regime
            self.current_regime = detected_regime
            self.regime_counter = 0
            return True  # 시장 전환 발생

        return False

    def _bull_strategy(self, df: pd.DataFrame, i: int, cash: float, current_price: float) -> Dict:
        """
        Bull Market Strategy

        진입: EMA Golden Cross OR MACD Golden Cross
        청산: Trailing Stop 12% OR Stop Loss 8%
        """
        params = self.config['bull_params']
        row = df.iloc[i]

        # 포지션 없음 → 진입 시도
        if self.position_qty == 0:
            ema_cross = self._check_ema_cross(df, i, params)
            macd_cross = self._check_macd_cross(df, i, params) if params['use_macd_entry'] else False

            if ema_cross or macd_cross:
                self.entry_price = current_price
                self.highest_price = current_price
                return {
                    'action': 'buy',
                    'fraction': params['position_fraction'],
                    'reason': f'bull_entry: ema={ema_cross}, macd={macd_cross}'
                }

        # 포지션 있음 → 청산 시도
        else:
            # Highest price 업데이트
            if current_price > self.highest_price:
                self.highest_price = current_price

            # Trailing Stop
            trailing_pct = params['trailing_stop_pct']
            trailing_price = self.highest_price * (1 - trailing_pct)

            if current_price <= trailing_price:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'bull_trailing_stop: {trailing_pct*100:.0f}%'
                }

            # Stop Loss
            stop_loss_pct = params['stop_loss_pct']
            stop_loss_price = self.entry_price * (1 - stop_loss_pct)

            if current_price <= stop_loss_price:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'bull_stop_loss: {stop_loss_pct*100:.0f}%'
                }

        return {'action': 'hold', 'reason': 'bull_hold'}

    def _sideways_strategy(self, df: pd.DataFrame, i: int, cash: float, current_price: float) -> Dict:
        """
        Sideways Market Strategy

        진입: EMA Golden Cross만 사용 (MACD 제외)
        청산: Trailing Stop 6% OR Stop Loss 5% (빠른 익절/손절)
        """
        params = self.config['sideways_params']
        row = df.iloc[i]

        # 포지션 없음 → 진입 시도
        if self.position_qty == 0:
            ema_cross = self._check_ema_cross(df, i, params)

            if ema_cross:
                self.entry_price = current_price
                self.highest_price = current_price
                return {
                    'action': 'buy',
                    'fraction': params['position_fraction'],
                    'reason': 'sideways_entry: ema_cross'
                }

        # 포지션 있음 → 청산 시도
        else:
            # Highest price 업데이트
            if current_price > self.highest_price:
                self.highest_price = current_price

            # Trailing Stop (빠른 익절)
            trailing_pct = params['trailing_stop_pct']
            trailing_price = self.highest_price * (1 - trailing_pct)

            if current_price <= trailing_price:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'sideways_trailing_stop: {trailing_pct*100:.0f}%'
                }

            # Stop Loss (빠른 손절)
            stop_loss_pct = params['stop_loss_pct']
            stop_loss_price = self.entry_price * (1 - stop_loss_pct)

            if current_price <= stop_loss_price:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'sideways_stop_loss: {stop_loss_pct*100:.0f}%'
                }

        return {'action': 'hold', 'reason': 'sideways_hold'}

    def _bear_strategy(self, df: pd.DataFrame, i: int, cash: float, current_price: float) -> Dict:
        """
        Bear Market Strategy

        현금 보유 (거래 중단)
        """
        # 포지션 있으면 청산
        if self.position_qty > 0:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'bear_cash_preservation'
            }

        # 현금 보유
        return {'action': 'hold', 'reason': 'bear_stay_in_cash'}

    def _check_ema_cross(self, df: pd.DataFrame, i: int, params: dict) -> bool:
        """EMA Golden Cross 체크"""
        if i < 1:
            return False

        ema_fast = params['ema_fast']
        ema_slow = params['ema_slow']

        prev_fast = df.iloc[i-1][f'ema_{ema_fast}']
        prev_slow = df.iloc[i-1][f'ema_{ema_slow}']
        curr_fast = df.iloc[i][f'ema_{ema_fast}']
        curr_slow = df.iloc[i][f'ema_{ema_slow}']

        # Golden Cross
        return (prev_fast <= prev_slow) and (curr_fast > curr_slow)

    def _check_macd_cross(self, df: pd.DataFrame, i: int, params: dict) -> bool:
        """MACD Golden Cross 체크"""
        if i < 1:
            return False

        prev_macd = df.iloc[i-1]['macd']
        prev_signal = df.iloc[i-1]['macd_signal']
        curr_macd = df.iloc[i]['macd']
        curr_signal = df.iloc[i]['macd_signal']

        # Golden Cross
        return (prev_macd <= prev_signal) and (curr_macd > curr_signal)

    def on_buy(self, quantity: float, price: float):
        """매수 실행 후 호출"""
        self.position_qty = quantity
        self.entry_price = price
        self.highest_price = price

    def on_sell(self, quantity: float, price: float):
        """매도 실행 후 호출"""
        self.position_qty -= quantity
        if self.position_qty <= 1e-8:  # 전량 매도
            self.position_qty = 0.0
            self.entry_price = 0.0
            self.highest_price = 0.0


def v08_strategy_wrapper(df, i, params):
    """
    SimpleBacktester 호환 래퍼 함수

    Args:
        df: DataFrame with indicators
        i: current index
        params: {
            'strategy_instance': V08Strategy instance,
            'backtester': SimpleBacktester instance
        }

    Returns:
        {'action': 'buy'|'sell'|'hold', 'fraction': float}
    """
    strategy = params['strategy_instance']
    backtester = params['backtester']

    cash = backtester.cash
    position_value = backtester.position * df.iloc[i]['close'] if backtester.position > 0 else 0.0

    decision = strategy.decide(df, i, cash, position_value)

    # 매수/매도 실행 후 콜백 호출
    if decision['action'] == 'buy':
        current_price = df.iloc[i]['close']
        fraction = decision.get('fraction', 1.0)
        available = cash * fraction
        exec_price = current_price * (1 + backtester.slippage)
        quantity = available / (exec_price * (1 + backtester.fee_rate))
        strategy.on_buy(quantity, exec_price)

    elif decision['action'] == 'sell':
        current_price = df.iloc[i]['close']
        fraction = decision.get('fraction', 1.0)
        sell_qty = backtester.position * fraction
        exec_price = current_price * (1 - backtester.slippage)
        strategy.on_sell(sell_qty, exec_price)

    return decision
