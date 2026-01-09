# Quickstart: Dashboard Upgrade

**Branch**: `001-dashboard-upgrade`

## Prerequisites

- Python 3.9+ with virtual environment activated
- Existing trading bot setup (Flask dashboard running)
- Exchange API credentials configured in `.env`
- SQLite database `trading_results.db` present

## Development Setup

```bash
# 1. Switch to feature branch
git checkout 001-dashboard-upgrade

# 2. Activate virtual environment
source .venv/bin/activate

# 3. Verify Flask dashboard runs
python web/app.py

# 4. Open dashboard in browser
# Navigate to: http://localhost:5080/btc-dashboard
# Enter TOTP code when prompted
```

## Key Files to Modify

| File | Changes |
|------|---------|
| `web/app.py` | Add new API endpoints for positions, trades, signals, analytics, backtest |
| `web/templates/dashboard.html` | Add tab navigation, new section containers |
| `web/static/js/dashboard.js` | Tab switching logic, API fetching for new sections |
| `web/static/css/style.css` | Tab styles, table styles, chart containers |

## New Files to Create

| File | Purpose |
|------|---------|
| `web/services/analytics.py` | Analytics calculation service |
| `web/services/backtest_runner.py` | Backtest job management |

## API Implementation Order

1. **`/api/positions`** - Consolidate existing exchange balance data
2. **`/api/trades`** - Query TradeLogger with pagination/filters
3. **`/api/signals`** - Read from JSON logs (extend existing endpoint)
4. **`/api/analytics`** - Calculate from trade data
5. **`/api/analytics/equity-curve`** - Generate chart data
6. **`/api/analytics/daily`** - Daily aggregation
7. **`/api/backtest/run`** - Start backtest job
8. **`/api/backtest/status/<id>`** - Poll job status
9. **`/api/backtest/strategies`** - List available strategies

## Frontend Implementation Order

1. **Tab navigation** - HTML structure + JS tab switching
2. **Positions tab** - Table display using existing data patterns
3. **History tab** - Sortable table with filters + pagination
4. **Signals tab** - Real-time list with status indicators
5. **Analytics tab** - Metrics cards + Chart.js equity curve
6. **Backtest tab** - Form + progress indicator + results display

## Testing Checklist

```bash
# Run existing tests to ensure no regression
pytest

# Manual testing sequence:
# 1. Verify existing dashboard still works
# 2. Test each new tab loads without errors
# 3. Test trade history pagination
# 4. Test analytics period switching
# 5. Run a backtest and verify results
```

## Chart.js Setup

Add to `dashboard.html` head:
```html
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
```

## Common Patterns

### Tab Navigation (HTML)
```html
<nav class="tab-nav">
  <button class="tab-btn active" data-tab="positions">Positions</button>
  <button class="tab-btn" data-tab="history">History</button>
  <!-- more tabs -->
</nav>
<div id="positions" class="tab-content active">...</div>
<div id="history" class="tab-content">...</div>
```

### Tab Switching (JS)
```javascript
document.querySelectorAll('.tab-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    // Remove active from all
    document.querySelectorAll('.tab-btn').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    // Activate clicked
    btn.classList.add('active');
    document.getElementById(btn.dataset.tab).classList.add('active');
  });
});
```

### API Endpoint Pattern (Flask)
```python
@app.route("/api/trades")
def get_trades():
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 100, type=int)
    exchange = request.args.get('exchange')
    # ... fetch and return data
    return jsonify({'trades': trades, 'total_count': total, 'page': page})
```

## Performance Notes

- Trade history: Always paginate, default 100 per page
- Analytics: Cache for 5 minutes with period key
- Equity curve: Limit to 500 points, downsample longer periods
- Backtest: Run in background thread, 120s timeout

## Deployment

```bash
# After implementation complete:
git add .
git commit -m "feat(dashboard): add positions, history, analytics, signals, backtest tabs"
git push origin 001-dashboard-upgrade

# Create PR to main
gh pr create --title "Dashboard Upgrade" --body "Adds comprehensive trading dashboard..."

# After merge and review:
# On server:
cd ~/bitcoin-trading-bot
git pull origin main
./bot.sh restart --trend=live
```
