#!/usr/bin/env python3
"""
v33_minute240 Strategy: Mid-term Trading on 4-hour Candles

전략:
- Minute240 (4시간봉) 타임프레임
- Day-level BULL 필터
- 강한 트렌드 진입 (ADX >= 25)
- 분할 익절 (5%, 8%, 12%)
- Kelly Criterion 포지션 사이징
- 목표: 3-5 거래/월, 평균 5% 수익
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional


def calculate_kelly_position(config: Dict, consecutive_losses: int = 0) -> float:
    """Kelly Criterion 포지션 계산"""
    ps = config['position_sizing']
    win_rate = ps['win_rate']
    avg_win = ps['avg_win']
    avg_loss = ps['avg_loss']

    if avg_loss == 0:
        return ps['max_position']

    b = avg_win / avg_loss
    q = 1 - win_rate
    kelly_f = (win_rate * b - q) / b

    kelly_f *= ps['kelly_fraction']

    if consecutive_losses > 0:
        reduction = config['risk_management']['reduce_position_after_loss'] ** consecutive_losses
        kelly_f *= reduction

    kelly_f = max(ps['min_position'], min(kelly_f, ps['max_position']))

    return kelly_f


def check_day_filter(day_data: pd.Series, config: Dict) -> tuple:
    """Day-level BULL 필터 체크"""
    df = config['day_filter']

    if df['bull_required']:
        day_mfi = day_data.get('mfi', 0)
        day_macd = day_data.get('macd', 0)
        day_signal = day_data.get('macd_signal', 0)

        if day_mfi < df['mfi_min']:
            return False, "DAY_MFI_LOW"

        if df['macd_bullish'] and day_macd <= day_signal:
            return False, "DAY_MACD_BEARISH"

    return True, "DAY_BULL"


def v33_strategy(
    df: pd.DataFrame,
    i: int,
    config: Dict,
    position_info: Optional[Dict] = None,
    day_data: Optional[pd.Series] = None,
    consecutive_losses: int = 0
) -> Dict[str, Any]:
    """
    v33_minute240 전략 로직

    Entry:
        - Day BULL 필터 통과
        - ADX >= 25 (강한 트렌드)
        - 24시간 모멘텀 >= +2.0%
        - 연속 상승 >= 2 캔들
        - Volume ratio >= 1.0
        - RSI 40-75 (과매도/과매수 회피)

    Exit:
        - 분할 익절: 5% (1/3), 8% (1/3), 12% (1/3)
        - 손절: -2.5%
        - Trailing stop: +4% 진입 시 peak -1.5%
        - 모멘텀 반전: -2%
        - 최대 보유: 168시간 (7일)
    """
    if i < 30:
        return {'action': 'hold', 'reason': 'WARMUP'}

    current = df.iloc[i]
    close = current['close']

    # === ENTRY LOGIC ===
    if position_info is None:
        # Day 필터
        if day_data is not None:
            is_valid, reason = check_day_filter(day_data, config)
            if not is_valid:
                return {'action': 'hold', 'reason': reason}

        ec = config['entry_conditions']

        # ADX (트렌드 강도)
        adx = current.get('adx', 0)
        if adx < ec['adx_min']:
            return {'action': 'hold', 'reason': f'ADX_WEAK: {adx:.1f}'}

        # 24시간 모멘텀 (6 캔들)
        if i >= 6:
            momentum_24h = (close / df.iloc[i-6]['close'] - 1) * 100
        else:
            momentum_24h = 0

        if momentum_24h < ec['momentum_24h_min']:
            return {'action': 'hold', 'reason': f'MOMENTUM_WEAK: {momentum_24h:.2f}%'}

        # 연속 상승
        consecutive_up = 0
        for j in range(i-1, max(i-10, 0), -1):
            if df.iloc[j]['close'] > df.iloc[j-1]['close']:
                consecutive_up += 1
            else:
                break

        if consecutive_up < ec['consecutive_up_min']:
            return {'action': 'hold', 'reason': f'NO_TREND: up={consecutive_up}'}

        # Volume ratio
        volume_ratio = current['volume'] / current.get('volume_sma_20', current['volume'] + 1e-10)
        if volume_ratio < ec['volume_ratio_min']:
            return {'action': 'hold', 'reason': f'VOLUME_LOW: {volume_ratio:.2f}x'}

        # RSI
        rsi = current.get('rsi_14', 50)
        if rsi < ec['rsi_min'] or rsi > ec['rsi_max']:
            return {'action': 'hold', 'reason': f'RSI_OUT: {rsi:.1f}'}

        # Kelly 포지션
        fraction = calculate_kelly_position(config, consecutive_losses)

        return {
            'action': 'buy',
            'fraction': fraction,
            'reason': f'M240_ENTRY: adx={adx:.1f} mom={momentum_24h:.2f}% kelly={fraction:.2f}'
        }

    # === EXIT LOGIC ===
    else:
        entry_price = position_info['entry_price']
        entry_time = position_info['entry_time']
        peak_price = position_info.get('peak_price', entry_price)
        remaining_fraction = position_info.get('remaining_fraction', 1.0)

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

        # 1. 손절
        if profit_pct <= -exc['stop_loss_pct'] * 100:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'STOP_LOSS: {profit_pct:.2f}%'}

        # 2. 분할 익절
        if profit_pct >= exc['take_profit_3'] * 100 and remaining_fraction > 0.7:
            # 12% 도달, 1/3 매도
            return {
                'action': 'sell',
                'fraction': 0.33,
                'reason': f'TP3: {profit_pct:.2f}%',
                'remaining_fraction': remaining_fraction - 0.33
            }
        elif profit_pct >= exc['take_profit_2'] * 100 and remaining_fraction > 0.4:
            # 8% 도달, 1/3 매도
            return {
                'action': 'sell',
                'fraction': 0.33,
                'reason': f'TP2: {profit_pct:.2f}%',
                'remaining_fraction': remaining_fraction - 0.33
            }
        elif profit_pct >= exc['take_profit_1'] * 100 and remaining_fraction > 0.1:
            # 5% 도달, 1/3 매도
            return {
                'action': 'sell',
                'fraction': 0.33,
                'reason': f'TP1: {profit_pct:.2f}%',
                'remaining_fraction': remaining_fraction - 0.33
            }

        # 3. Trailing stop
        if profit_pct >= exc['trailing_stop_trigger'] * 100:
            if drawdown_from_peak <= -exc['trailing_stop_distance'] * 100:
                return {'action': 'sell', 'fraction': 1.0, 'reason': f'TRAILING_STOP: peak={drawdown_from_peak:.2f}%'}

        # 4. 모멘텀 반전
        if i >= 6:
            momentum_24h = (close / df.iloc[i-6]['close'] - 1) * 100
            if momentum_24h <= exc['momentum_reverse_threshold'] * 100:
                return {'action': 'sell', 'fraction': 1.0, 'reason': f'MOMENTUM_REVERSE: {momentum_24h:.2f}%'}

        # 5. 최대 보유 시간
        if hold_hours >= exc['max_hold_hours']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'MAX_HOLD: {hold_hours:.1f}h'}

        return {
            'action': 'hold',
            'reason': 'IN_POSITION',
            'peak_price': peak_price,
            'remaining_fraction': remaining_fraction
        }


if __name__ == '__main__':
    print("v33_minute240 strategy module")
    print("Use backtest.py to run backtesting")
