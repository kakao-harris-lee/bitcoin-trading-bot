#!/usr/bin/env python3
"""
Signal Extractors v07 - Sideways 복원 + BEAR 선택적 차단
=========================================================
v-a-06 실패 교훈:
1. Trend: v-a-04와 동일 (ADX >= 16) - 유지
2. Swing: v-a-04와 동일 (RSI < 33) - 유지
3. Sideways: Volume 1.0x로 완화 (v-a-04 수준 복원)
4. Defensive: 유지
5. ⭐ Bear Filter 수정: BEAR_STRONG/MODERATE만 차단 (SIDEWAYS 시장 허용)
"""

import pandas as pd
from typing import Optional, Dict


class TrendFollowingEntryCheckerV07:
    """Trend Entry v07 - v-a-04와 동일"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """
        v-a-04와 동일:
        - MACD 골든크로스
        - ADX >= 16
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
        if not golden_cross:
            return None

        # ADX 임계값
        adx_threshold = self.config.get('trend_adx_threshold', 16)
        if adx < adx_threshold:
            return None

        return {
            'action': 'buy',
            'fraction': 0.8,
            'reason': f'TREND_GC_v06 (ADX={adx:.1f})',
            'strategy': 'trend_following'
        }


class SwingTradingEntryCheckerV07:
    """Swing Entry v07 - v-a-04와 동일"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """v-a-04와 동일: RSI < 33 + MACD GC"""
        if prev_row is None:
            return None

        rsi = row.get('rsi', 50)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # RSI 임계값
        rsi_threshold = 33
        rsi_extreme = 30

        # MACD 골든크로스
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        # 조건 1
        if rsi < rsi_threshold and golden_cross:
            return {
                'action': 'buy',
                'fraction': 0.6,
                'reason': f'SWING_RSI_OVERSOLD_v06 (RSI={rsi:.1f}, MACD_GC)',
                'strategy': 'swing_trading'
            }

        # 조건 2
        if rsi < rsi_extreme and macd > 0:
            return {
                'action': 'buy',
                'fraction': 0.6,
                'reason': f'SWING_EXTREME_v06 (RSI={rsi:.1f}, MACD+)',
                'strategy': 'swing_trading'
            }

        return None


class SidewaysEntryCheckerV07:
    """Sideways Entry v07 - v-a-04와 동일 (3종 OR 조건)"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series, df_recent: pd.DataFrame) -> Optional[Dict]:
        """
        v-a-04 원본 복원 (3종 OR 조건):
        1. RSI + BB
        2. Stochastic GC
        3. Volume Breakout

        목표: v-a-04 수준 177개 시그널 복원
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
                    'fraction': 0.4,
                    'reason': f'SIDEWAYS_RSI_BB (RSI={rsi:.1f}, BB={bb_position:.2f})',
                    'strategy': 'sideways'
                }

        # 2. Stochastic GC
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
                    'fraction': 0.4,
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
                    'fraction': 0.4,
                    'reason': f'SIDEWAYS_VOLUME_BREAKOUT (Vol={volume/avg_volume:.1f}x)',
                    'strategy': 'sideways'
                }

        return None


class DefensiveEntryCheckerV07:
    """Defensive Entry v07 - v-a-04와 동일"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, market_state: str) -> Optional[Dict]:
        """v-a-04와 동일"""
        rsi = row.get('rsi', 50)

        if market_state == 'BEAR_STRONG':
            rsi_threshold = 20
            position_size = 0.1
        else:
            rsi_threshold = 25
            position_size = 0.2

        if rsi < rsi_threshold:
            return {
                'action': 'buy',
                'fraction': position_size,
                'reason': f'DEFENSIVE_v06 (RSI={rsi:.1f}, {market_state})',
                'strategy': 'defensive'
            }

        return None


def apply_bear_market_filter_v07(signal: Optional[Dict], market_state: str) -> Optional[Dict]:
    """
    v07 개선: 선택적 약세장 필터

    v06 문제: SIDEWAYS 시장에서도 Sideways 차단 → 수익 기회 손실
    v07 해결: BEAR_MODERATE/STRONG에서만 Sideways 차단

    목표: v-a-04 수준 유지 + 2021-2022 약세장 개선
    """
    if signal is None:
        return None

    # BEAR 시장에서만 Sideways 차단 (SIDEWAYS 시장은 허용)
    if market_state in ['BEAR_MODERATE', 'BEAR_STRONG']:
        if signal['strategy'] == 'sideways':
            return None  # 거부

    return signal
