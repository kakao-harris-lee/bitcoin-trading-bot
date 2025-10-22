#!/usr/bin/env python3
"""
Stateless Signal Extractors
============================
v37 전략의 Entry 로직만 추출 (포지션 상태 제거)
"""

import pandas as pd
from typing import Optional, Dict


class TrendFollowingEntryChecker:
    """Trend Following Entry만 체크 (무상태)"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """
        Entry 조건: MACD 골든크로스 + ADX >= 16

        Returns:
            None or {'action': 'buy', 'fraction': 0.8, 'reason': str}
        """
        if prev_row is None:
            return None

        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)
        adx = row.get('adx', 20)

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # MACD 골든크로스
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        # ADX 임계값 v-a-10: 16 → 20 (품질 향상)
        adx_threshold = self.config.get('trend_adx_threshold', 20)

        if golden_cross and adx >= adx_threshold:
            return {
                'action': 'buy',
                'fraction': 0.8,
                'reason': f'TREND_FOLLOWING_ENTRY (ADX={adx:.1f})',
                'strategy': 'trend_following'
            }

        return None


class SwingTradingEntryChecker:
    """Swing Trading Entry만 체크 (무상태)"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """
        Entry 조건:
        1. RSI < 33 + MACD 골든크로스
        2. RSI < 30 + MACD > 0

        Returns:
            None or {'action': 'buy', 'fraction': 0.6, 'reason': str}
        """
        if prev_row is None:
            return None

        rsi = row.get('rsi', 50)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # RSI 임계값
        rsi_threshold = self.config.get('swing_rsi_oversold', 33)
        rsi_extreme = 30

        # MACD 골든크로스
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        # 조건 1: RSI 과매도 + MACD 골든크로스
        if rsi < rsi_threshold and golden_cross:
            return {
                'action': 'buy',
                'fraction': 0.6,
                'reason': f'SWING_ENTRY (RSI={rsi:.1f}, MACD_GC)',
                'strategy': 'swing_trading'
            }

        # 조건 2: RSI 극단 과매도 + MACD 양수
        if rsi < rsi_extreme and macd > 0:
            return {
                'action': 'buy',
                'fraction': 0.6,
                'reason': f'SWING_ENTRY_EXTREME (RSI={rsi:.1f}, MACD+)',
                'strategy': 'swing_trading'
            }

        return None


class SidewaysEntryChecker:
    """Sideways Entry만 체크 (무상태)"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series, df_recent: pd.DataFrame) -> Optional[Dict]:
        """
        Entry 조건 (3종):
        1. RSI + Bollinger Bands
        2. Stochastic Oscillator
        3. Volume Breakout

        Returns:
            None or {'action': 'buy', 'fraction': 0.25, 'reason': str}
        """
        if prev_row is None or len(df_recent) < 20:
            return None

        # 1. RSI + BB
        if self.config.get('use_rsi_bb', True):
            rsi = row.get('rsi', 50)
            bb_position = row.get('bb_position', 0.5)

            rsi_oversold = self.config.get('rsi_bb_oversold', 24)

            if rsi < rsi_oversold and bb_position < 0.2:
                return {
                    'action': 'buy',
                    'fraction': 0.25,  # v-a-10: 0.4 → 0.25 (리스크 감소)
                    'reason': f'SIDEWAYS_RSI_BB (RSI={rsi:.1f}, BB={bb_position:.2f})',
                    'strategy': 'sideways'
                }

        # 2. Stochastic
        if self.config.get('use_stoch', True):
            stoch_k = row.get('stoch_k', 50)
            stoch_d = row.get('stoch_d', 50)

            prev_k = prev_row.get('stoch_k', 50)
            prev_d = prev_row.get('stoch_d', 50)

            stoch_oversold = self.config.get('stoch_oversold', 20)

            # Stochastic 골든크로스 (과매도 구간)
            stoch_gc = (prev_k <= prev_d) and (stoch_k > stoch_d)

            if stoch_gc and stoch_k < stoch_oversold + 10:
                return {
                    'action': 'buy',
                    'fraction': 0.25,
                    'reason': f'SIDEWAYS_STOCH_GC (K={stoch_k:.1f}, D={stoch_d:.1f})',
                    'strategy': 'sideways'
                }

        # 3. Volume Breakout
        if self.config.get('use_volume_breakout', True):
            volume = row.get('volume', 0)
            avg_volume = df_recent['volume'].mean()

            volume_mult = self.config.get('volume_breakout_mult', 2.0)

            if volume >= avg_volume * volume_mult:
                return {
                    'action': 'buy',
                    'fraction': 0.25,
                    'reason': f'SIDEWAYS_VOLUME_BREAKOUT (Vol={volume/avg_volume:.1f}x)',
                    'strategy': 'sideways'
                }

        return None


class DefensiveEntryChecker:
    """Defensive Entry만 체크 (무상태)"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, market_state: str) -> Optional[Dict]:
        """
        Entry 조건: 극단적 RSI 과매도

        Args:
            market_state: BEAR_MODERATE or BEAR_STRONG

        Returns:
            None or {'action': 'buy', 'fraction': 0.1-0.2, 'reason': str}
        """
        rsi = row.get('rsi', 50)

        # BEAR 정도에 따라 RSI 임계값 조정
        if market_state == 'BEAR_STRONG':
            rsi_threshold = self.config.get('defensive_rsi_oversold', 25) - 5  # 20
            position_size = 0.1  # 매우 보수적
        else:  # BEAR_MODERATE
            rsi_threshold = self.config.get('defensive_rsi_oversold', 25)
            position_size = 0.2

        if rsi < rsi_threshold:
            return {
                'action': 'buy',
                'fraction': position_size,
                'reason': f'DEFENSIVE_ENTRY (RSI={rsi:.1f}, {market_state})',
                'strategy': 'defensive'
            }

        return None
