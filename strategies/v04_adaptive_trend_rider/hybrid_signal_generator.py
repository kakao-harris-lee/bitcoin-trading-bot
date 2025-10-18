#!/usr/bin/env python3
"""
hybrid_signal_generator.py
혼합 진입 신호 생성기 (Track A + Track B)

Track A: 추세 추종 진입 (Trend Following)
Track B: 역추세 반등 진입 (Mean Reversion)

OR 로직: 둘 중 하나만 있어도 매수
"""

import pandas as pd
import numpy as np
from typing import Dict, List


class HybridSignalGenerator:
    """혼합 진입 신호 생성기"""

    def __init__(
        self,
        # Track A: 추세 추종 파라미터
        trend_min_strength: float = 20.0,
        trend_rsi_max: float = 70.0,

        # Track B: 역추세 반등 파라미터
        reversion_rsi_min: float = 35.0,
        reversion_drop_min: float = 0.05,
        reversion_lookback: int = 20
    ):
        """
        Args:
            trend_min_strength: 추세 추종 최소 ADX (기본: 20)
            trend_rsi_max: 추세 추종 최대 RSI (기본: 70, 과매수 방지)
            reversion_rsi_min: 역추세 최소 RSI (기본: 35, 과매도)
            reversion_drop_min: 역추세 최소 하락률 (기본: 5%)
            reversion_lookback: 역추세 최고가 조회 기간 (기본: 20)
        """
        self.trend_min_strength = trend_min_strength
        self.trend_rsi_max = trend_rsi_max
        self.reversion_rsi_min = reversion_rsi_min
        self.reversion_drop_min = reversion_drop_min
        self.reversion_lookback = reversion_lookback

    def check_trend_following(
        self,
        df: pd.DataFrame,
        i: int,
        market_state: Dict
    ) -> Dict:
        """
        Track A: 추세 추종 진입 신호

        조건:
        1. 추세 방향 = 'up'
        2. 추세 강도 >= 20 (ADX)
        3. 가격 > EMA12 > EMA26
        4. RSI < 70 (과매수 아님)

        Returns:
            {
                'signal': bool,
                'details': str,
                'score': 0~4  # 충족한 조건 수
            }
        """
        if i < 26:
            return {'signal': False, 'details': 'insufficient_data', 'score': 0}

        current = df.iloc[i]
        price = current['close']

        trend = market_state['trend']
        momentum = market_state['momentum']

        # 조건 체크
        conditions = []
        score = 0

        # 1. 추세 방향 = up
        cond1 = trend['direction'] == 'up'
        conditions.append(f"Dir={'✓up' if cond1 else '✗' + trend['direction']}")
        if cond1:
            score += 1

        # 2. 추세 강도 >= 20
        cond2 = trend['strength'] >= self.trend_min_strength
        conditions.append(f"ADX={'✓' if cond2 else '✗'}{trend['adx']:.0f}")
        if cond2:
            score += 1

        # 3. 가격 > EMA12 > EMA26
        ema12 = trend['ema12']
        ema26 = trend['ema26']
        cond3 = price > ema12 > ema26
        conditions.append(f"EMA={'✓' if cond3 else '✗'}P>{ema12:.0f}>{ema26:.0f}")
        if cond3:
            score += 1

        # 4. RSI < 70
        rsi = momentum['rsi']
        cond4 = rsi < self.trend_rsi_max
        conditions.append(f"RSI={'✓' if cond4 else '✗'}{rsi:.0f}<{self.trend_rsi_max:.0f}")
        if cond4:
            score += 1

        # 최종 신호: 3개 이상 충족 (4개 중)
        signal = (score >= 3)

        details = " | ".join(conditions)

        return {
            'signal': signal,
            'details': details,
            'score': score
        }

    def check_mean_reversion(
        self,
        df: pd.DataFrame,
        i: int,
        market_state: Dict
    ) -> Dict:
        """
        Track B: 역추세 반등 진입 신호

        조건:
        1. RSI < 35 (과매도)
        2. 최고가 대비 -5% 이상 하락
        3. Bollinger Bands 하단 돌파 후 반등
        4. (선택) MACD 골든크로스

        Returns:
            {
                'signal': bool,
                'details': str,
                'score': 0~4
            }
        """
        if i < max(26, self.reversion_lookback):
            return {'signal': False, 'details': 'insufficient_data', 'score': 0}

        current = df.iloc[i]
        prev = df.iloc[i - 1]
        price = current['close']

        momentum = market_state['momentum']

        # 조건 체크
        conditions = []
        score = 0

        # 1. RSI < 35
        rsi = momentum['rsi']
        cond1 = rsi < self.reversion_rsi_min
        conditions.append(f"RSI={'✓' if cond1 else '✗'}{rsi:.0f}<{self.reversion_rsi_min:.0f}")
        if cond1:
            score += 1

        # 2. 최고가 대비 하락
        recent_high = df.iloc[i - self.reversion_lookback:i + 1]['high'].max()
        drop_from_high = (recent_high - price) / recent_high
        cond2 = drop_from_high >= self.reversion_drop_min
        conditions.append(f"Drop={'✓' if cond2 else '✗'}{drop_from_high:.1%}>={self.reversion_drop_min:.1%}")
        if cond2:
            score += 1

        # 3. BB 하단 돌파 후 반등
        bb_lower = current.get('bb_lower', 0)
        prev_bb_lower = prev.get('bb_lower', 0)
        prev_price = prev['close']

        if not pd.isna(bb_lower) and not pd.isna(prev_bb_lower):
            bb_bounce = (prev_price <= prev_bb_lower) and (price > bb_lower)
        else:
            bb_bounce = False

        conditions.append(f"BB={'✓Bounce' if bb_bounce else '✗'}")
        if bb_bounce:
            score += 1

        # 4. MACD 골든크로스 (선택)
        macd = current.get('macd', 0)
        macd_signal = current.get('macd_signal', 0)
        prev_macd = prev.get('macd', 0)
        prev_signal = prev.get('macd_signal', 0)

        if not pd.isna(macd) and not pd.isna(macd_signal):
            golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)
        else:
            golden_cross = False

        conditions.append(f"MACD={'✓GC' if golden_cross else '✗'}")
        if golden_cross:
            score += 1

        # 최종 신호: 3개 이상 충족 (4개 중)
        signal = (score >= 3)

        details = " | ".join(conditions)

        return {
            'signal': signal,
            'details': details,
            'score': score
        }

    def generate_entry_signal(
        self,
        df: pd.DataFrame,
        i: int,
        market_state: Dict
    ) -> Dict:
        """
        혼합 진입 신호 생성 (Track A OR Track B)

        Args:
            df: 데이터프레임
            i: 현재 인덱스
            market_state: 시장 상태 (DynamicMarketAnalyzer.analyze() 결과)

        Returns:
            {
                'should_buy': bool,
                'track': 'trend_following' | 'mean_reversion' | 'both' | None,
                'track_a': {...},
                'track_b': {...},
                'reason': str
            }
        """
        # Track A 체크
        track_a = self.check_trend_following(df, i, market_state)

        # Track B 체크
        track_b = self.check_mean_reversion(df, i, market_state)

        # OR 로직
        if track_a['signal'] and track_b['signal']:
            should_buy = True
            track = 'both'
            reason = f"Both tracks | A: {track_a['details']} | B: {track_b['details']}"
        elif track_a['signal']:
            should_buy = True
            track = 'trend_following'
            reason = f"Track A (Trend) | {track_a['details']}"
        elif track_b['signal']:
            should_buy = True
            track = 'mean_reversion'
            reason = f"Track B (Reversion) | {track_b['details']}"
        else:
            should_buy = False
            track = None
            reason = f"No signal | A({track_a['score']}/4) B({track_b['score']}/4)"

        return {
            'should_buy': should_buy,
            'track': track,
            'track_a': track_a,
            'track_b': track_b,
            'reason': reason
        }

    def generate_exit_signal(
        self,
        df: pd.DataFrame,
        i: int,
        market_state: Dict
    ) -> Dict:
        """
        매도 신호 생성 (간단한 추세 전환 감지)

        Returns:
            {
                'should_exit': bool,
                'reason': str
            }
        """
        if i < 26:
            return {'should_exit': False, 'reason': 'insufficient_data'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        # 1. MACD 데드크로스
        macd = current.get('macd', 0)
        macd_signal = current.get('macd_signal', 0)
        prev_macd = prev.get('macd', 0)
        prev_signal = prev.get('macd_signal', 0)

        if not pd.isna(macd) and not pd.isna(macd_signal):
            dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)
        else:
            dead_cross = False

        # 2. RSI 과매수
        rsi = market_state['momentum']['rsi']
        rsi_overbought = rsi > 75

        # 3. 추세 전환 (up → down)
        trend_reversal = market_state['trend']['direction'] == 'down'

        # 매도 신호: 데드크로스 or (과매수 + 추세전환)
        should_exit = dead_cross or (rsi_overbought and trend_reversal)

        if dead_cross:
            reason = f"MACD dead cross (RSI={rsi:.0f})"
        elif rsi_overbought and trend_reversal:
            reason = f"Overbought + trend reversal (RSI={rsi:.0f}, trend=down)"
        else:
            reason = "no_exit_signal"

        return {
            'should_exit': should_exit,
            'reason': reason
        }
