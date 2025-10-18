#!/usr/bin/env python3
"""
market_regime.py
시장 상황 분류 모듈

ADX, 거래량 등을 기반으로 현재 시장 상황을 4가지로 분류:
1. strong_trend: 강한 추세 (ADX >= 25)
2. sideways: 횡보장 (ADX < 15)
3. high_volume: 거래량 급증 (Volume > 평균 1.5배)
4. normal: 기타 일반 상황
"""

import pandas as pd
import numpy as np


def add_adx(df, period=14):
    """
    ADX (Average Directional Index) 계산

    ADX는 추세의 강도를 측정하는 지표
    - ADX > 25: 강한 추세
    - ADX < 15: 약한 추세 (횡보장)

    Args:
        df: DataFrame with 'high', 'low', 'close'
        period: ADX 계산 기간 (기본 14)

    Returns:
        DataFrame with 'adx' column
    """
    df = df.copy()

    # True Range (TR)
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift(1))
    low_close = abs(df['low'] - df['close'].shift(1))

    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    # Directional Movement (+DM, -DM)
    high_diff = df['high'] - df['high'].shift(1)
    low_diff = df['low'].shift(1) - df['low']

    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)

    df['plus_dm'] = plus_dm
    df['minus_dm'] = minus_dm
    df['tr'] = tr

    # Smoothed TR, +DM, -DM (Wilder's smoothing = EMA with alpha = 1/period)
    df['atr'] = df['tr'].ewm(alpha=1/period, adjust=False).mean()
    df['plus_di'] = 100 * df['plus_dm'].ewm(alpha=1/period, adjust=False).mean() / df['atr']
    df['minus_di'] = 100 * df['minus_dm'].ewm(alpha=1/period, adjust=False).mean() / df['atr']

    # DX (Directional Index)
    dx = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])

    # ADX (Average of DX)
    df['adx'] = dx.ewm(alpha=1/period, adjust=False).mean()

    return df


def classify_market_regime(df, i, config):
    """
    시장 상황 분류

    Args:
        df: DataFrame with ADX and volume indicators
        i: 현재 인덱스
        config: 설정 딕셔너리

    Returns:
        str: 'strong_trend' | 'sideways' | 'high_volume' | 'normal'
    """
    if i < 20:
        return 'normal'

    current = df.iloc[i]

    adx = current.get('adx', None)
    volume = current.get('volume', None)
    volume_ma20 = current.get('volume_ma20', None)

    # NaN 체크
    if pd.isna(adx):
        return 'normal'

    # 1. 강한 추세 (ADX >= 25)
    if adx >= config['market_regime']['adx_strong_trend']:
        return 'strong_trend'

    # 2. 횡보장 (ADX < 15)
    if adx < config['market_regime']['adx_sideways']:
        return 'sideways'

    # 3. 거래량 급증 (Volume > 평균 1.5배)
    if volume is not None and volume_ma20 is not None and not pd.isna(volume_ma20):
        if volume > volume_ma20 * config['market_regime']['volume_high_multiplier']:
            return 'high_volume'

    # 4. 기타 일반 상황
    return 'normal'


def get_regime_description(regime):
    """
    시장 상황 설명 반환

    Args:
        regime: 시장 상황 ('strong_trend' | 'sideways' | 'high_volume' | 'normal')

    Returns:
        str: 설명
    """
    descriptions = {
        'strong_trend': '강한 추세 (ADX >= 25)',
        'sideways': '횡보장 (ADX < 15)',
        'high_volume': '거래량 급증 (Volume > 평균 1.5배)',
        'normal': '일반 상황'
    }

    return descriptions.get(regime, '알 수 없음')


def analyze_regime_distribution(df, config):
    """
    전체 기간의 시장 상황 분포 분석

    Args:
        df: DataFrame with indicators
        config: 설정 딕셔너리

    Returns:
        dict: 각 regime별 출현 횟수 및 비율
    """
    regimes = []

    for i in range(len(df)):
        regime = classify_market_regime(df, i, config)
        regimes.append(regime)

    df['regime'] = regimes

    # 분포 계산
    regime_counts = df['regime'].value_counts()
    regime_pct = (regime_counts / len(df) * 100).round(2)

    distribution = {}
    for regime in ['strong_trend', 'sideways', 'high_volume', 'normal']:
        count = regime_counts.get(regime, 0)
        pct = regime_pct.get(regime, 0.0)
        distribution[regime] = {
            'count': count,
            'percentage': pct,
            'description': get_regime_description(regime)
        }

    return distribution


# 테스트용 코드
if __name__ == '__main__':
    import sys
    import os
    import json

    # 프로젝트 루트로 이동
    current_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(current_dir, '../..'))
    os.chdir(project_root)
    sys.path.insert(0, project_root)

    from core.data_loader import DataLoader

    # Config 로드
    with open('strategies/v15_adaptive/config.json', 'r') as f:
        config = json.load(f)

    # 데이터 로드
    with DataLoader('upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    # ADX 추가
    df = add_adx(df, period=14)

    # 거래량 이동평균 추가
    df['volume_ma20'] = df['volume'].rolling(window=20).mean()

    print("="*80)
    print("시장 상황 분류 테스트 (2024년)")
    print("="*80)

    # ADX 분포 확인
    print(f"\nADX 통계:")
    print(f"  평균: {df['adx'].mean():.2f}")
    print(f"  중앙값: {df['adx'].median():.2f}")
    print(f"  최소: {df['adx'].min():.2f}")
    print(f"  최대: {df['adx'].max():.2f}")

    # 시장 상황 분포 분석
    distribution = analyze_regime_distribution(df, config)

    print(f"\n시장 상황 분포:")
    for regime, data in distribution.items():
        print(f"  {data['description']}: {data['count']}일 ({data['percentage']}%)")

    # 예시: 특정 날짜의 시장 상황
    print(f"\n특정 날짜 시장 상황 예시:")
    for i in [50, 100, 150, 200, 250, 300]:
        if i < len(df):
            regime = classify_market_regime(df, i, config)
            timestamp = df.iloc[i]['timestamp']
            adx = df.iloc[i]['adx']
            print(f"  {timestamp}: {get_regime_description(regime)} (ADX={adx:.2f})")
