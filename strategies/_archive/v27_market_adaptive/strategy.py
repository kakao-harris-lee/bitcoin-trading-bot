#!/usr/bin/env python3
"""v27 전략: 시장 상황 적응형"""

import pandas as pd
import numpy as np


def classify_market(df, i, window=60, bull_threshold=0.50, bear_threshold=-0.20):
    """
    시장 분류: 상승/하락/횡보

    Args:
        df: 데이터프레임
        i: 현재 인덱스
        window: 분류 기간 (일)
        bull_threshold: 상승장 기준 (수익률)
        bear_threshold: 하락장 기준 (수익률)

    Returns:
        str: 'bull', 'bear', 'sideways'
    """
    if i < window:
        return 'sideways'  # 데이터 부족

    # 60일 전 가격
    past_price = df.iloc[i - window]['close']
    current_price = df.iloc[i]['close']

    # 60일 수익률
    return_pct = (current_price - past_price) / past_price

    if return_pct >= bull_threshold:
        return 'bull'
    elif return_pct <= bear_threshold:
        return 'bear'
    else:
        return 'sideways'


def v27_strategy(df, i, config, position_info=None):
    """v27 시장 적응형 전략"""
    if isinstance(config, dict):
        market_cfg = config['market_classification']
        bull_cfg = config['bull_market_strategy']
        bear_cfg = config['bear_market_strategy']
        sideways_cfg = config['sideways_market_strategy']
    else:
        return {'action': 'hold'}

    if i < 26:
        return {'action': 'hold'}

    row = df.iloc[i]

    if any(pd.isna(row[col]) for col in ['rsi', 'bb_position', 'volume_ratio']):
        return {'action': 'hold'}

    # 시장 분류
    market_type = classify_market(df, i,
                                   market_cfg['window'],
                                   market_cfg['bull_threshold'],
                                   market_cfg['bear_threshold'])

    # 시장별 전략 선택
    if market_type == 'bull':
        strategy_cfg = bull_cfg
    elif market_type == 'bear':
        strategy_cfg = bear_cfg
    else:  # sideways
        strategy_cfg = sideways_cfg

    entry = strategy_cfg['entry']
    exit_cond = strategy_cfg['exit']
    risk = strategy_cfg['risk']

    # 손절/익절
    if position_info and position_info.get('entry_price'):
        profit_pct = (row['close'] - position_info['entry_price']) / position_info['entry_price']

        if risk.get('stop_loss') and profit_pct <= risk['stop_loss']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'stop_loss_{market_type}'}

        if risk.get('take_profit') and profit_pct >= risk['take_profit']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'take_profit_{market_type}'}

    # 진입
    if (row['rsi'] < entry['rsi_threshold'] and
        row['bb_position'] < entry['bb_threshold'] and
        row['volume_ratio'] > entry['volume_threshold']):
        return {'action': 'buy', 'fraction': 1.0, 'market': market_type}

    # 청산
    if (row['rsi'] > exit_cond['rsi_threshold'] or
        row['bb_position'] > exit_cond['bb_threshold']):
        return {'action': 'sell', 'fraction': 1.0, 'market': market_type}

    return {'action': 'hold'}


if __name__ == '__main__':
    print("v27 전략: 시장 상황 적응형")
    print("\n시장 분류 (60일 수익률):")
    print("  상승장: +50% 이상 → v23 공격적")
    print("  하락장: -20% 이하 → v21 극단적 저점")
    print("  횡보장: -20% ~ +50% → 빈번한 단타")
    print("\n목표: 모든 시장에서 수익 달성")
