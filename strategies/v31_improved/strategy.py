#!/usr/bin/env python3
"""
v31_improved Strategy: Kelly Criterion Position Sizing + Multi-Timeframe Filter

개선 사항:
1. Kelly Criterion 기반 동적 포지션 사이징
2. Day + Minute240 + Minute60 multi-timeframe 필터링
3. 연속 손실 시 포지션 축소
4. 개선된 익절/손절 (1.5% / 1.0%)
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional

def calculate_kelly_position(config: Dict, consecutive_losses: int = 0) -> float:
    """
    Kelly Criterion으로 포지션 크기 계산

    Kelly formula: f = (p*b - q) / b
    - p = win rate
    - q = loss rate (1 - p)
    - b = avg_win / avg_loss
    """
    ps = config['position_sizing']
    win_rate = ps['win_rate']
    avg_win = ps['avg_win']
    avg_loss = ps['avg_loss']

    if avg_loss == 0:
        return ps['max_position']

    b = avg_win / avg_loss
    q = 1 - win_rate
    kelly_f = (win_rate * b - q) / b

    # Safety fraction 적용 (보수적 접근)
    kelly_f *= ps['kelly_fraction']

    # 연속 손실 시 포지션 축소
    if consecutive_losses > 0:
        reduction = config['risk_management']['reduce_position_after_loss'] ** consecutive_losses
        kelly_f *= reduction

    # Min/Max 제한
    kelly_f = max(ps['min_position'], min(kelly_f, ps['max_position']))

    return kelly_f


def check_multi_timeframe_filter(day_data: pd.Series, m240_data: pd.Series, config: Dict) -> tuple:
    """
    Multi-timeframe 필터 체크

    Returns:
        (is_valid, reason): (bool, str)
    """
    mtf = config['multi_timeframe_filter']

    # Day-level BULL 필터
    if mtf['day_bull_required']:
        day_mfi = day_data.get('mfi', 0)
        day_macd = day_data.get('macd', 0)
        day_signal = day_data.get('macd_signal', 0)

        if day_mfi < 50 or day_macd <= day_signal:
            return False, "DAY_NOT_BULL"

    # Minute240 트렌드 필터
    if mtf['minute240_trend_required']:
        m240_adx = m240_data.get('adx', 0)

        if m240_adx < mtf['minute240_adx_min']:
            return False, "M240_WEAK_TREND"

    # Minute240 MACD 필터
    if mtf['minute240_macd_bullish']:
        m240_macd = m240_data.get('macd', 0)
        m240_signal = m240_data.get('macd_signal', 0)

        if m240_macd <= m240_signal:
            return False, "M240_MACD_BEARISH"

    return True, "MTF_PASS"


def v31_improved_strategy(
    df: pd.DataFrame,
    i: int,
    config: Dict,
    position_info: Optional[Dict] = None,
    day_data: Optional[pd.Series] = None,
    m240_data: Optional[pd.Series] = None,
    consecutive_losses: int = 0
) -> Dict[str, Any]:
    """
    v31_improved 전략 로직

    Entry:
        - Multi-timeframe 필터 통과 (Day BULL + M240 Trend)
        - 최근 5시간 모멘텀 >= 0.7%
        - 연속 상승 >= 3시간
        - Volume ratio >= 1.3
        - RSI <= 70
        - Kelly Criterion 포지션 사이징

    Exit:
        - Take profit: +1.5%
        - Stop loss: -1.0%
        - Trailing stop: peak -0.5%
        - Momentum reverse: -1.0% over 5h
        - Max hold: 50 hours
    """
    # 지표 부족 시 대기
    if i < 30:
        return {'action': 'hold', 'reason': 'WARMUP'}

    current = df.iloc[i]
    close = current['close']

    # === ENTRY LOGIC ===
    if position_info is None:
        # Multi-timeframe 필터 체크
        if day_data is not None and m240_data is not None:
            is_valid, reason = check_multi_timeframe_filter(day_data, m240_data, config)
            if not is_valid:
                return {'action': 'hold', 'reason': reason}

        # Entry 조건
        ec = config['entry_conditions']

        # 5시간 모멘텀
        if i >= 5:
            momentum_5h = (close / df.iloc[i-5]['close'] - 1) * 100
        else:
            momentum_5h = 0

        # 연속 상승 카운트
        consecutive_up = 0
        for j in range(i-1, max(i-10, 0), -1):
            if df.iloc[j]['close'] > df.iloc[j-1]['close']:
                consecutive_up += 1
            else:
                break

        # Volume ratio
        volume_ratio = current['volume'] / current.get('volume_sma_20', current['volume'] + 1e-10)

        rsi = current.get('rsi_14', 50)

        # Entry 조건 체크
        strong_momentum = momentum_5h >= ec['momentum_5h_min']
        trend_confirmed = consecutive_up >= ec['consecutive_up_min']
        volume_surge = volume_ratio >= ec['volume_ratio_min']
        not_overbought = rsi <= ec['rsi_max']

        if strong_momentum and trend_confirmed and volume_surge and not_overbought:
            # Kelly Criterion 포지션 계산
            fraction = calculate_kelly_position(config, consecutive_losses)

            return {
                'action': 'buy',
                'fraction': fraction,
                'reason': f'KELLY_ENTRY: mom={momentum_5h:.2f}% up={consecutive_up} vol={volume_ratio:.2f}x kelly={fraction:.2f}'
            }

        return {'action': 'hold', 'reason': 'NO_ENTRY_SIGNAL'}

    # === EXIT LOGIC ===
    else:
        entry_price = position_info['entry_price']
        entry_time = position_info['entry_time']
        peak_price = position_info.get('peak_price', entry_price)

        profit_pct = (close / entry_price - 1) * 100

        # Peak 업데이트
        if close > peak_price:
            peak_price = close

        drawdown_from_peak = (close / peak_price - 1) * 100

        # 보유 시간
        current_time = current.name
        if isinstance(entry_time, str):
            entry_time = pd.to_datetime(entry_time)
        if isinstance(current_time, str):
            current_time = pd.to_datetime(current_time)

        hold_hours = (current_time - entry_time).total_seconds() / 3600

        exc = config['exit_conditions']

        # 1. 익절
        if profit_pct >= exc['take_profit_pct'] * 100:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'TAKE_PROFIT: {profit_pct:.2f}%'}

        # 2. 손절
        if profit_pct <= -exc['stop_loss_pct'] * 100:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'STOP_LOSS: {profit_pct:.2f}%'}

        # 3. Trailing stop
        if profit_pct >= exc['trailing_stop_trigger'] * 100:
            if drawdown_from_peak <= -exc['trailing_stop_distance'] * 100:
                return {'action': 'sell', 'fraction': 1.0, 'reason': f'TRAILING_STOP: peak={drawdown_from_peak:.2f}%'}

        # 4. 모멘텀 반전
        if i >= 5:
            momentum_5h = (close / df.iloc[i-5]['close'] - 1) * 100
            if momentum_5h <= exc['momentum_reverse_threshold'] * 100:
                return {'action': 'sell', 'fraction': 1.0, 'reason': f'MOMENTUM_REVERSE: {momentum_5h:.2f}%'}

        # 5. 최대 보유 시간
        if hold_hours >= exc['max_hold_hours']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'MAX_HOLD: {hold_hours:.1f}h'}

        # Peak 정보 업데이트를 위해 반환
        return {'action': 'hold', 'reason': 'IN_POSITION', 'peak_price': peak_price}


if __name__ == '__main__':
    print("v31_improved strategy module")
    print("Use backtest.py to run backtesting")
