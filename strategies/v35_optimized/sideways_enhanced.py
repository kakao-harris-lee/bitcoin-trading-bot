#!/usr/bin/env python3
"""
SIDEWAYS Enhanced Strategies
횡보장(SIDEWAYS_FLAT) 전략 강화

추가 전략:
1. RSI + Bollinger Bands (검증됨: 2020-2024 평균 +2.80%)
2. Stochastic Oscillator Scalping (빠른 반응)
3. Volume Breakout (거래량 돌파)

목표: 2023년 부진(+2.48%) 개선 → +8-10%
"""

from typing import Dict, Optional
import pandas as pd
import numpy as np


class SidewaysEnhancedStrategies:
    """SIDEWAYS 시장 상황을 위한 강화 전략 모음"""

    def __init__(self, config: Dict):
        """
        Args:
            config: 하이퍼파라미터 딕셔너리
        """
        self.config = config

        # 전략 활성화 여부
        self.use_rsi_bb = config.get('use_rsi_bb', True)
        self.use_stoch = config.get('use_stoch', True)
        self.use_volume_breakout = config.get('use_volume_breakout', True)

        # RSI + BB 파라미터
        self.rsi_bb_oversold = config.get('rsi_bb_oversold', 30)
        self.rsi_bb_overbought = config.get('rsi_bb_overbought', 70)

        # Stochastic 파라미터
        self.stoch_oversold = config.get('stoch_oversold', 20)
        self.stoch_overbought = config.get('stoch_overbought', 80)

        # Volume Breakout 파라미터
        self.volume_breakout_mult = config.get('volume_breakout_mult', 2.0)

    def check_rsi_bb_entry(self, row: pd.Series, prev_row: pd.Series = None) -> Optional[Dict]:
        """
        RSI + Bollinger Bands 전략

        Entry: RSI < 30 AND price < BB_lower
        Exit: RSI > 70 OR price > BB_upper

        2020-2024 평균 성과: 1.6회/년, 평균 +2.80%
        """
        if not self.use_rsi_bb:
            return None

        rsi = row.get('rsi', 50)
        close = row.get('close', 0)
        bb_lower = row.get('bb_lower', 0)
        bb_upper = row.get('bb_upper', 0)

        # Entry 조건
        if rsi < self.rsi_bb_oversold and close < bb_lower:
            return {
                'action': 'buy',
                'fraction': self.config.get('position_size', 0.5),
                'reason': 'RSI_BB_OVERSOLD',
                'strategy': 'rsi_bb'
            }

        return None

    def check_rsi_bb_exit(self, row: pd.Series, entry_strategy: str) -> Optional[Dict]:
        """RSI + BB Exit 조건"""
        if entry_strategy != 'rsi_bb':
            return None

        rsi = row.get('rsi', 50)
        close = row.get('close', 0)
        bb_upper = row.get('bb_upper', 0)

        # Exit 조건
        if rsi > self.rsi_bb_overbought or close > bb_upper:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'RSI_BB_OVERBOUGHT'
            }

        return None

    def check_stoch_entry(self, row: pd.Series, prev_row: pd.Series = None) -> Optional[Dict]:
        """
        Stochastic Oscillator Scalping

        Entry: Stoch_K > Stoch_D (골든크로스) AND K < 20
        Exit: Stoch_K < Stoch_D (데드크로스) OR K > 80
        """
        if not self.use_stoch or prev_row is None:
            return None

        stoch_k = row.get('stoch_k', 50)
        stoch_d = row.get('stoch_d', 50)
        prev_k = prev_row.get('stoch_k', 50)
        prev_d = prev_row.get('stoch_d', 50)

        # 골든크로스 감지
        golden_cross = (prev_k <= prev_d) and (stoch_k > stoch_d)

        # Entry 조건
        if golden_cross and stoch_k < self.stoch_oversold:
            return {
                'action': 'buy',
                'fraction': self.config.get('position_size', 0.5),
                'reason': 'STOCH_GOLDEN_CROSS',
                'strategy': 'stoch'
            }

        return None

    def check_stoch_exit(self, row: pd.Series, prev_row: pd.Series, entry_strategy: str) -> Optional[Dict]:
        """Stochastic Exit 조건"""
        if entry_strategy != 'stoch' or prev_row is None:
            return None

        stoch_k = row.get('stoch_k', 50)
        stoch_d = row.get('stoch_d', 50)
        prev_k = prev_row.get('stoch_k', 50)
        prev_d = prev_row.get('stoch_d', 50)

        # 데드크로스 감지
        dead_cross = (prev_k >= prev_d) and (stoch_k < stoch_d)

        # Exit 조건
        if dead_cross or stoch_k > self.stoch_overbought:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'STOCH_EXIT'
            }

        return None

    def check_volume_breakout_entry(self, row: pd.Series, df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        Volume Breakout 전략

        Entry: 거래량 > 평균 거래량 * 2.0 AND 가격 상승
        """
        if not self.use_volume_breakout or i < 20:
            return None

        volume = row.get('volume', 0)
        close = row.get('close', 0)
        prev_close = df.iloc[i-1]['close']

        # 20일 평균 거래량
        avg_volume = df.iloc[i-20:i]['volume'].mean()

        # Entry 조건
        price_up = close > prev_close * 1.005  # 0.5% 이상 상승
        volume_spike = volume > avg_volume * self.volume_breakout_mult

        if price_up and volume_spike:
            return {
                'action': 'buy',
                'fraction': self.config.get('position_size', 0.5),
                'reason': 'VOLUME_BREAKOUT',
                'strategy': 'volume_breakout'
            }

        return None

    def check_volume_breakout_exit(self, row: pd.Series, df: pd.DataFrame, i: int,
                                   entry_price: float, entry_strategy: str) -> Optional[Dict]:
        """Volume Breakout Exit 조건"""
        if entry_strategy != 'volume_breakout' or i < 1:
            return None

        volume = row.get('volume', 0)
        close = row.get('close', 0)

        # 평균 거래량
        if i >= 20:
            avg_volume = df.iloc[i-20:i]['volume'].mean()
        else:
            avg_volume = df.iloc[:i]['volume'].mean()

        # Exit 조건
        profit = (close - entry_price) / entry_price

        # 1. 수익 1.5% 이상
        if profit >= 0.015:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'VOLUME_BREAKOUT_TP'
            }

        # 2. 거래량 정상화 + 수익 0.5% 이상
        if profit >= 0.005 and volume < avg_volume * 1.2:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'VOLUME_NORMALIZED'
            }

        return None

    def check_all_entries(self, row: pd.Series, prev_row: pd.Series,
                         df: pd.DataFrame, i: int) -> Optional[Dict]:
        """
        모든 SIDEWAYS 전략 Entry 조건 확인

        우선순위:
        1. RSI + BB (검증됨, 가장 신뢰)
        2. Stochastic (빠른 반응)
        3. Volume Breakout (돌파 포착)
        """
        # RSI + BB
        signal = self.check_rsi_bb_entry(row, prev_row)
        if signal:
            return signal

        # Stochastic
        signal = self.check_stoch_entry(row, prev_row)
        if signal:
            return signal

        # Volume Breakout
        signal = self.check_volume_breakout_entry(row, df, i)
        if signal:
            return signal

        return None


if __name__ == '__main__':
    """테스트"""
    import sys
    sys.path.append('../..')
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    print("="*70)
    print("  SIDEWAYS Enhanced Strategies - 테스트")
    print("="*70)

    # 2023년 SIDEWAYS_FLAT 구간 데이터 (v34에서 부진했던 구간)
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2023-01-01', end_date='2023-12-31')

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'bb', 'stoch'])

    # 전략 테스트
    config = {
        'use_rsi_bb': True,
        'use_stoch': True,
        'use_volume_breakout': True,
        'rsi_bb_oversold': 30,
        'rsi_bb_overbought': 70,
        'stoch_oversold': 20,
        'stoch_overbought': 80,
        'volume_breakout_mult': 2.0,
        'position_size': 0.5
    }

    strategies = SidewaysEnhancedStrategies(config)

    # Entry 시그널 찾기
    signals = []
    for i in range(30, len(df)):
        prev_row = df.iloc[i-1] if i > 0 else None
        signal = strategies.check_all_entries(df.iloc[i], prev_row, df, i)
        if signal:
            signals.append({
                'date': df.iloc[i].name,
                'reason': signal['reason'],
                'strategy': signal.get('strategy', 'unknown'),
                'price': df.iloc[i]['close']
            })

    print(f"\n[2023년 SIDEWAYS 시그널: {len(signals)}개]")
    for sig in signals[:15]:  # 처음 15개만
        print(f"  {sig['date']} | {sig['strategy']:15s} | {sig['reason']:20s} | {sig['price']:,.0f}원")

    # 전략별 시그널 수
    print(f"\n[전략별 시그널 수]")
    from collections import Counter
    strategy_counts = Counter([s['strategy'] for s in signals])
    for strategy, count in strategy_counts.items():
        print(f"  {strategy:20s}: {count}개")

    print(f"\n테스트 완료!")
    print(f"v34 2023년 성과: +2.48% (SIDEWAYS_FLAT 45.6%)")
    print(f"v35 목표: +8-10% (SIDEWAYS 전략 강화)")
