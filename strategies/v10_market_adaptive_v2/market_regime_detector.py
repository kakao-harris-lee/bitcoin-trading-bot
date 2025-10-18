#!/usr/bin/env python3
"""
Market Regime Detector for v08

시장 상황을 3가지로 분류:
1. Bull (상승장): 강한 상승 추세
2. Sideways (횡보장): 약한 추세 또는 방향성 없음
3. Bear (하락장): 강한 하락 추세
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from core.market_analyzer import MarketAnalyzer


class MarketRegimeDetector:
    """시장 상황 감지기"""

    def __init__(self, config=None):
        """
        Args:
            config: {
                'adx_threshold': 25,  # ADX >= 25 → 강한 추세
                'adx_weak': 20,       # ADX < 20 → 약한 추세
                'momentum_window': 30, # 수익률 계산 기간 (일)
                'bull_momentum': 0.15, # 상승장 임계값 (+15%)
                'bear_momentum': -0.10 # 하락장 임계값 (-10%)
            }
        """
        if config is None:
            config = {}

        self.adx_threshold = config.get('adx_threshold', 25)
        self.adx_weak = config.get('adx_weak', 20)
        self.momentum_window = config.get('momentum_window', 30)
        self.bull_momentum = config.get('bull_momentum', 0.15)
        self.bear_momentum = config.get('bear_momentum', -0.10)

    def add_indicators(self, df):
        """필요한 지표 추가"""
        # EMA
        df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
        df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()

        # ADX
        df = MarketAnalyzer.add_indicators(df, indicators=['adx'])

        # Momentum (N일 수익률)
        df['momentum'] = df['close'].pct_change(self.momentum_window)

        return df

    def detect(self, df, i):
        """
        시장 상황 감지

        Args:
            df: DataFrame with indicators
            i: current index

        Returns:
            str: 'bull' | 'sideways' | 'bear'
        """
        if i < max(self.momentum_window, 26):
            return 'sideways'  # 데이터 부족 시 보수적으로 횡보로 판단

        row = df.iloc[i]

        adx = row['adx']
        ema12 = row['ema12']
        ema26 = row['ema26']
        momentum = row['momentum']

        # 1. 강한 상승 추세 (Bull)
        if (adx >= self.adx_threshold and
            ema12 > ema26 and
            momentum > self.bull_momentum):
            return 'bull'

        # 2. 강한 하락 추세 (Bear)
        if (adx >= self.adx_threshold and
            ema12 < ema26 and
            momentum < self.bear_momentum):
            return 'bear'

        # 3. 약한 추세 또는 횡보 (Sideways)
        if adx < self.adx_weak:
            return 'sideways'

        # 4. 중간 강도 추세
        if ema12 > ema26 and momentum > 0:
            return 'bull'  # 약한 상승
        elif ema12 < ema26 and momentum < 0:
            return 'bear'  # 약한 하락
        else:
            return 'sideways'  # 혼재


def test_market_classifier():
    """시장 분류기 테스트"""
    from core.data_loader import DataLoader

    print("="*80)
    print("Market Regime Detector Test")
    print("="*80)

    # Load 2024-2025 data
    print("\n[1/3] 데이터 로드...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2025-10-17')

    print(f"  {len(df)}개 캔들 로드")

    # Add indicators
    print("\n[2/3] 지표 추가 및 시장 분류...")
    detector = MarketRegimeDetector()
    df = detector.add_indicators(df)

    # Classify all dates
    regimes = []
    for i in range(len(df)):
        regime = detector.detect(df, i)
        regimes.append(regime)

    df['regime'] = regimes

    # Statistics
    print("\n[3/3] 시장 분류 통계")
    print("="*80)

    total = len(df)
    bull_count = (df['regime'] == 'bull').sum()
    sideways_count = (df['regime'] == 'sideways').sum()
    bear_count = (df['regime'] == 'bear').sum()

    print(f"\n전체 기간: {df.iloc[0]['timestamp'].date()} ~ {df.iloc[-1]['timestamp'].date()}")
    print(f"총 {total}일\n")

    print(f"Bull (상승장):    {bull_count:>4}일 ({bull_count/total*100:>5.1f}%)")
    print(f"Sideways (횡보장): {sideways_count:>4}일 ({sideways_count/total*100:>5.1f}%)")
    print(f"Bear (하락장):    {bear_count:>4}일 ({bear_count/total*100:>5.1f}%)")

    # 2024 vs 2025
    df_2024 = df[df['timestamp'] < '2025-01-01']
    df_2025 = df[df['timestamp'] >= '2025-01-01']

    print(f"\n--- 2024년 ({len(df_2024)}일) ---")
    print(f"Bull:     {(df_2024['regime'] == 'bull').sum():>4}일 ({(df_2024['regime'] == 'bull').sum()/len(df_2024)*100:>5.1f}%)")
    print(f"Sideways: {(df_2024['regime'] == 'sideways').sum():>4}일 ({(df_2024['regime'] == 'sideways').sum()/len(df_2024)*100:>5.1f}%)")
    print(f"Bear:     {(df_2024['regime'] == 'bear').sum():>4}일 ({(df_2024['regime'] == 'bear').sum()/len(df_2024)*100:>5.1f}%)")

    print(f"\n--- 2025년 ({len(df_2025)}일) ---")
    print(f"Bull:     {(df_2025['regime'] == 'bull').sum():>4}일 ({(df_2025['regime'] == 'bull').sum()/len(df_2025)*100:>5.1f}%)")
    print(f"Sideways: {(df_2025['regime'] == 'sideways').sum():>4}일 ({(df_2025['regime'] == 'sideways').sum()/len(df_2025)*100:>5.1f}%)")
    print(f"Bear:     {(df_2025['regime'] == 'bear').sum():>4}일 ({(df_2025['regime'] == 'bear').sum()/len(df_2025)*100:>5.1f}%)")

    # Sample dates for each regime
    print("\n" + "="*80)
    print("각 시장 상황 샘플 (최근 5개)")
    print("="*80)

    for regime_type in ['bull', 'sideways', 'bear']:
        samples = df[df['regime'] == regime_type].tail(5)
        print(f"\n--- {regime_type.upper()} ---")
        for idx, row in samples.iterrows():
            print(f"  {row['timestamp'].date()}: 가격 {row['close']:,.0f}원 | "
                  f"ADX {row['adx']:.1f} | Momentum {row['momentum']*100:+.1f}%")

    print("\n" + "="*80)

    # Save classification results
    df[['timestamp', 'close', 'regime', 'adx', 'momentum']].to_csv(
        'market_classification.csv', index=False
    )
    print("\n분류 결과 저장: market_classification.csv")


if __name__ == '__main__':
    test_market_classifier()
