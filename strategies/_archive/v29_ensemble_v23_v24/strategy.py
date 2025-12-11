#!/usr/bin/env python3
"""v29 전략: 앙상블 (v23 + v24)"""

import pandas as pd


def v23_signal(row, config):
    """v23 진입/청산 신호"""
    entry = config['entry']
    exit_cond = config['exit']

    # 진입
    if (row['rsi'] < entry['rsi_threshold'] and
        row['bb_position'] < entry['bb_threshold'] and
        row['volume_ratio'] > entry['volume_threshold'] and
        row['stoch_k'] < entry['stoch_threshold'] and
        row['adx'] > entry['adx_threshold']):
        return 'buy'

    # 청산
    if (row['rsi'] > exit_cond['rsi_threshold'] or
        row['bb_position'] > exit_cond['bb_threshold']):
        return 'sell'

    return 'hold'


def v24_signal(row, config):
    """v24 진입/청산 신호"""
    entry = config['entry']
    exit_cond = config['exit']

    # 진입
    if (row['rsi'] < entry['rsi_threshold'] and
        row['bb_position'] < entry['bb_threshold'] and
        row['volume_ratio'] > entry['volume_threshold']):
        return 'buy'

    # 청산
    if (row['rsi'] > exit_cond['rsi_threshold'] or
        row['bb_position'] > exit_cond['bb_threshold']):
        return 'sell'

    return 'hold'


def v29_strategy(df, i, config, position_info=None):
    """v29 앙상블 전략"""
    if isinstance(config, dict):
        v23_cfg = config['v23_config']
        v24_cfg = config['v24_config']
    else:
        return {'action': 'hold'}

    if i < 26:
        return {'action': 'hold'}

    row = df.iloc[i]

    required_cols = ['rsi', 'bb_position', 'volume_ratio', 'stoch_k', 'adx']
    if any(pd.isna(row[col]) for col in required_cols if col in row):
        return {'action': 'hold'}

    # 두 전략의 신호
    signal_v23 = v23_signal(row, v23_cfg)
    signal_v24 = v24_signal(row, v24_cfg)

    # 손절 체크
    if position_info and position_info.get('entry_price'):
        profit_pct = (row['close'] - position_info['entry_price']) / position_info['entry_price']

        # v23과 v24 중 더 보수적인 손절 적용
        stop_loss = max(v23_cfg['risk']['stop_loss'], v24_cfg['risk']['stop_loss'])
        if profit_pct <= stop_loss:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'stop_loss'}

        # 익절은 빠른 것 적용
        take_profit = min(v23_cfg['risk']['take_profit'], v24_cfg['risk']['take_profit'])
        if profit_pct >= take_profit:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'take_profit'}

    # 앙상블 규칙
    # 강한 매수: 둘 다 매수
    if signal_v23 == 'buy' and signal_v24 == 'buy':
        return {'action': 'buy', 'fraction': 1.0, 'strength': 'strong'}

    # 중간 매수: 하나만 매수
    if signal_v23 == 'buy' or signal_v24 == 'buy':
        return {'action': 'buy', 'fraction': 0.5, 'strength': 'medium'}

    # 강한 매도: 둘 다 매도
    if signal_v23 == 'sell' and signal_v24 == 'sell':
        return {'action': 'sell', 'fraction': 1.0, 'strength': 'strong'}

    # 중간 매도: 하나만 매도 (포지션 있고 수익인 경우)
    if position_info and position_info.get('entry_price'):
        profit_pct = (row['close'] - position_info['entry_price']) / position_info['entry_price']
        if profit_pct > 0 and (signal_v23 == 'sell' or signal_v24 == 'sell'):
            return {'action': 'sell', 'fraction': 0.5, 'strength': 'medium'}

    return {'action': 'hold'}


if __name__ == '__main__':
    print("v29 전략: 앙상블 (v23 + v24)")
    print("\n투표 방식:")
    print("  강한 매수: v23=매수 AND v24=매수 → 100% 투자")
    print("  중간 매수: v23=매수 OR v24=매수 → 50% 투자")
    print("  강한 매도: v23=매도 AND v24=매도 → 전량 매도")
    print("  중간 매도: (v23=매도 OR v24=매도) AND 수익>0 → 50% 매도")
    print("\n목표: 정확도 향상, 100-120% 달성")
