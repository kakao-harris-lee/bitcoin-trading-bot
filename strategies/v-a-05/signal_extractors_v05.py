#!/usr/bin/env python3
"""
Signal Extractors v05 - Ultimate Quality Filter
================================================
v-a-04 문제점 개선:
1. Sideways: 4조건 추가 (RSI 20, BB 0.1, Volume 1.2x, MACD 상승)
2. Trend: ADX 12, MACD strength 50k
3. Swing: RSI 40/35 (활성화)
"""

import pandas as pd
import numpy as np
from typing import Optional, Dict


class TrendFollowingEntryCheckerV05:
    """Trend Following Entry v05 - 문턱 낮춤 + 품질 필터"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """
        Entry 조건:
        - MACD 골든크로스
        - ADX >= 12 (기존 16 → 완화)
        - MACD strength >= 50,000 (새로 추가, 약한 GC 제외)

        예상: 8-11개/년 → 12-18개/년
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

        # ADX 임계값 완화: 16 → 12
        adx_threshold = 12

        if adx < adx_threshold:
            return None

        # MACD 강도 확인 (약한 골든크로스 제외)
        macd_strength = macd - macd_signal
        if macd_strength < 50_000:
            return None

        return {
            'action': 'buy',
            'fraction': 0.7,  # 0.8 → 0.7 (약간 보수적)
            'reason': f'TREND_GC_v05 (ADX={adx:.1f}, MACD_STR={macd_strength/1000:.0f}k)',
            'strategy': 'trend_following'
        }


class SwingTradingEntryCheckerV05:
    """Swing Trading Entry v05 - 조건 완화 (활성화)"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series) -> Optional[Dict]:
        """
        Entry 조건:
        1. RSI < 40 + MACD 골든크로스 (기존 33 → 40)
        2. RSI < 35 + MACD > 0 (기존 30 → 35)

        예상: 0개/년 → 5-10개/년
        """
        if prev_row is None:
            return None

        rsi = row.get('rsi', 50)
        macd = row.get('macd', 0)
        macd_signal = row.get('macd_signal', 0)

        prev_macd = prev_row.get('macd', 0)
        prev_signal = prev_row.get('macd_signal', 0)

        # RSI 임계값 (v37 최적화 값)
        rsi_threshold = 40
        rsi_extreme = 35

        # MACD 골든크로스
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        # 조건 1: RSI 과매도 + MACD 골든크로스
        if rsi < rsi_threshold and golden_cross:
            return {
                'action': 'buy',
                'fraction': 0.5,
                'reason': f'SWING_RSI_OVERSOLD_v05 (RSI={rsi:.1f}, MACD_GC)',
                'strategy': 'swing_trading'
            }

        # 조건 2: RSI 극단 과매도 + MACD 양수
        if rsi < rsi_extreme and macd > 0:
            return {
                'action': 'buy',
                'fraction': 0.5,
                'reason': f'SWING_EXTREME_v05 (RSI={rsi:.1f}, MACD+)',
                'strategy': 'swing_trading'
            }

        return None


class SidewaysEntryCheckerV05:
    """Sideways Entry v05 - 극도로 보수적 (품질 중심)"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, prev_row: pd.Series, df_recent: pd.DataFrame) -> Optional[Dict]:
        """
        Entry 조건 (RSI+BB만 사용, 4조건 강화):
        1. RSI < 20 (기존 24 → 더 엄격)
        2. BB position < 0.1 (기존 0.2 → 최하단만)
        3. Volume ratio >= 1.2 (새로 추가, 거래량 증가 확인)
        4. MACD 상승 (새로 추가, 모멘텀 전환 확인)

        예상: 38개/년 → 10-15개/년
        목표 승률: 63% → 75%+
        """
        if prev_row is None or len(df_recent) < 20:
            return None

        # 지표 값
        rsi = row.get('rsi', 50)
        bb_position = row.get('bb_position', 0.5)
        volume = row.get('volume', 0)
        macd = row.get('macd', 0)

        prev_macd = prev_row.get('macd', 0)

        # 평균 거래량
        avg_volume = df_recent['volume'].mean()
        volume_ratio = volume / avg_volume if avg_volume > 0 else 1.0

        # 조건 1: RSI 극단 과매도
        rsi_threshold = 20  # 24 → 20
        if rsi >= rsi_threshold:
            return None

        # 조건 2: BB 최하단
        bb_threshold = 0.1  # 0.2 → 0.1
        if bb_position >= bb_threshold:
            return None

        # 조건 3: Volume 증가 (새로 추가)
        volume_min = 1.2
        if volume_ratio < volume_min:
            return None

        # 조건 4: MACD 상승 전환 (새로 추가)
        macd_rising = macd > prev_macd
        if not macd_rising:
            return None

        return {
            'action': 'buy',
            'fraction': 0.3,  # 0.4 → 0.3 (더 보수적)
            'reason': f'SIDEWAYS_ULTRA_v05 (RSI={rsi:.1f}, BB={bb_position:.2f}, Vol={volume_ratio:.1f}x, MACD↑)',
            'strategy': 'sideways'
        }


class DefensiveEntryCheckerV05:
    """Defensive Entry v05 - 유지 (변경 없음)"""

    def __init__(self, config: Dict):
        self.config = config

    def check_entry(self, row: pd.Series, market_state: str) -> Optional[Dict]:
        """
        Entry 조건: 극단적 RSI 과매도
        (v-a-04와 동일, 변경 없음)
        """
        rsi = row.get('rsi', 50)

        # BEAR 정도에 따라 RSI 임계값 조정
        if market_state == 'BEAR_STRONG':
            rsi_threshold = 20
            position_size = 0.1
        else:  # BEAR_MODERATE
            rsi_threshold = 25
            position_size = 0.2

        if rsi < rsi_threshold:
            return {
                'action': 'buy',
                'fraction': position_size,
                'reason': f'DEFENSIVE_v05 (RSI={rsi:.1f}, {market_state})',
                'strategy': 'defensive'
            }

        return None
