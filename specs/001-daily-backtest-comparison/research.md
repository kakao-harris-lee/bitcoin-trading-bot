# Research: Daily Backtest Comparison Report

**Date**: 2025-01-09
**Feature**: 001-daily-backtest-comparison

## Research Summary

This document captures research findings for implementing the daily backtest comparison feature.

---

## 1. Existing Backtester Integration

### Decision
Reuse the existing `core/backtester.py` `Backtester` class for running daily backtests.

### Rationale
- Already implements fee and slippage calculations matching the 0.14% fee model
- Produces `Trade` dataclass objects with entry/exit times, prices, and P/L
- Provides `_generate_results()` for metrics calculation
- Battle-tested with existing strategies

### Alternatives Considered
- **New standalone backtester**: Rejected - duplicates existing functionality, higher maintenance burden
- **Call external backtest script**: Rejected - subprocess overhead, harder to integrate trade-by-trade comparison

### Integration Notes
- Backtester uses `fee_rate=0.0005` (0.05%) and `slippage=0.0002` (0.02%), totaling 0.14% for round-trip
- Output includes `trades` list and `equity_curve` for metrics extraction
- Need to run with single-day data window (00:00-23:59 KST)

---

## 2. Trade Log Database Schema

### Decision
Read actual trades from existing `trading_results.db` using `TradeLogger` conventions; store comparison reports in new `comparison_reports` table.

### Rationale
- `trading_results.db` already logs trades with: strategy_id, action, price, volume, profit, profit_pct, exchange, timestamp
- Consistent with existing infrastructure
- Single database simplifies backup and management

### Alternatives Considered
- **Separate reports database**: Rejected - adds operational complexity
- **File-based report storage (JSON/MD)**: Rejected - harder to query for historical access

### Schema for New Table
```sql
CREATE TABLE comparison_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    actual_trades_count INTEGER,
    backtest_trades_count INTEGER,
    actual_pnl REAL,
    backtest_pnl REAL,
    actual_pnl_pct REAL,
    backtest_pnl_pct REAL,
    discrepancy_count INTEGER,
    max_severity TEXT,  -- 'Low', 'Medium', 'High'
    report_json TEXT,   -- Full report details as JSON
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(report_date, strategy_name)
);
```

---

## 3. Trade Matching Algorithm

### Decision
Use timestamp-based matching with 5-minute tolerance window, then compare action types.

### Rationale
- Live execution latency makes exact timestamp matching impractical
- 5-minute window accommodates API delays and order fill times
- Matching by action type (BUY/SELL) after time alignment catches direction discrepancies

### Algorithm
```
1. Get actual trades for date, sorted by timestamp
2. Get backtest trades for date, sorted by timestamp
3. For each actual trade:
   a. Find backtest trade within ±5 minutes with same action type → MATCH
   b. Find backtest trade within ±5 minutes with different action → WRONG_DIRECTION
   c. No backtest trade within window → EXTRA_TRADE
4. For remaining unmatched backtest trades → MISSED_TRADE
5. Calculate severity based on P/L impact
```

### Alternatives Considered
- **Exact timestamp match**: Rejected - too strict for real-world latency
- **Hourly candle alignment**: Rejected - loses precision for intra-hour trades
- **Order-based matching (1st trade, 2nd trade)**: Rejected - fails when trade counts differ

---

## 4. Telegram Report Format

### Decision
Use compact Markdown summary with emoji indicators for severity.

### Rationale
- Telegram supports Markdown for formatting
- Emoji provides quick visual scan for issues
- Keeps message under Telegram's 4096 character limit

### Format Template
```
📊 *Daily Comparison Report*
📅 Date: {date}
⏰ Generated: {timestamp}

*{strategy_name}*
├ Actual: {actual_count} trades, {actual_pnl_pct:+.2f}%
├ Backtest: {backtest_count} trades, {backtest_pnl_pct:+.2f}%
└ Discrepancies: {discrepancy_count} ({max_severity})

{severity_emoji} {severity_summary}
```

Severity Emoji:
- ✅ No discrepancies or Low only
- ⚠️ Medium severity present
- 🚨 High severity present

### Alternatives Considered
- **HTML formatting**: Rejected - Telegram HTML more limited than Markdown
- **Attached file**: Rejected - extra step to view, harder for quick daily review
- **Rich table format**: Rejected - doesn't render well on mobile Telegram

---

## 5. Scheduling Mechanism

### Decision
Use system cron to invoke Python script at 00:05 KST daily.

### Rationale
- Server already runs on Linux with cron available
- 00:05 allows brief buffer after midnight for any pending trade logging
- Standard Unix approach, no additional dependencies

### Cron Entry
```
5 0 * * * cd /path/to/bitcoin-trading-bot && /path/to/venv/bin/python scripts/daily_comparison.py >> logs/comparison.log 2>&1
```

### Alternatives Considered
- **APScheduler in bot process**: Rejected - comparison should run even if bot is restarted
- **systemd timer**: Viable alternative but cron is simpler for single scheduled task
- **Celery beat**: Rejected - overkill for single daily task

---

## 6. Retry and Error Handling

### Decision
Implement retry with exponential backoff (3 attempts, 5-minute base interval), notify on final failure.

### Rationale
- Database or network issues may be transient
- 5-minute intervals provide recovery time
- Final failure notification ensures trader awareness

### Implementation
```python
def run_with_retry(func, max_attempts=3, base_delay=300):
    for attempt in range(max_attempts):
        try:
            return func()
        except Exception as e:
            if attempt == max_attempts - 1:
                notify_failure(e)
                raise
            time.sleep(base_delay * (attempt + 1))
```

### Alternatives Considered
- **No retry**: Rejected - transient failures would cause missed reports
- **Immediate retry**: Rejected - doesn't allow time for external issues to resolve
- **Background queue (Celery)**: Rejected - adds complexity for simple retry logic

---

## 7. Historical Report Retention

### Decision
Keep reports in database indefinitely; implement 90-day query scope for default retrieval.

### Rationale
- SQLite storage is cheap for text data
- No need for complex archival logic
- Query-time filtering simpler than scheduled cleanup

### Implementation
- Default query: `WHERE report_date >= date('now', '-90 days')`
- Full history available via explicit date range queries
- Consider adding index on `report_date` for performance

### Alternatives Considered
- **Auto-delete after 90 days**: Rejected - loses valuable long-term data
- **Separate archive table**: Rejected - unnecessary complexity
- **File-based archival**: Rejected - complicates retrieval
