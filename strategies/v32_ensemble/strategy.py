#!/usr/bin/env python3
"""
v32_ensemble Strategy: Dynamic Market-Based Strategy Switching

시장 상태에 따라 전략 자동 전환:
- BULL: v30 (long-term hold) - MFI>=50, MACD>Signal
- SIDEWAYS: v31 (scalping) - 나머지
- BEAR: Cash hold - MFI<=40, MACD<Signal

목표: BULL 포착으로 30-50% 수익
"""

import sys
sys.path.append('../..')

import pandas as pd
import numpy as np
from typing import Dict, Any, Optional


def classify_market(day_data: pd.Series, config: Dict) -> str:
    """
    Day-level 시장 분류

    Returns:
        'BULL', 'SIDEWAYS', or 'BEAR'
    """
    mc = config['market_classification']

    mfi = day_data.get('mfi', 50)
    macd = day_data.get('macd', 0)
    macd_signal = day_data.get('macd_signal', 0)

    # BULL 조건
    bull_mfi = mfi >= mc['bull_mfi_min']
    bull_macd = macd > macd_signal if mc['bull_macd_positive'] else True

    if bull_mfi and bull_macd:
        return 'BULL'

    # BEAR 조건
    bear_mfi = mfi <= mc['bear_mfi_max']
    bear_macd = macd < macd_signal if mc['bear_macd_negative'] else True

    if bear_mfi and bear_macd:
        return 'BEAR'

    return 'SIDEWAYS'


def v30_longterm_strategy(
    day_df: pd.DataFrame,
    i: int,
    config: Dict,
    position_info: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    v30 장기 전략 (Day-level)

    Entry: MFI>=45, MACD 골든크로스, ADX>=20
    Exit: MACD 데드크로스, Trailing -15%, Take profit +50%
    """
    if i < 30:
        return {'action': 'hold', 'reason': 'WARMUP'}

    current = day_df.iloc[i]
    close = current['close']
    v30 = config['v30_longterm_settings']

    # === ENTRY ===
    if position_info is None:
        entry = v30['entry']

        mfi = current.get('mfi', 0)
        macd = current.get('macd', 0)
        macd_signal = current.get('macd_signal', 0)
        adx = current.get('adx', 0)
        volume_ratio = current['volume'] / current.get('volume_sma_20', current['volume'] + 1e-10)

        # 이전 MACD
        if i >= 1:
            prev_macd = day_df.iloc[i-1]['macd']
            prev_signal = day_df.iloc[i-1]['macd_signal']
            golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)
        else:
            golden_cross = False

        # Entry 조건
        if (mfi >= entry['mfi_min'] and
            golden_cross and
            adx >= entry['adx_min'] and
            volume_ratio >= entry['volume_ratio_min']):

            fraction = v30['position_sizing']['initial_fraction']

            return {
                'action': 'buy',
                'fraction': fraction,
                'reason': f'V30_ENTRY: mfi={mfi:.1f} adx={adx:.1f}'
            }

        return {'action': 'hold', 'reason': 'NO_V30_ENTRY'}

    # === EXIT ===
    else:
        entry_price = position_info['entry_price']
        entry_time = position_info['entry_time']
        peak_price = position_info.get('peak_price', entry_price)

        profit_pct = (close / entry_price - 1) * 100

        # Peak 업데이트
        if close > peak_price:
            peak_price = close

        drawdown_from_peak = (close / peak_price - 1) * 100

        # 보유 일수
        current_time = current.name
        if isinstance(entry_time, str):
            entry_time = pd.to_datetime(entry_time)
        if isinstance(current_time, str):
            current_time = pd.to_datetime(current_time)

        hold_days = (current_time - entry_time).days

        exit_cfg = v30['exit']

        # 1. MACD 데드크로스
        if i >= 1:
            prev_macd = day_df.iloc[i-1]['macd']
            prev_signal = day_df.iloc[i-1]['macd_signal']
            macd = current.get('macd', 0)
            macd_signal = current.get('macd_signal', 0)
            dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)

            if dead_cross:
                return {'action': 'sell', 'fraction': 1.0, 'reason': f'V30_DEAD_CROSS: {profit_pct:.2f}%'}

        # 2. Trailing stop
        if drawdown_from_peak <= -exit_cfg['trailing_stop_pct'] * 100:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'V30_TRAILING: peak={drawdown_from_peak:.2f}%'}

        # 3. Take profit
        if profit_pct >= exit_cfg['take_profit_pct'] * 100:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'V30_TAKE_PROFIT: {profit_pct:.2f}%'}

        # 4. Max hold
        if hold_days >= exit_cfg['max_hold_days']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'V30_MAX_HOLD: {hold_days}d'}

        return {'action': 'hold', 'reason': 'V30_IN_POSITION', 'peak_price': peak_price}


def v31_scalping_strategy(
    m60_df: pd.DataFrame,
    i: int,
    config: Dict,
    position_info: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    v31 스캘핑 전략 (Minute60-level)

    Entry: 5h momentum >= 0.7%, consecutive up >= 3, volume ratio >= 1.3
    Exit: TP +1.2%, SL -0.7%, Trailing -0.5%, Momentum reverse -1%
    """
    if i < 30:
        return {'action': 'hold', 'reason': 'WARMUP'}

    current = m60_df.iloc[i]
    close = current['close']
    v31 = config['v31_scalping_settings']

    # === ENTRY ===
    if position_info is None:
        entry = v31['entry']

        # 5시간 모멘텀
        if i >= 5:
            momentum_5h = (close / m60_df.iloc[i-5]['close'] - 1) * 100
        else:
            momentum_5h = 0

        # 연속 상승
        consecutive_up = 0
        for j in range(i-1, max(i-10, 0), -1):
            if m60_df.iloc[j]['close'] > m60_df.iloc[j-1]['close']:
                consecutive_up += 1
            else:
                break

        # Volume ratio
        volume_ratio = current['volume'] / current.get('volume_sma_20', current['volume'] + 1e-10)

        rsi = current.get('rsi_14', 50)

        # Entry 조건
        if (momentum_5h >= entry['momentum_5h_min'] and
            consecutive_up >= entry['consecutive_up_min'] and
            volume_ratio >= entry['volume_ratio_min'] and
            rsi <= entry['rsi_max']):

            fraction = v31['position_sizing']['fixed_fraction']

            return {
                'action': 'buy',
                'fraction': fraction,
                'reason': f'V31_ENTRY: mom={momentum_5h:.2f}% up={consecutive_up}'
            }

        return {'action': 'hold', 'reason': 'NO_V31_ENTRY'}

    # === EXIT ===
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

        exit_cfg = v31['exit']

        # 1. 익절
        if profit_pct >= exit_cfg['take_profit_pct'] * 100:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'V31_TP: {profit_pct:.2f}%'}

        # 2. 손절
        if profit_pct <= -exit_cfg['stop_loss_pct'] * 100:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'V31_SL: {profit_pct:.2f}%'}

        # 3. Trailing stop
        if profit_pct >= exit_cfg['trailing_stop_trigger'] * 100:
            if drawdown_from_peak <= -exit_cfg['trailing_stop_distance'] * 100:
                return {'action': 'sell', 'fraction': 1.0, 'reason': f'V31_TRAILING: {drawdown_from_peak:.2f}%'}

        # 4. 모멘텀 반전
        if i >= 5:
            momentum_5h = (close / m60_df.iloc[i-5]['close'] - 1) * 100
            if momentum_5h <= exit_cfg['momentum_reverse_threshold'] * 100:
                return {'action': 'sell', 'fraction': 1.0, 'reason': f'V31_MOM_REV: {momentum_5h:.2f}%'}

        # 5. Max hold
        if hold_hours >= exit_cfg['max_hold_hours']:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'V31_MAX_HOLD: {hold_hours:.1f}h'}

        return {'action': 'hold', 'reason': 'V31_IN_POSITION', 'peak_price': peak_price}


