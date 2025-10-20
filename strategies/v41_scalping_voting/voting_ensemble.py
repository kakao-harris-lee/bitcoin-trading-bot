#!/usr/bin/env python3
"""
v41 Voting Ensemble System
3-Layer 투표 시스템 통합 엔진

구조:
┌─────────────────────────────────────┐
│ Layer 1: 단기 모멘텀 (3표)          │
│  - RSI Extreme                      │
│  - Volume Spike                     │
│  - MACD Cross                       │
├─────────────────────────────────────┤
│ Layer 2: 중기 트렌드 (3표)          │
│  - EMA Crossover                    │
│  - BB Reversion                     │
│  - ADX Strength                     │
├─────────────────────────────────────┤
│ Layer 3: Day 시장 필터 (1표)        │
│  - Day Market State                 │
└─────────────────────────────────────┘
         ↓ (7표 중 N표 이상)
     ┌───────────────┐
     │ BUY / SELL    │
     └───────────────┘
"""

import numpy as np
import pandas as pd
from typing import Dict, Literal, Tuple
from datetime import datetime

from layers import (
    Layer1MomentumVoter,
    Layer2TrendVoter,
    Layer3ClassifierVoter
)


class VotingEnsemble:
    """3-Layer 투표 시스템 통합 엔진"""

    def __init__(self, timeframe: str, config: Dict, db_path: str = None):
        """
        Args:
            timeframe: 'minute1', 'minute5', 'minute15', 'minute60', 'minute240'
            config: v41 config.json 전체
            db_path: upbit_bitcoin.db 경로 (Layer3용)
        """
        self.timeframe = timeframe
        self.config = config

        # 투표 규칙
        voting_rules = config['voting_system']['voting_rules'][timeframe]
        self.min_votes = voting_rules['min_votes']
        self.total_votes = voting_rules['total_votes']

        # 3개 Layer 투표자 초기화
        self.layer1 = Layer1MomentumVoter(timeframe, config)
        self.layer2 = Layer2TrendVoter(timeframe, config)
        self.layer3 = Layer3ClassifierVoter(config)

        # Layer3 Day 데이터 로드 (db_path 제공 시)
        if db_path:
            # 백테스팅 기간에 맞춰 로드
            backtest_config = config['backtesting']['periods']
            start_date = backtest_config['train']['start']
            end_date = backtest_config['test']['end']
            self.layer3.load_day_data(db_path, start_date, end_date)

        # Turn-of-Candle 설정 (minute15 전용)
        self.toc_enabled = False
        if timeframe == 'minute15' and config['turn_of_candle']['enabled']:
            self.toc_enabled = True
            self.toc_target_minutes = config['turn_of_candle']['target_minutes']
            self.toc_vote_boost = config['turn_of_candle']['vote_boost']

    def is_turn_of_candle(self, timestamp: str) -> bool:
        """
        Turn-of-Candle 시점 감지 (minute15 전용)

        15분 캔들 전환 시점: 매시 0, 15, 30, 45분

        Args:
            timestamp: 현재 타임스탬프 (예: '2024-01-15 10:15:00')

        Returns:
            True if 현재 분이 0, 15, 30, 45
        """
        if not self.toc_enabled:
            return False

        try:
            dt = pd.to_datetime(timestamp)
            return dt.minute in self.toc_target_minutes
        except:
            return False

    def get_all_votes(self, df: pd.DataFrame, idx: int, position: str) -> Dict:
        """
        3개 Layer의 모든 투표 수집

        Args:
            df: OHLCV + indicators 데이터 (minute timeframe)
            idx: 현재 캔들 인덱스
            position: 'none' | 'long'

        Returns:
            {
                'layer1': {...},
                'layer2': {...},
                'layer3': {...},
                'total_buy_votes': int,
                'total_sell_votes': int,
                'total_hold_votes': int,
                'turn_of_candle': bool,
                'vote_boost_applied': bool
            }
        """
        if idx < 0 or idx >= len(df):
            return self._empty_votes()

        current_timestamp = df.iloc[idx]['timestamp']

        # Layer 1, 2 투표 (데이터 기반)
        layer1_votes = self.layer1.get_votes(df, idx, position)
        layer2_votes = self.layer2.get_votes(df, idx, position)

        # Layer 3 투표 (타임스탬프 기반)
        layer3_votes = self.layer3.get_votes(current_timestamp, position)

        # 총 투표 집계
        total_buy = layer1_votes['buy_votes'] + layer2_votes['buy_votes'] + layer3_votes['buy_votes']
        total_sell = layer1_votes['sell_votes'] + layer2_votes['sell_votes'] + layer3_votes['sell_votes']
        total_hold = layer1_votes['hold_votes'] + layer2_votes['hold_votes'] + layer3_votes['hold_votes']

        # Turn-of-Candle 체크
        is_toc = self.is_turn_of_candle(current_timestamp)
        vote_boost_applied = False

        # Turn-of-Candle 투표 부스트 적용
        if is_toc and position == 'none' and total_buy > 0:
            # 매수 투표에 부스트 (+1표)
            total_buy += self.toc_vote_boost
            vote_boost_applied = True

        return {
            'layer1': layer1_votes,
            'layer2': layer2_votes,
            'layer3': layer3_votes,
            'total_buy_votes': total_buy,
            'total_sell_votes': total_sell,
            'total_hold_votes': total_hold,
            'turn_of_candle': is_toc,
            'vote_boost_applied': vote_boost_applied
        }

    def get_signal(self, df: pd.DataFrame, idx: int, position: str) -> Tuple[Literal['buy', 'sell', 'hold'], Dict]:
        """
        투표 집계 후 최종 신호 결정

        규칙:
        - 매수: total_buy_votes >= min_votes AND position == 'none'
        - 매도: total_sell_votes >= min_votes AND position == 'long'
        - 관망: 그 외

        Args:
            df: OHLCV + indicators 데이터
            idx: 현재 캔들 인덱스
            position: 'none' | 'long'

        Returns:
            (signal, votes_detail)
            signal: 'buy' | 'sell' | 'hold'
            votes_detail: 투표 상세 정보
        """
        votes = self.get_all_votes(df, idx, position)

        signal = 'hold'

        # 매수 신호
        if position == 'none' and votes['total_buy_votes'] >= self.min_votes:
            signal = 'buy'

        # 매도 신호
        elif position == 'long' and votes['total_sell_votes'] >= self.min_votes:
            signal = 'sell'

        return signal, votes

    def _empty_votes(self) -> Dict:
        """빈 투표 딕셔너리 (에러 상황용)"""
        return {
            'layer1': {'buy_votes': 0, 'sell_votes': 0, 'hold_votes': 0, 'details': {}},
            'layer2': {'buy_votes': 0, 'sell_votes': 0, 'hold_votes': 0, 'details': {}},
            'layer3': {'buy_votes': 0, 'sell_votes': 0, 'hold_votes': 0, 'details': {}},
            'total_buy_votes': 0,
            'total_sell_votes': 0,
            'total_hold_votes': 0,
            'turn_of_candle': False,
            'vote_boost_applied': False
        }


