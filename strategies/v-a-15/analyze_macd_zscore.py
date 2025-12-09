#!/usr/bin/env python3
"""
MACD z-score 분석
통계적으로 유의미한 MACD 신호 찾기
"""

import sys
from pathlib import Path
project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pandas as pd
import numpy as np
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

def calculate_macd_zscore(df: pd.DataFrame, lookback: int = 60):
    """
    MACD z-score 계산

    Args:
        df: DataFrame with MACD
        lookback: 과거 데이터 기간 (기본 60일)

    Returns:
        DataFrame with z-score columns
    """
    df = df.copy()

    # MACD - Signal 차이 (Histogram)
    df['macd_histogram'] = df['macd'] - df['macd_signal']

    # Rolling 평균 및 표준편차
    df['macd_mean'] = df['macd'].rolling(window=lookback).mean()
    df['macd_std'] = df['macd'].rolling(window=lookback).std()

    df['histogram_mean'] = df['macd_histogram'].rolling(window=lookback).mean()
    df['histogram_std'] = df['macd_histogram'].rolling(window=lookback).std()

    # z-score 계산
    df['macd_zscore'] = (df['macd'] - df['macd_mean']) / df['macd_std']
    df['histogram_zscore'] = (df['macd_histogram'] - df['histogram_mean']) / df['histogram_std']

    # NaN 처리
    df['macd_zscore'] = df['macd_zscore'].fillna(0)
    df['histogram_zscore'] = df['histogram_zscore'].fillna(0)

    return df

