#!/usr/bin/env python3
"""
ichimoku.py
Category: Trend Following
Purpose: Ichimoku Cloud (일목균형표) 지표 및 신호 생성

Ichimoku Cloud:
  - 5개의 선으로 구성된 종합 지표
  - Tenkan-sen (전환선): 9일 중간값
  - Kijun-sen (기준선): 26일 중간값
  - Senkou Span A (선행스팬 A): (전환선 + 기준선) / 2, 26일 선행
  - Senkou Span B (선행스팬 B): 52일 중간값, 26일 선행
  - Chikou Span (후행스팬): 현재 가격, 26일 후행

전략:
  - 가격이 구름(Cloud) 위 → 상승 추세
  - 가격이 구름 아래 → 하락 추세
  - Tenkan-Kijun 골든크로스 + 가격 > 구름 → 강력한 매수
"""

import pandas as pd
import numpy as np


class IchimokuCloud:
    def __init__(self, tenkan_period=9, kijun_period=26, senkou_b_period=52, displacement=26):
        """
        Args:
            tenkan_period: 전환선 기간 (기본 9)
            kijun_period: 기준선 기간 (기본 26)
            senkou_b_period: 선행스팬 B 기간 (기본 52)
            displacement: 선행/후행 이동 기간 (기본 26)
        """
        self.tenkan_period = tenkan_period
        self.kijun_period = kijun_period
        self.senkou_b_period = senkou_b_period
        self.displacement = displacement

    def _midpoint(self, df, period, column='close'):
        """중간값 계산 (High + Low) / 2"""
        high = df['high'].rolling(window=period).max()
        low = df['low'].rolling(window=period).min()
        return (high + low) / 2

    def calculate(self, df):
        """
        Ichimoku Cloud 계산

        Args:
            df: DataFrame with 'high', 'low', 'close'

        Returns:
            DataFrame with added columns:
                - tenkan_sen: 전환선
                - kijun_sen: 기준선
                - senkou_span_a: 선행스팬 A
                - senkou_span_b: 선행스팬 B
                - chikou_span: 후행스팬
        """
        df = df.copy()

        # 1. Tenkan-sen (전환선): 9일 중간값
        df['tenkan_sen'] = self._midpoint(df, self.tenkan_period)

        # 2. Kijun-sen (기준선): 26일 중간값
        df['kijun_sen'] = self._midpoint(df, self.kijun_period)

        # 3. Senkou Span A (선행스팬 A): (전환선 + 기준선) / 2, 26일 선행
        df['senkou_span_a'] = ((df['tenkan_sen'] + df['kijun_sen']) / 2).shift(self.displacement)

        # 4. Senkou Span B (선행스팬 B): 52일 중간값, 26일 선행
        df['senkou_span_b'] = self._midpoint(df, self.senkou_b_period).shift(self.displacement)

        # 5. Chikou Span (후행스팬): 현재 가격, 26일 후행
        df['chikou_span'] = df['close'].shift(-self.displacement)

        # Cloud top/bottom (구름 상단/하단)
        df['cloud_top'] = df[['senkou_span_a', 'senkou_span_b']].max(axis=1)
        df['cloud_bottom'] = df[['senkou_span_a', 'senkou_span_b']].min(axis=1)

        return df

    def detect_signals(self, df, i):
        """
        Ichimoku 매매 신호 감지

        Args:
            df: DataFrame with Ichimoku indicators
            i: 현재 인덱스

        Returns:
            dict: {'signal': 'BUY'/'SELL'/'HOLD', 'reason': str, ...}
        """
        if i < max(self.senkou_b_period, self.displacement):
            return {'signal': 'HOLD', 'reason': 'INSUFFICIENT_DATA'}

        current = df.iloc[i]
        prev = df.iloc[i - 1]

        close = current['close']
        tenkan = current['tenkan_sen']
        kijun = current['kijun_sen']
        prev_tenkan = prev['tenkan_sen']
        prev_kijun = prev['kijun_sen']
        cloud_top = current['cloud_top']
        cloud_bottom = current['cloud_bottom']

        # NaN 체크
        if pd.isna(tenkan) or pd.isna(kijun) or pd.isna(cloud_top):
            return {'signal': 'HOLD', 'reason': 'INCOMPLETE_DATA'}

        # 1. Tenkan-Kijun 골든크로스 + 가격 > 구름
        tk_golden = (prev_tenkan <= prev_kijun) and (tenkan > kijun)
        above_cloud = close > cloud_top

        if tk_golden and above_cloud:
            return {
                'signal': 'BUY',
                'reason': 'ICHIMOKU_TK_GOLDEN_ABOVE_CLOUD',
                'tenkan': tenkan,
                'kijun': kijun,
                'cloud_top': cloud_top,
                'confidence': 0.9
            }

        # 2. Tenkan-Kijun 골든크로스 (구름 내부)
        if tk_golden:
            return {
                'signal': 'BUY',
                'reason': 'ICHIMOKU_TK_GOLDEN',
                'tenkan': tenkan,
                'kijun': kijun,
                'confidence': 0.65
            }

        # 3. 가격이 구름 상향 돌파
        prev_close = prev['close']
        prev_cloud_top = prev['cloud_top']
        cloud_breakout_up = (prev_close <= prev_cloud_top) and (close > cloud_top)

        if cloud_breakout_up:
            return {
                'signal': 'BUY',
                'reason': 'ICHIMOKU_CLOUD_BREAKOUT_UP',
                'cloud_top': cloud_top,
                'confidence': 0.75
            }

        # 4. Tenkan-Kijun 데드크로스 + 가격 < 구름
        tk_dead = (prev_tenkan >= prev_kijun) and (tenkan < kijun)
        below_cloud = close < cloud_bottom

        if tk_dead and below_cloud:
            return {
                'signal': 'SELL',
                'reason': 'ICHIMOKU_TK_DEAD_BELOW_CLOUD',
                'tenkan': tenkan,
                'kijun': kijun,
                'cloud_bottom': cloud_bottom,
                'confidence': 0.85
            }

        # 5. 가격이 구름 하향 돌파
        prev_cloud_bottom = prev['cloud_bottom']
        cloud_breakout_down = (prev_close >= prev_cloud_bottom) and (close < cloud_bottom)

        if cloud_breakout_down:
            return {
                'signal': 'SELL',
                'reason': 'ICHIMOKU_CLOUD_BREAKOUT_DOWN',
                'cloud_bottom': cloud_bottom,
                'confidence': 0.7
            }

        return {'signal': 'HOLD', 'reason': 'NO_SIGNAL'}

    def generate_signals(self, df):
        """
        전체 DataFrame에 대해 신호 생성

        Args:
            df: OHLCV DataFrame

        Returns:
            List of signals
        """
        df = self.calculate(df)
        signals = []

        for i in range(len(df)):
            signal = self.detect_signals(df, i)

            if signal['signal'] == 'BUY':
                signals.append({
                    'index': i,
                    'timestamp': df.iloc[i]['timestamp'] if 'timestamp' in df.columns else i,
                    'price': df.iloc[i]['close'],
                    **signal
                })

        return signals


