#!/usr/bin/env python3
"""
v16: Improved Voting Ensemble Strategy
v13 개선: Vote Threshold 완화 + ADX 횡보장 감지 + 동적 Trailing Stop

개선 사항:
  1. Vote Threshold 3.0 → 2.5 (거래 기회 증가)
  2. ADX < 15 횡보장 감지 → 거래 회피 (7-9월 손실 방지)
  3. 동적 Trailing Stop:
     - 강한 추세 (ADX >= 25): 30%
     - 일반 (15 <= ADX < 25): 20%
     - 횡보장 (ADX < 15): 15%

매수 규칙:
  - 각 알고리즘의 가중치 합산
  - VWAP: 2.0, BREAKOUT: 1.5, Stochastic: 1.0
  - 총 Score >= 2.5 → 매수
  - ADX < 15 (횡보장) 시 매수 회피

매도 규칙:
  - 동적 Trailing Stop (시장 상황별 15-30%)
  - Stop Loss 10%
"""

import sys
import os
sys.path.append('../..')

import pandas as pd
import numpy as np


def add_adx(df, period=14):
    """
    ADX (Average Directional Index) 계산

    Args:
        df: OHLCV DataFrame
        period: ADX 계산 기간

    Returns:
        DataFrame with ADX, +DI, -DI
    """
    # True Range
    high_low = df['high'] - df['low']
    high_close = abs(df['high'] - df['close'].shift(1))
    low_close = abs(df['low'] - df['close'].shift(1))
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)

    # +DM, -DM
    high_diff = df['high'] - df['high'].shift(1)
    low_diff = df['low'].shift(1) - df['low']

    plus_dm = np.where((high_diff > low_diff) & (high_diff > 0), high_diff, 0)
    minus_dm = np.where((low_diff > high_diff) & (low_diff > 0), low_diff, 0)

    # ATR (Smoothed)
    df['atr'] = tr.ewm(alpha=1/period, adjust=False).mean()

    # +DI, -DI (Smoothed)
    df['plus_di'] = 100 * pd.Series(plus_dm).ewm(alpha=1/period, adjust=False).mean() / df['atr']
    df['minus_di'] = 100 * pd.Series(minus_dm).ewm(alpha=1/period, adjust=False).mean() / df['atr']

    # DX
    dx = 100 * abs(df['plus_di'] - df['minus_di']) / (df['plus_di'] + df['minus_di'])

    # ADX (Smoothed DX)
    df['adx'] = dx.ewm(alpha=1/period, adjust=False).mean()

    return df


def add_indicators(df, config):
    """
    필요한 지표 추가

    Args:
        df: OHLCV DataFrame
        config: 설정 딕셔너리

    Returns:
        DataFrame with indicators
    """
    from strategies._library.volume.vwap import VWAP
    from strategies._library.trend.breakout import Breakout
    from strategies._library.momentum.stochastic import StochasticOscillator

    # VWAP
    vwap = VWAP(**config['algorithms']['vwap']['params'])
    df = vwap.calculate(df, reset_period=None)

    # Breakout (highest_high)
    breakout = Breakout(**config['algorithms']['breakout']['params'])
    df = breakout.calculate(df)

    # Stochastic
    stoch = StochasticOscillator(**config['algorithms']['stochastic']['params'])
    df = stoch.calculate(df)

    # ADX
    df = add_adx(df, period=config['adx_period'])

    return df


def check_vwap_signal(df, i, params):
    """VWAP 매수 신호 확인"""
    if i < 2:
        return False

    current = df.iloc[i]
    prev = df.iloc[i - 1]

    close = current['close']
    vwap = current['vwap']
    prev_close = prev['close']
    prev_vwap = prev['vwap']
    deviation = current['vwap_deviation']

    if pd.isna(vwap) or pd.isna(deviation):
        return False

    # VWAP 상향 돌파 또는 과매도
    vwap_cross_up = (prev_close <= prev_vwap) and (close > vwap)
    vwap_oversold = deviation <= -params['deviation_threshold']

    return vwap_cross_up or vwap_oversold


def check_breakout_signal(df, i, params):
    """BREAKOUT 매수 신호 확인"""
    if i < params['period'] + 1:
        return False

    current = df.iloc[i]
    prev = df.iloc[i - 1]

    close = current['close']
    prev_close = prev['close']
    prev_highest = prev['highest_high']

    if pd.isna(prev_highest):
        return False

    # N일 최고가 돌파
    breakout_up = (prev_close <= prev_highest) and (close > prev_highest)

    return breakout_up