def v32_ensemble_strategy(
    day_df: pd.DataFrame,
    day_i: int,
    m60_df: pd.DataFrame,
    m60_i: int,
    config: Dict,
    position_info: Optional[Dict] = None
) -> Dict[str, Any]:
    """
    v32 앙상블 전략

    시장 상태에 따라 v30 또는 v31 실행
    - BULL: v30 (day-level long-term)
    - SIDEWAYS: v31 (minute60-level scalping)
    - BEAR: Hold cash
    """
    # 현재 Day 데이터
    current_day = day_df.iloc[day_i]
    market_state = classify_market(current_day, config)

    strategy_map = config['strategy_selection']
    selected_strategy = strategy_map[f'{market_state.lower()}_market']

    # BEAR: 현금 보유
    if selected_strategy == 'hold_cash':
        if position_info is not None:
            # 포지션 청산
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'BEAR_MARKET_EXIT'}
        else:
            return {'action': 'hold', 'reason': 'BEAR_MARKET_CASH'}

    # BULL: v30 장기 전략
    elif selected_strategy == 'v30_longterm':
        decision = v30_longterm_strategy(day_df, day_i, config, position_info)
        decision['market_state'] = market_state
        decision['active_strategy'] = 'v30'
        return decision

    # SIDEWAYS: v31 스캘핑
    elif selected_strategy == 'v31_scalping':
        decision = v31_scalping_strategy(m60_df, m60_i, config, position_info)
        decision['market_state'] = market_state
        decision['active_strategy'] = 'v31'
        return decision

    else:
        return {'action': 'hold', 'reason': 'UNKNOWN_STRATEGY'}


if __name__ == '__main__':
    print("v32_ensemble strategy module")
    print("Use backtest.py to run backtesting")
