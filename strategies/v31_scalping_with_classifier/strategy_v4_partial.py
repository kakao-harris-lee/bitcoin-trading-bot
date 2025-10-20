#!/usr/bin/env python3
"""
v31 Strategy V4: 분할 매매 + 유연한 익절
많은 거래로 작은 수익 누적 전략

핵심:
- 분할 진입 (30% → 60% → 100%)
- 분할 청산 (익절 시 50% → 50% 나눠서)
- 손절은 엄격, 익절은 유연 (trailing)
- 거래 횟수 많아도 OK - 수익 누적이 목표
"""

def v31_strategy(df, i, config, position_info=None, market_state='SIDEWAYS'):
    """
    분할 매매 스캘핑: 작은 수익 누적
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

    # 단기 모멘텀 (최근 3캔들)
    if i >= 3:
        price_3ago = df.iloc[i - 3]['close']
        momentum_3 = (close / price_3ago - 1) * 100
    else:
        momentum_3 = 0

    # ====================
    # ENTRY: 적극적 진입 (조건 완화)
    # ====================
    if position_info is None:
        # 조건 완화 - 거래 기회 증가
        # 1. 최근 3캔들 +0.3% 이상 상승
        # 2. 거래량 1.0배 이상

        momentum_ok = momentum_3 >= 0.3
        volume_ok = volume_ratio >= 1.0

        if momentum_ok and volume_ok:
            # 분할 진입 1단계: 30%
            return {
                'action': 'buy',
                'fraction': 0.3,
                'reason': f'ENTRY_30%: momentum={momentum_3:.2f}%'
            }

    # ====================
    # EXIT: 유연한 익절, 엄격한 손절
    # ====================
    else:
        entry_price = position_info['entry_price']
        profit_pct = (close / entry_price - 1) * 100
        hold_candles = position_info.get('hold_candles', 0)

        # Trailing stop (최고 수익 추적)
        if not hasattr(position_info, 'peak_profit'):
            position_info['peak_profit'] = profit_pct
        else:
            if profit_pct > position_info['peak_profit']:
                position_info['peak_profit'] = profit_pct

        peak = position_info.get('peak_profit', 0)

        # Exit 1: 첫 익절 타겟 (+0.8% - 낮춤)
        if profit_pct >= 0.8 and hold_candles >= 3:  # 최소 3캔들 보유
            return {
                'action': 'sell',
                'fraction': 0.5,  # 50%만 청산
                'reason': f'PARTIAL_PROFIT: {profit_pct:.2f}% (50% 청산)'
            }

        # Exit 2: 큰 익절 (+1.5%)
        if profit_pct >= 1.5:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'FULL_PROFIT: {profit_pct:.2f}%'
            }

        # Exit 3: Trailing stop (최고점에서 -0.4% 하락)
        if peak >= 0.8 and profit_pct <= (peak - 0.4):
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TRAILING_STOP: peak={peak:.2f}%, now={profit_pct:.2f}%'
            }

        # Exit 4: 엄격한 손절 (-0.6%)
        if profit_pct <= -0.6:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS: {profit_pct:.2f}%'
            }

        # Exit 5: 타임아웃 (40캔들 = 200분)
        if hold_candles >= 40:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TIMEOUT: {hold_candles}캔들 (profit: {profit_pct:.2f}%)'
            }

    return {'action': 'hold'}
