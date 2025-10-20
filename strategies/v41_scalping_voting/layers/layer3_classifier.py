#!/usr/bin/env python3
"""
Layer 3: Day 캔들 시장 분류기 (1개)
- Day Market State: BULL/BEAR 시장 상태 판별 (v35, v38 기반)
"""

import numpy as np
import pandas as pd
from typing import Dict, Literal, Tuple
from datetime import datetime


class DayMarketStateClassifier:
    """
    Day 캔들 기반 시장 상태 분류

    분류:
    - BULL_STRONG: 강한 상승장 (MFI > 52, MACD > 0, MA20 상승)
    - BULL_MODERATE: 보통 상승장
    - SIDEWAYS: 횡보장
    - BEAR_MODERATE: 보통 하락장
    - BEAR_STRONG: 강한 하락장

    투표 규칙:
    - BULL → 매수 투표
    - SIDEWAYS → 중립 (조건부 매수)
    - BEAR → 매도 투표 (포지션 있을 때만)
    """

    def __init__(self, config: Dict):
        self.config = config

        # Day 캔들 지표 설정
        self.day_config = config['indicators']['day']

        # 시장 분류 기준 (v35, v38에서 검증된 값)
        # MFI 기준
        self.mfi_bull_strong = 52
        self.mfi_bull_moderate = 45
        self.mfi_sideways_up = 42
        self.mfi_bear_moderate = 38
        self.mfi_bear_strong = 35

        # Day 캔들 DataFrame (별도로 관리)
        self.day_df = None
        self.day_df_loaded = False

    def load_day_data(self, db_path: str, start_date: str = None, end_date: str = None):
        """
        Day 캔들 데이터 로드 및 지표 계산

        Args:
            db_path: upbit_bitcoin.db 경로
            start_date: 시작 날짜 (YYYY-MM-DD)
            end_date: 종료 날짜 (YYYY-MM-DD)
        """
        import sys
        sys.path.append('../..')
        from core import DataLoader
        import talib

        print(f"[Layer3] Day 캔들 데이터 로드 중...")
        with DataLoader(db_path) as loader:
            self.day_df = loader.load_timeframe('day', start_date=start_date, end_date=end_date)

        print(f"[Layer3] Day 캔들 지표 계산 중... ({len(self.day_df)} 캔들)")

        # MFI (Money Flow Index)
        self.day_df['mfi'] = talib.MFI(
            self.day_df['high'],
            self.day_df['low'],
            self.day_df['close'],
            self.day_df['volume'],
            timeperiod=self.day_config['mfi_period']
        )

        # MACD
        macd, macd_signal, macd_hist = talib.MACD(
            self.day_df['close'],
            fastperiod=self.day_config['macd_fast'],
            slowperiod=self.day_config['macd_slow'],
            signalperiod=self.day_config['macd_signal']
        )
        self.day_df['macd'] = macd
        self.day_df['macd_signal'] = macd_signal
        self.day_df['macd_hist'] = macd_hist

        # MA20
        self.day_df['ma20'] = talib.SMA(self.day_df['close'], timeperiod=self.day_config['ma20_period'])

        # NaN 제거
        self.day_df = self.day_df.dropna().reset_index(drop=True)

        # timestamp를 datetime으로 변환 (빠른 검색을 위해)
        self.day_df['date'] = pd.to_datetime(self.day_df['timestamp']).dt.date

        self.day_df_loaded = True
        print(f"[Layer3] Day 캔들 준비 완료: {len(self.day_df)} 캔들")

    def get_market_state(self, current_date: datetime.date) -> Tuple[str, Dict]:
        """
        특정 날짜의 시장 상태 분류

        Args:
            current_date: 분류할 날짜 (datetime.date)

        Returns:
            (state, details)
            state: 'BULL_STRONG' | 'BULL_MODERATE' | 'SIDEWAYS' | 'BEAR_MODERATE' | 'BEAR_STRONG'
            details: 판별 근거 딕셔너리
        """
        if not self.day_df_loaded:
            return 'SIDEWAYS', {'error': 'Day data not loaded'}

        # 해당 날짜의 Day 캔들 찾기
        day_candle = self.day_df[self.day_df['date'] == current_date]

        if day_candle.empty:
            # 해당 날짜가 없으면 가장 최근 데이터 사용
            recent_candle = self.day_df[self.day_df['date'] <= current_date]
            if recent_candle.empty:
                return 'SIDEWAYS', {'error': 'No day candle available'}
            day_candle = recent_candle.iloc[-1]
        else:
            day_candle = day_candle.iloc[0]

        # 지표 추출
        mfi = day_candle['mfi']
        macd = day_candle['macd']
        macd_signal = day_candle['macd_signal']
        ma20 = day_candle['ma20']
        close = day_candle['close']

        # NaN 체크
        if pd.isna(mfi) or pd.isna(macd) or pd.isna(ma20):
            return 'SIDEWAYS', {'error': 'Indicators contain NaN'}

        # 분류 로직
        details = {
            'date': str(current_date),
            'mfi': round(mfi, 2),
            'macd': round(macd, 2),
            'macd_signal': round(macd_signal, 2),
            'ma20': round(ma20, 2),
            'close': round(close, 2)
        }

        # BULL STRONG: MFI > 52 AND MACD > Signal AND Close > MA20
        if mfi > self.mfi_bull_strong and macd > macd_signal and close > ma20:
            return 'BULL_STRONG', details

        # BULL MODERATE: MFI > 45 AND (MACD > Signal OR Close > MA20)
        if mfi > self.mfi_bull_moderate and (macd > macd_signal or close > ma20):
            return 'BULL_MODERATE', details

        # BEAR STRONG: MFI < 35 AND MACD < Signal AND Close < MA20
        if mfi < self.mfi_bear_strong and macd < macd_signal and close < ma20:
            return 'BEAR_STRONG', details

        # BEAR MODERATE: MFI < 38 AND (MACD < Signal OR Close < MA20)
        if mfi < self.mfi_bear_moderate and (macd < macd_signal or close < ma20):
            return 'BEAR_MODERATE', details

        # SIDEWAYS: 그 외
        return 'SIDEWAYS', details

    def vote(self, current_timestamp: str, position: str) -> Literal['buy', 'sell', 'hold']:
        """
        시장 상태 기반 투표

        투표 규칙:
        - BULL_STRONG / BULL_MODERATE: 강한 매수 투표
        - SIDEWAYS: 약한 매수 투표 (단타 허용)
        - BEAR_MODERATE / BEAR_STRONG: 매도 투표 (포지션 있을 때만)

        Args:
            current_timestamp: 현재 타임스탬프 (예: '2024-01-15 10:30:00')
            position: 'none' | 'long' (현재 포지션)

        Returns:
            'buy' | 'sell' | 'hold'
        """
        if not self.day_df_loaded:
            return 'hold'

        # 타임스탬프에서 날짜 추출
        try:
            current_date = pd.to_datetime(current_timestamp).date()
        except:
            return 'hold'

        # 시장 상태 분류
        state, details = self.get_market_state(current_date)

        # 투표 결정
        if state in ['BULL_STRONG', 'BULL_MODERATE']:
            # 포지션 없을 때만 매수 투표
            if position == 'none':
                return 'buy'

        elif state == 'SIDEWAYS':
            # 횡보장에서도 단타 기회 허용 (약한 매수)
            if position == 'none':
                return 'buy'

        elif state in ['BEAR_STRONG', 'BEAR_MODERATE']:
            # 포지션 있을 때만 매도 투표
            if position == 'long':
                return 'sell'

        return 'hold'


