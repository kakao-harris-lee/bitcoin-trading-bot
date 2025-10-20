#!/usr/bin/env python3
"""
Layer 1: 단기 모멘텀 전략 (3개)
- RSI Extreme: RSI 극단값 포착
- Volume Spike: 거래량 급증 감지
- MACD Cross: MACD 골든/데드 크로스
"""

import numpy as np
import pandas as pd
from typing import Dict, Literal


class RsiExtremeStrategy:
    """RSI 극단값 전략 - 과매도/과매수 구간 감지"""

    def __init__(self, timeframe: str, config: Dict):
        self.timeframe = timeframe
        self.config = config

        # 타임프레임별 설정
        tf_config = config['entry_conditions'][timeframe]
        self.rsi_oversold = tf_config['rsi_oversold']

        # RSI 과매수는 대칭으로 계산 (예: 15 → 85, 30 → 70, 40 → 60)
        self.rsi_overbought = 100 - self.rsi_oversold

    def vote(self, df: pd.DataFrame, idx: int, position: str) -> Literal['buy', 'sell', 'hold']:
        """
        매수 투표: RSI < oversold_threshold (과매도)
        매도 투표: RSI > overbought_threshold (과매수)

        Args:
            df: OHLCV + indicators 데이터
            idx: 현재 캔들 인덱스
            position: 'none' | 'long' (현재 포지션)

        Returns:
            'buy' | 'sell' | 'hold'
        """
        if idx < 0 or idx >= len(df):
            return 'hold'

        rsi = df.iloc[idx]['rsi']

        # 포지션 없을 때: 매수 신호 찾기
        if position == 'none':
            if rsi < self.rsi_oversold:
                return 'buy'

        # 포지션 있을 때: 매도 신호 찾기
        elif position == 'long':
            if rsi > self.rsi_overbought:
                return 'sell'

        return 'hold'


class VolumeSpikeStrategy:
    """거래량 급증 전략 - 비정상적 거래량 감지"""

    def __init__(self, timeframe: str, config: Dict):
        self.timeframe = timeframe
        self.config = config

        # 타임프레임별 설정
        tf_config = config['entry_conditions'][timeframe]
        self.volume_mult = tf_config['volume_mult']

        # 지표 설정
        ind_config = config['indicators'][timeframe]
        self.volume_sma_period = ind_config['volume_sma']

    def vote(self, df: pd.DataFrame, idx: int, position: str) -> Literal['buy', 'sell', 'hold']:
        """
        매수 투표: Volume > SMA(Volume) × mult AND Price 하락 중
        매도 투표: Volume > SMA(Volume) × mult AND Price 상승 후 반전

        Args:
            df: OHLCV + indicators 데이터
            idx: 현재 캔들 인덱스
            position: 'none' | 'long' (현재 포지션)

        Returns:
            'buy' | 'sell' | 'hold'
        """
        if idx < 1 or idx >= len(df):
            return 'hold'

        current = df.iloc[idx]
        prev = df.iloc[idx - 1]

        volume = current['volume']
        volume_sma = current['volume_sma']
        close = current['close']
        prev_close = prev['close']

        # 거래량 급증 확인
        is_volume_spike = volume > volume_sma * self.volume_mult

        if not is_volume_spike:
            return 'hold'

        # 포지션 없을 때: 하락 중 거래량 급증 = 매수 신호 (공포 매도)
        if position == 'none':
            # 가격이 하락 중
            if close < prev_close:
                return 'buy'

        # 포지션 있을 때: 상승 후 거래량 급증 = 매도 신호 (과열)
        elif position == 'long':
            # 가격이 상승 중이거나 고점
            if close >= prev_close:
                return 'sell'

        return 'hold'


class MacdCrossStrategy:
    """MACD 크로스 전략 - 모멘텀 전환 포착"""

    def __init__(self, timeframe: str, config: Dict):
        self.timeframe = timeframe
        self.config = config

    def vote(self, df: pd.DataFrame, idx: int, position: str) -> Literal['buy', 'sell', 'hold']:
        """
        매수 투표: MACD 골든크로스 (MACD > Signal로 전환)
        매도 투표: MACD 데드크로스 (MACD < Signal로 전환)

        Args:
            df: OHLCV + indicators 데이터
            idx: 현재 캔들 인덱스
            position: 'none' | 'long' (현재 포지션)

        Returns:
            'buy' | 'sell' | 'hold'
        """
        if idx < 1 or idx >= len(df):
            return 'hold'

        current = df.iloc[idx]
        prev = df.iloc[idx - 1]

        macd = current['macd']
        macd_signal = current['macd_signal']
        prev_macd = prev['macd']
        prev_signal = prev['macd_signal']

        # 골든크로스: 이전에는 MACD <= Signal, 현재는 MACD > Signal
        golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)

        # 데드크로스: 이전에는 MACD >= Signal, 현재는 MACD < Signal
        dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)

        # 포지션 없을 때: 골든크로스 = 매수 신호
        if position == 'none':
            if golden_cross:
                return 'buy'

        # 포지션 있을 때: 데드크로스 = 매도 신호
        elif position == 'long':
            if dead_cross:
                return 'sell'

        return 'hold'


