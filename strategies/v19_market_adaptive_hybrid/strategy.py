#!/usr/bin/env python3
"""
v19 Strategy: Market-Adaptive Hybrid
시장 상황(하락/상승/횡보)에 따라 전략을 자동 전환
"""

import pandas as pd
import numpy as np
import talib


def add_indicators(df):
    """기술 지표 추가"""
    df = df.copy()

    # RSI
    df['rsi'] = talib.RSI(df['close'].values, timeperiod=14)

    # ADX
    df['adx'] = talib.ADX(df['high'].values, df['low'].values, df['close'].values, timeperiod=14)

    # VWAP (Volume Weighted Average Price)
    df['vwap'] = (df['close'] * df['volume']).cumsum() / df['volume'].cumsum()

    # 20일 수익률
    df['return_20d'] = df['close'].pct_change(periods=20)

    return df


def classify_market(df, i, config):
    """
    시장 상황 분류

    Returns:
        str: "BEAR", "BULL", "SIDEWAYS"
    """
    if i < 30:
        return "SIDEWAYS"  # 초기 데이터 부족 시 중립

    adx = df.iloc[i]['adx']
    return_20d = df.iloc[i]['return_20d']

    adx_threshold = config['market_classification']['adx_trend_threshold']
    bull_threshold = config['market_classification']['bull_return_threshold']
    bear_threshold = config['market_classification']['bear_return_threshold']

    # 강한 추세 + 상승
    if adx >= adx_threshold and return_20d >= bull_threshold:
        return "BULL"

    # 강한 추세 + 하락
    elif adx >= adx_threshold and return_20d <= bear_threshold:
        return "BEAR"

    # 약한 추세 or 중간 수익률
    else:
        return "SIDEWAYS"


def bear_market_strategy(df, i, position, config):
    """
    하락장 전략: 방어적 접근
    - RSI < 20 극단적 과매도 시에만 매수
    - 빠른 익절 +5%
    - 강한 손절 -3%
    """
    rsi = df.iloc[i]['rsi']
    close = df.iloc[i]['close']

    params = config['bear_strategy']

    # 포지션 없을 때
    if position is None:
        # 극단적 과매도
        if rsi < params['rsi_entry']:
            return {
                'action': 'buy',
                'fraction': params['max_position_fraction'],
                'reason': 'BEAR_RSI_BOUNCE',
                'market_type': 'BEAR'
            }

    # 포지션 있을 때
    else:
        entry_price = position['entry_price']
        pnl_pct = (close - entry_price) / entry_price

        # 익절
        if pnl_pct >= params['take_profit_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f"BEAR_TP_{params['take_profit_pct']*100:.0f}%",
                'pnl_pct': pnl_pct
            }

        # 손절
        if pnl_pct <= params['stop_loss_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f"BEAR_SL_{abs(params['stop_loss_pct'])*100:.0f}%",
                'pnl_pct': pnl_pct
            }

    return {'action': 'hold'}


def bull_market_strategy(df, i, position, config):
    """
    상승장 전략: 공격적 추세 추종
    - VWAP 상향 돌파 시 매수
    - 익절 +30%
    - Trailing Stop 20%
    """
    close = df.iloc[i]['close']
    vwap = df.iloc[i]['vwap']

    params = config['bull_strategy']

    # 포지션 없을 때
    if position is None:
        # VWAP 돌파 확인
        if i > 0:
            prev_close = df.iloc[i-1]['close']
            prev_vwap = df.iloc[i-1]['vwap']

            # 전일 VWAP 이하 → 금일 VWAP 돌파
            if prev_close <= prev_vwap and close > vwap:
                return {
                    'action': 'buy',
                    'fraction': params['max_position_fraction'],
                    'reason': 'BULL_VWAP_BREAKOUT',
                    'market_type': 'BULL'
                }

    # 포지션 있을 때
    else:
        entry_price = position['entry_price']
        high_since_entry = position.get('high_price', entry_price)

        # 최고가 갱신
        if close > high_since_entry:
            position['high_price'] = close
            high_since_entry = close

        pnl_pct = (close - entry_price) / entry_price
        drawdown_from_peak = (close - high_since_entry) / high_since_entry

        # 익절
        if pnl_pct >= params['take_profit_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f"BULL_TP_{params['take_profit_pct']*100:.0f}%",
                'pnl_pct': pnl_pct
            }

        # Trailing Stop (수익 중일 때만)
        if pnl_pct > 0 and drawdown_from_peak <= -params['trailing_stop_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f"BULL_TRAILING_{params['trailing_stop_pct']*100:.0f}%",
                'pnl_pct': pnl_pct
            }

        # 손절
        if pnl_pct <= params['stop_loss_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f"BULL_SL_{abs(params['stop_loss_pct'])*100:.0f}%",
                'pnl_pct': pnl_pct
            }

    return {'action': 'hold'}


def sideways_market_strategy(df, i, position, config):
    """
    횡보장 전략: 역추세 적극 거래
    - RSI < 30 매수, RSI > 70 매도
    - 익절 +10%
    - 손절 -5%
    """
    rsi = df.iloc[i]['rsi']
    close = df.iloc[i]['close']

    params = config['sideways_strategy']

    # 포지션 없을 때
    if position is None:
        # 과매도
        if rsi < params['rsi_oversold']:
            return {
                'action': 'buy',
                'fraction': params['max_position_fraction'],
                'reason': 'SIDEWAYS_RSI_OVERSOLD',
                'market_type': 'SIDEWAYS'
            }

    # 포지션 있을 때
    else:
        entry_price = position['entry_price']
        pnl_pct = (close - entry_price) / entry_price

        # 과매수 → 즉시 매도
        if rsi > params['rsi_overbought']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': 'SIDEWAYS_RSI_OVERBOUGHT',
                'pnl_pct': pnl_pct
            }

        # 익절
        if pnl_pct >= params['take_profit_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f"SIDEWAYS_TP_{params['take_profit_pct']*100:.0f}%",
                'pnl_pct': pnl_pct
            }

        # 손절
        if pnl_pct <= params['stop_loss_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f"SIDEWAYS_SL_{abs(params['stop_loss_pct'])*100:.0f}%",
                'pnl_pct': pnl_pct
            }

    return {'action': 'hold'}


def v19_strategy(df, i, position, config):
    """
    v19 메인 전략: 시장 적응형 혼합

    Args:
        df: 데이터프레임 (지표 포함)
        i: 현재 인덱스
        position: 현재 포지션 정보 (dict or None)
        config: 전략 설정

    Returns:
        dict: {'action': 'buy'|'sell'|'hold', 'fraction': float, 'reason': str}
    """
    # 초기 캔들 스킵
    if i < 30:
        return {'action': 'hold'}

    # 시장 상황 분류
    market_type = classify_market(df, i, config)

    # 포지션이 있는데 시장 타입이 변경된 경우
    if position is not None:
        entry_market = position.get('market_type', None)
        if entry_market and entry_market != market_type:
            # 시장 전환 시 기존 포지션 청산
            pnl_pct = (df.iloc[i]['close'] - position['entry_price']) / position['entry_price']
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'MARKET_SWITCH_{entry_market}_TO_{market_type}',
                'pnl_pct': pnl_pct
            }

    # 시장별 전략 실행
    if market_type == "BEAR":
        return bear_market_strategy(df, i, position, config)
    elif market_type == "BULL":
        return bull_market_strategy(df, i, position, config)
    else:  # SIDEWAYS
        return sideways_market_strategy(df, i, position, config)