if __name__ == "__main__":
    """VotingEnsemble 통합 테스트"""
    import json
    import sys
    sys.path.append('../..')

    from core import DataLoader
    import talib

    # Config 로드
    with open('config.json') as f:
        config = json.load(f)

    # 테스트 타임프레임
    timeframe = 'minute15'

    print(f"\n{'='*60}")
    print(f"v41 Voting Ensemble 통합 테스트 - {timeframe}")
    print(f"{'='*60}\n")

    # 데이터 로드
    print(f"[1/4] {timeframe} 데이터 로드 중...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(timeframe, start_date='2024-01-01', end_date='2024-01-31')

    print(f"      로드 완료: {len(df)} 캔들")

    # 지표 추가
    print(f"\n[2/4] 지표 계산 중...")
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
    df['adx'] = talib.ADX(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])
    df['plus_di'] = talib.PLUS_DI(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])
    df['minus_di'] = talib.MINUS_DI(df['high'], df['low'], df['close'], timeperiod=ind_config['adx_period'])

    # NaN 제거
    df = df.dropna().reset_index(drop=True)
    print(f"      지표 계산 완료: {len(df)} 캔들 (NaN 제거 후)")

    # VotingEnsemble 초기화
    print(f"\n[3/4] VotingEnsemble 초기화 중...")
    ensemble = VotingEnsemble(timeframe, config, db_path='../../upbit_bitcoin.db')
    print(f"      투표 규칙: {ensemble.min_votes}/{ensemble.total_votes}")
    print(f"      Turn-of-Candle: {'Enabled' if ensemble.toc_enabled else 'Disabled'}")

    # 신호 샘플링
    print(f"\n[4/4] 신호 생성 테스트...")
    buy_signals = []
    sell_signals = []
    toc_signals = 0

    for i in range(50, min(200, len(df))):
        signal, votes = ensemble.get_signal(df, i, 'none')

        if signal == 'buy':
            buy_signals.append({
                'timestamp': df.iloc[i]['timestamp'],
                'close': df.iloc[i]['close'],
                'votes': votes,
                'toc': votes['turn_of_candle']
            })

            if votes['turn_of_candle']:
                toc_signals += 1

    print(f"\n{'='*60}")
    print(f"신호 생성 결과 (150 캔들)")
    print(f"{'='*60}")
    print(f"매수 신호: {len(buy_signals)} 개")
    print(f"  - Turn-of-Candle 포함: {toc_signals} 개 ({toc_signals/max(len(buy_signals),1)*100:.1f}%)")
    print(f"  - 일반 신호: {len(buy_signals) - toc_signals} 개")

    # 상세 출력 (처음 5개)
    if buy_signals:
        print(f"\n매수 신호 상세 (처음 5개):")
        for i, sig in enumerate(buy_signals[:5]):
            print(f"\n  [{i+1}] {sig['timestamp']} (₩{sig['close']:,.0f})")
            votes = sig['votes']
            print(f"      총 투표: {votes['total_buy_votes']}/{ensemble.total_votes} 매수")
            print(f"      Layer1: {votes['layer1']['buy_votes']}/3 - {votes['layer1']['details']}")
            print(f"      Layer2: {votes['layer2']['buy_votes']}/3 - {votes['layer2']['details']}")
            print(f"      Layer3: {votes['layer3']['buy_votes']}/1 - {votes['layer3']['details']['market_state']}")
            if sig['toc']:
                print(f"      ⭐ Turn-of-Candle 부스트 적용!")

    print(f"\n{'='*60}")
    print(f"✅ VotingEnsemble 통합 테스트 완료")
    print(f"{'='*60}\n")
