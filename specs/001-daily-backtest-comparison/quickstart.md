# Quickstart: Daily Backtest Comparison Report

> Current scope note (2026-04-24): apply this spec to the Binance spot-only runtime. Any remaining references to Upbit, futures, short_v1, or sideways_v2 are historical draft context, not current implementation guidance.


**Date**: 2025-01-09
**Feature**: 001-daily-backtest-comparison

## Prerequisites

- Python 3.10+ with virtual environment activated
- Trading bot has been running and logging trades to `trading_results.db`
- Market data available via existing data loaders
- Telegram bot configured in `.env` file

## Quick Test

### 1. Generate Report for Yesterday

```bash
# From project root with venv activated
python scripts/daily_comparison.py
```

Expected output:
```
📊 Generating comparison reports for 2025-01-08...
✅ mlp_direction_btc: 2 trades actual, 2 backtest, 0 discrepancies
✅ mlp_direction_eth: 0 trades actual, 0 backtest, 0 discrepancies
📤 Reports sent via Telegram
```

### 2. Generate Report for Specific Date

```bash
python scripts/daily_comparison.py --date 2025-01-07
```

### 3. Dry Run (No Save, No Notification)

```bash
python scripts/daily_comparison.py --dry-run
```

### 4. Single Strategy Only

```bash
python scripts/daily_comparison.py --strategies mlp_direction_btc
```

## Cron Setup

Add to crontab (`crontab -e`):

```cron
# Daily comparison report at 00:05 KST
5 0 * * * cd /path/to/bitcoin-trading-bot && /path/to/.venv/bin/python scripts/daily_comparison.py >> logs/comparison.log 2>&1
```

## Verify Setup

### Check Database Table Exists

```bash
sqlite3 trading_results.db ".schema comparison_reports"
```

Expected:
```sql
CREATE TABLE comparison_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date DATE NOT NULL,
    strategy_name TEXT NOT NULL,
    ...
    UNIQUE(report_date, strategy_name)
);
```

### Check Recent Reports

```bash
sqlite3 trading_results.db "SELECT report_date, strategy_name, discrepancy_count, max_severity FROM comparison_reports ORDER BY created_at DESC LIMIT 5;"
```

### Check Telegram Delivery

Run manual test and verify message received:

```bash
python scripts/daily_comparison.py --date 2025-01-08
```

You should receive a Telegram message like:

```
📊 Daily Comparison Report
📅 Date: 2025-01-08
⏰ Generated: 2025-01-09 00:05:23

mlp_direction_btc
├ Actual: 2 trades, +1.45%
├ Backtest: 2 trades, +1.52%
└ Discrepancies: 0 (Low)

✅ All strategies performing as expected
```

## Troubleshooting

### No Market Data

```
DataNotFoundError: No market data for 2025-01-08
```

**Fix**: Ensure data collection ran for that date:
```bash
python scripts/collect_data.py --date 2025-01-08
```

### No Trades Found

```
⚠️ No actual trades found for v35_classic_wide on 2025-01-08
```

**Cause**: Trading bot was not running or held position all day. This is informational, not an error.

### Telegram Send Failed

```
❌ 텔레그램 전송 실패: status=401
```

**Fix**: Check `.env` for valid `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.

### Report Already Exists

```
Report for 2025-01-08/v35_classic_wide already exists. Regenerating...
```

**Behavior**: Existing report is replaced. This is by design for data corrections.

## Sample Output Files

### Telegram Message (Success)

```
📊 Daily Comparison Report
📅 Date: 2025-01-08
⏰ Generated: 2025-01-09 00:05:23

v35_classic_wide
├ Actual: 3 trades, +2.15%
├ Backtest: 3 trades, +2.23%
└ Discrepancies: 1 (Low)

short_v1
├ Actual: 1 trades, -0.42%
├ Backtest: 1 trades, -0.38%
└ Discrepancies: 0 (Low)

✅ All strategies performing as expected
```

### Telegram Message (Warning)

```
📊 Daily Comparison Report
📅 Date: 2025-01-08
⏰ Generated: 2025-01-09 00:05:23

v35_classic_wide
├ Actual: 2 trades, +0.85%
├ Backtest: 3 trades, +1.92%
└ Discrepancies: 1 (High)

⚠️ High severity discrepancy detected:
- MISSED_TRADE at 14:30: Backtest signaled BUY, no actual trade
```

### Telegram Message (Failure)

```
🚨 Comparison Report Generation Failed
📅 Date: 2025-01-08
❌ Error: DatabaseError - Connection refused after 3 retries

Please check logs/comparison.log for details.
```
