#!/usr/bin/env python3
"""
atr.py
Category: Volatility
Purpose: Average True Range (ATR) 계산 및 Dynamic Trailing Stop 구현

ATR 정의:
  - True Range (TR) = max(high - low, |high - prev_close|, |low - prev_close|)
  - ATR = TR의 이동평균 (보통 14일)

용도:
  - 변동성 측정
  - Dynamic Trailing Stop (ATR × 배수)
  - Position Sizing (변동성 기반)
"""

import pandas as pd
import numpy as np


class ATR:
    def __init__(self, period=14):
        """
        Args:
            period: ATR 계산 기간 (기본 14일)
        """
        self.period = period

    def calculate(self, df):
        """
        ATR 지표 계산

        Args:
            df: DataFrame with 'high', 'low', 'close' columns

        Returns:
            DataFrame with added columns:
                - tr: True Range
                - atr: Average True Range
                - atr_pct: ATR을 가격 대비 %로 표현
        """
        df = df.copy()

        # True Range 계산
        # TR = max(H - L, |H - C_prev|, |L - C_prev|)
        high_low = df['high'] - df['low']
        high_close = abs(df['high'] - df['close'].shift(1))
        low_close = abs(df['low'] - df['close'].shift(1))

        df['tr'] = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

        # ATR: TR의 이동평균 (EMA 사용)
        df['atr'] = df['tr'].ewm(span=self.period, adjust=False).mean()

        # ATR을 % 로 표현 (가격 대비)
        df['atr_pct'] = (df['atr'] / df['close']) * 100

        return df

    def get_dynamic_stop_distance(self, df, i, multiplier=2.0):
        """
        ATR 기반 Dynamic Stop Loss 거리 계산

        Args:
            df: DataFrame with ATR
            i: 현재 인덱스
            multiplier: ATR 배수 (기본 2.0)

        Returns:
            float: Stop Loss까지의 거리 (가격 단위)
        """
        if i < self.period:
            return None

        current_atr = df.iloc[i]['atr']
        return current_atr * multiplier

    def get_trailing_stop_price(self, df, i, entry_price, highest_price, multiplier=2.5, is_long=True):
        """
        ATR 기반 Trailing Stop 가격 계산

        Args:
            df: DataFrame with ATR
            i: 현재 인덱스
            entry_price: 진입 가격
            highest_price: 진입 후 최고가
            multiplier: ATR 배수
            is_long: True면 롱, False면 숏

        Returns:
            float: Trailing Stop 가격
        """
        if i < self.period:
            return None

        current_atr = df.iloc[i]['atr']

        if is_long:
            # 롱 포지션: 최고가에서 ATR × multiplier 아래
            stop_price = highest_price - (current_atr * multiplier)
        else:
            # 숏 포지션: 최저가에서 ATR × multiplier 위
            stop_price = highest_price + (current_atr * multiplier)

        return stop_price

    def adaptive_multiplier(self, df, i, base_multiplier=2.0, adx_col='adx', adx_threshold=25):
        """
        시장 상황에 따른 Adaptive ATR Multiplier

        ADX 높음 (강한 추세) → Multiplier 증가 (넓은 Stop)
        ADX 낮음 (횡보) → Multiplier 감소 (좁은 Stop)

        Args:
            df: DataFrame with ATR and ADX
            i: 현재 인덱스
            base_multiplier: 기본 배수
            adx_col: ADX 컬럼명
            adx_threshold: ADX 기준값

        Returns:
            float: 조정된 multiplier
        """
        if i < self.period or adx_col not in df.columns:
            return base_multiplier

        adx = df.iloc[i][adx_col]

        if adx >= adx_threshold + 10:  # 매우 강한 추세 (ADX >= 35)
            return base_multiplier * 1.5  # 2.0 → 3.0
        elif adx >= adx_threshold:  # 강한 추세 (ADX >= 25)
            return base_multiplier * 1.2  # 2.0 → 2.4
        elif adx < 15:  # 횡보
            return base_multiplier * 0.7  # 2.0 → 1.4
        else:
            return base_multiplier

    def position_size_by_volatility(self, capital, atr, price, risk_per_trade=0.02, atr_multiplier=2.0):
        """
        ATR 기반 Position Sizing

        변동성 높을 때 → 포지션 축소
        변동성 낮을 때 → 포지션 증가

        Args:
            capital: 현재 자본
            atr: ATR 값
            price: 현재 가격
            risk_per_trade: 거래당 리스크 비율 (기본 2%)
            atr_multiplier: Stop Loss까지 ATR 배수

        Returns:
            int: 매수할 수량 (BTC 기준)
        """
        # 거래당 허용 손실액
        risk_amount = capital * risk_per_trade

        # Stop Loss 거리
        stop_distance = atr * atr_multiplier

        # 수량 계산
        # risk_amount = quantity × stop_distance
        # quantity = risk_amount / stop_distance
        quantity = risk_amount / stop_distance

        return quantity