def analyze_zscore_signals(df: pd.DataFrame):
    """z-score 기반 신호 분석"""

    print("="*70)
    print("  MACD z-score 분석 (2024)")
    print("="*70)

    # 기본 통계
    print(f"\n1. MACD z-score 분포:")
    print(f"  평균: {df['macd_zscore'].mean():.2f}")
    print(f"  표준편차: {df['macd_zscore'].std():.2f}")
    print(f"  최대: {df['macd_zscore'].max():.2f}")
    print(f"  최소: {df['macd_zscore'].min():.2f}")

    print(f"\n2. Histogram z-score 분포:")
    print(f"  평균: {df['histogram_zscore'].mean():.2f}")
    print(f"  표준편차: {df['histogram_zscore'].std():.2f}")
    print(f"  최대: {df['histogram_zscore'].max():.2f}")
    print(f"  최소: {df['histogram_zscore'].min():.2f}")

    # z-score 임계값별 신호 수
    print(f"\n3. z-score 임계값별 신호 수:")

    thresholds = [0.5, 1.0, 1.5, 2.0, 2.5]

    print(f"\n  MACD z-score:")
    for threshold in thresholds:
        count = len(df[df['macd_zscore'] > threshold])
        pct = count / len(df) * 100
        print(f"    > {threshold}: {count}일 ({pct:.1f}%)")

    print(f"\n  Histogram z-score:")
    for threshold in thresholds:
        count = len(df[df['histogram_zscore'] > threshold])
        pct = count / len(df) * 100
        print(f"    > {threshold}: {count}일 ({pct:.1f}%)")

    # Golden Cross 분석
    print(f"\n4. Golden Cross + z-score 조합:")

    golden_crosses = []
    for i in range(1, len(df)):
        prev_macd = df.iloc[i-1]['macd']
        prev_signal = df.iloc[i-1]['macd_signal']
        curr_macd = df.iloc[i]['macd']
        curr_signal = df.iloc[i]['macd_signal']

        # Golden Cross
        if (prev_macd <= prev_signal) and (curr_macd > curr_signal):
            golden_crosses.append({
                'date': df.iloc[i]['timestamp'],
                'macd_zscore': df.iloc[i]['macd_zscore'],
                'histogram_zscore': df.iloc[i]['histogram_zscore'],
                'macd': curr_macd,
                'signal': curr_signal
            })

    print(f"\n  총 Golden Cross: {len(golden_crosses)}회")

    if golden_crosses:
        gc_df = pd.DataFrame(golden_crosses)

        for threshold in [0.5, 1.0, 1.5, 2.0]:
            count_macd = len(gc_df[gc_df['macd_zscore'] > threshold])
            count_hist = len(gc_df[gc_df['histogram_zscore'] > threshold])

            print(f"\n  z-score > {threshold}:")
            print(f"    MACD z-score: {count_macd}회")
            print(f"    Histogram z-score: {count_hist}회")

    # 현재 Trend Enhanced 시그널 분석
    print(f"\n5. 현재 Trend Enhanced 시그널과 z-score:")

    # MACD > Signal인 날 중 ADX >= 15, RSI < 70
    trend_signals = df[
        (df['macd'] > df['macd_signal']) &
        (df['adx'] >= 15) &
        (df['rsi'] < 70)
    ].copy()

    print(f"\n  현재 조건 (MACD > Signal + ADX >= 15 + RSI < 70): {len(trend_signals)}일")

    if len(trend_signals) > 0:
        print(f"\n  이 중 z-score 분포:")
        for threshold in [0.5, 1.0, 1.5, 2.0]:
            count_macd = len(trend_signals[trend_signals['macd_zscore'] > threshold])
            count_hist = len(trend_signals[trend_signals['histogram_zscore'] > threshold])
            pct_macd = count_macd / len(trend_signals) * 100
            pct_hist = count_hist / len(trend_signals) * 100

            print(f"\n    z-score > {threshold}:")
            print(f"      MACD z-score: {count_macd}일 ({pct_macd:.1f}%)")
            print(f"      Histogram z-score: {count_hist}일 ({pct_hist:.1f}%)")

    # 실제 거래 분석
    print(f"\n6. 실제 거래된 시그널의 z-score:")

    trade_dates = [
        '2024-05-23', '2024-07-25', '2024-07-27', '2024-07-29',
        '2024-08-03', '2024-08-05', '2024-08-31', '2024-09-30',
        '2024-10-21', '2024-10-25', '2024-10-31', '2024-11-01',
        '2024-12-18', '2024-12-19'
    ]

    print(f"\n  {'Date':<12} {'Strategy':<15} {'MACD z':<8} {'Hist z':<8} {'Result'}")
    print(f"  {'-'*60}")

    for date_str in trade_dates:
        row = df[df['timestamp'].dt.strftime('%Y-%m-%d') == date_str]
        if len(row) > 0:
            row = row.iloc[0]
            macd_z = row['macd_zscore']
            hist_z = row['histogram_zscore']

            # Strategy 판단
            if row['macd'] > row['macd_signal']:
                strategy = 'trend_enhanced'
            else:
                strategy = 'stoch/rsi_bb'

            print(f"  {date_str:<12} {strategy:<15} {macd_z:>7.2f} {hist_z:>7.2f}")

def main():
    db_path = Path(__file__).parent.parent.parent / 'upbit_bitcoin.db'

    with DataLoader(str(db_path)) as loader:
        df = loader.load_timeframe('day', '2024-01-01', '2024-12-31')

    if df is None:
        print("❌ 데이터 로드 실패")
        return

    # 지표 추가
    df = MarketAnalyzer.add_indicators(df, ['rsi', 'macd', 'adx'])

    # z-score 계산
    df = calculate_macd_zscore(df, lookback=60)

    # 분석
    analyze_zscore_signals(df)

    # CSV 저장
    output_file = Path(__file__).parent / 'results' / 'macd_zscore_analysis.csv'
    output_file.parent.mkdir(exist_ok=True)

    df_save = df[['timestamp', 'close', 'macd', 'macd_signal', 'macd_histogram',
                   'macd_zscore', 'histogram_zscore', 'adx', 'rsi']].copy()
    df_save.to_csv(output_file, index=False)

    print(f"\n✅ 분석 결과 저장: {output_file}")

if __name__ == '__main__':
    main()
