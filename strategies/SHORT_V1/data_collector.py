#!/usr/bin/env python3
"""
SHORT_V1 - 바이낸스 선물 데이터 수집 모듈
BTC/USDT 무기한 선물 캔들스틱 및 펀딩비 데이터 수집
"""

import os
import sys
import time
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from pathlib import Path

# binance-python 라이브러리 사용
try:
    from binance.client import Client
    from binance.exceptions import BinanceAPIException
except ImportError:
    print("binance 라이브러리가 설치되지 않았습니다: pip install python-binance")
    sys.exit(1)

from dotenv import load_dotenv


def find_and_load_env():
    """프로젝트 루트에서 .env 파일 검색 및 로드"""
    # 검색 경로 (우선순위 순)
    search_paths = [
        Path(__file__).parent / '.env',                    # strategies/SHORT_V1/.env
        Path(__file__).parent.parent.parent / '.env',      # cairo/.env
        Path(__file__).parent.parent.parent.parent / '.env',  # bitcoin-trading-bot/.env
        Path.home() / '.env',                              # 홈 디렉토리
    ]

    for env_path in search_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f".env 로드: {env_path}")
            return True

    # 기본 load_dotenv() 시도
    load_dotenv()
    return False


class BinanceDataCollector:
    """바이낸스 선물 데이터 수집기"""

    TIMEFRAME_MAP = {
        '1m': Client.KLINE_INTERVAL_1MINUTE,
        '5m': Client.KLINE_INTERVAL_5MINUTE,
        '15m': Client.KLINE_INTERVAL_15MINUTE,
        '30m': Client.KLINE_INTERVAL_30MINUTE,
        '1h': Client.KLINE_INTERVAL_1HOUR,
        '2h': Client.KLINE_INTERVAL_2HOUR,
        '4h': Client.KLINE_INTERVAL_4HOUR,
        '6h': Client.KLINE_INTERVAL_6HOUR,
        '8h': Client.KLINE_INTERVAL_8HOUR,
        '12h': Client.KLINE_INTERVAL_12HOUR,
        '1d': Client.KLINE_INTERVAL_1DAY,
        '3d': Client.KLINE_INTERVAL_3DAY,
        '1w': Client.KLINE_INTERVAL_1WEEK,
    }

    def __init__(self, api_key: Optional[str] = None, api_secret: Optional[str] = None):
        """
        초기화

        Args:
            api_key: 바이낸스 API 키 (없으면 .env에서 로드)
            api_secret: 바이낸스 API 시크릿 (없으면 .env에서 로드)
        """
        find_and_load_env()

        self.api_key = api_key or os.getenv('BINANCE_API_KEY')
        self.api_secret = api_secret or os.getenv('BINANCE_API_SECRET')

        # API 키 없이도 public 데이터는 수집 가능
        if self.api_key and self.api_secret:
            self.client = Client(self.api_key, self.api_secret)
            print("API 키로 인증됨")
        else:
            self.client = Client()
            print("비인증 모드 (public 데이터만 수집 가능)")

        self.symbol = 'BTCUSDT'

    def get_futures_klines(
        self,
        start_date: str,
        end_date: str,
        timeframe: str = '4h',
        save_path: Optional[str] = None
    ) -> pd.DataFrame:
        """
        선물 캔들스틱 데이터 수집

        Args:
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
            timeframe: 타임프레임 (1m, 5m, 15m, 30m, 1h, 4h, 1d 등)
            save_path: CSV 저장 경로 (선택)

        Returns:
            캔들스틱 데이터프레임
        """
        if timeframe not in self.TIMEFRAME_MAP:
            raise ValueError(f"지원하지 않는 타임프레임: {timeframe}")

        interval = self.TIMEFRAME_MAP[timeframe]

        # 날짜 변환
        start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)

        print(f"데이터 수집: {self.symbol} {timeframe} ({start_date} ~ {end_date})")

        all_klines = []
        current_start = start_ts

        while current_start < end_ts:
            try:
                # 바이낸스 선물 API 호출
                klines = self.client.futures_klines(
                    symbol=self.symbol,
                    interval=interval,
                    startTime=current_start,
                    endTime=end_ts,
                    limit=1500  # 최대 1500개
                )

                if not klines:
                    break

                all_klines.extend(klines)

                # 다음 시작 시간 설정
                last_close_time = klines[-1][6]  # Close time
                current_start = last_close_time + 1

                print(f"  수집: {len(all_klines)}개 캔들")

                # API 제한 방지
                time.sleep(0.1)

            except BinanceAPIException as e:
                print(f"API 에러: {e}")
                time.sleep(1)
                continue

        if not all_klines:
            print("데이터가 없습니다")
            return pd.DataFrame()

        # 데이터프레임 변환
        df = pd.DataFrame(all_klines, columns=[
            'open_time', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])

        # 타입 변환
        df['open_time'] = pd.to_datetime(df['open_time'], unit='ms')
        df['close_time'] = pd.to_datetime(df['close_time'], unit='ms')

        numeric_cols = ['open', 'high', 'low', 'close', 'volume', 'quote_volume']
        for col in numeric_cols:
            df[col] = df[col].astype(float)

        df['trades'] = df['trades'].astype(int)

        # 인덱스 설정
        df.set_index('open_time', inplace=True)
        df.index.name = 'timestamp'

        # 불필요한 컬럼 제거
        df = df[['open', 'high', 'low', 'close', 'volume', 'quote_volume', 'trades']]

        # 중복 제거
        df = df[~df.index.duplicated(keep='first')]

        print(f"총 {len(df)}개 캔들 수집 완료")

        # 저장
        if save_path:
            df.to_csv(save_path)
            print(f"저장: {save_path}")

        return df

    def get_funding_rates(
        self,
        start_date: str,
        end_date: str,
        save_path: Optional[str] = None
    ) -> pd.DataFrame:
        """
        펀딩비 히스토리 수집

        Args:
            start_date: 시작일 (YYYY-MM-DD)
            end_date: 종료일 (YYYY-MM-DD)
            save_path: CSV 저장 경로 (선택)

        Returns:
            펀딩비 데이터프레임
        """
        start_ts = int(datetime.strptime(start_date, '%Y-%m-%d').timestamp() * 1000)
        end_ts = int(datetime.strptime(end_date, '%Y-%m-%d').timestamp() * 1000)

        print(f"펀딩비 수집: {self.symbol} ({start_date} ~ {end_date})")

        all_funding = []
        current_start = start_ts

        while current_start < end_ts:
            try:
                funding_rates = self.client.futures_funding_rate(
                    symbol=self.symbol,
                    startTime=current_start,
                    endTime=end_ts,
                    limit=1000
                )

                if not funding_rates:
                    break

                all_funding.extend(funding_rates)

                # 다음 시작 시간 설정
                last_time = funding_rates[-1]['fundingTime']
                current_start = last_time + 1

                print(f"  수집: {len(all_funding)}개 펀딩비")

                time.sleep(0.1)

            except BinanceAPIException as e:
                print(f"API 에러: {e}")
                time.sleep(1)
                continue

        if not all_funding:
            print("펀딩비 데이터가 없습니다")
            return pd.DataFrame()

        # 데이터프레임 변환
        df = pd.DataFrame(all_funding)
        df['timestamp'] = pd.to_datetime(df['fundingTime'], unit='ms')
        df['funding_rate'] = df['fundingRate'].astype(float)
        df['mark_price'] = df['markPrice'].astype(float) if 'markPrice' in df.columns else np.nan

        df = df[['timestamp', 'funding_rate', 'mark_price']]
        df.set_index('timestamp', inplace=True)

        # 중복 제거
        df = df[~df.index.duplicated(keep='first')]

        print(f"총 {len(df)}개 펀딩비 수집 완료")

        if save_path:
            df.to_csv(save_path)
            print(f"저장: {save_path}")

        return df

    def merge_klines_funding(
        self,
        klines_df: pd.DataFrame,
        funding_df: pd.DataFrame
    ) -> pd.DataFrame:
        """
        캔들스틱과 펀딩비 데이터 병합

        Args:
            klines_df: 캔들스틱 데이터프레임
            funding_df: 펀딩비 데이터프레임

        Returns:
            병합된 데이터프레임
        """
        if klines_df.empty:
            print("캔들 데이터가 비어있습니다")
            return klines_df

        merged = klines_df.copy()

        if funding_df.empty:
            merged['funding_rate'] = 0.0
            return merged

        try:
            # 펀딩비 인덱스 정렬 및 중복 제거
            funding_df = funding_df.sort_index()
            funding_df = funding_df[~funding_df.index.duplicated(keep='first')]

            # merge_asof를 사용한 효율적인 병합
            # 각 캔들 시점에서 가장 최근의 펀딩비를 매핑
            merged = merged.reset_index()
            funding_reset = funding_df.reset_index()

            # timestamp 컬럼명 통일
            if 'timestamp' not in merged.columns:
                merged = merged.rename(columns={merged.columns[0]: 'timestamp'})

            merged = pd.merge_asof(
                merged.sort_values('timestamp'),
                funding_reset[['timestamp', 'funding_rate']].sort_values('timestamp'),
                on='timestamp',
                direction='backward'
            )

            merged = merged.set_index('timestamp')
            merged['funding_rate'] = merged['funding_rate'].fillna(0.0)

            print(f"펀딩비 병합 완료: {len(merged)}개 캔들")

        except Exception as e:
            print(f"펀딩비 병합 오류 (기본값 0 사용): {e}")
            merged['funding_rate'] = 0.0

        return merged