class Layer3ClassifierVoter:
    """Layer 3 투표 집계기 - Day 시장 분류기 래퍼"""

    def __init__(self, config: Dict, db_path: str = None, start_date: str = None, end_date: str = None):
        self.config = config
        self.classifier = DayMarketStateClassifier(config)

        # DB 경로가 주어지면 자동 로드
        if db_path:
            self.classifier.load_day_data(db_path, start_date, end_date)

    def load_day_data(self, db_path: str, start_date: str = None, end_date: str = None):
        """Day 캔들 데이터 로드 (외부 호출용)"""
        self.classifier.load_day_data(db_path, start_date, end_date)

    def get_votes(self, current_timestamp: str, position: str) -> Dict:
        """
        Layer 3 투표 수집 (1개 전략)

        Returns:
            {
                'buy_votes': int (0 or 1),
                'sell_votes': int (0 or 1),
                'details': {
                    'day_market_state': 'buy' | 'sell' | 'hold',
                    'market_state': 'BULL_STRONG' | ...,
                    'indicators': {...}
                }
            }
        """
        vote = self.classifier.vote(current_timestamp, position)

        # 시장 상태 추가 정보
        try:
            current_date = pd.to_datetime(current_timestamp).date()
            state, indicators = self.classifier.get_market_state(current_date)
        except:
            state = 'UNKNOWN'
            indicators = {}

        votes = {
            'buy_votes': 1 if vote == 'buy' else 0,
            'sell_votes': 1 if vote == 'sell' else 0,
            'hold_votes': 1 if vote == 'hold' else 0,
            'details': {
                'day_market_state': vote,
                'market_state': state,
                'indicators': indicators
            }
        }

        return votes

    def get_consensus(self, current_timestamp: str, position: str) -> Literal['buy', 'sell', 'hold']:
        """
        Layer 3 합의 (단일 전략이므로 그대로 반환)

        Returns:
            'buy' | 'sell' | 'hold'
        """
        return self.classifier.vote(current_timestamp, position)


