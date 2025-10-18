#!/usr/bin/env python3
"""
signal_ensemble.py
4개 신호 앙상블 투표 시스템

신호 4개:
1. RSI 과매도 (< 40, 역추세)
2. MACD 골든크로스 (추세 전환)
3. Bollinger Bands 하단 돌파 (변동성 기회)
4. 급격한 가격 하락 (최고가 대비 -8%, 공포 매수)

투표 시스템:
- Strong Bull: 3/4 신호 → 매수
- Moderate Bull: 3/4 신호 → 매수
- Neutral-Bear: 4/4 신호 → 매수 (보수적)
"""

import pandas as pd
import numpy as np
from typing import Dict, List


class SignalEnsemble:
    """4개 신호 앙상블 투표 시스템"""

    def __init__(
        self,
        rsi_threshold: float = 40.0,
        price_drop_threshold: float = 0.08,
        lookback_period: int = 20
    ):
        """
        Args:
            rsi_threshold: RSI 과매도 임계값 (기본: 40)
            price_drop_threshold: 급락 임계값 (기본: 8%)
            lookback_period: 최고가 계산 기간 (기본: 20 캔들)
        """
        self.rsi_threshold = rsi_threshold
        self.price_drop_threshold = price_drop_threshold
        self.lookback_period = lookback_period

    def generate_signals(self, df: pd.DataFrame, i: int) -> Dict:
        """
        4개 매수 신호 생성

        Args:
            df: 거래 타임프레임 데이터프레임 (minute240 등)
            i: 현재 인덱스

        Returns:
            {
                'signals': [bool, bool, bool, bool],  # 4개 신호
                'signal_names': ['rsi', 'macd', 'bb', 'price_drop'],
                'vote_count': int,  # 1~4
                'details': str
            }
        """
        # 최소 데이터 확보
        if i < max(26, self.lookback_period):
            return {
                'signals': [False, False, False, False],
                'signal_names': ['rsi', 'macd', 'bb', 'price_drop'],
                'vote_count': 0,
                'details': 'insufficient_data'
            }

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        signals = []
        signal_details = []

        # === 신호 1: RSI 과매도 ===
        rsi = current['rsi']
        rsi_signal = (rsi < self.rsi_threshold)
        signals.append(rsi_signal)
        signal_details.append(f"RSI({rsi:.1f}{'<' if rsi_signal else '≥'}{self.rsi_threshold})")

        # === 신호 2: MACD 골든크로스 ===
        macd = current['macd']
        macd_signal = current['macd_signal']
        prev_macd = prev['macd']
        prev_signal = prev['macd_signal']

        # 골든크로스: 이전 캔들에서 MACD < Signal, 현재 캔들에서 MACD > Signal
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)
        signals.append(golden_cross)
        signal_details.append(f"MACD({'GC✓' if golden_cross else 'X'})")

        # === 신호 3: Bollinger Bands 하단 돌파 후 반등 ===
        bb_lower = current['bb_lower']
        price = current['close']
        prev_price = prev['close']

        # 이전 캔들이 하단 아래, 현재 캔들이 하단 위로 올라옴
        bb_bounce = (prev_price <= prev['bb_lower']) and (price > bb_lower)
        signals.append(bb_bounce)
        signal_details.append(f"BB({'Bounce✓' if bb_bounce else 'X'})")

        # === 신호 4: 급격한 가격 하락 (공포 매수) ===
        # 최근 N 캔들 최고가 대비 현재가 하락률
        recent_high = df.iloc[i - self.lookback_period:i + 1]['high'].max()
        drop_from_high = (recent_high - price) / recent_high

        price_drop_signal = (drop_from_high >= self.price_drop_threshold)
        signals.append(price_drop_signal)
        signal_details.append(f"Drop({drop_from_high:.1%}{'≥' if price_drop_signal else '<'}{self.price_drop_threshold:.1%})")

        # === 투표 집계 ===
        vote_count = sum(signals)
        details = " | ".join(signal_details)

        return {
            'signals': signals,
            'signal_names': ['rsi', 'macd', 'bb', 'price_drop'],
            'vote_count': vote_count,
            'details': details
        }

    def should_buy(
        self,
        signals: Dict,
        required_votes: int
    ) -> bool:
        """
        매수 여부 판단

        Args:
            signals: generate_signals() 반환값
            required_votes: 필요한 최소 신호 개수 (3 or 4)

        Returns:
            bool: 매수 신호 여부
        """
        return signals['vote_count'] >= required_votes

    def generate_exit_signals(self, df: pd.DataFrame, i: int) -> Dict:
        """
        매도 신호 생성 (간단한 역신호)

        Returns:
            {
                'rsi_overbought': bool,  # RSI > 70
                'macd_dead_cross': bool,  # MACD 데드크로스
                'bb_upper_break': bool,   # BB 상단 돌파
                'exit_vote_count': int
            }
        """
        if i < 26:
            return {
                'rsi_overbought': False,
                'macd_dead_cross': False,
                'bb_upper_break': False,
                'exit_vote_count': 0
            }

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        # RSI 과매수 (70 이상)
        rsi_overbought = current['rsi'] > 70

        # MACD 데드크로스
        macd = current['macd']
        macd_signal = current['macd_signal']
        prev_macd = prev['macd']
        prev_signal = prev['macd_signal']
        dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)

        # BB 상단 돌파
        bb_upper_break = current['close'] > current['bb_upper']

        exit_vote_count = sum([rsi_overbought, dead_cross, bb_upper_break])

        return {
            'rsi_overbought': rsi_overbought,
            'macd_dead_cross': dead_cross,
            'bb_upper_break': bb_upper_break,
            'exit_vote_count': exit_vote_count
        }
