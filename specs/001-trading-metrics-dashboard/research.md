# Research: Real-Time Trading Metrics Dashboard

> Current scope note (2026-04-24): apply this spec to the Binance spot-only runtime. Any remaining references to Upbit, futures, short_v1, or sideways_v2 are historical draft context, not current implementation guidance.


**Date**: 2026-01-09
**Feature**: 001-trading-metrics-dashboard

## Research Summary

All technical unknowns have been resolved through codebase analysis.

## Findings

### R1: Existing Data Structures

**Question**: What data is available in existing log files for the dashboard?

**Decision**: Use existing JSON log files that already contain all required data

**Analysis of `logs/v2_engine_upbit.json`**:
```json
{
  "exchange": "upbit",
  "mode": "paper",
  "initial_capital": 10000000.0,
  "current_cash": 7497951.30,
  "btc_balance": 0.0195,
  "total_value": 10012724.92,
  "strategy": "va02",
  "regime": "BEAR",
  "market_state": "BEAR_STRONG",
  "trades": [...],      // Historical trades with pnl
  "signals": [...]      // Recent signals with indicators
}
```

**Available Fields**:
| Spec Requirement | Source Field | Location |
|-----------------|--------------|----------|
| Strategy name | `strategy` | v2_engine_*.json |
| Mode (paper/live) | `mode` | v2_engine_*.json |
| Market regime | `regime`, `market_state` | v2_engine_*.json |
| Current price | signals[].indicators.close | v2_engine_*.json |
| Position info | `btc_balance`, trades[] | v2_engine_*.json |
| Unrealized P&L | Calculated from position + price | - |
| Decision history | `signals[]` array | v2_engine_*.json |
| Reasoning | signals[].reason | v2_engine_*.json |
| Indicators | signals[].indicators | v2_engine_*.json |

**Rationale**: Existing log files contain all data needed. No new logging required.

**Alternatives Considered**:
- Reading from SQLite `trading_results.db`: More complex queries, same data
- Adding new bot endpoints: Would require bot code changes

---

### R2: Existing API Patterns

**Question**: What patterns does the existing Flask app use for similar data?

**Decision**: Follow existing `/api/status` endpoint pattern

**Analysis of `web/app.py`**:
- Existing endpoints: `/api/status`, `/api/signals`, `/api/trades`, `/api/positions`
- Data loading: `metrics_service.get_dashboard_state()` reads the Redis-backed dashboard snapshot
- Response format: JSON with nested objects
- Error handling: Returns 404 with `{'error': 'message'}` when data unavailable
- TOTP protection: Some endpoints use `@requires_totp` decorator

**Pattern to Follow**:
```python
@app.route("/api/metrics/realtime")
def get_realtime_metrics():
    data = load_trading_log('upbit')  # Existing function
    if not data:
        return jsonify({'error': 'No data available'}), 404
    # Transform and return
    return jsonify(transformed_data)
```

**Rationale**: Consistency with existing codebase patterns reduces learning curve and maintenance burden.

---

### R3: Frontend Patterns

**Question**: What JavaScript/template patterns does the existing dashboard use?

**Decision**: Use vanilla JavaScript with `fetch()` and `setInterval()`

**Analysis of `web/templates/dashboard.html`**:
- Uses vanilla JavaScript (no React, Vue, etc.)
- Polling done via `setInterval` + `fetch`
- Updates DOM directly
- Uses Tailwind CSS classes for styling

**Pattern to Follow**:
```javascript
function updateMetrics() {
    fetch('/api/metrics/realtime')
        .then(r => r.json())
        .then(data => {
            document.getElementById('regime').textContent = data.regime;
            // ... more updates
        });
}
setInterval(updateMetrics, 4000);  // 4 second polling
```

**Rationale**: Match existing patterns for consistency.

---

### R4: Stale Data Detection

**Question**: How to detect and display stale data (>30 seconds old)?

**Decision**: Compare signal timestamp to current time in JavaScript

**Implementation**:
```javascript
const lastUpdate = new Date(data.signals[0].timestamp);
const now = new Date();
const ageSeconds = (now - lastUpdate) / 1000;

if (ageSeconds > 30) {
    document.getElementById('freshness').classList.add('stale');
    document.getElementById('freshness').textContent = `Stale: ${Math.floor(ageSeconds)}s ago`;
}
```

**Rationale**: Simple client-side calculation, no server changes needed.

---

### R5: Multi-Exchange Display

**Question**: How to display both Upbit and Binance data when both active?

**Decision**: Separate sections/cards for each exchange

**Design**:
- Check for both `v2_engine_upbit.json` and `v2_engine_binance.json`
- Display each in its own card/section
- Show "Not Active" if a file doesn't exist or is empty

**Rationale**: Clear separation, matches spec requirement for "separate sections with clear labels".

---

## Unresolved Items

None. All technical questions answered through codebase analysis.

## Dependencies Identified

| Dependency | Version | Purpose |
|------------|---------|---------|
| Flask | existing | Web framework |
| Jinja2 | existing | Templates |
| Tailwind CSS | existing (via CDN) | Styling |

No new dependencies required.
