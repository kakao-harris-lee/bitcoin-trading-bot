# Web Dashboard

Flask-based monitoring dashboard.

## Usage

```bash
cd web
python app.py
```

Open http://localhost:8080

## API Endpoints

- `GET /api/status` - Current status
- `GET /api/trades/upbit` - Upbit trades
- `GET /api/trades/binance` - Binance trades
- `GET /api/statistics` - Statistics
- `GET /api/kill_switch/status` - Kill switch status