# 사용 예시 및 테스트
if __name__ == '__main__':
    import sys
    import os

    # 프로젝트 루트로 이동
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '../../..'))
    os.chdir(project_root)
    sys.path.insert(0, project_root)

    from core.data_loader import DataLoader
    from automation.test_algorithm import AlgorithmTester

    # 데이터 로드
    with DataLoader('upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    # Ichimoku 계산
    ichimoku = IchimokuCloud()
    df = ichimoku.calculate(df)

    print("Ichimoku Cloud 지표 추가 완료:")
    print(df[['timestamp', 'close', 'tenkan_sen', 'kijun_sen', 'cloud_top', 'cloud_bottom']].tail(10))

    # 신호 생성
    signals = ichimoku.generate_signals(df)
    print(f"\n발견된 Ichimoku 신호: {len(signals)}개")
    for sig in signals[:10]:
        print(f"  {sig['timestamp']}: {sig['reason']}")

    # AlgorithmTester로 자동 테스트
    print("\n" + "="*80)
    print("AlgorithmTester로 자동 테스트")
    print("="*80)

    class IchimokuTester(AlgorithmTester):
        def _generate_signals(self, df, params):
            ichimoku = IchimokuCloud(**(params or {}))
            return ichimoku.generate_signals(df)

    tester = IchimokuTester('ichimoku')
    result = tester.run(
        timeframe='day',
        period='2024-01-01:2024-12-31',
        params={},
        trailing_stop=0.20,
        stop_loss=0.10
    )
