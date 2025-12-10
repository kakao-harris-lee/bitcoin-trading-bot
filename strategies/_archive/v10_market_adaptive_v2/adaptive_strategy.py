#!/usr/bin/env python3
"""
v10 Market-Adaptive Strategy v2

v08 + v09 조합:
- v08: 시장 분류 (Bull/Sideways/Bear)
- v09: Golden Cross 진입 조건
- v08 실패 보완: Golden Cross 유지하되 Sideways에서 진입 조건 완화
- v09 실패 보완: Trailing Stop 17.52% → 12% (Bull), 시장 전환 시 수익 중이면 유지
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict


def v10_strategy_function(df, i, params, detector):
    """
    v10 전략 함수

    Args:
        df: DataFrame with indicators
        i: current index
        params: strategy parameters
        detector: MarketRegimeDetector instance

    Returns:
        dict: {'action': 'buy'|'sell'|'hold', 'fraction': float, 'reason': str}
    """
    global in_position, entry_price, highest_price, entry_time, entry_regime, hold_days

    if i < 30:
        return {'action': 'hold'}

    row = df.iloc[i]
    current_price = row['close']
    current_time = row['timestamp']

    # 시장 분류
    regime = detector.detect(df, i)

    # 보유 일수 계산
    if in_position and entry_time is not None:
        hold_days = (current_time - entry_time).days

    # ===== 매수 로직 =====
    if not in_position:
        # 시장별 파라미터 선택
        if regime == 'bull':
            market_params = params['bull_market']
        elif regime == 'sideways':
            market_params = params['sideways_market']
        elif regime == 'bear':
            market_params = params['bear_market']
        else:
            return {'action': 'hold'}

        # 진입 조건 확인
        should_buy = False

        # EMA/MACD 값
        ema12 = row['ema12']
        ema26 = row['ema26']
        macd = row['macd']
        macd_signal = row['macd_signal']
        momentum = row['momentum']

        prev_row = df.iloc[i-1]
        prev_ema12 = prev_row['ema12']
        prev_ema26 = prev_row['ema26']
        prev_macd = prev_row['macd']
        prev_macd_signal = prev_row['macd_signal']

        # Golden Cross 확인
        ema_golden = (prev_ema12 <= prev_ema26) and (ema12 > ema26)
        macd_golden = (prev_macd <= prev_macd_signal) and (macd > macd_signal)

        # 시장별 진입 조건
        if regime == 'bull':
            # Bull: Golden Cross (EMA OR MACD)
            if market_params['require_golden_cross']:
                should_buy = ema_golden or macd_golden
            else:
                should_buy = ema12 > ema26

        elif regime == 'sideways':
            # Sideways: v08 실패 보완 - Golden Cross 불필요, 단순 EMA 위치 + 모멘텀
            if market_params['require_golden_cross']:
                should_buy = ema_golden or macd_golden
            else:
                # 단순 EMA 위치 + 최소 모멘텀
                min_momentum = market_params.get('min_momentum', 0.03)
                should_buy = (ema12 > ema26 and momentum > min_momentum)

        elif regime == 'bear':
            # Bear: v09 2022년 -57.81% 방지 - 매우 보수적 진입
            if market_params['require_golden_cross'] and market_params['require_macd_cross']:
                # 둘 다 필요
                min_momentum = market_params.get('min_momentum', 0.10)
                should_buy = (ema_golden and macd_golden and momentum > min_momentum)
            else:
                should_buy = False  # Bear에서는 거래 안함

        if should_buy:
            in_position = True
            entry_price = current_price
            highest_price = current_price
            entry_time = current_time
            entry_regime = regime
            hold_days = 0

            return {
                'action': 'buy',
                'fraction': market_params['position_fraction'],
                'reason': f'{regime.upper()}_ENTRY'
            }

    # ===== 매도 로직 =====
    else:
        # 현재 수익률
        profit_pct = (current_price - entry_price) / entry_price

        # 최고가 업데이트
        if current_price > highest_price:
            highest_price = current_price

        # 시장 전환 확인
        regime_changed = (regime != entry_regime)

        # v08 실패 방지: 시장 전환 시 수익 중이면 유지
        hold_profit_threshold = params['exit_rules']['regime_change_hold_profit_threshold']
        if regime_changed and profit_pct > hold_profit_threshold:
            # 수익 중이면 청산하지 않고 계속 보유
            # ⚠️ CRITICAL: entry_regime 업데이트하여 다음 날 또 regime_changed가 되지 않도록 함
            entry_regime = regime
        elif regime_changed:
            # 손실 중이거나 소량 수익이면 청산
            in_position = False
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'REGIME_CHANGE_{entry_regime.upper()}_TO_{regime.upper()}'
            }

        # 현재 시장 파라미터
        if regime == 'bull':
            market_params = params['bull_market']
        elif regime == 'sideways':
            market_params = params['sideways_market']
        elif regime == 'bear':
            market_params = params['bear_market']
        else:
            market_params = params['bull_market']  # fallback

        # Trailing Stop
        trailing_stop_pct = market_params['trailing_stop_pct']
        trailing_threshold = highest_price * (1 - trailing_stop_pct)
        if current_price <= trailing_threshold:
            in_position = False
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TRAILING_STOP_{regime.upper()}'
            }

        # Stop Loss
        stop_loss_pct = market_params['stop_loss_pct']
        stop_loss_threshold = entry_price * (1 - stop_loss_pct)
        if current_price <= stop_loss_threshold:
            in_position = False
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS_{regime.upper()}'
            }

        # 최대 보유 기간
        max_hold_days = params['exit_rules']['max_hold_days']
        if hold_days >= max_hold_days:
            in_position = False
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'MAX_HOLD_{hold_days}DAYS'
            }

    return {'action': 'hold'}


# Global state
in_position = False
entry_price = 0.0
highest_price = 0.0
entry_time = None
entry_regime = 'sideways'
hold_days = 0


def reset_state():
    """전역 상태 초기화"""
    global in_position, entry_price, highest_price, entry_time, entry_regime, hold_days
    in_position = False
    entry_price = 0.0
    highest_price = 0.0
    entry_time = None
    entry_regime = 'sideways'
    hold_days = 0
