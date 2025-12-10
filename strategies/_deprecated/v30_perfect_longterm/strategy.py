#!/usr/bin/env python3
"""
v30 Strategy V4: ULTIMATE HOLD STRATEGY
Buy early, hold through entire bull market, exit only on sustained bear

Entry: MFI crosses above 45 (early)
Exit: MFI below 35 for 3+ consecutive days (sustained bear)
"""

def v30_strategy(df, i, config, position_info=None):
    """
    Buy and hold strategy with early entry and late exit
    """

    if i < 30:
        return {'action': 'hold'}

    row = df.iloc[i]
    prev_row = df.iloc[i-1]

    mfi = row.get('mfi', 50)
    prev_mfi = prev_row.get('mfi', 50)

    # ====================
    # ENTRY - Early!
    # ====================
    if position_info is None:
        # MFI crosses above 45 (earlier than 50)
        mfi_cross_up = (prev_mfi <= 45) and (mfi > 45)

        if mfi_cross_up:
            return {
                'action': 'buy',
                'fraction': 0.95,
                'reason': f'EARLY_ENTRY: MFI={mfi:.1f}'
            }

    # ====================
    # EXIT - Late! (Sustained bear only)
    # ====================
    else:
        entry_price = position_info['entry_price']
        current_price = row['close']
        profit_pct = (current_price / entry_price - 1)

        # Check if MFI has been below 35 for last 3 days
        mfi_sustained_bear = True
        for lookback in range(3):
            if i - lookback < 0:
                mfi_sustained_bear = False
                break
            past_mfi = df.iloc[i - lookback].get('mfi', 50)
            if past_mfi >= 35:
                mfi_sustained_bear = False
                break

        # Stop-loss (safety)
        stop_loss = profit_pct <= -0.20  # Wider stop

        if mfi_sustained_bear:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'SUSTAINED_BEAR: MFI<35 for 3d (profit: {profit_pct*100:.2f}%)'}

        if stop_loss:
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'STOP_LOSS: {profit_pct*100:.2f}%'}

    return {'action': 'hold'}
