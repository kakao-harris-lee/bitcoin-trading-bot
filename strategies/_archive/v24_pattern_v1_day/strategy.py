#!/usr/bin/env python3
"""v24 전략: Pattern V1 (검증된 고정확도 패턴)"""

import pandas as pd


def v24_strategy(df, i, config, position_info=None):
    """Pattern V1 전략 - 단순하고 강력함"""
    if isinstance(config, dict):
        entry = config['entry_conditions']
        exit_cond = config['exit_conditions']
        risk = config['risk_management']
    else:
        entry = {'rsi_threshold': 30, 'bb_threshold': 0.2, 'volume_threshold': 1.5}
        exit_cond = {'rsi_threshold': 70, 'bb_threshold': 0.8}
        risk = {'stop_loss': -0.15, 'take_profit': 0.20}

    if i < 26:
        return {'action': 'hold'}

    row = df.iloc[i]

    if any(pd.isna(row[col]) for col in ['rsi', 'bb_position', 'volume_ratio']):
        return {'action': 'hold'}

    # 손절/익절
    if position_info and position_info.get('entry_price'):
        profit_pct = (row['close'] - position_info['entry_price']) / position_info['entry_price']
        if risk.get('stop_loss') and profit_pct <= risk['stop_loss']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'stop_loss'}
        if risk.get('take_profit') and profit_pct >= risk['take_profit']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'take_profit'}

    # 진입: RSI < 30 AND BB < 0.2 AND Volume > 1.5
    if (row['rsi'] < entry['rsi_threshold'] and
        row['bb_position'] < entry['bb_threshold'] and
        row['volume_ratio'] > entry['volume_threshold']):
        return {'action': 'buy', 'fraction': 1.0}

    # 청산: RSI > 70 OR BB > 0.8
    if (row['rsi'] > exit_cond['rsi_threshold'] or
        row['bb_position'] > exit_cond['bb_threshold']):
        return {'action': 'sell', 'fraction': 1.0}

    return {'action': 'hold'}
