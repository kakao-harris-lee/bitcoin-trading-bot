#!/usr/bin/env python3
"""
v31 Scalping Strategy with Market Classifier
High-frequency minute5 trading, enabled only during BULL market (day-level)

Entry: Oversold (BB < 0.3, Volume > 1.5x, RSI < 35) during BULL
Exit: +2.5% take profit or -1% stop loss
"""

def v31_strategy(df, i, config, position_info=None, market_state='SIDEWAYS'):
    """
    Scalping strategy with market classifier filter

    Args:
        df: minute5 DataFrame with indicators
        i: Current index
        config: Strategy configuration
        position_info: Current position (if any)
        market_state: Current market state from day classifier ('BULL', 'BEAR', 'SIDEWAYS')
    """

    if i < 30:
        return {'action': 'hold'}

    # ====================
    # Market Filter
    # ====================
    only_trade_in_bull = config['scalping_settings']['only_trade_in_bull']

    if only_trade_in_bull and market_state != 'BULL':
        # Exit existing position if market turns bearish
        if position_info is not None and market_state == 'BEAR':
            return {'action': 'sell', 'fraction': 1.0, 'reason': f'MARKET_BEAR_EXIT'}
        return {'action': 'hold', 'reason': f'MARKET_NOT_BULL: {market_state}'}

    row = df.iloc[i]

    # Current indicators
    bb_position = row.get('bb_position', 0.5)
    volume_ratio = row.get('volume_ratio', 1.0)
    rsi = row.get('rsi_14', 50)
    close = row['close']

    # ====================
    # ENTRY LOGIC
    # ====================
    if position_info is None:
        entry_cfg = config['scalping_settings']['entry_conditions']

        # Core entry: Oversold during bull market
        oversold_bb = bb_position <= entry_cfg['bb_position_max']
        high_volume = volume_ratio >= entry_cfg['volume_ratio_min']
        oversold_rsi = rsi <= entry_cfg['rsi_oversold']

        # Additional filter: Recent red candles (price declined)
        recent_red = 0
        for lookback in range(1, entry_cfg['additional_filters']['recent_candles_red'] + 1):
            if i - lookback >= 0:
                prev_row = df.iloc[i - lookback]
                if prev_row['close'] < prev_row['open']:
                    recent_red += 1

        enough_red_candles = recent_red >= entry_cfg['additional_filters']['recent_candles_red']

        # Entry signal
        entry_signal = oversold_bb and high_volume and oversold_rsi and enough_red_candles

        if entry_signal:
            # Position sizing (simple version - 30% of capital)
            position_pct = config['scalping_settings']['position_sizing']['max_position_pct']

            return {
                'action': 'buy',
                'fraction': position_pct,
                'reason': f'SCALP_ENTRY: BB={bb_position:.2f}, Vol={volume_ratio:.2f}x, RSI={rsi:.1f}, Market={market_state}'
            }

    # ====================
    # EXIT LOGIC
    # ====================
    else:
        entry_price = position_info['entry_price']
        profit_pct = (close / entry_price - 1)
        hold_candles = position_info.get('hold_candles', 0)

        exit_cfg = config['scalping_settings']['exit_conditions']

        # Take profit
        if profit_pct >= exit_cfg['take_profit_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'TAKE_PROFIT: {profit_pct*100:.2f}%'
            }

        # Stop loss
        if profit_pct <= -exit_cfg['stop_loss_pct']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'STOP_LOSS: {profit_pct*100:.2f}%'
            }

        # Trailing stop (if profit > 1.5%)
        if profit_pct >= exit_cfg['trail_profit_after']:
            # Trail at -0.5% from peak
            if profit_pct <= (exit_cfg['trail_profit_after'] - exit_cfg['trail_stop_pct']):
                return {
                    'action': 'sell',
                    'fraction': 1.0,
                    'reason': f'TRAILING_STOP: {profit_pct*100:.2f}%'
                }

        # Max hold time
        if hold_candles >= exit_cfg['max_hold_candles']:
            return {
                'action': 'sell',
                'fraction': 1.0,
                'reason': f'MAX_HOLD: {hold_candles} candles (profit: {profit_pct*100:.2f}%)'
            }

    return {'action': 'hold'}
