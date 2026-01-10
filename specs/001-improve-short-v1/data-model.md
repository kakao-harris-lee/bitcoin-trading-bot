# Data Model: Improve Short V1 Strategy

**Feature**: 001-improve-short-v1
**Date**: 2026-01-09

## Entities

### 1. PositionState (Enhanced)

Current position status with two-tier exit tracking.

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `in_position` | bool | Whether position is open | - |
| `entry_price` | float | Short entry price | > 0 when in_position |
| `entry_time` | datetime | When position was opened | - |
| `entry_reason` | str | Entry signal reasoning | - |
| `position_tier` | enum | FULL, HALF, CLOSED | Default: CLOSED |
| `initial_quantity` | float | Full position size at entry | > 0 |
| `remaining_quantity` | float | Current position size | 0 to initial_quantity |
| `stop_loss_price` | float | Current stop loss level | > entry_price (for short) |
| `take_profit_1r` | float | First tier TP (1R target) | < entry_price |
| `take_profit_2r` | float | Second tier TP (2R target) | < take_profit_1r |
| `first_tp_hit` | bool | Whether 1R target reached | - |
| `trailing_stop_active` | bool | Whether trailing stop is on | Only after first_tp_hit |
| `trailing_stop_price` | float | Current trailing stop | Tightens only, never widens |
| `lowest_since_1r` | float | Lowest price since 1R hit | Used for trailing calculation |

**State Transitions**:
```
CLOSED --[entry_signal]--> FULL
FULL --[1R_target_hit]--> HALF (exit 50%, activate trailing)
HALF --[trailing_stop_hit]--> CLOSED (exit remaining)
HALF --[2R_target_hit]--> CLOSED (exit remaining)
FULL/HALF --[stop_loss_hit]--> CLOSED (exit all)
FULL/HALF --[golden_cross]--> CLOSED (exit all)
```

### 2. TradeSignal (Enhanced)

Entry/exit signal with confidence and metadata.

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `action` | enum | open_short, close_short, partial_close | - |
| `fraction` | float | Position fraction to trade | 0.0 to 1.0 |
| `confidence` | float | Signal confidence score | 0.0 to 1.0, >= 0.7 for entry |
| `reason` | str | Signal reasoning | Concatenated conditions |
| `leverage` | int | Position leverage | Max 2 |
| `stop_loss` | float | Stop loss price | - |
| `stop_loss_pct` | float | Stop loss percentage | Max 5% |
| `take_profit` | float | Primary take profit price | - |
| `take_profit_pct` | float | Take profit percentage | Min 1.4% |
| `exit_type` | enum | STOP_LOSS, TAKE_PROFIT_1R, TAKE_PROFIT_2R, TRAILING_STOP, GOLDEN_CROSS, GAP_EXIT | For close signals |
| `metadata` | dict | Additional indicator values | - |

### 3. MarketIndicators (Enhanced)

Calculated technical indicators for signal generation.

| Field | Type | Description | Constraints |
|-------|------|-------------|-------------|
| `ema_fast` | float | Fast EMA (e.g., 50 or 68) | - |
| `ema_slow` | float | Slow EMA (e.g., 200 or 128) | - |
| `adx` | float | ADX value | 0-100 |
| `adx_prev` | float | ADX value N bars ago | For slope detection |
| `adx_declining` | bool | ADX < ADX_prev | Entry filter |
| `plus_di` | float | +DI value | 0-100 |
| `minus_di` | float | -DI value | 0-100 |
| `di_bearish` | bool | minus_di > plus_di | Entry requirement |
| `atr` | float | Average True Range | - |
| `swing_high` | float | Recent swing high | 10-bar rolling max |
| `swing_low` | float | Recent swing low | 10-bar rolling min |
| `death_cross` | bool | EMA fast crossed below slow | Entry trigger |
| `golden_cross` | bool | EMA fast crossed above slow | Exit trigger |
| `trend` | enum | BULL, BEAR, NEUTRAL | EMA relationship |
| `daily_volatility` | float | Daily range as percentage | For extreme vol check |
| `extreme_volatility` | bool | daily_volatility > 10% | Halt entries |

### 4. StrategyConfig (Enhanced)

Configuration parameters from JSON.

| Section | Field | Type | Default | Description |
|---------|-------|------|---------|-------------|
| indicators | ema_fast | int | 68 | Fast EMA period |
| indicators | ema_slow | int | 128 | Slow EMA period |
| indicators | adx_period | int | 14 | ADX calculation period |
| indicators | atr_period | int | 14 | ATR calculation period |
| entry | adx_min | int | 25 | Minimum ADX for entry |
| entry | adx_slope_bars | int | 3 | Bars for ADX slope check |
| entry | require_adx_not_declining | bool | true | FR-011 filter |
| entry | require_death_cross | bool | true | Death cross requirement |
| entry | di_negative_dominant | bool | true | -DI > +DI requirement |
| exit | two_tier_enabled | bool | true | Enable two-tier exits |
| exit | first_tier_pct | float | 0.5 | Exit 50% at 1R |
| exit | first_tier_r_multiple | float | 1.0 | 1R target |
| exit | second_tier_r_multiple | float | 2.0 | 2R target |
| exit | trailing_stop_atr_multiplier | float | 1.5 | Trail distance |
| exit | exit_on_golden_cross | bool | true | Exit on reversal |
| stop_loss | atr_buffer_multiplier | float | 1.5 | ATR buffer for SL |
| stop_loss | max_stop_loss_pct | float | 5.0 | Constitution limit |
| risk_management | max_leverage | int | 2 | Constitution limit |
| risk_management | extreme_volatility_threshold | float | 0.10 | 10% daily range |
| risk_management | halt_entries_on_extreme_vol | bool | true | FR-013 |

## Relationships

```
StrategyConfig 1--* PositionState (config drives position management)
PositionState 1--* TradeSignal (position generates signals)
MarketIndicators 1--1 TradeSignal (indicators inform signal)
```

## Validation Rules

### Entry Validation
1. `adx >= adx_min` (FR-002)
2. `di_bearish == true` (FR-003)
3. `adx_declining == false` (FR-011)
4. `extreme_volatility == false` (FR-013)
5. `death_cross == true OR trend == BEAR` (current behavior)

### Stop Loss Validation
1. `stop_loss_pct <= max_stop_loss_pct` (FR-005)
2. `stop_loss > entry_price` (short position)
3. `stop_loss = min(swing_high + atr_buffer, entry_price * 1.05)`

### Take Profit Validation
1. `take_profit_pct >= 1.4%` (FR-010, constitution)
2. `take_profit_1r = entry_price * (1 - risk_pct * 1.0)`
3. `take_profit_2r = entry_price * (1 - risk_pct * 2.0)`

### Exit Validation
1. First tier: exit exactly 50% of position
2. Trailing stop: only tighten, never widen
3. Gap handling: immediate market exit (FR-012)
