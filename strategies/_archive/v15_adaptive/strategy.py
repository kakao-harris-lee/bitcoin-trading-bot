#!/usr/bin/env python3
"""
v15: Adaptive Strategy
시장 상황별 최적 전략 동적 선택

Market Regime 분류:
1. strong_trend (58.36%) → BREAKOUT (추세 추종)
2. sideways (1.1%) → Bollinger Bounce (평균 회귀)
3. high_volume (2.74%) → VWAP + OBV (거래량 기반)
4. normal (37.81%) → Voting Ensemble (v13)

목표: 시장 상황에 맞는 전략으로 170% 수익률 달성
"""

import sys
import os
sys.path.append('../..')

import pandas as pd
import numpy as np

from market_regime import add_adx, classify_market_regime


def add_all_indicators(df, config):
    """
    모든 전략에 필요한 지표 추가

    Args:
        df: OHLCV DataFrame
        config: 설정 딕셔너리

    Returns:
        DataFrame with all indicators
    """
    from strategies._library.volume.vwap import VWAP
    from strategies._library.volume.obv import OBV
    from strategies._library.trend.breakout import Breakout
    from strategies._library.volatility.bollinger_bands import BollingerBands
    from strategies._library.momentum.stochastic import StochasticOscillator

    # ADX (시장 상황 분류용)
    df = add_adx(df, period=14)

    # 거래량 이동평균
    df['volume_ma20'] = df['volume'].rolling(window=20).mean()

    # VWAP
    vwap = VWAP(deviation_threshold=0.02)
    df = vwap.calculate(df, reset_period=None)

    # OBV
    obv = OBV(ma_period=20)
    df = obv.calculate(df)

    # Breakout (highest_high)
    breakout = Breakout(period=20)
    df = breakout.calculate(df)

    # Bollinger Bands
    bb = BollingerBands(window=20, num_std=2.0)
    df = bb.calculate(df)

    # Stochastic
    stoch = StochasticOscillator(k_period=14, d_period=3)
    df = stoch.calculate(df)

    return df


# ============================================================================
# 전략 1: BREAKOUT (강한 추세용)
# ============================================================================
def breakout_strategy(df, i, params):
    """
    BREAKOUT 전략: 20일 최고가 돌파 시 매수

    Args:
        df: DataFrame with indicators
        i: 현재 인덱스
        params: 파라미터

    Returns:
        dict: {'signal': bool, 'reason': str}
    """
    if i < params['period'] + 1:
        return {'signal': False, 'reason': 'INSUFFICIENT_DATA'}

    current = df.iloc[i]
    prev = df.iloc[i - 1]

    close = current['close']
    prev_close = prev['close']
    prev_highest = prev['highest_high']

    if pd.isna(prev_highest):
        return {'signal': False, 'reason': 'INCOMPLETE_DATA'}

    # N일 최고가 돌파
    breakout_up = (prev_close <= prev_highest) and (close > prev_highest)

    if breakout_up:
        return {
            'signal': True,
            'reason': 'BREAKOUT_HIGH',
            'algorithm': 'breakout'
        }

    return {'signal': False, 'reason': 'NO_SIGNAL'}


# ============================================================================
# 전략 2: Bollinger Bounce (횡보장용)
# ============================================================================
def bollinger_bounce_strategy(df, i, params):
    """
    Bollinger Bounce 전략: 하단 밴드 터치 후 반등 시 매수

    Args:
        df: DataFrame with indicators
        i: 현재 인덱스
        params: 파라미터

    Returns:
        dict: {'signal': bool, 'reason': str}
    """
    if i < params['window']:
        return {'signal': False, 'reason': 'INSUFFICIENT_DATA'}

    current = df.iloc[i]
    prev = df.iloc[i - 1]

    close = current['close']
    bb_lower = current['bb_lower']
    bb_pctb = current['bb_pctb']
    prev_pctb = prev['bb_pctb']

    if pd.isna(bb_lower) or pd.isna(bb_pctb):
        return {'signal': False, 'reason': 'INCOMPLETE_DATA'}

    # 하단 밴드 터치 (%B <= 0.05) 후 반등
    touch_threshold = 0.05
    bounce = (prev_pctb <= touch_threshold) and (bb_pctb > touch_threshold)

    if bounce:
        return {
            'signal': True,
            'reason': 'BOLLINGER_BOUNCE',
            'algorithm': 'bollinger_bounce'
        }

    return {'signal': False, 'reason': 'NO_SIGNAL'}