def collect_all_data(
    start_date: str = '2022-01-01',
    end_date: str = '2024-12-31',
    timeframe: str = '4h'
) -> pd.DataFrame:
    """
    전체 데이터 수집 편의 함수

    Args:
        start_date: 시작일
        end_date: 종료일
        timeframe: 타임프레임

    Returns:
        캔들 + 펀딩비 병합 데이터
    """
    collector = BinanceDataCollector()

    # 저장 경로
    data_dir = Path(__file__).parent / 'results'
    data_dir.mkdir(exist_ok=True)

    # 캔들 데이터 수집
    klines_path = data_dir / f'btcusdt_{timeframe}_{start_date}_{end_date}.csv'
    klines_df = collector.get_futures_klines(
        start_date=start_date,
        end_date=end_date,
        timeframe=timeframe,
        save_path=str(klines_path)
    )

    # 펀딩비 수집
    funding_path = data_dir / f'funding_rate_{start_date}_{end_date}.csv'
    funding_df = collector.get_funding_rates(
        start_date=start_date,
        end_date=end_date,
        save_path=str(funding_path)
    )

    # 병합
    merged_df = collector.merge_klines_funding(klines_df, funding_df)

    merged_path = data_dir / f'btcusdt_{timeframe}_with_funding_{start_date}_{end_date}.csv'
    merged_df.to_csv(merged_path)
    print(f"\n병합 데이터 저장: {merged_path}")

    return merged_df


if __name__ == '__main__':
    # 3년치 데이터 수집 (2022-2024)
    df = collect_all_data(
        start_date='2022-01-01',
        end_date='2024-12-31',
        timeframe='4h'
    )

    print(f"\n=== 데이터 요약 ===")
    print(f"기간: {df.index.min()} ~ {df.index.max()}")
    print(f"캔들 수: {len(df)}")
    print(f"\n첫 5행:")
    print(df.head())
    print(f"\n마지막 5행:")
    print(df.tail())
