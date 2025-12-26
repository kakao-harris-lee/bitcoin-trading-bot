# Dashboard Restructure Design

**Date:** 2025-12-27
**Version:** v0.0.3
**Status:** Approved

## Overview

Restructure the web dashboard after directory reorganization. Add detailed strategy signal logging with separate Upbit/Binance views.

## Data Model

### Signal History Structure

```python
_signal_history = {
    "upbit": [],    # Last 100 signals
    "binance": []   # Last 100 signals
}

# Each signal record:
{
    "timestamp": "2025-12-27T00:14:54",
    "strategy": "v35",
    "action": "hold",
    "reason": "V35_NO_SIGNAL",
    "regime": "BULL",
    "market_state": "BULL_MODERATE",
    "indicators": {
        "rsi": 52.3,
        "mfi": 48.7,
        "adx": 22.1,
        "price": 127639000
    }
}
```

## API Endpoints

### Modified: GET /api/status

Adds `last_signal` to each exchange.

### New: GET /api/signals/<exchange>

Returns last 50 signals with full indicator data.

```json
{
    "exchange": "upbit",
    "signals": [...]
}
```

## UI Layout

Two-column layout with separate sections per exchange:

- Market regime header
- Exchange cards (strategy, position, cash, return)
- Signal history (last 10, expandable)
- Trade history (separate per exchange)

## Path Fixes

| Old Path | New Path |
|----------|----------|
| `analysis/KILL_SWITCH` | `data/KILL_SWITCH` |
| Project root check: `analysis/` | Project root check: `trading/` |

## Files to Modify

1. `trading/engine.py` - Signal logging
2. `web/app.py` - API endpoints, path fixes
3. `web/templates/dashboard.html` - New layout
4. `web/static/js/dashboard.js` - Signal rendering
5. `web/static/css/style.css` - Styling

## Implementation Order

1. Engine signal logging
2. API fixes and new endpoint
3. HTML template
4. JavaScript
5. CSS
6. Deploy and test
