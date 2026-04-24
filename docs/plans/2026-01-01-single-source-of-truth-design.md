# Single Source of Truth: Regime Classification Refactor

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


## Problem Statement

Current system has **double regime filtering**:

1. **RegimeRouter** (external): Classifies market and decides which strategy to run
2. **V35 Entry Strategy** (internal): Has its own MarketClassifier that gates entries

Result: Even when RegimeRouter allows V35 to run, V35's internal classifier may block trades.

Historical context: Original V35 without RegimeRouter had S-Tier win rates with more trades.

## Current Architecture

```
┌──────────────────┐
│  RegimeRouter    │  Classifies: BULL/SIDEWAYS/BEAR
│  (Daily MFI/ADX) │  Routes to: v35, sideways_v2, short_v1, or None
└────────┬─────────┘
         │
         ▼ (if regime=BULL → run v35)
┌──────────────────┐
│ V35 Entry        │  Internal MarketClassifier
│  (H1 MFI/ADX)    │  Re-classifies: 7 states
│                  │  BLOCKS entries in: SIDEWAYS_DOWN, BEAR_*
└──────────────────┘
```

**V35 internal gating (`trading/strategies/components/v35_entry.py`):**
- BULL_STRONG → momentum_entry
- BULL_MODERATE → momentum_entry
- SIDEWAYS_UP → breakout_entry
- SIDEWAYS_FLAT → range_entry
- SIDEWAYS_DOWN → None (blocked)
- BEAR_MODERATE → None (blocked)
- BEAR_STRONG → None (blocked)

## Proposed Solution

**Make V35 a pure signal generator** - it generates signals in ALL market states.
**RegimeRouter is the only gatekeeper** - decides whether V35 runs at all.

```
┌──────────────────┐
│  RegimeRouter    │  SINGLE classification authority
│  (Daily MFI/ADX) │  Decides: run v35? run sideways_v2? run short_v1?
└────────┬─────────┘
         │
         ▼ (if regime=BULL → run v35)
┌──────────────────┐
│ V35 Entry        │  Pure signal generator
│  (H1 indicators) │  Generates signals for ANY market state
│                  │  Uses state for: position sizing, exits
└──────────────────┘
```

## Changes Required

### 1. V35EntryStrategy (`trading/strategies/components/v35_entry.py`)

**Modify `_check_entry()` to generate signals in all states:**

```python
def check_entry(self, market_data, context) -> Optional[Dict]:
    row = market_data.df.iloc[market_data.index]

    # BULL states: aggressive momentum
    if market_state == 'BULL_STRONG':
        return self._momentum_entry(row, aggressive=True)
    elif market_state == 'BULL_MODERATE':
        return self._momentum_entry(row, aggressive=False)

    # SIDEWAYS states: breakout or range
    elif market_state == 'SIDEWAYS_UP':
        return self._breakout_entry(market_data)
    elif market_state in ['SIDEWAYS_FLAT', 'SIDEWAYS_DOWN']:
        return self._range_entry(market_data)  # Conservative entry

    # BEAR states: very conservative range entry
    elif market_state in ['BEAR_MODERATE', 'BEAR_STRONG']:
        return self._range_entry(market_data)  # Only if conditions met

    return None
```

**Keep existing features:**
- MarketClassifier: Still used for position sizing and exit TP levels
- BEAR_PROTECTION sell: Still exits positions when market turns BEAR (safety net)
- DynamicExitManager: Still uses market state for TP calculations

### 2. Position Sizing (already exists)

V35 already has market-state-aware position sizing in `_get_tp_levels()`:
- BULL_STRONG: wider take profits
- BULL_MODERATE: moderate take profits
- SIDEWAYS/*: tighter take profits

No changes needed - this stays.

### 3. RegimeRouter (no changes needed)

RegimeRouter already controls when V35 runs:
- BULL regime → v35
- SIDEWAYS regime → sideways_v2 (not v35)
- BEAR regime → None (no longs)

The router is already the gatekeeper.

## Implementation

### Phase 1: Modify V35 Entry Logic

1. Update `_check_entry()` to handle SIDEWAYS_DOWN and BEAR states
2. Add conservative entry conditions for BEAR states (tight RSI, support zones)
3. Optionally add position size reduction for BEAR entries

### Phase 2: Test

1. Run backtest with modified V35
2. Compare trade count: before vs after
3. Verify win rate maintained

## Risk Mitigation

1. **BEAR_PROTECTION stays**: V35 still exits positions when market turns BEAR
2. **Conservative BEAR entries**: Very strict conditions (RSI < 30, strong support)
3. **Reduced position sizes**: Could add smaller position sizes for BEAR entries

## Expected Outcome

- More trades generated (SIDEWAYS_DOWN and BEAR states now tradeable)
- Win rate should remain similar (same entry logic, just applied more broadly)
- RegimeRouter still prevents V35 from running in BEAR (so BEAR entries won't happen in practice)

## Alternative: Disable Internal Classification Entirely

More aggressive option - completely remove V35's internal MarketClassifier from entry logic:

```python
def _check_entry(self, df, i, market_state, prev_row) -> Optional[Dict]:
    # Use unified entry logic regardless of market state
    row = df.iloc[i]

    # Check all entry conditions
    momentum = self._momentum_entry(row, aggressive=False)
    if momentum:
        return momentum

    breakout = self._breakout_entry(df, i)
    if breakout:
        return breakout

    range_entry = self._range_entry(df, i)
    if range_entry:
        return range_entry

    return None
```

This would let V35 use ANY entry strategy in ANY market state. The RegimeRouter controls when V35 runs at all.

## Decision

**Proceed with Phase 1** - Enable SIDEWAYS_DOWN and BEAR state entries with conservative conditions. This is less disruptive and maintains the strategy's character while increasing trade opportunities.
