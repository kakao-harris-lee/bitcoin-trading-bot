# Research: Dashboard Upgrade

**Date**: 2026-01-09
**Branch**: `001-dashboard-upgrade`

## Data Sources Analysis

### 1. Trade History Data

**Decision**: Use both SQLite database (`trading_results.db`) and JSON log files (`logs/v2_engine_*.json`)

**Rationale**:
- SQLite `trading_results.db` has structured trades table via `TradeLogger` class with: action, price, volume, profit, profit_pct, exchange, timestamp
- JSON logs contain more detail: strategy name, reason, indicators at time of trade
- SQLite preferred for filtering/pagination, JSON for detailed signal context

**Alternatives considered**:
- JSON only: Rejected - poor query performance for large histories
- New database: Rejected - unnecessary complexity, existing schema sufficient

**Existing API**: `TradeLogger.get_recent_trades()`, `get_trades_for_date_range()` already implemented

### 2. Signal Data

**Decision**: Source from JSON log files (`logs/v2_engine_*.json`) via `signals` array

**Rationale**:
- Signals already captured with: timestamp, strategy, action, reason, regime, market_state, indicators
- JSON structure includes rich context (RSI, MFI, ADX, close price, score, tier)
- Existing `/api/signals/<exchange>` endpoint already returns recent 50 signals

**Alternatives considered**:
- Store signals in SQLite: Deferred - JSON sufficient for dashboard read-only access
- Real-time WebSocket: Rejected - polling at 30s interval adequate for personal use

### 3. Position Data

**Decision**: Use existing `/api/exchange_balances` endpoint which fetches live from exchanges

**Rationale**:
- Already implemented with Upbit positions (symbol, quantity, avg_price, current_price, value, pnl)
- Already implemented with Binance Futures positions (symbol, size, entry_price, unrealized_pnl)
- Real-time data via exchange APIs (pyupbit, binance.client)

**Alternatives considered**:
- Cache positions locally: Not needed - direct API calls fast enough for 1-3 users

### 4. Analytics Calculation

**Decision**: Calculate metrics server-side in Python using existing trade data

**Rationale**:
- Python has numpy/pandas for efficient metric calculation
- Metrics needed: return %, win rate, profit factor, Sharpe ratio, max drawdown
- Existing `Backtester` class already calculates: win_rate, avg_profit, avg_loss, profit_factor
- Equity curve already tracked in backtester

**Implementation approach**:
- New `/api/analytics` endpoint with period parameter (7d, 30d, 90d, all)
- Reuse `TradeLogger.get_trades_for_date_range()` to fetch trade data
- Calculate metrics in analytics service module

### 5. Backtesting Integration

**Decision**: Invoke existing `core/backtester.py` via new API endpoint

**Rationale**:
- `Backtester` class fully implemented with: `run()`, equity curve, trade list, statistics
- Accepts strategy function and parameters, returns comprehensive results
- Need to wrap as async/background task for dashboard (60s timeout for 1-year backtest)

**Implementation approach**:
- New `/api/backtest/run` POST endpoint with: strategy, start_date, end_date, capital
- New `/api/backtest/status/<job_id>` GET for progress polling
- Store results in memory dict with TTL (personal use, no persistence needed)

**Alternatives considered**:
- Client-side backtesting: Rejected - requires data transfer and JS implementation
- Celery task queue: Rejected - overkill for 1-3 users, simple threading sufficient

### 6. Frontend Charting

**Decision**: Use Chart.js for equity curves and analytics charts

**Rationale**:
- Lightweight (~60KB), no build step required
- Supports line charts (equity curve), bar charts (daily P&L), easy customization
- CDN delivery, no npm required - matches existing vanilla JS approach

**Alternatives considered**:
- D3.js: Rejected - more complex API, overkill for simple charts
- Plotly.js: Rejected - larger bundle size
- No charts (tables only): Rejected - equity curve visualization is core requirement

### 7. Tab Navigation

**Decision**: CSS-based tab navigation with vanilla JavaScript

**Rationale**:
- Consistent with existing vanilla JS approach
- HTML5 tab pattern with hidden content sections, CSS for active states
- No framework dependencies, fast initial load

**Implementation**:
```html
<nav class="tab-nav">
  <button data-tab="positions" class="active">Positions</button>
  <button data-tab="history">History</button>
  <button data-tab="signals">Signals</button>
  <button data-tab="analytics">Analytics</button>
  <button data-tab="backtest">Backtest</button>
</nav>
<div id="positions" class="tab-content active">...</div>
<div id="history" class="tab-content">...</div>
...
```

## API Endpoint Summary

| Endpoint | Method | Purpose | Data Source |
|----------|--------|---------|-------------|
| `/api/positions` | GET | All positions (both exchanges) | Exchange APIs |
| `/api/trades` | GET | Trade history with filters | SQLite + JSON |
| `/api/signals` | GET | Recent signals | JSON logs |
| `/api/analytics` | GET | Performance metrics | Calculated from trades |
| `/api/backtest/run` | POST | Start backtest job | core/backtester.py |
| `/api/backtest/status/<id>` | GET | Backtest progress/results | Memory cache |

## Performance Considerations

- **Trade history pagination**: Limit default to 100, support `?page=N&limit=M`
- **Analytics caching**: Cache metrics for 5 minutes (invalidate on new trade)
- **Backtest timeout**: 120s max, background thread with status polling
- **Chart data points**: Limit equity curve to 500 points (downsample if needed)

## Dependencies to Add

- `chart.js` via CDN (no pip install) - version 4.x
- No new Python dependencies - all required packages already installed

## Risk Mitigations

| Risk | Mitigation |
|------|------------|
| Slow backtest blocks server | Run in background thread, return job ID |
| Large trade history slows page | Server-side pagination, default 100 limit |
| Exchange API rate limits | Cache exchange data for 30s (existing pattern) |
| Chart library size | CDN with async loading, defer non-critical |
