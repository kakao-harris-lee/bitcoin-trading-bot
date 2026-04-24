# Data Model: Real-Time Trading Metrics Dashboard

**Date**: 2026-01-09
**Feature**: 001-trading-metrics-dashboard

> Current scope note (2026-04-24): the active dashboard tracks a single Binance spot runtime. Earlier multi-exchange and futures examples are historical only.

## Entities

### 1. RuntimeMetrics

Represents real-time state for the active trading runtime.

| Field | Type | Description | Source |
|---|---|---|---|
| exchange | string | Always `binance` | Runtime snapshot |
| market | string | Always `spot` | Runtime snapshot |
| mode | string | `paper` or `live` | Runtime snapshot |
| strategy | string | Active strategy or sleeve name | Runtime snapshot |
| regime | string | Current market regime | Runtime snapshot |
| market_state | string | Detailed state such as `BULL_STRONG` | Runtime snapshot |
| current_price | float | Latest market price | Feed snapshot |
| position_active | boolean | Whether a spot position is open | Runtime snapshot |
| position_qty | float | Position quantity | Runtime snapshot |
| entry_price | float | Entry price if active | Runtime snapshot |
| unrealized_pnl | float | Current unrealized P&L | Calculated |
| unrealized_pnl_pct | float | P&L as percentage | Calculated |
| total_value | float | Total portfolio value | Runtime snapshot |
| last_updated | datetime | Latest update timestamp | Runtime snapshot |

### 2. StrategyDecision

Represents a single strategy decision or emitted signal.

| Field | Type | Description | Source |
|---|---|---|---|
| timestamp | datetime | Decision timestamp | Signals log |
| strategy | string | Strategy identifier | Signals log |
| action | string | `buy`, `sell`, or `hold` | Signals log |
| reason | string | Reason code or summary | Signals log |
| regime | string | Regime at decision time | Signals log |
| market_state | string | Detailed market state | Signals log |
| indicators | object | Indicator snapshot | Signals log |

### 3. ConnectionStatus

Represents health of the runtime and feed path.

| Field | Type | Description |
|---|---|---|
| exchange | string | Always `binance` |
| connected | boolean | Whether the runtime can read fresh feed/runtime state |
| last_heartbeat | datetime | Last successful update |
| is_stale | boolean | Data older than threshold |
| stale_seconds | int | Seconds since last update |

### 4. DashboardState

Aggregate response for the runtime metrics dashboard.

| Field | Type | Description |
|---|---|---|
| timestamp | datetime | Response generation time |
| runtime | RuntimeMetrics | Current runtime metrics |
| recent_decisions | StrategyDecision[] | Recent decisions |
| connection_status | ConnectionStatus[] | Runtime/feed status |
