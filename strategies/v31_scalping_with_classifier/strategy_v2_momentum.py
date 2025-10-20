#!/usr/bin/env python3
"""
v31 Strategy V2: 반응형 모멘텀 추종
예측하지 않고, 가격 변동에 빠르게 대응

핵심:
- 가격이 빠르게 상승 중 → 매수 (모멘텀 탑승)
- 가격이 빠르게 하락 중 → 매도 또는 관망
- 상승 모멘텀 끝날 때 → 즉시 매도
"""

def v31_strategy(df, i, config, position_info=None, market_state='SIDEWAYS'):
    """
    모멘텀 추종 전략: 변화에 반응, 예측하지 않음
    """

    if i < 30:
        return {'action': 'hold'}

    # Market filter (BULL만 거래)
    if config['scalping_settings']['only_trade_in_bull'] and market_state != 'BULL':
        if position_info is not None:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'MARKET_NOT_BULL'}
        return {'action': 'hold'}

    row = df.iloc[i]
    close = row['close']

    # ====================
    # 모멘텀 계산 (최근 N개 캔들의 가격 변화)
    # ====================
    lookback = 5  # 최근 5개 캔들 (25분)
    prices = [df.iloc[i - j]['close'] for j in range(lookback) if i - j >= 0]

    if len(prices) < lookback:
        return {'action': 'hold'}

    # 모멘텀: 현재가 vs N캔들 전
    momentum_pct = (prices[0] / prices[-1] - 1) * 100  # 최근 25분 변화율

    # 단기 변동성
    price_range = (max(prices) - min(prices)) / min(prices) * 100

    # 거래량
    volume_ratio = row.get('volume_ratio', 1.0)

    # ====================
    # ENTRY: 상승 모멘텀 시작 감지
    # ====================
    if position_info is None:
        # 조건:
        # 1. 최근 25분간 상승 (+0.5% 이상)
        # 2. 거래량 증가 (1.2배 이상)
        # 3. 변동성 충분 (0.5% 이상)

        momentum_up = momentum_pct >= 0.5
        volume_surge = volume_ratio >= 1.2
        sufficient_volatility = price_range >= 0.5

        if momentum_up and volume_surge and sufficient_volatility:
            return {
                'action': 'buy',
                'fraction': 0.5,  # 50% 포지션
                'reason': f'MOMENTUM_UP: {momentum_pct:.2f}%, Vol={volume_ratio:.2f}x'
            }

    # ====================
    # EXIT: 모멘텀 끝 또는 반전
    # ====================
    else:
        entry_price = position_info['entry_price']
        profit_pct = (close / entry_price - 1) * 100
        hold_candles = position_info.get('hold_candles', 0)

        # Exit 1: 모멘텀 반전 (최근 25분간 -0.3% 이상 하락)
        if momentum_pct <= -0.3:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'MOMENTUM_REVERSE: {momentum_pct:.2f}% (profit: {profit_pct:.2f}%)'
            }

        # Exit 2: 빠른 익절 (+1.5%)
        if profit_pct >= 1.5:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'QUICK_PROFIT: {profit_pct:.2f}%'
            }

        # Exit 3: 빠른 손절 (-0.8%)
        if profit_pct <= -0.8:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'QUICK_STOP: {profit_pct:.2f}%'
            }

        # Exit 4: 타임아웃 (30캔들 = 150분)
        if hold_candles >= 30:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TIMEOUT: {hold_candles} candles (profit: {profit_pct:.2f}%)'
            }

    return {'action': 'hold'}