def check_stochastic_signal(df, i, params):
    """Stochastic 매수 신호 확인"""
    if i < params['k_period']:
        return False

    current = df.iloc[i]
    prev = df.iloc[i - 1]

    stoch_k = current['stoch_k']
    stoch_d = current['stoch_d']
    prev_k = prev['stoch_k']
    prev_d = prev['stoch_d']

    if pd.isna(stoch_k) or pd.isna(stoch_d):
        return False

    # 과매도에서 반등 또는 골든크로스
    oversold_bounce = (prev_k <= params['oversold']) and (stoch_k > params['oversold'])
    golden_cross = (prev_k <= prev_d) and (stoch_k > stoch_d) and (stoch_k < params['oversold'] * 1.5)

    return oversold_bounce or golden_cross


def get_market_regime(df, i, config):
    """
    시장 상황 분류

    Returns:
        str: 'strong_trend' (ADX >= 25)
             'normal' (15 <= ADX < 25)
             'sideways' (ADX < 15)
    """
    adx = df.iloc[i]['adx']

    if pd.isna(adx):
        return 'normal'

    if adx >= config['adx_strong_trend']:
        return 'strong_trend'
    elif adx < config['adx_sideways']:
        return 'sideways'
    else:
        return 'normal'


def get_trailing_stop(regime, config):
    """
    시장 상황별 Trailing Stop 반환

    Args:
        regime: 'strong_trend', 'normal', 'sideways'
        config: 설정 딕셔너리

    Returns:
        float: Trailing Stop 비율
    """
    return config['trailing_stop'][regime]


def v16_strategy(df, i, config):
    """
    v16 Improved Voting Ensemble 전략

    Args:
        df: DataFrame with indicators
        i: 현재 인덱스
        config: 설정 딕셔너리

    Returns:
        dict: {'action': 'buy'/'sell'/'hold', ...}
    """
    if i < 26:
        return {'action': 'hold'}

    # 시장 상황 파악
    regime = get_market_regime(df, i, config)

    # 횡보장에서는 매수 회피 (v13의 7-9월 손실 방지)
    if regime == 'sideways':
        return {'action': 'hold', 'reason': 'ADX < 15 (횡보장 회피)'}

    # 각 알고리즘 신호 확인
    vwap_signal = check_vwap_signal(df, i, config['algorithms']['vwap']['params'])
    breakout_signal = check_breakout_signal(df, i, config['algorithms']['breakout']['params'])
    stoch_signal = check_stochastic_signal(df, i, config['algorithms']['stochastic']['params'])

    # Score 계산
    score = 0.0
    signals = []

    if vwap_signal:
        score += config['algorithms']['vwap']['weight']
        signals.append('VWAP')

    if breakout_signal:
        score += config['algorithms']['breakout']['weight']
        signals.append('BREAKOUT')

    if stoch_signal:
        score += config['algorithms']['stochastic']['weight']
        signals.append('STOCHASTIC')

    # 매수 결정 (v13: 3.0 → v16: 2.5)
    if score >= config['vote_threshold']:
        trailing_stop = get_trailing_stop(regime, config)

        return {
            'action': 'buy',
            'fraction': 1.0,
            'score': score,
            'signals': signals,
            'regime': regime,
            'trailing_stop': trailing_stop,
            'reason': f"Voting: {'+'.join(signals)} (Score={score:.1f}, {regime.upper()})"
        }

    return {'action': 'hold'}


if __name__ == '__main__':
    """테스트용 코드"""
    import json
    from core.data_loader import DataLoader

    # Config 로드
    with open('config.json', 'r') as f:
        config = json.load(f)

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    # 지표 추가
    df = add_indicators(df, config)

    # 신호 테스트
    print(f"Testing v16 Improved Voting Ensemble...")
    signals_found = 0

    for i in range(len(df)):
        result = v16_strategy(df, i, config)

        if result['action'] == 'buy':
            signals_found += 1
            adx = df.iloc[i]['adx']
            print(f"{df.iloc[i]['timestamp']}: {result['reason']} | "
                  f"ADX={adx:.1f} | Trailing={result['trailing_stop']*100:.0f}%")

    print(f"\n총 매수 신호: {signals_found}개")
