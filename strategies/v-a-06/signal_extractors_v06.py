#!/usr/bin/env python3
"""
Signal Extractors v06 - 약세장 대응 강화
=========================================
v-a-04 기반 + 개선:
1. Trend: v-a-04와 동일 (ADX >= 16) - 성공했으므로 유지
2. Swing: v-a-04와 동일 (RSI < 33)
3. Sideways: 조건 완화 (RSI 24, BB 0.2, Volume 1.1x) - v-a-05 실패 반영
4. Defensive: 유지
5. ⭐ 약세장 필터: BEAR 시장에서 Sideways 차단
"""

import pandas as pd
from typing import Optional, Dict


class TrendFollowingEntryCheckerV06:
    """Trend Entry v06 - v-a-04와 동일 (성공)"""

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


class SwingTradingEntryCheckerV06:
    """Swing Entry v06 - v-a-04와 동일"""

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


class SidewaysEntryCheckerV06:
    """Sideways Entry v06 - 조건 완화 (v-a-05 실패 교훈)"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series, df_recent: pd.DataFrame) -> Optional[Dict]:
        """
        조건 완화:
        1. RSI < 24 (v-a-04와 동일)
        2. BB < 0.2 (v-a-04와 동일)
        3. Volume >= 1.1x (1.2x → 완화)
        4. MACD 조건 제거 ⭐ (v-a-05 실패 원인)

        목표: 177개 유지하면서 품질만 약간 향상
        """
        if prev_row is None or len(df_recent) < 20:
            return None

        rsi = row.get('rsi', 50)
        bb_position = row.get('bb_position', 0.5)
        volume = row.get('volume', 0)

        avg_volume = df_recent['volume'].mean()
        volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

        # 조건 1: RSI 과매도 (v-a-04와 동일)
        rsi_threshold = self.config.get('rsi_bb_oversold', 24)
        if rsi >= rsi_threshold:
            return None

        # 조건 2: BB (v-a-04와 동일)
        if bb_position >= 0.2:
            return None

        # 조건 3: Volume (1.2x → 1.1x 완화)
        if volume_ratio < 1.1:
            return None

        # MACD 조건 제거! (v-a-05 실패 원인)

        return {
            'action': 'buy',
            'fraction': 0.4,
            'reason': f'SIDEWAYS_v06 (RSI={rsi:.1f}, BB={bb_position:.2f}, Vol={volume_ratio:.1f}x)',
            'strategy': 'sideways'
        }


class DefensiveEntryCheckerV06:
    """Defensive Entry v06 - v-a-04와 동일"""

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


def apply_bear_market_filter_v06(signal: Optional[Dict], market_state: str) -> Optional[Dict]:
    """
    v06 핵심 개선: 약세장 필터

    BEAR 시장에서 Sideways 차단
    → 2021-2022 손실 방지
    """
    if signal is None:
        return None

    # BEAR 시장: Sideways 차단
    if market_state in ['BEAR_MODERATE', 'BEAR_STRONG']:
        if signal['strategy'] == 'sideways':
            return None  # 거부

    return signal
