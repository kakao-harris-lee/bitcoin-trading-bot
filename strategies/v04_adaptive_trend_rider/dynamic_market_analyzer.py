#!/usr/bin/env python3
"""
dynamic_market_analyzer.py
동적 시장 상태 분석기

고정된 분류(strong_bull 등) 대신 매 캔들마다 실시간으로:
- 추세 방향 (up/down/sideways)
- 추세 강도 (0~100)
- 변동성 수준 (low/medium/high)
- 모멘텀 (-100~100)
"""

import pandas as pd
import numpy as np
from typing import Dict


class DynamicMarketAnalyzer:
    """실시간 동적 시장 분석기"""

    def __init__(self):
        """초기화"""
        pass

    def analyze_trend(self, df: pd.DataFrame, i: int) -> Dict:
        """
        추세 분석 (방향 + 강도)

        Args:
            df: 데이터프레임 (EMA, ADX 포함)
            i: 현재 인덱스

        Returns:
            {
                'direction': 'up' | 'down' | 'sideways',
                'strength': 0~100,
                'ema12': float,
                'ema26': float,
                'adx': float
            }
        """
        if i < 26:
            return {
                'direction': 'sideways',
                'strength': 0,
                'ema12': 0,
                'ema26': 0,
                'adx': 0
            }

        current = df.iloc[i]
        price = current['close']

        # EMA 값 확인 (NaN 처리)
        ema12 = current.get('ema_12', np.nan)
        ema26 = current.get('ema_26', np.nan)
        adx = current.get('adx', np.nan)

        # NaN이면 계산 불가
        if pd.isna(ema12) or pd.isna(ema26):
            ema12 = price
            ema26 = price

        if pd.isna(adx):
            adx = 0

        # === 추세 방향 판단 ===
        # 1. 가격 위치
        price_above_ema12 = price > ema12
        price_above_ema26 = price > ema26

        # 2. EMA 배열
        ema12_above_ema26 = ema12 > ema26

        # 3. EMA 기울기 (최근 5 캔들)
        if i >= 30:
            ema12_prev = df.iloc[i-5]['ema_12']
            ema12_slope = (ema12 - ema12_prev) / ema12_prev if not pd.isna(ema12_prev) else 0
        else:
            ema12_slope = 0

        # 방향 결정
        if price_above_ema12 and price_above_ema26 and ema12_above_ema26 and ema12_slope > 0:
            direction = 'up'
        elif not price_above_ema12 and not price_above_ema26 and not ema12_above_ema26 and ema12_slope < 0:
            direction = 'down'
        else:
            direction = 'sideways'

        # === 추세 강도 (ADX 기반) ===
        # ADX: 0~100 (보통 0~60 범위)
        strength = min(adx, 100)

        return {
            'direction': direction,
            'strength': strength,
            'ema12': ema12,
            'ema26': ema26,
            'adx': adx
        }

    def analyze_volatility(self, df: pd.DataFrame, i: int) -> Dict:
        """
        변동성 분석

        Args:
            df: 데이터프레임 (ATR 포함)
            i: 현재 인덱스

        Returns:
            {
                'level': 'low' | 'medium' | 'high',
                'atr': float,
                'atr_pct': float  # 가격 대비 ATR 비율
            }
        """
        if i < 14:
            return {
                'level': 'medium',
                'atr': 0,
                'atr_pct': 0
            }

        current = df.iloc[i]
        price = current['close']
        atr = current.get('atr', 0)

        if pd.isna(atr) or atr == 0:
            atr = price * 0.02  # 기본값 2%

        # ATR 비율 (가격 대비)
        atr_pct = atr / price

        # 변동성 수준 분류
        if atr_pct < 0.015:  # 1.5% 미만
            level = 'low'
        elif atr_pct < 0.03:  # 3% 미만
            level = 'medium'
        else:  # 3% 이상
            level = 'high'

        return {
            'level': level,
            'atr': atr,
            'atr_pct': atr_pct
        }

    def analyze_momentum(self, df: pd.DataFrame, i: int) -> Dict:
        """
        모멘텀 분석 (RSI 기반)

        Args:
            df: 데이터프레임 (RSI 포함)
            i: 현재 인덱스

        Returns:
            {
                'score': -100~100,  # -100=극과매도, 0=중립, 100=극과매수
                'rsi': float,
                'state': 'oversold' | 'neutral' | 'overbought'
            }
        """
        if i < 14:
            return {
                'score': 0,
                'rsi': 50,
                'state': 'neutral'
            }

        current = df.iloc[i]
        rsi = current.get('rsi', 50)

        if pd.isna(rsi):
            rsi = 50

        # RSI를 -100~100 스코어로 변환
        # RSI 0 → -100, RSI 50 → 0, RSI 100 → 100
        score = (rsi - 50) * 2

        # 상태 분류
        if rsi < 30:
            state = 'oversold'
        elif rsi > 70:
            state = 'overbought'
        else:
            state = 'neutral'

        return {
            'score': score,
            'rsi': rsi,
            'state': state
        }

    def analyze(self, df: pd.DataFrame, i: int) -> Dict:
        """
        종합 시장 상태 분석

        Args:
            df: 데이터프레임
            i: 현재 인덱스

        Returns:
            {
                'trend': {...},
                'volatility': {...},
                'momentum': {...},
                'timestamp': str,
                'price': float
            }
        """
        trend = self.analyze_trend(df, i)
        volatility = self.analyze_volatility(df, i)
        momentum = self.analyze_momentum(df, i)

        current = df.iloc[i]

        return {
            'trend': trend,
            'volatility': volatility,
            'momentum': momentum,
            'timestamp': str(current['timestamp']),
            'price': current['close']
        }

    def get_description(self, market_state: Dict) -> str:
        """
        시장 상태 설명 문자열 생성

        Args:
            market_state: analyze() 반환값

        Returns:
            예: "Trend:up(ADX=35) | Vol:medium(2.1%) | Mom:oversold(RSI=28)"
        """
        trend = market_state['trend']
        vol = market_state['volatility']
        mom = market_state['momentum']

        return (
            f"Trend:{trend['direction']}(ADX={trend['adx']:.0f}) | "
            f"Vol:{vol['level']}({vol['atr_pct']:.1%}) | "
            f"Mom:{mom['state']}(RSI={mom['rsi']:.0f})"
        )
