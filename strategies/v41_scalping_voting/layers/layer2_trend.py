#!/usr/bin/env python3
"""
Layer 2: 중기 트렌드 전략 (3개)
- EMA Crossover: EMA 교차 트렌드 확인
- BB Reversion: 볼린저밴드 평균회귀
- ADX Strength: 추세 강도 필터
"""

import numpy as np
import pandas as pd
from typing import Dict, Literal


class EmaCrossoverStrategy:
    """EMA 교차 전략 - 단기/장기 EMA 크로스"""

    def __init__(self, timeframe: str, config: Dict):
        self.timeframe = timeframe
        self.config = config

        # 지표 설정
        ind_config = config['indicators'][timeframe]
        self.ema_fast_period = ind_config['ema_fast']
        self.ema_slow_period = ind_config['ema_slow']

        # minute15는 3-EMA 시스템 (fast, mid, slow)
        if timeframe == 'minute15' and 'ema_mid' in ind_config:
            self.use_triple_ema = True
            self.ema_mid_period = ind_config['ema_mid']
        else:
            self.use_triple_ema = False

    def vote(self, df: pd.DataFrame, idx: int, position: str) -> Literal['buy', 'sell', 'hold']:
        """
        매수 투표: EMA_fast > EMA_slow 골든크로스 OR 정렬 상태
        매도 투표: EMA_fast < EMA_slow 데드크로스 OR 역정렬

        minute15 3-EMA: fast > mid > slow 정렬 필요

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

        ema_fast = current['ema_fast']
        ema_slow = current['ema_slow']
        prev_fast = prev['ema_fast']
        prev_slow = prev['ema_slow']

        # 3-EMA 시스템 (minute15)
        if self.use_triple_ema:
            ema_mid = current['ema_mid']

            # 완벽한 정렬: fast > mid > slow (강한 상승 추세)
            perfect_alignment = (ema_fast > ema_mid) and (ema_mid > ema_slow)

            # 역정렬: fast < mid < slow (강한 하락 추세)
            reverse_alignment = (ema_fast < ema_mid) and (ema_mid < ema_slow)

            if position == 'none':
                if perfect_alignment:
                    return 'buy'
            elif position == 'long':
                if reverse_alignment:
                    return 'sell'

            return 'hold'

        # 2-EMA 시스템 (기본)
        else:
            # 골든크로스
            golden_cross = (prev_fast <= prev_slow) and (ema_fast > ema_slow)

            # 데드크로스
            dead_cross = (prev_fast >= prev_slow) and (ema_fast < ema_slow)

            # 상승 정렬 유지
            bullish_alignment = ema_fast > ema_slow

            # 하락 정렬 유지
            bearish_alignment = ema_fast < ema_slow

            if position == 'none':
                # 골든크로스 or 이미 상승 정렬
                if golden_cross or bullish_alignment:
                    return 'buy'
            elif position == 'long':
                # 데드크로스 or 하락 정렬 전환
                if dead_cross or bearish_alignment:
                    return 'sell'

            return 'hold'


class BbReversionStrategy:
    """볼린저밴드 평균회귀 전략"""

    def __init__(self, timeframe: str, config: Dict):
        self.timeframe = timeframe
        self.config = config

        # Entry 조건
        entry_config = config['entry_conditions'][timeframe]

        # minute15는 bb_position_min 사용 (하단 밴드 근처)
        if 'bb_position_min' in entry_config:
            self.use_min_position = True
            self.bb_position_threshold = entry_config['bb_position_min']
        # 나머지는 bb_position_max 사용 (하단 돌파)
        elif 'bb_position_max' in entry_config:
            self.use_min_position = False
            self.bb_position_threshold = entry_config['bb_position_max']
        else:
            # 기본값
            self.use_min_position = False
            self.bb_position_threshold = 0.3

    def vote(self, df: pd.DataFrame, idx: int, position: str) -> Literal['buy', 'sell', 'hold']:
        """
        매수 투표: BB Position < threshold (하단 근처 - 과매도)
        매도 투표: BB Position > (1 - threshold) (상단 근처 - 과매수)

        BB Position = (Close - BB_Lower) / (BB_Upper - BB_Lower)
        0.0 = 하단 밴드, 0.5 = 중심선, 1.0 = 상단 밴드

        Args:
            df: OHLCV + indicators 데이터
            idx: 현재 캔들 인덱스
            position: 'none' | 'long' (현재 포지션)

        Returns:
            'buy' | 'sell' | 'hold'
        """
        if idx < 0 or idx >= len(df):
            return 'hold'

        current = df.iloc[idx]

        bb_upper = current['bb_upper']
        bb_middle = current['bb_middle']
        bb_lower = current['bb_lower']
        close = current['close']

        # BB Position 계산
        bb_width = bb_upper - bb_lower
        if bb_width == 0:
            return 'hold'

        bb_position = (close - bb_lower) / bb_width

        # 포지션 없을 때: 하단 근처 = 매수 신호
        if position == 'none':
            if self.use_min_position:
                # minute15: bb_position_min 이상이어야 함 (너무 극단적이지 않은)
                if self.bb_position_threshold <= bb_position <= 0.4:
                    return 'buy'
            else:
                # 나머지: bb_position_max 이하 (하단 돌파)
                if bb_position < self.bb_position_threshold:
                    return 'buy'

        # 포지션 있을 때: 상단 근처 = 매도 신호
        elif position == 'long':
            # 대칭 조건: 1 - threshold
            upper_threshold = 1.0 - self.bb_position_threshold
            if bb_position > upper_threshold:
                return 'sell'

        return 'hold'


class AdxStrengthStrategy:
    """ADX 추세 강도 전략"""

    def __init__(self, timeframe: str, config: Dict):
        self.timeframe = timeframe
        self.config = config

        # Entry 조건
        entry_config = config['entry_conditions'][timeframe]

        # ADX 임계값 (있으면 사용, 없으면 기본값)
        self.adx_min = entry_config.get('adx_min', 15)

    def vote(self, df: pd.DataFrame, idx: int, position: str) -> Literal['buy', 'sell', 'hold']:
        """
        매수 투표: ADX > threshold AND +DI > -DI (강한 상승 추세)
        매도 투표: ADX 감소 OR +DI < -DI (추세 약화/반전)

        ADX: Average Directional Index (추세 강도)
        +DI: Positive Directional Indicator (상승 방향성)
        -DI: Negative Directional Indicator (하락 방향성)

        Args:
            df: OHLCV + indicators 데이터
            idx: 현재 캔들 인덱스
            position: 'none' | 'long' (현재 포지션)

        Returns:
            'buy' | 'sell' | 'hold'
        """
        # ADX 지표가 없는 타임프레임은 항상 'hold' 반환
        if 'adx' not in df.columns:
            return 'hold'

        if idx < 1 or idx >= len(df):
            return 'hold'

        current = df.iloc[idx]
        prev = df.iloc[idx - 1]

        adx = current['adx']
        plus_di = current['plus_di']
        minus_di = current['minus_di']
        prev_adx = prev['adx']

        # NaN 체크
        if pd.isna(adx) or pd.isna(plus_di) or pd.isna(minus_di):
            return 'hold'

        # 포지션 없을 때: 강한 상승 추세 진입
        if position == 'none':
            # ADX가 임계값 이상 AND 상승 방향성 우세
            if adx > self.adx_min and plus_di > minus_di:
                return 'buy'

        # 포지션 있을 때: 추세 약화/반전 감지
        elif position == 'long':
            # ADX 감소 (추세 약화) OR 방향성 반전
            adx_declining = adx < prev_adx
            direction_reversed = plus_di < minus_di

            if adx_declining or direction_reversed:
                return 'sell'

        return 'hold'


class Layer2TrendVoter:
    """Layer 2 투표 집계기 - 3개 트렌드 전략 통합"""

    def __init__(self, timeframe: str, config: Dict):
        self.timeframe = timeframe
        self.config = config

        # 3개 전략 초기화
        self.ema_strategy = EmaCrossoverStrategy(timeframe, config)
        self.bb_strategy = BbReversionStrategy(timeframe, config)
        self.adx_strategy = AdxStrengthStrategy(timeframe, config)

        self.strategies = [
            ('ema_crossover', self.ema_strategy),
            ('bb_reversion', self.bb_strategy),
            ('adx_strength', self.adx_strategy)
        ]

    def get_votes(self, df: pd.DataFrame, idx: int, position: str) -> Dict:
        """
        Layer 2의 3개 전략 투표 수집

        Returns:
            {
                'buy_votes': int (0~3),
                'sell_votes': int (0~3),
                'details': {
                    'ema_crossover': 'buy' | 'sell' | 'hold',
                    'bb_reversion': ...,
                    'adx_strength': ...
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
        Layer 2 합의 도출 (다수결)

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
    """Layer 2 전략 단위 테스트"""
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

    # EMA
    df['ema_fast'] = talib.EMA(df['close'], timeperiod=ind_config['ema_fast'])
    df['ema_slow'] = talib.EMA(df['close'], timeperiod=ind_config['ema_slow'])
    if 'ema_mid' in ind_config:
        df['ema_mid'] = talib.EMA(df['close'], timeperiod=ind_config['ema_mid'])

    # Bollinger Bands
    bb_upper, bb_middle, bb_lower = talib.BBANDS(
        df['close'],
        timeperiod=ind_config['bb_period'],
        nbdevup=ind_config['bb_std'],
        nbdevdn=ind_config['bb_std']
    )
    df['bb_upper'] = bb_upper
    df['bb_middle'] = bb_middle
    df['bb_lower'] = bb_lower

    # ADX + DI
    if 'adx_period' in ind_config:
        df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])
        df['plus_di'] = talib.PLUS_DI(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])
        df['minus_di'] = talib.MINUS_DI(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])

    # NaN 제거
    df = df.dropna().reset_index(drop=True)
    print(f"지표 계산 완료: {len(df)} 캔들 (NaN 제거 후)")

    # Layer2 투표자 생성
    print(f"\n[테스트] Layer 2 Trend Voter 초기화...")
    voter = Layer2TrendVoter(timeframe, config)

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

    print(f"\n=== Layer 2 투표 결과 요약 ===")
    print(f"매수 신호: {buy_signals}")
    print(f"매도 신호: {sell_signals}")
    print(f"관망: {hold_signals}")
    print(f"신호율: {(buy_signals + sell_signals) / 100 * 100:.1f}%")
    print(f"\n✅ Layer 2 전략 테스트 완료\n")
