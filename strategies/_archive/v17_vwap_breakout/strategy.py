# -*- coding: utf-8 -*-
import sys
sys.path.append('../..')
import pandas as pd

def add_indicators(df, config):
    from strategies._library.volume.vwap import VWAP
    from strategies._library.trend.breakout import Breakout
    vwap = VWAP(**config['algorithms']['vwap']['params'])
    df = vwap.calculate(df, reset_period=None)
    breakout = Breakout(**config['algorithms']['breakout']['params'])
    df = breakout.calculate(df)
    return df

def check_vwap_signal(df, i, params):
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
    vwap_cross_up = (prev_close <= prev_vwap) and (close > vwap)
    vwap_oversold = deviation <= -params['deviation_threshold']
    return vwap_cross_up or vwap_oversold

def check_breakout_signal(df, i, params):
    if i < params['period'] + 1:
        return False
    current = df.iloc[i]
    prev = df.iloc[i - 1]
    close = current['close']
    prev_close = prev['close']
    prev_highest = prev['highest_high']
    if pd.isna(prev_highest):
        return False
    breakout_up = (prev_close <= prev_highest) and (close > prev_highest)
    return breakout_up

def v17_strategy(df, i, config):
    if i < 26:
        return {'action': 'hold'}
    vwap_signal = check_vwap_signal(df, i, config['algorithms']['vwap']['params'])
    breakout_signal = check_breakout_signal(df, i, config['algorithms']['breakout']['params'])
    score = 0.0
    signals = []
    if vwap_signal:
        score += config['algorithms']['vwap']['weight']
        signals.append('VWAP')
    if breakout_signal:
        score += config['algorithms']['breakout']['weight']
        signals.append('BREAKOUT')
    if score >= config['vote_threshold']:
        return {
            'action': 'buy',
            'fraction': 1.0,
            'score': score,
            'signals': signals,
            'reason': f"Voting: {'+'.join(signals)} (Score={score:.1f})"
        }
    return {'action': 'hold'}