# ============================================================================
# 전략 3: VWAP + OBV (거래량 급증용)
# ============================================================================
def vwap_obv_strategy(df, i, params):
    """
    VWAP + OBV 전략: 두 지표 모두 매수 신호 시 진입

    Args:
        df: DataFrame with indicators
        i: 현재 인덱스
        params: 파라미터

    Returns:
        dict: {'signal': bool, 'reason': str}
    """
    if i < 20:
        return {'signal': False, 'reason': 'INSUFFICIENT_DATA'}

    current = df.iloc[i]
    prev = df.iloc[i - 1]

    # VWAP 신호
    close = current['close']
    vwap = current['vwap']
    prev_close = prev['close']
    prev_vwap = prev['vwap']
    deviation = current['vwap_deviation']

    if pd.isna(vwap) or pd.isna(deviation):
        return {'signal': False, 'reason': 'INCOMPLETE_DATA'}

    vwap_cross_up = (prev_close <= prev_vwap) and (close > vwap)
    vwap_oversold = deviation <= -params['vwap']['deviation_threshold']
    vwap_signal = vwap_cross_up or vwap_oversold

    if not vwap_signal:
        return {'signal': False, 'reason': 'NO_VWAP_SIGNAL'}

    # OBV 신호
    obv = current['obv']
    obv_ma = current['obv_ma']
    prev_obv = prev['obv']
    prev_obv_ma = prev['obv_ma']

    if pd.isna(obv) or pd.isna(obv_ma):
        return {'signal': False, 'reason': 'INCOMPLETE_DATA'}

    obv_golden_cross = (prev_obv <= prev_obv_ma) and (obv > obv_ma)

    if not obv_golden_cross:
        return {'signal': False, 'reason': 'NO_OBV_SIGNAL'}

    # 두 신호 모두 만족
    return {
        'signal': True,
        'reason': 'VWAP+OBV',
        'algorithm': 'vwap_obv'
    }


# ============================================================================
# 전략 4: Voting Ensemble (일반 상황용 - v13 재사용)
# ============================================================================
def voting_ensemble_strategy(df, i, params):
    """
    Voting Ensemble 전략: VWAP + BREAKOUT + Stochastic 투표

    Args:
        df: DataFrame with indicators
        i: 현재 인덱스
        params: 파라미터

    Returns:
        dict: {'signal': bool, 'reason': str}
    """
    if i < 26:
        return {'signal': False, 'reason': 'INSUFFICIENT_DATA'}

    score = 0.0
    signals = []

    # VWAP 신호
    current = df.iloc[i]
    prev = df.iloc[i - 1]

    close = current['close']
    vwap = current['vwap']
    prev_close = prev['close']
    prev_vwap = prev['vwap']
    deviation = current['vwap_deviation']

    if not pd.isna(vwap) and not pd.isna(deviation):
        vwap_cross_up = (prev_close <= prev_vwap) and (close > vwap)
        vwap_oversold = deviation <= -0.02

        if vwap_cross_up or vwap_oversold:
            score += params['vwap_weight']
            signals.append('VWAP')

    # BREAKOUT 신호
    prev_highest = prev['highest_high']
    if not pd.isna(prev_highest):
        breakout_up = (prev_close <= prev_highest) and (close > prev_highest)

        if breakout_up:
            score += params['breakout_weight']
            signals.append('BREAKOUT')

    # Stochastic 신호
    stoch_k = current['stoch_k']
    stoch_d = current['stoch_d']
    prev_k = prev['stoch_k']
    prev_d = prev['stoch_d']

    if not pd.isna(stoch_k) and not pd.isna(stoch_d):
        oversold_bounce = (prev_k <= 20) and (stoch_k > 20)
        golden_cross = (prev_k <= prev_d) and (stoch_k > stoch_d) and (stoch_k < 30)

        if oversold_bounce or golden_cross:
            score += params['stochastic_weight']
            signals.append('STOCHASTIC')

    # 투표 결과
    if score >= params['vote_threshold']:
        return {
            'signal': True,
            'reason': f"Voting: {'+'.join(signals)} (Score={score:.1f})",
            'algorithm': 'voting_ensemble',
            'score': score,
            'signals': signals
        }

    return {'signal': False, 'reason': 'VOTE_THRESHOLD_NOT_MET'}


