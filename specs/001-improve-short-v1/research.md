# Research: Improve Short V1 Strategy

**Feature**: 001-improve-short-v1
**Date**: 2026-01-09

## Research Topics

### 1. ATR-Based Stop Loss Calculation

**Decision**: Use ATR multiplier (1.5-2.0x) added to swing high for stop loss buffer.

**Rationale**:
- ATR measures average price movement over period, reflecting current volatility
- Adding ATR buffer to swing high prevents stop-outs during normal volatility
- 1.5x ATR is conservative, 2.0x gives more room but wider stops
- Must still respect max 5% stop loss limit per constitution

**Implementation**:
```python
# Pseudocode
atr_value = ta.atr(high, low, close, period=14)
swing_high = df['high'].rolling(window=10).max()
volatility_buffer = atr_value * atr_multiplier  # 1.5-2.0
stop_loss = swing_high + volatility_buffer
stop_loss = min(stop_loss, entry_price * 1.05)  # Cap at 5%
```

**Alternatives Considered**:
- Fixed percentage stop (current): Too rigid, doesn't adapt to volatility
- Bollinger Band-based: Adds complexity (4th indicator), rejected
- Parabolic SAR: Better for trailing, not initial placement

### 2. Two-Tier Exit Implementation

**Decision**: Track position quantity in halves, manage each tier independently.

**Rationale**:
- First tier (50% at 1R) locks in profit, reduces risk exposure
- Second tier uses trailing stop to capture extended moves
- Trailing stop activates only after 1R is reached (per clarification)
- Position state needs to track: full_position, half_position, trailing_active

**Implementation**:
```python
# Position state additions
self.position_tier = 'FULL'  # FULL, HALF, CLOSED
self.first_tp_hit = False
self.trailing_stop_price = None
self.trailing_stop_active = False

# Exit logic
if at_1R_target and position_tier == 'FULL':
    exit_50_percent()
    position_tier = 'HALF'
    activate_trailing_stop()

if trailing_stop_active and price >= trailing_stop_price:
    exit_remaining()
    position_tier = 'CLOSED'
```

**Alternatives Considered**:
- Three-tier (33/33/34): More complex, diminishing returns
- Single exit with adaptive target: Simpler but less profit capture
- Time-based exits: Not momentum-following, rejected

### 3. ADX Trend Direction Detection

**Decision**: Compare current ADX to previous value (ADX slope) to detect declining trends.

**Rationale**:
- ADX declining = trend weakening, even if absolute value still high
- ADX slope over 3-5 bars provides smooth direction signal
- Avoids single-bar noise in ADX values

**Implementation**:
```python
# ADX slope calculation
adx_current = df['adx'].iloc[-1]
adx_prev = df['adx'].iloc[-3]  # 3 bars ago
adx_declining = adx_current < adx_prev

# Entry filter
if death_cross and not adx_declining:
    enter_short()
elif death_cross and adx_declining:
    skip_entry()  # FR-011
```

**Alternatives Considered**:
- ADX momentum (rate of change): More complex, similar result
- ADX threshold only: Current approach, misses weakening trends
- ADXR (ADX rating): Adds lag, not recommended

### 4. Trailing Stop Mechanics

**Decision**: Use ATR-based trailing stop, updated on each new low.

**Rationale**:
- Trail stop at entry_price after 1R hit (break-even)
- Then trail at distance = 1.5x ATR above lowest low since 1R
- Updates only when price makes new low (favorable direction for short)
- Never widens, only tightens

**Implementation**:
```python
# Trailing stop logic (for remaining 50%)
if first_tp_hit and not trailing_stop_active:
    trailing_stop_price = entry_price  # Break-even initially
    trailing_stop_active = True
    lowest_since_1r = current_price

if trailing_stop_active:
    if current_low < lowest_since_1r:
        lowest_since_1r = current_low
        new_trail = lowest_since_1r + (atr_value * 1.5)
        if new_trail < trailing_stop_price:
            trailing_stop_price = new_trail  # Tighten only
```

**Alternatives Considered**:
- Fixed percentage trail: Doesn't adapt to volatility
- Parabolic SAR: More complex, acceleration factor tuning needed
- Chandelier Exit: Essentially ATR-based, similar to chosen approach

### 5. Extreme Volatility Detection

**Decision**: Check daily price range against 10% threshold.

**Rationale**:
- Extreme volatility = (high - low) / open > 0.10 (10%)
- Calculate on daily timeframe even though strategy uses 4H
- Halt new entries but manage existing positions normally
- Simple check, no additional indicators needed

**Implementation**:
```python
# Daily volatility check (before entry)
daily_range = (daily_high - daily_low) / daily_open
if daily_range > 0.10:
    self.extreme_volatility = True
    return None  # No new entries

# Existing positions: normal stop/TP rules apply
```

**Alternatives Considered**:
- ATR percentile: More nuanced but complex
- VIX-equivalent: Not available for crypto
- Bollinger width: Adds indicator, rejected for simplicity

### 6. Gap Opening Handling

**Decision**: Market order exit on next candle open if gap past stop loss.

**Rationale**:
- In 4H timeframe, gaps are rare but can occur (exchange downtime, flash crashes)
- If open price > stop_loss for short, loss already realized
- Market order accepts slippage to exit immediately
- Better than hoping for recovery (discipline over hope)

**Implementation**:
```python
# Gap check at candle open
if in_position and candle_open > stop_loss_price:
    exit_at_market(reason='GAP_PAST_STOP')
    log_warning(f'Gap exit: open={candle_open}, stop={stop_loss_price}')
```

**Alternatives Considered**:
- Limit order at stop price: May not fill in fast market
- Hold position: Risk management violation
- Partial exit: Prolongs exposure to adverse move

## Configuration Parameters

New/modified parameters for `config/strategies/short_v1.json`:

```json
{
  "entry": {
    "adx_slope_bars": 3,
    "require_adx_not_declining": true
  },
  "exit": {
    "two_tier_enabled": true,
    "first_tier_pct": 0.5,
    "first_tier_r_multiple": 1.0,
    "trailing_stop_atr_multiplier": 1.5
  },
  "stop_loss": {
    "atr_buffer_multiplier": 1.5,
    "atr_period": 14
  },
  "risk_management": {
    "extreme_volatility_threshold": 0.10,
    "halt_entries_on_extreme_vol": true
  }
}
```

## Dependencies

| Dependency | Status | Notes |
|------------|--------|-------|
| `trading.indicators.technical.atr` | ✅ Exists | Line 94-101 in technical.py |
| `trading.indicators.technical.adx` | ✅ Exists | Line 61-72 in technical.py |
| `trading.indicators.technical.ema` | ✅ Exists | Line 89-91 in technical.py |
| `BaseStrategy.generate_signal` | ✅ Exists | Abstract method in base.py |
| `config/strategies/short_v1.json` | ✅ Exists | To be extended |

## Open Questions (Resolved)

All clarifications resolved in spec.md. No open questions remaining.
