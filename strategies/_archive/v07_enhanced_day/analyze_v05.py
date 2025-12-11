#!/usr/bin/env python3
"""
v05 DAY 전략 분석 및 RSI 기반 추가 진입 기회 탐색

목표:
1. v05 기존 4개 거래 상세 분석
2. RSI < 30 구간에서 놓친 진입 기회 탐색
3. RSI 임계값별 (25, 28, 30, 32, 35) 추가 진입 횟수 계산
4. 추가 진입 시 예상 수익률 추정
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from datetime import datetime
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

# v05 검증된 파라미터
POSITION_FRACTION = 0.98
TRAILING_STOP_PCT = 0.21
STOP_LOSS_PCT = 0.10
INITIAL_CAPITAL = 10_000_000
FEE_RATE = 0.0005
SLIPPAGE = 0.0002

def analyze_v05_trades(df):
    """v05 기존 4개 거래 분석"""
    print("\n" + "="*80)
    print("v05 기존 거래 분석 (4개)")
    print("="*80)

    # v05 진입 로직: EMA Golden Cross
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df['prev_ema12'] = df['ema12'].shift(1)
    df['prev_ema26'] = df['ema26'].shift(1)

    # Golden Cross 시점 탐색
    df['golden_cross'] = (
        (df['prev_ema12'] <= df['prev_ema26']) &
        (df['ema12'] > df['ema26'])
    )

    golden_cross_dates = df[df['golden_cross']].copy()
    print(f"\n총 Golden Cross 발생 횟수: {len(golden_cross_dates)}회")

    if len(golden_cross_dates) > 0:
        print("\nGolden Cross 발생 시점:")
        for idx, row in golden_cross_dates.iterrows():
            print(f"  {row['timestamp']}: {row['close']:,.0f}원 (EMA12: {row['ema12']:.0f}, EMA26: {row['ema26']:.0f})")

    return golden_cross_dates

def find_rsi_opportunities(df, rsi_thresholds=[25, 28, 30, 32, 35]):
    """RSI 기반 추가 진입 기회 탐색"""
    print("\n" + "="*80)
    print("RSI 기반 추가 진입 기회 탐색")
    print("="*80)

    # RSI 계산
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi'])

    # EMA 계산
    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()

    results = {}

    for threshold in rsi_thresholds:
        # RSI 과매도 + 상승 추세 확인 (가격 > EMA26)
        df[f'rsi_oversold_{threshold}'] = (
            (df['rsi'] < threshold) &
            (df['close'] > df['ema26'])
        )

        # 연속된 신호 제거 (첫 번째만 유효)
        df[f'rsi_entry_{threshold}'] = False
        prev_signal = False

        for i in range(len(df)):
            current_signal = df.iloc[i][f'rsi_oversold_{threshold}']

            if current_signal and not prev_signal:
                df.iloc[i, df.columns.get_loc(f'rsi_entry_{threshold}')] = True

            prev_signal = current_signal

        rsi_entries = df[df[f'rsi_entry_{threshold}']].copy()

        results[threshold] = {
            'count': len(rsi_entries),
            'dates': rsi_entries
        }

        print(f"\n--- RSI < {threshold} 진입 기회 ---")
        print(f"총 {len(rsi_entries)}회 발생")

        if len(rsi_entries) > 0:
            print("\n발생 시점:")
            for idx, row in rsi_entries.iterrows():
                print(f"  {row['timestamp']}: {row['close']:,.0f}원 (RSI: {row['rsi']:.1f}, EMA26: {row['ema26']:.0f})")

    return results

def compare_opportunities(golden_cross_dates, rsi_results):
    """Golden Cross vs RSI 진입 기회 비교"""
    print("\n" + "="*80)
    print("진입 기회 비교 분석")
    print("="*80)

    golden_dates = set(golden_cross_dates['timestamp'].dt.date)

    print(f"\n기존 Golden Cross: {len(golden_dates)}회")

    for threshold, data in rsi_results.items():
        rsi_dates = set(data['dates']['timestamp'].dt.date)

        # 추가 진입 기회 (RSI only)
        additional = rsi_dates - golden_dates

        # 중복 (both)
        overlap = rsi_dates & golden_dates

        print(f"\nRSI < {threshold}:")
        print(f"  총 진입: {len(rsi_dates)}회")
        print(f"  중복: {len(overlap)}회")
        print(f"  추가 기회: {len(additional)}회")

        if len(additional) > 0:
            print(f"  추가 진입 시점:")
            for date in sorted(additional):
                row = data['dates'][data['dates']['timestamp'].dt.date == date].iloc[0]
                print(f"    {row['timestamp']}: {row['close']:,.0f}원 (RSI: {row['rsi']:.1f})")

def estimate_additional_returns(df, rsi_threshold=30):
    """RSI 진입 추가 시 예상 수익률 추정"""
    print("\n" + "="*80)
    print(f"RSI < {rsi_threshold} 추가 진입 시 예상 수익률")
    print("="*80)

    # RSI 진입 시점
    df = MarketAnalyzer.add_indicators(df, indicators=['rsi'])
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()

    df['rsi_oversold'] = (df['rsi'] < rsi_threshold) & (df['close'] > df['ema26'])
    df['rsi_entry'] = False

    prev_signal = False
    for i in range(len(df)):
        current_signal = df.iloc[i]['rsi_oversold']
        if current_signal and not prev_signal:
            df.iloc[i, df.columns.get_loc('rsi_entry')] = True
        prev_signal = current_signal

    rsi_entries = df[df['rsi_entry']].copy()

    # 각 진입 시점에서 7일 후 수익률 계산
    print(f"\n총 {len(rsi_entries)}개 RSI 진입 기회 분석")
    print("\n개별 진입 시 7일 후 수익률:")

    returns_7d = []

    for idx, row in rsi_entries.iterrows():
        entry_date = row['timestamp']
        entry_price = row['close']
        entry_idx = df[df['timestamp'] == entry_date].index[0]

        # 7일 후 (또는 마지막 데이터)
        exit_idx = min(entry_idx + 7, len(df) - 1)
        exit_row = df.iloc[exit_idx]
        exit_price = exit_row['close']

        ret = ((exit_price - entry_price) / entry_price) * 100
        returns_7d.append(ret)

        print(f"  {entry_date.date()}: {entry_price:,.0f}원 → {exit_row['timestamp'].date()}: {exit_price:,.0f}원 ({ret:+.2f}%)")

    # 통계
    if len(returns_7d) > 0:
        avg_return = np.mean(returns_7d)
        win_rate = len([r for r in returns_7d if r > 0]) / len(returns_7d)

        print(f"\n--- 통계 ---")
        print(f"평균 수익률 (7일 보유): {avg_return:+.2f}%")
        print(f"승률: {win_rate:.1%}")
        print(f"최대 수익: {max(returns_7d):+.2f}%")
        print(f"최대 손실: {min(returns_7d):+.2f}%")

def main():
    """메인 분석 실행"""
    print("="*80)
    print("v05 DAY 전략 분석 및 RSI 기반 개선 방향 탐색")
    print("="*80)

    # 1. 데이터 로드
    print("\n[1/5] 데이터 로드 중...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            'day',
            start_date='2024-01-01',
            end_date='2024-12-30'
        )

    print(f"  로드 완료: {len(df)}개 캔들 (2024년)")

    # 2. v05 기존 거래 분석
    print("\n[2/5] v05 기존 거래 분석...")
    golden_cross_dates = analyze_v05_trades(df)

    # 3. RSI 진입 기회 탐색
    print("\n[3/5] RSI 진입 기회 탐색...")
    rsi_results = find_rsi_opportunities(df, rsi_thresholds=[25, 28, 30, 32, 35])

    # 4. 비교 분석
    print("\n[4/5] 진입 기회 비교...")
    compare_opportunities(golden_cross_dates, rsi_results)

    # 5. 예상 수익률 추정
    print("\n[5/5] 예상 수익률 추정...")
    estimate_additional_returns(df, rsi_threshold=30)

    print("\n" + "="*80)
    print("분석 완료")
    print("="*80)

if __name__ == '__main__':
    main()
