# Quickstart: Real-Time Trading Metrics Dashboard

> Current scope note (2026-04-24): apply this spec to the Binance spot-only runtime. Any remaining references to Upbit, futures, short_v1, or sideways_v2 are historical draft context, not current implementation guidance.


## Overview

This feature adds a real-time metrics page to the existing Flask dashboard that displays current strategy decisions, market regime, positions, and P&L.

## Prerequisites

- Python 3.10+
- Existing Flask dashboard running (`web/app.py`)
- Trading bot generating log files in `logs/`

## Quick Test

1. **Start the dashboard** (if not running):
   ```bash
   cd web && python app.py
   ```

2. **Access the metrics page**:
   ```
   http://localhost:5080/metrics
   ```

3. **Verify data appears**:
   - Strategy name and mode (paper/live) should display
   - Market regime should show (BULL/SIDEWAYS/BEAR)
   - If bot is running with position, P&L should update every 4 seconds

## Files Modified/Created

| File | Action | Purpose |
|------|--------|---------|
| `web/app.py` | MODIFY | Add `/metrics` route and `/api/metrics/*` endpoints |
| `web/templates/metrics.html` | CREATE | Dashboard template |
| `web/static/js/metrics.js` | CREATE | Polling and DOM updates |
| `web/services/metrics_service.py` | CREATE | Data aggregation logic |
| `tests/web/test_metrics_api.py` | CREATE | API tests |

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/metrics` | GET | HTML page for real-time metrics |
| `/api/metrics/realtime` | GET | JSON with current state |
| `/api/metrics/decisions` | GET | JSON with decision history |

## Key Implementation Notes

1. **Polling Interval**: 4 seconds (configurable in `metrics.js`)
2. **Stale Data Threshold**: 30 seconds (shows warning if exceeded)
3. **Data Source**: Reads from `logs/v2_engine_*.json` files
4. **No Bot Changes**: Dashboard is read-only, no bot modifications needed

## Troubleshooting

### No data displayed
- Check that `logs/v2_engine_upbit.json` or `logs/v2_engine_binance.json` exists
- Verify the bot has run at least once to generate initial logs

### Data not updating
- Check browser console for JavaScript errors
- Verify `/api/metrics/realtime` returns valid JSON
- Confirm bot is still running and updating log files

### Stale data warning
- Normal if bot is stopped
- If bot is running, check bot logs for errors