# ============================================================================
# v15 메인 전략: Adaptive Strategy
# ============================================================================
def v15_strategy(df, i, config):
    """
    v15 Adaptive Strategy: 시장 상황별 최적 전략 동적 선택

    Args:
        df: DataFrame with indicators
        i: 현재 인덱스
        config: 설정 딕셔너리

    Returns:
        dict: {'action': 'buy'/'hold', ...}
    """
    if i < 26:
        return {'action': 'hold'}

    # 시장 상황 분류
    regime = classify_market_regime(df, i, config)

    # 상황별 전략 선택 및 실행
    if regime == 'strong_trend':
        # 강한 추세 → BREAKOUT
        result = breakout_strategy(df, i, config['strategies']['strong_trend']['params'])

        if result['signal']:
            return {
                'action': 'buy',
                'fraction': 1.0,
                'regime': regime,
                'algorithm': result['algorithm'],
                'reason': f"[{regime.upper()}] {result['reason']}",
                'trailing_stop': config['strategies']['strong_trend']['trailing_stop']
            }

    elif regime == 'sideways':
        # 횡보장 → Bollinger Bounce
        result = bollinger_bounce_strategy(df, i, config['strategies']['sideways']['params'])

        if result['signal']:
            return {
                'action': 'buy',
                'fraction': 1.0,
                'regime': regime,
                'algorithm': result['algorithm'],
                'reason': f"[{regime.upper()}] {result['reason']}",
                'trailing_stop': config['strategies']['sideways']['trailing_stop']
            }

    elif regime == 'high_volume':
        # 거래량 급증 → VWAP + OBV
        result = vwap_obv_strategy(df, i, config['strategies']['high_volume']['params'])

        if result['signal']:
            return {
                'action': 'buy',
                'fraction': 1.0,
                'regime': regime,
                'algorithm': result['algorithm'],
                'reason': f"[{regime.upper()}] {result['reason']}",
                'trailing_stop': config['strategies']['high_volume']['trailing_stop']
            }

    else:  # normal
        # 일반 상황 → Voting Ensemble
        result = voting_ensemble_strategy(df, i, config['strategies']['normal']['params'])

        if result['signal']:
            return {
                'action': 'buy',
                'fraction': 1.0,
                'regime': regime,
                'algorithm': result['algorithm'],
                'reason': f"[{regime.upper()}] {result['reason']}",
                'trailing_stop': config['strategies']['normal']['trailing_stop']
            }

    return {'action': 'hold'}


# 테스트용 코드
if __name__ == '__main__':
    import json
    from core.data_loader import DataLoader

    # Config 로드
    with open('config.json', 'r') as f:
        config = json.load(f)

    # 데이터 로드
    with DataLoader('../../upbit_bitcoin.db') as loader:
        df = loader.load_timeframe('day', start_date='2024-01-01', end_date='2024-12-31')

    # 지표 추가
    df = add_all_indicators(df, config)

    # 신호 테스트
    print("="*80)
    print(f"v15 Adaptive Strategy 신호 테스트")
    print("="*80)

    signals_found = 0
    regime_signals = {'strong_trend': 0, 'sideways': 0, 'high_volume': 0, 'normal': 0}

    for i in range(len(df)):
        result = v15_strategy(df, i, config)

        if result['action'] == 'buy':
            signals_found += 1
            regime = result['regime']
            regime_signals[regime] += 1

            timestamp = df.iloc[i]['timestamp']
            print(f"{timestamp}: {result['reason']}")

    print(f"\n총 매수 신호: {signals_found}개")
    print(f"\n시장 상황별 신호 분포:")
    for regime, count in regime_signals.items():
        print(f"  {regime}: {count}개")
