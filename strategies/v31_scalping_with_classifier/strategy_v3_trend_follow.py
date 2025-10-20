#!/usr/bin/env python3
"""
v31 Strategy V3: 트렌드 추종 (확립된 모멘텀 탑승)
False signal 최소화 - 확인된 트렌드만 따라감

핵심:
- 가격이 **지속적으로** 상승 중 (3+ 연속 상승 캔들)
- 거래량 동반 상승
- 진입 후 빠른 익절/손절
"""

def v31_strategy(df, i, config, position_info=None, market_state='SIDEWAYS'):
    """
    트렌드 추종: 확립된 상승만 따라감
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

    # ====================
    # 트렌드 확인: 최근 N개 캔들 모두 상승
    # ====================
    consecutive_up = 0
    for lookback in range(1, 6):  # 최근 5개 확인
        if i - lookback < 0:
            break
        prev_candle = df.iloc[i - lookback]
        curr_candle = df.iloc[i - lookback + 1] if lookback > 1 else row

        if curr_candle['close'] > prev_candle['close']:
            consecutive_up += 1
        else:
            break

    # 전체 상승폭
    if i >= 5:
        price_5_ago = df.iloc[i - 5]['close']
        momentum_5 = (close / price_5_ago - 1) * 100
    else:
        momentum_5 = 0

    # ====================
    # ENTRY: 확립된 상승 트렌드
    # ====================
    if position_info is None:
        # 조건:
        # 1. 3+ 연속 상승 캔들
        # 2. 최근 5캔들 동안 +1% 이상 상승
        # 3. 거래량 증가

        strong_trend = consecutive_up >= 3
        good_momentum = momentum_5 >= 1.0
        volume_confirm = volume_ratio >= 1.1

        if strong_trend and good_momentum and volume_confirm:
            return {
                'action': 'buy',
                'fraction': 0.6,  # 60% 포지션
                'reason': f'TREND_ENTRY: {consecutive_up}캔들 연속상승, {momentum_5:.2f}%'
            }

    # ====================
    # EXIT: 트렌드 끝 또는 목표 달성
    # ====================
    else:
        entry_price = position_info['entry_price']
        profit_pct = (close / entry_price - 1) * 100
        hold_candles = position_info.get('hold_candles', 0)

        # 현재 캔들이 하락?
        if i > 0:
            prev_close = df.iloc[i - 1]['close']
            current_down = close < prev_close
        else:
            current_down = False

        # Exit 1: 하락 캔들 출현 (트렌드 끝)
        if current_down:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TREND_END: 하락캔들 (profit: {profit_pct:.2f}%)'
            }

        # Exit 2: 목표 수익 (+2%)
        if profit_pct >= 2.0:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TARGET_PROFIT: {profit_pct:.2f}%'
            }

        # Exit 3: 손절 (-1%)
        if profit_pct <= -1.0:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS: {profit_pct:.2f}%'
            }

        # Exit 4: 타임아웃 (20캔들 = 100분)
        if hold_candles >= 20:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TIMEOUT: {hold_candles}캔들 (profit: {profit_pct:.2f}%)'
            }

    return {'action': 'hold'}