if __name__ == "__main__":
    """Layer 3 분류기 단위 테스트"""
    import json
    import sys
    sys.path.append('../..')

    # Config 로드
    with open('../config.json') as f:
        config = json.load(f)

    # Layer3 투표자 생성 및 데이터 로드
    print("\n[테스트] Layer 3 Classifier Voter 초기화...")
    voter = Layer3ClassifierVoter(config)
    voter.load_day_data('../../upbit_bitcoin.db', start_date='2024-01-01', end_date='2024-12-31')

    # 샘플 날짜 테스트
    print("\n[테스트] 2024년 주요 날짜 시장 상태 분류...")
    test_dates = [
        '2024-01-15 09:00:00',  # 연초
        '2024-03-01 09:00:00',  # Q1
        '2024-06-15 09:00:00',  # 중반
        '2024-09-01 09:00:00',  # Q3
        '2024-12-15 09:00:00',  # 연말
    ]

    for timestamp in test_dates:
        votes = voter.get_votes(timestamp, 'none')
        consensus = voter.get_consensus(timestamp, 'none')

        print(f"\n  [{timestamp}]")
        print(f"    시장 상태: {votes['details']['market_state']}")
        print(f"    투표: {consensus}")
        print(f"    지표: MFI={votes['details']['indicators'].get('mfi', 'N/A')}, "
              f"MACD={votes['details']['indicators'].get('macd', 'N/A')}")

    # 통계 요약
    print("\n[테스트] 2024년 전체 시장 상태 분포...")
    from collections import Counter

    states = []
    for i in range(len(voter.classifier.day_df)):
        candle = voter.classifier.day_df.iloc[i]
        state, _ = voter.classifier.get_market_state(candle['date'])
        states.append(state)

    state_counts = Counter(states)
    total = len(states)

    print(f"\n=== 2024년 시장 상태 분포 ===")
    for state, count in state_counts.most_common():
        pct = count / total * 100
        print(f"  {state}: {count}일 ({pct:.1f}%)")

    print(f"\n✅ Layer 3 분류기 테스트 완료\n")
