#!/usr/bin/env python3
"""
대안적 진입 조건 탐색

RSI < 30이 작동하지 않으므로 다른 방법 모색:
1. Price dip (N일 최고가 대비 X% 하락)
2. Pullback to EMA (가격이 EMA26까지 하락)
3. MACD 골든크로스
4. ADX 강한 추세 + 가격 조정
5. RSI 상대적 저점 (N일 중 최저 RSI)
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from datetime import datetime
from core.data_loader import DataLoader
from core.market_analyzer import MarketAnalyzer

def analyze_price_dips(df, lookback=20, dip_pcts=[0.05, 0.10, 0.15, 0.20]):
    """N일 최고가 대비 X% 하락 시점 탐색"""
    print("\n" + "="*80)
    print(f"가격 조정(Dip) 진입 기회 탐색 (최근 {lookback}일 최고가 대비)")
    print("="*80)

    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()
    df[f'high_{lookback}d'] = df['high'].rolling(lookback).max()

    for dip_pct in dip_pcts:
        df[f'dip_{int(dip_pct*100)}pct'] = (
            (df['close'] < df[f'high_{lookback}d'] * (1 - dip_pct)) &
            (df['close'] > df['ema26'])  # 상승 추세 유지
        )

        # 연속 신호 제거
        df[f'dip_entry_{int(dip_pct*100)}pct'] = False
        prev_signal = False

        for i in range(len(df)):
            current_signal = df.iloc[i][f'dip_{int(dip_pct*100)}pct']
            if current_signal and not prev_signal:
                df.iloc[i, df.columns.get_loc(f'dip_entry_{int(dip_pct*100)}pct')] = True
            prev_signal = current_signal

        dip_entries = df[df[f'dip_entry_{int(dip_pct*100)}pct']].copy()

        print(f"\n--- {lookback}일 최고가 대비 -{dip_pct*100:.0f}% 하락 ---")
        print(f"총 {len(dip_entries)}회 발생")

        if len(dip_entries) > 0:
            print("\n발생 시점:")
            for idx, row in dip_entries.iterrows():
                high_20d = row[f'high_{lookback}d']
                dip_from_high = ((row['close'] - high_20d) / high_20d) * 100
                print(f"  {row['timestamp'].date()}: {row['close']:,.0f}원 ({lookback}일 최고: {high_20d:,.0f}원, {dip_from_high:+.1f}%)")

def analyze_pullback_to_ema(df):
    """EMA26까지 하락 후 반등 시점 탐색"""
    print("\n" + "="*80)
    print("EMA26 Pullback 진입 기회 탐색")
    print("="*80)

    df['ema12'] = df['close'].ewm(span=12, adjust=False).mean()
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()

    # 조건: 가격이 EMA26 근처 (±2%) + EMA12 > EMA26
    df['near_ema26'] = (
        (df['close'] >= df['ema26'] * 0.98) &
        (df['close'] <= df['ema26'] * 1.02) &
        (df['ema12'] > df['ema26'])
    )

    # 연속 신호 제거
    df['pullback_entry'] = False
    prev_signal = False

    for i in range(len(df)):
        current_signal = df.iloc[i]['near_ema26']
        if current_signal and not prev_signal:
            df.iloc[i, df.columns.get_loc('pullback_entry')] = True
        prev_signal = current_signal

    pullback_entries = df[df['pullback_entry']].copy()

    print(f"\n총 {len(pullback_entries)}회 발생")

    if len(pullback_entries) > 0:
        print("\n발생 시점:")
        for idx, row in pullback_entries.iterrows():
            dist_to_ema26 = ((row['close'] - row['ema26']) / row['ema26']) * 100
            print(f"  {row['timestamp'].date()}: {row['close']:,.0f}원 (EMA26: {row['ema26']:,.0f}원, 거리: {dist_to_ema26:+.2f}%)")

def analyze_macd_signals(df):
    """MACD 골든크로스 진입 기회"""
    print("\n" + "="*80)
    print("MACD 골든크로스 진입 기회 탐색")
    print("="*80)

    df = MarketAnalyzer.add_indicators(df, indicators=['macd'])

    df['prev_macd'] = df['macd'].shift(1)
    df['prev_macd_signal'] = df['macd_signal'].shift(1)

    df['macd_golden_cross'] = (
        (df['prev_macd'] <= df['prev_macd_signal']) &
        (df['macd'] > df['macd_signal'])
    )

    macd_entries = df[df['macd_golden_cross']].copy()

    print(f"\n총 {len(macd_entries)}회 발생")

    if len(macd_entries) > 0:
        print("\n발생 시점:")
        for idx, row in macd_entries.iterrows():
            print(f"  {row['timestamp'].date()}: {row['close']:,.0f}원 (MACD: {row['macd']:.0f}, Signal: {row['macd_signal']:.0f})")

    return macd_entries

def analyze_rsi_relative_lows(df, lookback=14):
    """N일 중 상대적 RSI 저점 탐색"""
    print("\n" + "="*80)
    print(f"상대적 RSI 저점 진입 기회 탐색 ({lookback}일 중 최저)")
    print("="*80)

    df = MarketAnalyzer.add_indicators(df, indicators=['rsi'])
    df['ema26'] = df['close'].ewm(span=26, adjust=False).mean()

    df[f'rsi_min_{lookback}d'] = df['rsi'].rolling(lookback).min()

    # 조건: 현재 RSI가 N일 중 최저 + 상승 추세
    df['rsi_relative_low'] = (
        (df['rsi'] == df[f'rsi_min_{lookback}d']) &
        (df['close'] > df['ema26']) &
        (df['rsi'] < 50)  # RSI 중립 이하
    )

    # 연속 신호 제거
    df['rsi_low_entry'] = False
    prev_signal = False

    for i in range(len(df)):
        current_signal = df.iloc[i]['rsi_relative_low']
        if current_signal and not prev_signal:
            df.iloc[i, df.columns.get_loc('rsi_low_entry')] = True
        prev_signal = current_signal

    rsi_low_entries = df[df['rsi_low_entry']].copy()

    print(f"\n총 {len(rsi_low_entries)}회 발생")

    if len(rsi_low_entries) > 0:
        print("\n발생 시점:")
        for idx, row in rsi_low_entries.iterrows():
            print(f"  {row['timestamp'].date()}: {row['close']:,.0f}원 (RSI: {row['rsi']:.1f}, {lookback}일 최저)")

def estimate_returns(df, entry_column, strategy_name):
    """각 전략의 7일 후 수익률 추정"""
    entries = df[df[entry_column]].copy()

    if len(entries) == 0:
        return

    print(f"\n{'='*80}")
    print(f"{strategy_name} - 7일 후 수익률 추정")
    print("="*80)

    returns_7d = []

    for idx, row in entries.iterrows():
        entry_date = row['timestamp']
        entry_price = row['close']
        entry_idx = df[df['timestamp'] == entry_date].index[0]

        exit_idx = min(entry_idx + 7, len(df) - 1)
        exit_row = df.iloc[exit_idx]
        exit_price = exit_row['close']

        ret = ((exit_price - entry_price) / entry_price) * 100
        returns_7d.append(ret)

        print(f"  {entry_date.date()}: {entry_price:,.0f}원 → {exit_row['timestamp'].date()}: {exit_price:,.0f}원 ({ret:+.2f}%)")

    if len(returns_7d) > 0:
        avg_return = np.mean(returns_7d)
        win_rate = len([r for r in returns_7d if r > 0]) / len(returns_7d)

        print(f"\n--- 통계 ---")
        print(f"진입 횟수: {len(returns_7d)}회")
        print(f"평균 수익률 (7일): {avg_return:+.2f}%")
        print(f"승률: {win_rate:.1%}")
        print(f"최대 수익: {max(returns_7d):+.2f}%")
        print(f"최대 손실: {min(returns_7d):+.2f}%")

def main():
    """메인 분석 실행"""
    print("="*80)
    print("대안적 진입 조건 탐색")
    print("="*80)

    # 데이터 로드
    print("\n데이터 로드 중...")
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe(
            'day',
            start_date='2024-01-01',
            end_date='2024-12-30'
        )

    print(f"로드 완료: {len(df)}개 캔들 (2024년)")

    # 1. 가격 조정(Dip) 분석
    analyze_price_dips(df, lookback=20, dip_pcts=[0.05, 0.10, 0.15, 0.20])

    # 2. EMA26 Pullback 분석
    df_copy = df.copy()
    analyze_pullback_to_ema(df_copy)
    estimate_returns(df_copy, 'pullback_entry', 'EMA26 Pullback')

    # 3. MACD 골든크로스 분석
    df_copy = df.copy()
    df_copy = MarketAnalyzer.add_indicators(df_copy, indicators=['macd'])
    df_copy['prev_macd'] = df_copy['macd'].shift(1)
    df_copy['prev_macd_signal'] = df_copy['macd_signal'].shift(1)
    df_copy['macd_golden_cross'] = (
        (df_copy['prev_macd'] <= df_copy['prev_macd_signal']) &
        (df_copy['macd'] > df_copy['macd_signal'])
    )
    macd_entries = analyze_macd_signals(df_copy)
    if len(macd_entries) > 0:
        estimate_returns(df_copy, 'macd_golden_cross', 'MACD Golden Cross')

    # 4. 상대적 RSI 저점 분석
    df_copy = df.copy()
    analyze_rsi_relative_lows(df_copy, lookback=14)
    estimate_returns(df_copy, 'rsi_low_entry', 'RSI Relative Low (14일)')

    print("\n" + "="*80)
    print("분석 완료")
    print("="*80)

if __name__ == '__main__':
    main()
