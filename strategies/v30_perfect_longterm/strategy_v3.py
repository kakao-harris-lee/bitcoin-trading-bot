#!/usr/bin/env python3
"""
v30 Strategy V3: HOLD THROUGH BULL MARKETS
Key insight: Don't exit on every MACD dead cross - only exit on BEAR CONFIRMATION

Entry: MFI > 50 + MACD > Signal
Exit: MFI < 40 AND MACD < Signal (both bearish, not just one)
"""

def v30_strategy(df, i, config, position_info=None):
    """
    Bull market strategy: Enter easily, exit only on confirmed bear
    """

    if i < 30:
        return {'action': 'hold'}

    row = df.iloc[i]
    prev_row = df.iloc[i-1]

    mfi = row.get('mfi', 50)
    macd = row.get('macd', 0)
    macd_signal = row.get('macd_signal', 0)
    rsi = row.get('rsi_14', 50)

    prev_mfi = prev_row.get('mfi', 50)

    # ====================
    # ENTRY
    # ====================
    if position_info is None:
        # MFI cross above 50
        mfi_cross_up = (prev_mfi <= 50) and (mfi > 50)

        # MACD bullish
        macd_bullish = macd > macd_signal

        if mfi_cross_up and macd_bullish:
            return {
                'action': 'buy',
                'fraction': 0.95,
                'reason': f'BULL_ENTRY: MFI={mfi:.1f}, MACD_BULL'
            }

    # ====================
    # EXIT (Conservative - hold through bull)
    # ====================
    else:
        entry_price = position_info['entry_price']
        current_price = row['close']
        profit_pct = (current_price / entry_price - 1)

        # *** CONFIRMED BEAR: Both MFI and MACD bearish ***
        mfi_bearish = mfi < 40
        macd_bearish = macd < macd_signal
        confirmed_bear = mfi_bearish and macd_bearish

        # Stop-loss (safety)
        stop_loss = profit_pct <= -0.15

        # Take profit at extreme (safety)
        extreme_profit = profit_pct >= 1.00  # 100%+

        if confirmed_bear:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'CONFIRMED_BEAR: MFI={mfi:.1f}, MACD_BEAR (profit: {profit_pct*100:.2f}%)'}

        if stop_loss:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'STOP_LOSS: {profit_pct*100:.2f}%'}

        if extreme_profit:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'EXTREME_PROFIT: {profit_pct*100:.2f}%'}

    return {'action': 'hold'}
