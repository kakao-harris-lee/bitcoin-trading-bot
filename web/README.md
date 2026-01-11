# Web Dashboard

Flask-based monitoring dashboard.

## Usage

```bash
cd web
python app.py
```

Open http://localhost:8080

## Pages

- `/btc-dashboard` - Main trading dashboard with balances and positions
- `/metrics` - Real-time trading metrics with strategy decisions

## API Endpoints

### Status & Trades

- `GET /api/status` - Current status
- `GET /api/trades/binance` - Binance trades
- `GET /api/statistics` - Statistics
- `GET /api/kill_switch/status` - Kill switch status

### Real-Time Metrics

- `GET /api/metrics/realtime` - Current trading state (strategy, regime, positions)
- `GET /api/metrics/decisions` - Decision history
  - Query params: `exchange` (binance), `hours` (1-72), `limit` (1-200)

## Real-Time Metrics Dashboard

The `/metrics` page displays:

1. **Strategy Decisions** - Current action (buy/sell/hold) with reason and timestamp
2. **Market Regime** - BULL/SIDEWAYS/BEAR classification with color coding
3. **Position Metrics** - Entry price, current price, size, unrealized P&L
4. **Decision History** - Last 24 hours of strategy decisions with expandable details
5. **Connection Status** - Live/stale indicators for each exchange

Data refreshes every 4 seconds via JavaScript polling.