class Layer1MomentumVoter:
    """Layer 1 투표 집계기 - 3개 모멘텀 전략 통합"""

    def __init__(self, timeframe: str, config: Dict):
        self.timeframe = timeframe
        self.config = config

        # 3개 전략 초기화
        self.rsi_strategy = RsiExtremeStrategy(timeframe, config)
        self.volume_strategy = VolumeSpikeStrategy(timeframe, config)
        self.macd_strategy = MacdCrossStrategy(timeframe, config)

        self.strategies = [
            ('rsi_extreme', self.rsi_strategy),
            ('volume_spike', self.volume_strategy),
            ('macd_cross', self.macd_strategy)
        ]

    def get_votes(self, df: pd.DataFrame, idx: int, position: str) -> Dict:
        """
        Layer 1의 3개 전략 투표 수집

        Returns:
            {
                'buy_votes': int (0~3),
                'sell_votes': int (0~3),
                'details': {
                    'rsi_extreme': 'buy' | 'sell' | 'hold',
                    'volume_spike': ...,
                    'macd_cross': ...
                }
            }
        """
        votes = {
            'buy_votes': 0,
            'sell_votes': 0,
            'hold_votes': 0,
            'details': {}
        }

        for name, strategy in self.strategies:
            vote = strategy.vote(df, idx, position)
            votes['details'][name] = vote

            if vote == 'buy':
                votes['buy_votes'] += 1
            elif vote == 'sell':
                votes['sell_votes'] += 1
            else:
                votes['hold_votes'] += 1

        return votes

    def get_consensus(self, df: pd.DataFrame, idx: int, position: str) -> Literal['buy', 'sell', 'hold']:
        """
        Layer 1 합의 도출 (다수결)

        Returns:
            'buy': 2개 이상 매수 투표
            'sell': 2개 이상 매도 투표
            'hold': 그 외
        """
        votes = self.get_votes(df, idx, position)

        if votes['buy_votes'] >= 2:
            return 'buy'
        elif votes['sell_votes'] >= 2:
            return 'sell'
        else:
            return 'hold'


if __name__ == "__main__":
    """Layer 1 전략 단위 테스트"""
    import json
    import sys
    sys.path.append('../..')

    from core import DataLoader
    import talib

    # Config 로드
    with open('../config.json') as f:
        config = json.load(f)

    # 테스트 타임프레임
    timeframe = 'minute15'

    # 데이터 로드
    print(f"\n[테스트] {timeframe} 데이터 로드 중...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(timeframe, start_date='2024-01-01', end_date='2024-01-31')

    print(f"로드 완료: {len(df)} 캔들")

    # 지표 추가
    print("\n[테스트] 지표 계산 중...")
    ind_config = config['indicators'][timeframe]

    # RSI
    df['rsi'] = talib.RSI(df['close'], timeperiod=ind_config['rsi_period'])

    # Volume SMA
    df['volume_sma'] = talib.SMA(df['volume'], timeperiod=ind_config['volume_sma'])

    # MACD
    macd, macd_signal, macd_hist = talib.MACD(
        df['close'],
        fastperiod=ind_config['macd_fast'],
        slowperiod=ind_config['macd_slow'],
        signalperiod=ind_config['macd_signal']
    )
    df['macd'] = macd
    df['macd_signal'] = macd_signal
    df['macd_hist'] = macd_hist

    # NaN 제거
    df = df.dropna().reset_index(drop=True)
    print(f"지표 계산 완료: {len(df)} 캔들 (NaN 제거 후)")

    # Layer1 투표자 생성
    print(f"\n[테스트] Layer 1 Momentum Voter 초기화...")
    voter = Layer1MomentumVoter(timeframe, config)

    # 샘플 투표 테스트
    print(f"\n[테스트] 첫 100 캔들 투표 샘플링...")
    buy_signals = 0
    sell_signals = 0
    hold_signals = 0

    for i in range(50, min(150, len(df))):
        votes = voter.get_votes(df, i, 'none')
        consensus = voter.get_consensus(df, i, 'none')

        if consensus == 'buy':
            buy_signals += 1
            print(f"  [{df.iloc[i]['timestamp']}] BUY - {votes['details']}")
        elif consensus == 'sell':
            sell_signals += 1
        else:
            hold_signals += 1

    print(f"\n=== Layer 1 투표 결과 요약 ===")
    print(f"매수 신호: {buy_signals}")
    print(f"매도 신호: {sell_signals}")
    print(f"관망: {hold_signals}")
    print(f"신호율: {(buy_signals + sell_signals) / 100 * 100:.1f}%")
    print(f"\n✅ Layer 1 전략 테스트 완료\n")
