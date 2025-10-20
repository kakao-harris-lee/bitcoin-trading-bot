#!/usr/bin/env python3
"""
Multi-Timeframe DataLoader
- 5개 타임프레임 동시 로드
- 지표 계산 및 동기화
"""

import sys
sys.path.append('../../..')

import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
import talib
import warnings
warnings.filterwarnings('ignore')


class MultiTimeframeDataLoader:
    """다중 타임프레임 데이터 로더"""

    def __init__(self, db_path='../../../upbit_bitcoin.db'):
        self.db_path = db_path

        self.table_map = {
            'minute5': 'bitcoin_minute5',
            'minute15': 'bitcoin_minute15',
            'minute60': 'bitcoin_minute60',
            'minute240': 'bitcoin_minute240',
            'day': 'bitcoin_day'
        }

    def load_timeframe(self, timeframe, start_date=None, end_date=None):
        """단일 타임프레임 데이터 로드"""
        print(f"[{timeframe}] 데이터 로드 중...")

        conn = sqlite3.connect(self.db_path)

        table = self.table_map.get(timeframe)
        if not table:
            raise ValueError(f"Unknown timeframe: {timeframe}")

        # 쿼리 생성
        query = f"""
            SELECT timestamp,
                   opening_price as open,
                   high_price as high,
                   low_price as low,
                   trade_price as close,
                   candle_acc_trade_volume as volume
            FROM {table}
            WHERE 1=1
        """

        if start_date:
            query += f" AND timestamp >= '{start_date}'"
        if end_date:
            query += f" AND timestamp < '{end_date}'"

        query += " ORDER BY timestamp ASC"

        df = pd.read_sql_query(query, conn)
        conn.close()

        print(f"  - {len(df):,}개 캔들 로드")

        # timestamp를 datetime으로 변환
        df['timestamp'] = pd.to_datetime(df['timestamp'])

        return df

    def calculate_indicators(self, df, timeframe='minute15'):
        """기술적 지표 계산"""
        print(f"[{timeframe}] 지표 계산 중...")

        # 기본 지표
        df['rsi'] = talib.RSI(df['close'].values, timeperiod=14)
        df['mfi'] = talib.MFI(df['high'].values, df['low'].values,
                               df['close'].values, df['volume'].values,
                               timeperiod=14)

        # MACD
        df['macd'], df['macd_signal'], df['macd_hist'] = talib.MACD(
            df['close'].values, fastperiod=12, slowperiod=26, signalperiod=9
        )

        # Bollinger Bands
        df['bb_upper'], df['bb_middle'], df['bb_lower'] = talib.BBANDS(
            df['close'].values, timeperiod=20, nbdevup=2, nbdevdn=2
        )

        # ATR (변동성)
        df['atr'] = talib.ATR(df['high'].values, df['low'].values,
                               df['close'].values, timeperiod=14)

        # ADX (추세 강도)
        df['adx'] = talib.ADX(df['high'].values, df['low'].values,
                               df['close'].values, timeperiod=14)

        # EMA
        df['ema_fast'] = talib.EMA(df['close'].values, timeperiod=9)
        df['ema_slow'] = talib.EMA(df['close'].values, timeperiod=21)

        # SMA
        df['sma_20'] = talib.SMA(df['close'].values, timeperiod=20)
        df['sma_50'] = talib.SMA(df['close'].values, timeperiod=50)

        # Volume 비율
        df['volume_sma'] = talib.SMA(df['volume'].values, timeperiod=20)
        df['volume_ratio'] = df['volume'] / df['volume_sma']

        # ATR 비율 (변동성 측정)
        df['atr_sma'] = talib.SMA(df['atr'].values, timeperiod=20)
        df['atr_ratio'] = df['atr'] / df['atr_sma']

        # BB Position
        df['bb_position'] = (df['close'] - df['bb_lower']) / (df['bb_upper'] - df['bb_lower'])

        # NaN 제거
        df = df.dropna().reset_index(drop=True)

        print(f"  - 지표 계산 완료: {len(df):,}개")

        return df

    def load_all_timeframes(self, start_date=None, end_date=None):
        """모든 타임프레임 로드 및 지표 계산"""
        print(f"\n{'='*70}")
        print(f"다중 타임프레임 데이터 로드")
        print(f"{'='*70}\n")

        data = {}

        for timeframe in ['minute5', 'minute15', 'minute60', 'minute240', 'day']:
            try:
                # 데이터 로드
                df = self.load_timeframe(timeframe, start_date, end_date)

                # 지표 계산
                df = self.calculate_indicators(df, timeframe)

                # 타임프레임명 추가
                df['timeframe'] = timeframe

                data[timeframe] = df

            except Exception as e:
                print(f"[{timeframe}] 오류: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n{'='*70}")
        print(f"데이터 로드 완료")
        print(f"{'='*70}\n")

        return data

    def synchronize_timeframes(self, data):
        """타임프레임 간 타임스탬프 동기화"""
        print(f"타임프레임 동기화 중...")

        # 가장 긴 타임프레임 (day)을 기준으로
        base_timestamps = set(data['day']['timestamp'])

        for timeframe, df in data.items():
            if timeframe == 'day':
                continue

            # 상위 타임프레임 타임스탬프만 남기기
            df['aligned'] = df['timestamp'].apply(
                lambda x: x in base_timestamps
            )

        print(f"  - 동기화 완료")

        return data


def test_data_loader():
    """DataLoader 테스트"""
    loader = MultiTimeframeDataLoader()

    # 2024년 데이터 로드
    data = loader.load_all_timeframes(
        start_date='2024-01-01',
        end_date='2025-01-01'
    )

    # 결과 출력
    print(f"\n{'='*70}")
    print(f"로드된 데이터 요약")
    print(f"{'='*70}\n")

    for timeframe, df in data.items():
        print(f"{timeframe}:")
        print(f"  - 캔들 수: {len(df):,}")
        print(f"  - 기간: {df['timestamp'].min()} ~ {df['timestamp'].max()}")
        print(f"  - 컬럼: {len(df.columns)}개")
        print()


if __name__ == '__main__':
    test_data_loader()
