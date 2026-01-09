# Data Model: Real-Time Trading Metrics Dashboard

**Date**: 2026-01-09
**Feature**: 001-trading-metrics-dashboard

## Entities

### 1. ExchangeMetrics

Represents real-time metrics for a single exchange (Upbit or Binance).

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| exchange | string | Exchange identifier ("upbit" or "binance") | v2_engine_*.json |
| mode | string | Trading mode ("paper" or "live") | v2_engine_*.json |
| strategy | string | Active strategy name (e.g., "va02", "short_v1") | v2_engine_*.json |
| regime | string | Market regime ("BULL", "SIDEWAYS", "BEAR") | v2_engine_*.json |
| market_state | string | Detailed state ("BEAR_STRONG", etc.) | v2_engine_*.json |
| current_price | float | Latest BTC price | signals[0].indicators.close |
| position_active | boolean | Whether a position is open | btc_balance > 0 |
| position_qty | float | Position quantity in BTC | btc_balance |
| entry_price | float | Entry price if position active | Last buy trade price |
| unrealized_pnl | float | Current unrealized P&L in KRW/USDT | Calculated |
| unrealized_pnl_pct | float | P&L as percentage | Calculated |
| total_value | float | Total portfolio value | total_value |
| last_updated | datetime | Timestamp of last data update | signals[0].timestamp |

### 2. StrategyDecision

Represents a single strategy decision/signal.

| Field | Type | Description | Source |
|-------|------|-------------|--------|
| timestamp | datetime | When decision was made | signals[].timestamp |
| strategy | string | Strategy that made the decision | signals[].strategy |
| action | string | Decision type ("buy", "sell", "hold") | signals[].action |
| reason | string | Reason code (e.g., "VA02_HOLDING_S") | signals[].reason |
| regime | string | Market regime at decision time | signals[].regime |
| market_state | string | Detailed market state | signals[].market_state |
| indicators | object | Technical indicators at decision time | signals[].indicators |

### 3. Indicators (nested in StrategyDecision)

| Field | Type | Description |
|-------|------|-------------|
| rsi | float | RSI value (0-100) |
| mfi | float | MFI value (0-100) |
| adx | float | ADX value |
| close | float | Closing price |
| score | int | Strategy score |
| tier | string | Score tier ("S", "A", "B", etc.) |

### 4. ConnectionStatus

Represents exchange connection health.

| Field | Type | Description |
|-------|------|-------------|
| exchange | string | Exchange identifier |
| connected | boolean | Whether connected |
| last_heartbeat | datetime | Last successful data fetch |
| is_stale | boolean | Data older than 30 seconds |
| stale_seconds | int | Seconds since last update |

### 5. DashboardState

Aggregate response for the metrics dashboard.

| Field | Type | Description |
|-------|------|-------------|
| timestamp | datetime | Response generation time |
| upbit | ExchangeMetrics | Upbit metrics (nullable) |
| binance | ExchangeMetrics | Binance metrics (nullable) |
| recent_decisions | StrategyDecision[] | Last 24h of decisions (max 50) |
| connection_status | ConnectionStatus[] | Status for each exchange |

## Relationships

```
DashboardState
├── ExchangeMetrics (upbit)
│   └── last_decision: StrategyDecision
├── ExchangeMetrics (binance)
│   └── last_decision: StrategyDecision
├── recent_decisions: StrategyDecision[]
│   └── indicators: Indicators
└── connection_status: ConnectionStatus[]
```

## Validation Rules

1. **regime**: Must be one of ["BULL", "SIDEWAYS", "BEAR", "UNKNOWN"]
2. **market_state**: Must be one of ["BULL_STRONG", "BULL_WEAK", "SIDEWAYS", "BEAR_WEAK", "BEAR_STRONG", "UNKNOWN"]
3. **action**: Must be one of ["buy", "sell", "hold"]
4. **mode**: Must be one of ["paper", "live"]
5. **exchange**: Must be one of ["upbit", "binance"]

## State Transitions

### Position Lifecycle

```
NO_POSITION --[buy signal]--> POSITION_OPEN
POSITION_OPEN --[sell signal]--> NO_POSITION
POSITION_OPEN --[hold signal]--> POSITION_OPEN (no change)
```

### Connection State

```
CONNECTED --[no update > 30s]--> STALE
STALE --[new update received]--> CONNECTED
CONNECTED --[file not found]--> DISCONNECTED
DISCONNECTED --[file appears]--> CONNECTED
```

## Data Volume Assumptions

- Signals array: ~100-500 entries per exchange (rolling 24h)
- Trades array: ~5-20 entries per exchange (per month)
- Update frequency: Every 5 minutes from bot
- Dashboard poll frequency: Every 4 seconds
