# -*- coding: utf-8 -*-
import sys
sys.path.append('../..')
import pandas as pd

def add_indicators(df, config):
    from strategies._library.volume.vwap import VWAP
    vwap = VWAP(**config['algorithms']['vwap']['params'])
    df = vwap.calculate(df, reset_period=None)
    return df

def v18_strategy(df, i, config):
    if i < 2:
        return {'action': 'hold'}
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    close = current['close']
    vwap = current['vwap']
    prev_close = prev['close']
    prev_vwap = prev['vwap']
    deviation = current['vwap_deviation']
    if pd.isna(vwap) or pd.isna(deviation):
        return {'action': 'hold'}
    vwap_cross_up = (prev_close <= prev_vwap) and (close > vwap)
    vwap_oversold = deviation <= -config['algorithms']['vwap']['params']['deviation_threshold']
    if vwap_cross_up or vwap_oversold:
        return {
            'action': 'buy',
            'fraction': 1.0,
            'reason': f"VWAP {'Cross Up' if vwap_cross_up else 'Oversold'}"
        }
    return {'action': 'hold'}
