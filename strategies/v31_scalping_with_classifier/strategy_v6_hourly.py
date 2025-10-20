#!/usr/bin/env python3
"""
v31 Strategy V6: 1시간봉 최적화
Minute60에 특화된 전략 - 더 큰 타겟, 더 긴 보유

핵심:
- 1시간봉: 더 확실한 트렌드
- 목표: +2-4% (수수료 극복)
- 하루 3-5거래 정도
- BULL 시장에서만 거래
"""

def v31_strategy(df, i, config, position_info=None, market_state='SIDEWAYS'):
    """
    1시간봉 트렌드 추종
    """

    if i < 30:
        return {'action': 'hold'}

    # Market filter - BULL만
    if config['scalping_settings']['only_trade_in_bull'] and market_state != 'BULL':
        if position_info is not None:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'MARKET_NOT_BULL'}
        return {'action': 'hold'}

    row = df.iloc[i]
    close = row['close']
    volume_ratio = row.get('volume_ratio', 1.0)
    rsi = row.get('rsi_14', 50)

    # 중기 모멘텀 (최근 6시간)
    if i >= 6:
        price_6h_ago = df.iloc[i - 6]['close']
        momentum_6h = (close / price_6h_ago - 1) * 100
    else:
        momentum_6h = 0

    # 연속 상승 확인
    consecutive_up = 0
    for j in range(1, 5):  # 최근 4시간
        if i - j < 0:
            break
        if df.iloc[i - j + 1]['close'] > df.iloc[i - j]['close']:
            consecutive_up += 1

    # ====================
    # ENTRY: 강한 트렌드
    # ====================
    if position_info is None:
        # 더 강한 조건 (1시간봉이니까)
        strong_momentum = momentum_6h >= 1.5  # 6시간에 +1.5%
        trend_confirmed = consecutive_up >= 3  # 3시간 연속 상승
        volume_good = volume_ratio >= 1.2
        not_overbought = rsi <= 70  # 과매수 회피

        if strong_momentum and trend_confirmed and volume_good and not_overbought:
            return {
                'action': 'buy',
                'fraction': 0.7,  # 70% 포지션 (크게)
                'reason': f'HOURLY_ENTRY: {consecutive_up}h연속, {momentum_6h:.2f}%'
            }

    # ====================
    # EXIT: 더 큰 목표
    # ====================
    else:
        entry_price = position_info['entry_price']
        profit_pct = (close / entry_price - 1) * 100
        hold_hours = position_info.get('hold_candles', 0)

        # Peak tracking
        if not hasattr(position_info, 'peak_profit'):
            position_info['peak_profit'] = profit_pct
        else:
            if profit_pct > position_info['peak_profit']:
                position_info['peak_profit'] = profit_pct

        peak = position_info.get('peak_profit', 0)

        # Exit 1: 목표 달성 (+3%)
        if profit_pct >= 3.0:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TARGET_3%: {profit_pct:.2f}%'
            }

        # Exit 2: 중간 익절 (+2%) - 50%만 청산
        if profit_pct >= 2.0 and hold_hours >= 2:
            return {
                'action': 'sell',
                'fraction': 0.5,
                'reason': f'PARTIAL_2%: {profit_pct:.2f}% (50% 청산)'
            }

        # Exit 3: Trailing stop (최고점에서 -0.8%)
        if peak >= 2.0 and profit_pct <= (peak - 0.8):
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TRAILING: peak={peak:.2f}%, now={profit_pct:.2f}%'
            }

        # Exit 4: 손절 (-1.2%)
        if profit_pct <= -1.2:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS: {profit_pct:.2f}%'
            }

        # Exit 5: 모멘텀 반전 (최근 3시간 -1%)
        if i >= 3:
            recent_momentum = (close / df.iloc[i-3]['close'] - 1) * 100
            if recent_momentum <= -1.0:
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'MOMENTUM_REVERSE: {recent_momentum:.2f}%'
                }

        # Exit 6: 타임아웃 (48시간)
        if hold_hours >= 48:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TIMEOUT: {hold_hours}h (profit: {profit_pct:.2f}%)'
            }

    return {'action': 'hold'}
