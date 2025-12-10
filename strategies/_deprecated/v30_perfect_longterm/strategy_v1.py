#!/usr/bin/env python3
"""
v30: Perfect Long-term Strategy
Based on raw data analysis - MFI + MACD + ADX on day timeframe

Target: 150-200% in 2024
Key insight: MFI is the most predictive indicator (1.33% Q4-Q1 spread)
"""

def v30_strategy(df, i, config, position_info=None):
    """
    Entry: MFI > 50, MACD golden cross, ADX > 25, Volume ratio > 1.5
    Exit: MACD dead cross OR trailing stop -15% OR take profit +50%
    """

    if i < 30:  # Need sufficient history
        return {'action': 'hold'}

    row = df.iloc[i]
    prev_row = df.iloc[i-1]

    # Current indicators
    mfi = row.get('mfi', 50)
    macd = row.get('macd', 0)
    macd_signal = row.get('macd_signal', 0)
    adx = row.get('adx', 0)
    volume_ratio = row.get('volume_ratio', 1.0)
    rsi = row.get('rsi_14', 50)
    bb_position = row.get('bb_position', 0.5)

    # Previous indicators
    prev_macd = prev_row.get('macd', 0)
    prev_macd_signal = prev_row.get('macd_signal', 0)

    # ====================
    # ENTRY LOGIC
    # ====================

    if position_info is None:  # No position
        # Golden cross detection
        golden_cross = (prev_macd <= prev_macd_signal) and (macd > macd_signal)

        # Entry conditions (from raw analysis)
        entry_signal = (
            mfi >= config['entry_conditions']['mfi_min'] and
            golden_cross and
            adx >= config['entry_conditions']['adx_min'] and
            volume_ratio >= config['entry_conditions']['volume_ratio_min']
        )

        # Additional filters (avoid overbought)
        additional_filters = (
            rsi <= config['entry_conditions']['additional_filters']['rsi_max'] and
            bb_position <= config['entry_conditions']['additional_filters']['bb_position_max']
        )

        if entry_signal and additional_filters:
            return {
                'action': 'buy',
                'fraction': config['position_sizing']['initial_fraction'],
                'reason': f'ENTRY: MFI={mfi:.1f}, MACD_GC, ADX={adx:.1f}, Vol={volume_ratio:.2f}x'
            }

    # ====================
    # EXIT LOGIC
    # ====================

    else:  # Has position
        entry_price = position_info['entry_price']
        current_price = row['close']
        profit_pct = (current_price / entry_price - 1)
        hold_days = position_info.get('hold_days', 0)

        # Dead cross detection
        dead_cross = (prev_macd >= prev_macd_signal) and (macd < macd_signal)

        # Exit condition 1: MACD dead cross
        if config['exit_conditions']['macd_dead_cross'] and dead_cross:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'EXIT_MACD_DEAD_CROSS (profit: {profit_pct*100:.2f}%)'
            }

        # Exit condition 2: Trailing stop
        if profit_pct <= -config['exit_conditions']['trailing_stop_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'EXIT_TRAILING_STOP: {profit_pct*100:.2f}%'
            }

        # Exit condition 3: Take profit
        if profit_pct >= config['exit_conditions']['take_profit_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'EXIT_TAKE_PROFIT: {profit_pct*100:.2f}%'
            }

        # Exit condition 4: Max hold period
        if hold_days >= config['exit_conditions']['max_hold_days']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'EXIT_MAX_HOLD: {hold_days} days (profit: {profit_pct*100:.2f}%)'
            }

        # Exit condition 5: Stop loss
        if profit_pct <= -config['risk_management']['stop_loss_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'EXIT_STOP_LOSS: {profit_pct*100:.2f}%'
            }

    return {'action': 'hold'}
