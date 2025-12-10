#!/usr/bin/env python3
"""
v20 Strategy: Simplified Adaptive
VWAP Breakout + 20일 추세 기반 동적 포지션 사이징
"""

import pandas as pd
import numpy as np


def add_indicators(df):
    """기술 지표 추가"""
    df = df.copy()

    # VWAP (Volume Weighted Average Price)
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

    # 20일 수익률
    df['return_20d'] = df['close'].pct_change(periods=20)

    return df


def determine_risk_mode(return_20d, config):
    """
    20일 수익률 기반 리스크 모드 결정

    Returns:
        tuple: (mode_name, params)
    """
    pos_config = config['position_sizing']

    if return_20d < pos_config['defensive_threshold']:
        # 하락 추세
        return "DEFENSIVE", config['defensive_mode'], pos_config['defensive_fraction']
    elif return_20d > pos_config['aggressive_threshold']:
        # 강한 상승 추세
        return "AGGRESSIVE", config['aggressive_mode'], pos_config['aggressive_fraction']
    else:
        # 중립 추세
        return "NEUTRAL", config['neutral_mode'], pos_config['neutral_fraction']


def v20_strategy(df, i, position, config):
    """
    v20 메인 전략: 단순화 적응형

    Args:
        df: 데이터프레임 (지표 포함)
        i: 현재 인덱스
        position: 현재 포지션 정보 (dict or None)
        config: 전략 설정

    Returns:
        dict: {'action': 'buy'|'sell'|'hold', ...}
    """
    # 초기 캔들 스킵 (20일 수익률 계산 필요)
    if i < 25:
        return {'action': 'hold'}

    close = df.iloc[i]['close']
    vwap = df.iloc[i]['vwap']
    return_20d = df.iloc[i]['return_20d']

    # NaN 체크
    if pd.isna(vwap) or pd.isna(return_20d):
        return {'action': 'hold'}

    # 포지션 없을 때: 매수 신호 확인
    if position is None:
        # VWAP 돌파 확인
        if i > 0:
            prev_close = df.iloc[i-1]['close']
            prev_vwap = df.iloc[i-1]['vwap']

            # 전일 VWAP 이하 → 금일 VWAP 돌파
            if prev_close <= prev_vwap and close > vwap:
                # 리스크 모드 결정
                risk_mode, params, fraction = determine_risk_mode(return_20d, config)

                return {
                    'action': 'buy',
                    'fraction': fraction,
                    'risk_mode': risk_mode,
                    'return_20d': return_20d,
                    'reason': f'VWAP_BREAKOUT_{risk_mode}'
                }

    # 포지션 있을 때: 매도 신호 확인
    else:
        entry_price = position['entry_price']
        risk_mode = position.get('risk_mode', 'NEUTRAL')

        # 리스크 모드별 파라미터
        if risk_mode == "DEFENSIVE":
            params = config['defensive_mode']
        elif risk_mode == "AGGRESSIVE":
            params = config['aggressive_mode']
        else:
            params = config['neutral_mode']

        # 손익률
        pnl_pct = (close - entry_price) / entry_price

        # 익절
        if pnl_pct >= params['take_profit_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TP_{params["take_profit_pct"]*100:.0f}%_{risk_mode}',
                'pnl_pct': pnl_pct
            }

        # Trailing Stop (수익 중일 때만)
        if pnl_pct > 0:
            high_since_entry = position.get('high_price', entry_price)

            # 최고가 갱신
            if close > high_since_entry:
                position['high_price'] = close
                high_since_entry = close

            drawdown = (close - high_since_entry) / high_since_entry

            if drawdown <= -params['trailing_stop_pct']:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TRAILING_{params["trailing_stop_pct"]*100:.0f}%_{risk_mode}',
                    'pnl_pct': pnl_pct
                }

        # 손절
        if pnl_pct <= params['stop_loss_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'SL_{abs(params["stop_loss_pct"])*100:.0f}%_{risk_mode}',
                'pnl_pct': pnl_pct
            }

    return {'action': 'hold'}
