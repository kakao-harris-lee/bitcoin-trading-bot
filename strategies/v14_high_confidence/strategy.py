#!/usr/bin/env python3
"""
v14: High Confidence Only Strategy
VWAP(필수) + OBV/CCI(선택) + 거래량 증가(필수)

엄격한 필터링으로 신뢰도 극대화

매수 규칙:
  1. VWAP 매수 신호 (필수)
  2. OBV 또는 CCI 동의 (필수)
  3. 거래량 > 평균 1.2배 (필수)

매도 규칙:
  - Trailing Stop 20%
  - Stop Loss 10%
  - VWAP 매도 신호 즉시 매도
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
    from strategies._library.volume.obv import OBV
    from strategies._library.momentum.cci import CCI

    # VWAP
    vwap = VWAP(**config['algorithms']['vwap']['params'])
    df = vwap.calculate(df, reset_period=None)

    # OBV
    obv = OBV(**config['algorithms']['obv']['params'])
    df = obv.calculate(df)

    # CCI
    cci = CCI(**config['algorithms']['cci']['params'])
    df = cci.calculate(df)

    # 거래량 이동평균 (20일)
    df['volume_ma20'] = df['volume'].rolling(window=20).mean()

    return df


def check_vwap_buy_signal(df, i, params):
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


def check_vwap_sell_signal(df, i, params):
    """VWAP 매도 신호 확인"""
    if i < 2:
        return False

    current = df.iloc[i]
    prev = df.iloc[i - 1]

    close = current['close']
    vwap = current['vwap']
    prev_close = prev['close']
    prev_vwap = prev['vwap']

    if pd.isna(vwap):
        return False

    # VWAP 하향 돌파
    vwap_cross_down = (prev_close >= prev_vwap) and (close < vwap)

    return vwap_cross_down


def check_obv_signal(df, i, params):
    """OBV 매수 신호 확인"""
    if i < params['ma_period']:
        return False

    current = df.iloc[i]
    prev = df.iloc[i - 1]

    obv = current['obv']
    obv_ma = current['obv_ma']
    prev_obv = prev['obv']
    prev_obv_ma = prev['obv_ma']

    if pd.isna(obv) or pd.isna(obv_ma):
        return False

    # OBV 골든크로스
    golden_cross = (prev_obv <= prev_obv_ma) and (obv > obv_ma)

    return golden_cross


def check_cci_signal(df, i, config):
    """CCI 매수 신호 확인"""
    params = config['algorithms']['cci']

    if i < params['params']['period']:
        return False

    current = df.iloc[i]
    prev = df.iloc[i - 1]

    cci = current['cci']
    prev_cci = prev['cci']

    if pd.isna(cci):
        return False

    # CCI 과매도에서 반등 또는 제로라인 상향 돌파
    oversold_bounce = (prev_cci < params['oversold']) and (cci >= params['oversold'])
    zero_cross_up = (prev_cci < 0) and (cci >= 0)

    return oversold_bounce or zero_cross_up


def check_volume_increase(df, i, threshold):
    """거래량 증가 확인"""
    if i < 20:
        return False

    current = df.iloc[i]
    volume = current['volume']
    volume_ma = current['volume_ma20']

    if pd.isna(volume_ma):
        return False

    return volume > volume_ma * threshold


def v14_strategy(df, i, config):
    """
    v14 High Confidence Only 전략

    Args:
        df: DataFrame with indicators
        i: 현재 인덱스
        config: 설정 딕셔너리

    Returns:
        dict: {'action': 'buy'/'sell'/'hold', ...}
    """
    if i < 26:
        return {'action': 'hold'}

    # 1. VWAP 신호 (필수)
    vwap_buy = check_vwap_buy_signal(df, i, config['algorithms']['vwap']['params'])
    if not vwap_buy:
        return {'action': 'hold'}

    # 2. OBV 또는 CCI 동의 (필수)
    obv_buy = check_obv_signal(df, i, config['algorithms']['obv']['params'])
    cci_buy = check_cci_signal(df, i, config)

    if not (obv_buy or cci_buy):
        return {'action': 'hold'}

    # 3. 거래량 증가 (필수)
    volume_ok = check_volume_increase(df, i, config['volume_threshold'])
    if not volume_ok:
        return {'action': 'hold'}

    # 모든 조건 만족 → 매수
    signals = ['VWAP']
    if obv_buy:
        signals.append('OBV')
    if cci_buy:
        signals.append('CCI')

    return {
        'action': 'buy',
        'fraction': 1.0,
        'signals': signals,
        'reason': f"High Confidence: {'+'.join(signals)} + Volume"
    }


def check_sell_signal(df, i, config):
    """매도 신호 확인 (VWAP 하향 돌파)"""
    return check_vwap_sell_signal(df, i, config['algorithms']['vwap']['params'])


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
    print(f"Testing v14 High Confidence...")
    signals_found = 0

    for i in range(len(df)):
        result = v14_strategy(df, i, config)

        if result['action'] == 'buy':
            signals_found += 1
            print(f"{df.iloc[i]['timestamp']}: {result['reason']}")

    print(f"\n총 매수 신호: {signals_found}개")
