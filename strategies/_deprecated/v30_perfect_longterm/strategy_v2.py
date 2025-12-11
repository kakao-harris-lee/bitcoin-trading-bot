#!/usr/bin/env python3
"""
v30 Strategy V2: Simplified MFI-based trend following
Keep it simple: Enter when MFI > 50 + MACD bullish, exit on reversal
"""

def v30_strategy(df, i, config, position_info=None):
    """
    Ultra-simple: Enter when MFI > 50 and MACD > Signal
    Exit when MFI < 45 or MACD dead cross or stop-loss
    """

    if i < 30:
        return {'action': 'hold'}

    row = df.iloc[i]
    prev_row = df.iloc[i-1]

    mfi = row.get('mfi', 50)
    macd = row.get('macd', 0)
    macd_signal = row.get('macd_signal', 0)

    prev_mfi = prev_row.get('mfi', 50)
    prev_macd = prev_row.get('macd', 0)
    prev_macd_signal = prev_row.get('macd_signal', 0)

    # ====================
    # ENTRY
    # ====================
    if position_info is None:
        # MFI crossover above 50
        mfi_cross_up = (prev_mfi <= 50) and (mfi > 50)

        # MACD bullish
        macd_bullish = macd > macd_signal

        if mfi_cross_up and macd_bullish:
            return {
                'action': 'buy',
                'fraction': 0.95,
                'reason': f'MFI_CROSS_UP={mfi:.1f}, MACD_BULL'
            }

    # ====================
    # EXIT
    # ====================
    else:
        entry_price = position_info['entry_price']
        current_price = row['close']
        profit_pct = (current_price / entry_price - 1)

        # MFI crossdown below 45
        mfi_cross_down = (prev_mfi >= 45) and (mfi < 45)

        # MACD dead cross
        dead_cross = (prev_macd >= prev_macd_signal) and (macd < macd_signal)

        # Stop-loss
        stop_loss = profit_pct <= -0.10

        # Take profit (optional)
        take_profit = profit_pct >= 0.50

        if mfi_cross_down:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'MFI_CROSS_DOWN={mfi:.1f} (profit: {profit_pct*100:.2f}%)'}

        if dead_cross:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'MACD_DEAD_CROSS (profit: {profit_pct*100:.2f}%)'}

        if stop_loss:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'STOP_LOSS: {profit_pct*100:.2f}%'}

        if take_profit:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'TAKE_PROFIT: {profit_pct*100:.2f}%'}

    return {'action': 'hold'}
