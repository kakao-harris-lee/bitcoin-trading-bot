#!/usr/bin/env python3
"""
v31 Strategy V5: 최적화된 스캘핑
수수료 극복을 위한 더 큰 수익 타겟 + 더 확실한 신호

핵심:
- 더 확실한 진입 (모멘텀 +0.5%)
- 더 큰 익절 (+1.2%)
- 더 큰 포지션 (50%)
- 수수료 고려한 기대값 최적화
"""

def v31_strategy(df, i, config, position_info=None, market_state='SIDEWAYS'):
    """
    최적화된 스캘핑: 수수료 극복
    """

    if i < 30:
        return {'action': 'hold'}

    # Market filter
    if config['scalping_settings']['only_trade_in_bull'] and market_state != 'BULL':
        if position_info is not None:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'MARKET_NOT_BULL'}
        return {'action': 'hold'}

    row = df.iloc[i]
    close = row['close']
    volume_ratio = row.get('volume_ratio', 1.0)

    # 단기 모멘텀 (최근 5캔들)
    if i >= 5:
        price_5ago = df.iloc[i - 5]['close']
        momentum_5 = (close / price_5ago - 1) * 100
    else:
        momentum_5 = 0

    # 연속 상승 확인
    consecutive_up = 0
    for j in range(1, 4):  # 최근 3캔들
        if i - j < 0:
            break
        if df.iloc[i - j + 1]['close'] > df.iloc[i - j]['close']:
            consecutive_up += 1

    # ====================
    # ENTRY: 확실한 신호만
    # ====================
    if position_info is None:
        # 더 엄격한 조건
        strong_momentum = momentum_5 >= 0.7  # +0.7% 이상
        volume_surge = volume_ratio >= 1.3  # 거래량 1.3배
        trend_confirmed = consecutive_up >= 2  # 2+ 연속 상승

        if strong_momentum and volume_surge and trend_confirmed:
            return {
                'action': 'buy',
                'fraction': 0.5,  # 50% 포지션 (더 크게)
                'reason': f'STRONG_ENTRY: {momentum_5:.2f}%, {consecutive_up}연속'
            }

    # ====================
    # EXIT: 더 큰 목표
    # ====================
    else:
        entry_price = position_info['entry_price']
        profit_pct = (close / entry_price - 1) * 100
        hold_candles = position_info.get('hold_candles', 0)

        # Peak tracking
        if not hasattr(position_info, 'peak_profit'):
            position_info['peak_profit'] = profit_pct
        else:
            if profit_pct > position_info['peak_profit']:
                position_info['peak_profit'] = profit_pct

        peak = position_info.get('peak_profit', 0)

        # Exit 1: 목표 익절 (+1.2% - 수수료 고려)
        if profit_pct >= 1.2:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TARGET_PROFIT: {profit_pct:.2f}%'
            }

        # Exit 2: Trailing stop (최고점에서 -0.5%)
        if peak >= 1.0 and profit_pct <= (peak - 0.5):
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TRAILING_STOP: peak={peak:.2f}%, now={profit_pct:.2f}%'
            }

        # Exit 3: 엄격한 손절 (-0.7%)
        if profit_pct <= -0.7:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS: {profit_pct:.2f}%'
            }

        # Exit 4: 타임아웃 (50캔들 = 250분)
        if hold_candles >= 50:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TIMEOUT: {hold_candles}캔들 (profit: {profit_pct:.2f}%)'
            }

        # Exit 5: 모멘텀 반전 (최근 5캔들 -0.5% 하락)
        if i >= 5:
            recent_momentum = (close / df.iloc[i-5]['close'] - 1) * 100
            if recent_momentum <= -0.5:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'MOMENTUM_REVERSE: {recent_momentum:.2f}% (profit: {profit_pct:.2f}%)'
                }

    return {'action': 'hold'}
