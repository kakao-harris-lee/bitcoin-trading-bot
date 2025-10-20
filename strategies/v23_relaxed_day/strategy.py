#!/usr/bin/env python3
"""
v23 전략: 조건 완화 Day 전략
거래 빈도 증가로 수익 기회 확대
"""

import pandas as pd
import numpy as np


def v23_strategy(df, i, config, position_info=None):
    """
    v23 전략 로직

    Args:
        df: OHLCV + 지표 데이터프레임
        i: 현재 인덱스
        config: 설정
        position_info: 포지션 정보 {'entry_price': float}

    Returns:
        dict: {'action': 'buy'|'sell'|'hold', 'fraction': float}
    """
    if isinstance(config, dict):
        entry = config['entry_conditions']
        exit_cond = config['exit_conditions']
        risk = config['risk_management']
    else:
        entry = {
            'rsi_threshold': getattr(config, 'rsi_threshold', 40),
            'bb_threshold': getattr(config, 'bb_threshold', 0.3),
            'volume_threshold': getattr(config, 'volume_threshold', 1.2),
            'stoch_threshold': getattr(config, 'stoch_threshold', 35),
            'adx_threshold': getattr(config, 'adx_threshold', 25)
        }
        exit_cond = {
            'rsi_threshold': getattr(config, 'exit_rsi', 60),
            'bb_threshold': getattr(config, 'exit_bb', 0.75),
            'stoch_threshold': getattr(config, 'exit_stoch', 80)
        }
        risk = {
            'stop_loss': getattr(config, 'stop_loss', -0.10),
            'take_profit': getattr(config, 'take_profit', 0.30)
        }

    if i < 26:
        return {'action': 'hold'}

    row = df.iloc[i]
    prev_row = df.iloc[i-1]

    required_cols = ['rsi', 'bb_position', 'volume_ratio', 'stoch_k', 'stoch_d', 'adx']
    if any(pd.isna(row[col]) for col in required_cols if col in row):
        return {'action': 'hold'}

    # 손절/익절 체크
    if position_info and position_info.get('entry_price'):
        current_price = row['close']
        entry_price = position_info['entry_price']
        profit_pct = (current_price - entry_price) / entry_price

        # 손절
        if risk.get('stop_loss') and profit_pct <= risk['stop_loss']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'stop_loss'}

        # 익절
        if risk.get('take_profit') and profit_pct >= risk['take_profit']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'take_profit'}

    # 진입 조건 (완화)
    entry_signal = (
        row['rsi'] < entry['rsi_threshold'] and
        row['bb_position'] < entry['bb_threshold'] and
        row['volume_ratio'] > entry['volume_threshold'] and
        row['stoch_k'] < entry['stoch_threshold'] and
        row['adx'] > entry['adx_threshold']
    )

    if entry_signal:
        return {'action': 'buy', 'fraction': 1.0}

    # 청산 조건 (완화)
    stoch_dead_cross = False
    if 'stoch_k' in prev_row and 'stoch_d' in prev_row:
        if not pd.isna(prev_row['stoch_k']) and not pd.isna(prev_row['stoch_d']):
            stoch_dead_cross = (
                prev_row['stoch_k'] >= prev_row['stoch_d'] and
                row['stoch_k'] < row['stoch_d']
            )

    exit_signal = (
        (row['rsi'] > exit_cond['rsi_threshold'] and
         row['bb_position'] > exit_cond['bb_threshold'] and
         row['stoch_k'] > exit_cond['stoch_threshold']) or
        (row['bb_position'] > exit_cond['bb_threshold'] and stoch_dead_cross)
    )

    if exit_signal:
        return {'action': 'sell', 'fraction': 1.0}

    return {'action': 'hold'}


if __name__ == '__main__':
    print("v23 전략: 조건 완화 Day 전략")
    print("\n진입 조건 (완화):")
    print("  - RSI < 40 (기존 35)")
    print("  - BB Position < 0.3 (기존 0.189)")
    print("  - Volume Ratio > 1.2 (기존 1.56)")
    print("  - Stochastic K < 35 (기존 27)")
    print("  - ADX > 25 (기존 38)")
    print("\n청산 조건 (완화):")
    print("  - (RSI > 60 AND BB > 0.75 AND Stoch > 80)")
    print("  - OR (BB > 0.75 AND Stochastic Dead Cross)")
    print("\n리스크 관리:")
    print("  - 손절: -10%")
    print("  - 익절: +30%")
    print("\n목표: 거래 빈도 증가 (연 10-20회)")