class ATRTrailingStop:
    """
    ATR 기반 Trailing Stop 전략

    v07의 고정 Trailing Stop 10%를 ATR 기반 Dynamic Stop으로 대체
    """

    def __init__(self, atr_multiplier=2.5, use_adaptive=True):
        """
        Args:
            atr_multiplier: ATR 배수 (기본 2.5)
            use_adaptive: ADX 기반 Adaptive Multiplier 사용 여부
        """
        self.atr_multiplier = atr_multiplier
        self.use_adaptive = use_adaptive
        self.atr = ATR(period=14)

    def should_exit(self, df, i, entry_price, highest_price, adx=None):
        """
        Trailing Stop 청산 여부 판단

        Args:
            df: DataFrame with ATR
            i: 현재 인덱스
            entry_price: 진입 가격
            highest_price: 진입 후 최고가
            adx: 현재 ADX 값 (옵션)

        Returns:
            dict: {'exit': bool, 'reason': str, 'stop_price': float}
        """
        if i < 14:
            return {'exit': False, 'reason': 'INSUFFICIENT_DATA', 'stop_price': None}

        # Adaptive Multiplier 계산
        multiplier = self.atr_multiplier
        if self.use_adaptive and adx is not None:
            if adx >= 35:
                multiplier = self.atr_multiplier * 1.5  # 강한 추세: 넓은 Stop
            elif adx < 15:
                multiplier = self.atr_multiplier * 0.7  # 횡보: 좁은 Stop

        # Trailing Stop 가격 계산
        stop_price = self.atr.get_trailing_stop_price(
            df, i, entry_price, highest_price, multiplier=multiplier
        )

        if stop_price is None:
            return {'exit': False, 'reason': 'CALCULATION_ERROR', 'stop_price': None}

        current_price = df.iloc[i]['close']

        # 청산 판단
        if current_price <= stop_price:
            return {
                'exit': True,
                'reason': f'ATR_TRAILING_STOP (×{multiplier:.1f})',
                'stop_price': stop_price,
                'drop_pct': ((highest_price - current_price) / highest_price) * 100
            }

        return {'exit': False, 'reason': 'HOLDING', 'stop_price': stop_price}


# 사용 예시
if __name__ == '__main__':
    import sys
    sys.path.append('../../..')
    from core.data_loader import DataLoader
    from core.market_analyzer import MarketAnalyzer

    # 데이터 로드
    with DataLoader('../../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    # ADX 추가
    df = MarketAnalyzer.add_indicators(df, indicators=['adx'])

    # ATR 계산
    atr = ATR(period=14)
    df = atr.calculate(df)

    print("ATR 지표 추가 완료:")
    print(df[['timestamp', 'close', 'tr', 'atr', 'atr_pct', 'adx']].tail(10))

    # v07 거래 1번 재현: 02-08 진입 → 03-19 청산
    # 고정 Trailing Stop 10% vs ATR Dynamic Stop 비교
    print("\n" + "="*80)
    print("v07 거래 1번 분석: 02-08 진입 → 03-19 청산 (+49.22%)")
    print("="*80)

    entry_date = '2024-02-08'
    exit_date = '2024-03-19'

    entry_idx = df[df['timestamp'].astype(str).str.contains(entry_date)].index[0]
    exit_idx = df[df['timestamp'].astype(str).str.contains(exit_date)].index[0]

    entry_price = df.iloc[entry_idx]['close']
    exit_price = df.iloc[exit_idx]['close']

    print(f"\n진입: {entry_date} @ {entry_price:,.0f}원")
    print(f"청산: {exit_date} @ {exit_price:,.0f}원")
    print(f"수익: +{((exit_price - entry_price) / entry_price) * 100:.2f}%")

    # ATR Trailing Stop 시뮬레이션
    atr_ts = ATRTrailingStop(atr_multiplier=2.5, use_adaptive=True)
    highest_price = entry_price

    print(f"\nATR Trailing Stop 추적:")
    for i in range(entry_idx, exit_idx + 1):
        curr_price = df.iloc[i]['close']
        if curr_price > highest_price:
            highest_price = curr_price

        result = atr_ts.should_exit(df, i, entry_price, highest_price, adx=df.iloc[i]['adx'])

        if i % 7 == 0 or result['exit']:  # 주간 샘플링
            print(f"  {df.iloc[i]['timestamp']}: 가격={curr_price:,.0f}, "
                  f"Stop={result['stop_price']:,.0f}, "
                  f"최고가={highest_price:,.0f}, "
                  f"상태={result['reason']}")

            if result['exit']:
                print(f"\n  → ATR Stop으로 청산됨! (Drop: {result['drop_pct']:.2f}%)")
                break
