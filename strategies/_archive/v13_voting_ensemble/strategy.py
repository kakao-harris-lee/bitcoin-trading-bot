#!/usr/bin/env python3
"""
v13: Voting Ensemble Strategy
VWAP + BREAKOUT + Stochastic 투표 방식 앙상블

매수 규칙:
  - 각 알고리즘의 가중치 합산
  - VWAP: 2.0 (신뢰도 가장 높음)
  - BREAKOUT: 1.5 (안정성)
  - Stochastic: 1.0 (큰 수익 포착)
  - 총 Score >= 3.0 → 매수

매도 규칙:
  - Trailing Stop 20%
  - Stop Loss 10%
"""

import sys
import os
sys.path.append('../..')

import pandas as pd
import numpy as np


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


def v13_strategy(df, i, config):
    """
    v13 Voting Ensemble 전략

    Args:
        df: DataFrame with indicators
        i: 현재 인덱스
        config: 설정 딕셔너리

    Returns:
        dict: {'action': 'buy'/'sell'/'hold', ...}
    """
    if i < 26:
        return {'action': 'hold'}

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

    # 매수 결정
    if score >= config['vote_threshold']:
        return {
            'action': 'buy',
            'fraction': 1.0,  # 전액 투자
            'score': score,
            'signals': signals,
            'reason': f"Voting: {'+'.join(signals)} (Score={score:.1f})"
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
    print(f"Testing v13 Voting Ensemble...")
    signals_found = 0

    for i in range(len(df)):
        result = v13_strategy(df, i, config)

        if result['action'] == 'buy':
            signals_found += 1
            print(f"{df.iloc[i]['timestamp']}: {result['reason']} (Score={result['score']:.1f})")

    print(f"\n총 매수 신호: {signals_found}개")
