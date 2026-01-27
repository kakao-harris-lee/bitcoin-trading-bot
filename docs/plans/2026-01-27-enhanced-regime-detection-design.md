# Enhanced Regime Detection v2 Design

## Overview

Improve regime transition accuracy by adding noise filters to the existing MFI/ADX-based classification system. The goal is to reduce whipsaw losses caused by frequent regime changes.

## Problem Statement

Current regime detection using MFI and ADX experiences:
- Frequent regime transitions causing whipsaw trades
- False signals in sideways/low-volatility markets
- No confirmation from higher timeframes

## Goals

- Reduce regime transition frequency by 50%+
- Decrease whipsaw-related losing trades
- Maintain existing 7-level regime classification
- Enable A/B testing between v1 and v2 systems

## Design

### Filter Stack

Three filters applied sequentially when a regime change is detected:

```
1. Base regime calculation (MFI/ADX) → candidate_regime
2. Multi-timeframe confirmation (4h) → block if direction conflict
3. Bollinger Band Width filter → block in low volatility
4. Volume confirmation filter → block if volume insufficient
5. Final regime decision
```

### Filter 1: Bollinger Band Width (BBW)

Narrow bands indicate consolidation where regime signals are likely noise.

**Calculation:**
```python
BBW = (bb_upper - bb_lower) / bb_middle * 100
BBW_percentile = percentile_rank(BBW, window=100)
```

**Rules:**
| BBW Percentile | Action |
|----------------|--------|
| < 25 | Block transition (keep previous regime) |
| 25-50 | Allow with 2-candle confirmation |
| > 50 | Allow immediate transition |

### Filter 2: Multi-Timeframe (MTF) Confirmation

Use 4-hour timeframe to confirm direction alignment.

**Data Source:** Aggregate 4 consecutive minute60 candles (no additional API calls).

**Direction Groups:**
- BULL: BULL_STRONG, BULL_MODERATE, SIDEWAYS_UP
- BEAR: BEAR_STRONG, BEAR_MODERATE, SIDEWAYS_DOWN
- NEUTRAL: SIDEWAYS_FLAT

**Rules:**
```python
if minute60_direction == minute240_direction:
    allow_transition()
elif minute240_regime in NEUTRAL:
    allow_transition()  # Upper frame neutral, follow lower
else:
    block_transition()  # Direction conflict
```

### Filter 3: Volume Confirmation

Price movement without volume is "unconvinced movement."

**Calculation:**
```python
volume_ratio = current_volume / SMA(volume, 20)
```

**Rules:**
| Volume Ratio | Action |
|--------------|--------|
| < 0.8 | Block transition |
| 0.8-1.2 | AND with BBW filter |
| > 1.2 | Relax BBW threshold |

**Exceptions:**
- BEAR transitions: Relaxed volume requirement (panic sells can be low volume)
- SIDEWAYS transitions: Volume check disabled (low volume is normal)

### Combined Logic

```python
def get_filtered_regime(market_data, prev_regime, regime_4h):
    candidate = _classify_regime(mfi, adx)

    # No change, no filtering needed
    if candidate == prev_regime:
        return candidate

    # 1. MTF direction check
    if not is_direction_aligned(candidate, regime_4h):
        return prev_regime

    # 2. BBW check
    if bbw_percentile < bbw_block_threshold:
        return prev_regime

    # 3. Volume check (with exceptions)
    if candidate not in BEAR_REGIMES + SIDEWAYS_REGIMES:
        if volume_ratio < volume_block_ratio:
            return prev_regime

    return candidate
```

### Configuration Parameters

```json
{
  "regime_v2": {
    "enabled": true,
    "bbw_block_threshold": 25,
    "bbw_confirm_threshold": 50,
    "volume_block_ratio": 0.8,
    "volume_boost_ratio": 1.2,
    "mtf_enabled": true,
    "mtf_timeframe": 240
  }
}
```

## A/B Test Structure

Run v1 (current) and v2 (enhanced) in parallel to compare performance.

```
                    ┌─────────────────────┐
  market_data ──────►  RegimeRouter (v1)  │──► regime_v1 ──► v35_long
                    └─────────────────────┘

                    ┌─────────────────────┐
  market_data ──────►  EnhancedRegime (v2)│──► regime_v2 ──► v35_long_v2
                    └─────────────────────┘
```

**Metrics to Compare:**
- Regime transition count
- Whipsaw trade count
- Total PnL
- Sharpe ratio

**Test Duration:**
- Backtest: 6+ months historical data
- Paper trading: 2 weeks parallel operation

## Implementation Plan

### Phase 1: Analysis Tools
- Extract regime transition logs from backtests
- Build analysis script for transition frequency and whipsaw patterns
- Establish baseline metrics for v1

### Phase 2: Core Filter Implementation

New file: `trading/strategies/components/regime_filter.py`

```python
class BBWFilter:
    """Bollinger Band Width filter."""

class MTFFilter:
    """Multi-timeframe direction filter."""

class VolumeFilter:
    """Volume confirmation filter."""

class EnhancedRegimeRouter:
    """Combines all filters for regime decision."""
```

### Phase 3: Integration
- Add `regime_version` parameter to `CompositeStrategyTask`
- Update `allocation.json` schema for v2 configuration
- Enable parallel operation of v1 and v2 strategies

### Phase 4: Validation
- Backtest comparison: v1 vs v2 on 6 months data
- Paper trading: 2 weeks parallel operation
- Dashboard metrics for comparison charts

## File Changes

| File | Change |
|------|--------|
| `trading/strategies/components/regime_filter.py` | New file |
| `trading/strategies/components/models.py` | Add MTF aggregation functions |
| `trading/strategies/components/composite_task.py` | Add regime_version branching |
| `config/strategies/allocation.json` | Add v2 strategy configuration |

## Risks and Mitigations

| Risk | Mitigation |
|------|------------|
| Filters too conservative, missing good entries | Parameter tuning via backtest |
| 4h aggregation lag vs real 4h candles | Acceptable trade-off for simplicity |
| Increased complexity | Modular filter design, easy to disable individual filters |

## Success Criteria

1. Regime transitions reduced by 50%+ compared to v1
2. Whipsaw trades reduced by 40%+
3. Overall PnL improvement or at least neutral
4. No increase in missed profitable entries
