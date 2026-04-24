# Data Model: Daily Backtest Comparison Report

> Current scope note (2026-04-24): apply this spec to the Binance spot-only runtime. Any remaining references to Upbit, futures, short_v1, or sideways_v2 are historical draft context, not current implementation guidance.


**Date**: 2025-01-09
**Feature**: 001-daily-backtest-comparison

## Entity Overview

```
┌─────────────────────────┐     ┌─────────────────────────┐
│  DailyComparisonReport  │────<│     TradeComparison     │
│         (1)             │     │          (N)            │
└─────────────────────────┘     └─────────────────────────┘
            │
            │ contains
            ▼
┌─────────────────────────┐
│    DiscrepancyRecord    │
│          (N)            │
└─────────────────────────┘
```

---

## Entities

### DailyComparisonReport

Represents the comparison results for a single day and strategy.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| id | Integer | Primary Key, Auto | Unique identifier |
| report_date | Date | Required, Unique with strategy_name | The date being compared (YYYY-MM-DD) |
| strategy_name | String | Required | Strategy identifier (e.g., "mlp_direction_btc", "mlp_direction_eth") |
| actual_trades_count | Integer | >= 0 | Number of trades executed in live trading |
| backtest_trades_count | Integer | >= 0 | Number of trades the backtest generated |
| actual_pnl | Float | | Actual profit/loss in KRW |
| backtest_pnl | Float | | Backtest profit/loss in KRW |
| actual_pnl_pct | Float | | Actual profit/loss percentage |
| backtest_pnl_pct | Float | | Backtest profit/loss percentage |
| actual_max_drawdown | Float | >= 0 | Maximum drawdown during live trading (%) |
| backtest_max_drawdown | Float | >= 0 | Maximum drawdown in backtest (%) |
| discrepancy_count | Integer | >= 0 | Total number of discrepancies found |
| max_severity | Enum | Low/Medium/High | Highest severity among discrepancies |
| trade_comparisons | List[TradeComparison] | | Detailed trade-by-trade comparison |
| discrepancies | List[DiscrepancyRecord] | | List of identified discrepancies |
| report_json | String | | Full serialized report for storage |
| created_at | Timestamp | Auto | Report generation timestamp |

**Uniqueness**: (report_date, strategy_name) must be unique.

**Lifecycle**:
1. **Generated** → Report created at midnight
2. **Stored** → Persisted to database
3. **Retrieved** → Queried for display or analysis

---

### TradeComparison

Represents a single comparison point between an actual trade and backtest trade.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| actual_timestamp | Datetime | Optional | When the actual trade occurred |
| backtest_timestamp | Datetime | Optional | When the backtest trade occurred |
| actual_action | Enum | BUY/SELL/None | Action taken in live trading |
| backtest_action | Enum | BUY/SELL/None | Action recommended by backtest |
| actual_price | Float | Optional | Execution price in live trading |
| backtest_price | Float | Optional | Price used in backtest |
| price_difference | Float | | Absolute difference in price |
| price_difference_pct | Float | | Percentage difference in price |
| match_status | Enum | Required | MATCH/MISMATCH/EXTRA/MISSING |

**Match Status Values**:
- `MATCH`: Actual and backtest trade align within tolerance
- `MISMATCH`: Trades exist but differ (timing/direction)
- `EXTRA`: Actual trade with no corresponding backtest trade
- `MISSING`: Backtest trade with no corresponding actual trade

---

### DiscrepancyRecord

Represents a specific mismatch requiring attention.

| Field | Type | Constraints | Description |
|-------|------|-------------|-------------|
| timestamp | Datetime | Required | When the discrepancy occurred |
| discrepancy_type | Enum | Required | Type of mismatch |
| severity | Enum | Low/Medium/High | Impact severity |
| actual_value | String | Optional | What actually happened |
| expected_value | String | Optional | What was expected (from backtest) |
| pnl_impact | Float | | Estimated profit/loss impact |
| pnl_impact_pct | Float | | Estimated impact as percentage |
| explanation | String | | Human-readable description |

**Discrepancy Types**:
- `MISSED_TRADE`: Backtest signaled trade not executed
- `EXTRA_TRADE`: Trade executed not in backtest
- `WRONG_DIRECTION`: BUY vs SELL mismatch
- `TIMING_DIFFERENCE`: Trade outside 5-minute tolerance
- `PRICE_DEVIATION`: Significant execution price difference

**Severity Calculation**:
- `Low`: P/L impact < 1%
- `Medium`: P/L impact 1-5%
- `High`: P/L impact > 5% OR wrong direction trade

---

## Database Schema (SQLite)

### Existing Table Reference: `trades`

```sql
-- Already exists in trading_results.db
CREATE TABLE trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    strategy_id INTEGER NOT NULL,
    action TEXT NOT NULL,           -- 'BUY' or 'SELL'
    price REAL NOT NULL,
    volume REAL NOT NULL,
    profit REAL,                    -- For SELL trades
    profit_pct REAL,                -- For SELL trades
    exchange TEXT DEFAULT 'upbit',  -- 'upbit' or 'binance'
    timestamp TEXT NOT NULL,
    FOREIGN KEY (strategy_id) REFERENCES strategies(strategy_id)
);
```

### New Table: `comparison_reports`

```sql
CREATE TABLE IF NOT EXISTS comparison_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    actual_trades_count INTEGER DEFAULT 0,
    backtest_trades_count INTEGER DEFAULT 0,
    actual_pnl REAL DEFAULT 0.0,
    backtest_pnl REAL DEFAULT 0.0,
    actual_pnl_pct REAL DEFAULT 0.0,
    backtest_pnl_pct REAL DEFAULT 0.0,
    actual_max_drawdown REAL DEFAULT 0.0,
    backtest_max_drawdown REAL DEFAULT 0.0,
    discrepancy_count INTEGER DEFAULT 0,
    max_severity TEXT DEFAULT 'Low',
    report_json TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(report_date, strategy_name)
);

CREATE INDEX IF NOT EXISTS idx_comparison_reports_date
ON comparison_reports(report_date);

CREATE INDEX IF NOT EXISTS idx_comparison_reports_strategy
ON comparison_reports(strategy_name);
```

---

## Validation Rules

### DailyComparisonReport
- `report_date` must be a valid past date (not future)
- `strategy_name` must match a known strategy identifier
- `max_severity` must be derived from `discrepancies` list

### TradeComparison
- At least one of `actual_timestamp` or `backtest_timestamp` must be present
- `match_status` must align with which fields are populated

### DiscrepancyRecord
- `severity` must be computed from `pnl_impact_pct`:
  - `|pnl_impact_pct| < 1.0` → Low
  - `1.0 <= |pnl_impact_pct| < 5.0` → Medium
  - `|pnl_impact_pct| >= 5.0` OR `WRONG_DIRECTION` → High

---

## State Transitions

Reports are immutable once created. The only state transition is:

```
[Not Exists] → [Generated] → [Stored]
```

If regeneration is needed (e.g., data correction), the existing report is replaced via `INSERT OR REPLACE` on the unique constraint.
