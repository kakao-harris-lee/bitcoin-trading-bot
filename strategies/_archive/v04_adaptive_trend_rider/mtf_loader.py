#!/usr/bin/env python3
"""
mtf_loader.py
Multi-Timeframe Data Loader

핵심 기능:
1. Day 타임프레임 (추세 판단용)
2. Trade 타임프레임 (minute240 등, 실제 거래용)
3. 시간 동기화 (Day의 현재 상태를 Trade 캔들마다 매칭)
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Tuple, Dict
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer


class MTFLoader:
    """Multi-Timeframe Data Loader"""

    def __init__(self, db_path: str = '../../upbit_bitcoin.db'):
        """
        Args:
            db_path: DB 경로
        """
        self.db_path = db_path

    def load_with_day_context(
        self,
        trade_timeframe: str,
        start_date: str,
        end_date: str = None
    ) -> Tuple[pd.DataFrame, pd.DataFrame]:
        """
        Day + Trade 타임프레임 동시 로드 및 동기화

        Args:
            trade_timeframe: 실제 거래 타임프레임 (minute5, minute240 등)
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (None이면 최신까지)

        Returns:
            (df_trade, df_day):
                - df_trade: 거래 타임프레임 (지표 포함, 'day_idx' 컬럼 추가)
                - df_day: Day 타임프레임 (지표 포함)
        """
        with DataLoader(self.db_path) as loader:
            # 1. Day 데이터 로드 (추세 판단용)
            df_day = loader.load_timeframe(
                'day',
                start_date=start_date,
                end_date=end_date
            )

            # 2. Trade 데이터 로드
            df_trade = loader.load_timeframe(
                trade_timeframe,
                start_date=start_date,
                end_date=end_date
            )

        # === 지표 추가 ===

        # Day: SMA, EMA, ADX, RSI, ATR
        df_day = MarketAnalyzer.add_indicators(
            df_day,
            indicators=['sma', 'ema', 'adx', 'rsi', 'atr']
        )

        # EMA 20, 50 수동 추가 (MarketAnalyzer는 12, 26만 제공)
        import talib
        df_day['ema_20'] = talib.EMA(df_day['close'], timeperiod=20)
        df_day['ema_50'] = talib.EMA(df_day['close'], timeperiod=50)

        # Trade: RSI, MACD, BB, ATR
        df_trade = MarketAnalyzer.add_indicators(
            df_trade,
            indicators=['rsi', 'macd', 'bb', 'atr']
        )

        # === 시간 동기화: Trade → Day 매칭 ===
        df_trade = self._sync_day_index(df_trade, df_day)

        return df_trade, df_day

    def _sync_day_index(
        self,
        df_trade: pd.DataFrame,
        df_day: pd.DataFrame
    ) -> pd.DataFrame:
        """
        Trade 데이터에 'day_idx' 컬럼 추가
        각 Trade 캔들이 어느 Day 캔들에 속하는지 인덱스 저장

        Args:
            df_trade: 거래 타임프레임 데이터
            df_day: Day 타임프레임 데이터

        Returns:
            df_trade (day_idx 컬럼 추가됨)
        """
        # Day 데이터의 날짜 인덱스 생성
        df_day = df_day.reset_index(drop=True)
        df_day['date'] = pd.to_datetime(df_day['timestamp']).dt.date

        # Trade 데이터의 날짜 추출
        df_trade = df_trade.reset_index(drop=True)
        df_trade['date'] = pd.to_datetime(df_trade['timestamp']).dt.date

        # 매핑 딕셔너리 생성: {날짜: day_idx}
        date_to_idx = {}
        for idx, row in df_day.iterrows():
            date_to_idx[row['date']] = idx

        # Trade 캔들마다 day_idx 할당
        day_indices = []
        for trade_date in df_trade['date']:
            # 정확한 날짜 매칭 (없으면 -1)
            day_idx = date_to_idx.get(trade_date, -1)

            # 날짜가 없으면 이전 유효한 Day 인덱스 사용
            if day_idx == -1:
                # 이전 Trade 캔들의 day_idx 재사용 (있다면)
                if len(day_indices) > 0 and day_indices[-1] != -1:
                    day_idx = day_indices[-1]

            day_indices.append(day_idx)

        df_trade['day_idx'] = day_indices

        # 날짜 컬럼 제거 (필요 없음)
        df_trade = df_trade.drop(columns=['date'])
        if 'date' in df_day.columns:
            df_day = df_day.drop(columns=['date'])

        return df_trade

    def get_day_row(
        self,
        df_day: pd.DataFrame,
        df_trade: pd.DataFrame,
        i_trade: int
    ) -> Dict:
        """
        현재 Trade 인덱스에 해당하는 Day 데이터 반환

        Args:
            df_day: Day 데이터프레임
            df_trade: Trade 데이터프레임
            i_trade: 현재 Trade 인덱스

        Returns:
            Day 캔들 데이터 (dict)
            없으면 None
        """
        day_idx = df_trade.iloc[i_trade]['day_idx']

        if day_idx == -1 or day_idx >= len(df_day):
            return None

        return df_day.iloc[int(day_idx)].to_dict()
