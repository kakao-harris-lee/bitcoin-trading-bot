# Live Decision Feed Design

**Date**: 2026-01-18
**Status**: Implementing

## Problem

The Trading Signals panel only shows executed trades. Users cannot see:
- What data is coming into the system
- What decisions strategies are making between trades
- Current indicator values (MFI, ADX) and regime classification

## Solution

Record strategy decisions at every candle close (hourly) to a Redis stream, displaying them in the dashboard.

## Data Structure

```json
{
  "timestamp": "2026-01-18T19:00:00",
  "symbol": "BTC",
  "strategy": "v35_long",
  "market": "spot",
  "price": 90748.10,
  "indicators": {
    "mfi": 52.3,
    "adx": 24.1
  },
  "regime": "BULL_MODERATE",
  "decision": "HOLD",
  "reason": "Already in position, trailing stop active",
  "position": {
    "active": true,
    "entry_price": 89500.00,
    "quantity": 0.00195,
    "unrealized_pnl": 2.43,
    "unrealized_pnl_pct": 1.39
  }
}
```

**Decision values**: `BUY`, `SELL`, `HOLD`, `WAIT`

## Architecture

```
CompositeStrategyTask
    │
    ├── on each price tick: evaluate() → trade signal (existing)
    │
    └── on candle close: _record_decision() → Redis stream (NEW)
            │
            ▼
    strategy:decisions stream (trimmed to 48h)
            │
            ▼
    /api/metrics/decisions (enhanced)
            │
            ▼
    Dashboard "Trading Signals" panel
```

## Implementation

### 1. CompositeStrategyTask Changes
- Track `last_candle_hour` per symbol
- On hour boundary, call `_record_decision()`
- Write to `strategy:decisions` stream

### 2. MetricsService Changes
- Read from `strategy:decisions` stream
- Return formatted decision records

### 3. Dashboard Changes
- Update signals panel to show decision records
- Color-coded decisions and regimes
