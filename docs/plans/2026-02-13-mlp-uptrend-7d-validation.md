# MLP Uptrend Alpha - 7-Day Validation Runbook

**Start (KST):** 2026-02-13 09:30  
**End (KST):** 2026-02-20 09:30  
**Mode:** Existing paper bot (no additional `run.py` instance)

## 1. Goal

Validate whether the implemented MLP improvements increase up-market responsiveness without destabilizing behavior.

Primary daily checkpoints:

- `up_market_alpha_pct`
- `early_exit_rate_pct`

## 2. Runtime Jobs

### 2.1 Cron Registration

Registered entry (Asia/Seoul timezone):

```cron
CRON_TZ=Asia/Seoul
30 9 * * * /usr/bin/bash /home/deploy/project/bitcoin-trading-bot/scripts/paper/run_daily_soak_and_notify.sh
```

### 2.2 Final Validation Date (Joint Review)

Final 7-day summary run is scheduled on validation date:

- **Date/Time (KST):** 2026-02-20 09:40
- **Script:** `scripts/paper/run_final_7d_validation_and_notify.sh`
- **Output:** `validation_7d_summary_*.md`, `validation_7d_summary_*.json`
- **Notify:** Telegram summary message sent after aggregation

One-time cron entry:

```cron
CRON_TZ=Asia/Seoul
40 9 20 2 * /usr/bin/bash /home/deploy/project/bitcoin-trading-bot/scripts/paper/run_final_7d_validation_and_notify.sh
```

### 2.3 Reminder Alerts (Memory Support)

Reminder script:

- `scripts/paper/run_validation_reminder_and_notify.sh`
- 내부 호출: `scripts/paper/send_validation_reminder.py`

Reminder cron entries:

```cron
CRON_TZ=Asia/Seoul
0 18 19 2 * /usr/bin/bash /home/deploy/project/bitcoin-trading-bot/scripts/paper/run_validation_reminder_and_notify.sh --label D-1
0 9 20 2 * /usr/bin/bash /home/deploy/project/bitcoin-trading-bot/scripts/paper/run_validation_reminder_and_notify.sh --label D-DAY
```

### 2.4 Daily Cron Wrapper

Script: `scripts/paper/run_daily_soak_and_notify.sh`

Sequence:

1. `python scripts/paper/collect_daily_mlp_soak_metrics.py --lookback-hours 24`
2. `python scripts/paper/run_soak_vs_bnh.py --no-run --lookback-seconds 86400 --output-dir logs/paper_soak`
3. Send summary to Telegram (`TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` from `.env`)

## 3. Artifacts

### 3.1 KPI History

`logs/paper_soak/mlp_daily_metrics.csv`

Columns:

- `run_ts`
- `symbol`
- `up_market_alpha_pct`
- `early_exit_rate_pct`
- `alpha_pct`
- `up_market_capture_ratio`
- `decision_count`
- `metric_source`

### 3.2 Daily Soak Reports

Generated daily:

- `logs/paper_soak/paper_soak_vs_bnh_YYYYMMDD_HHMMSS.csv`
- `logs/paper_soak/paper_soak_vs_bnh_YYYYMMDD_HHMMSS.md`
- `logs/paper_soak/paper_soak_vs_bnh_YYYYMMDD_HHMMSS.json`
- `logs/paper_soak/cron_daily_YYYYMMDD_HHMMSS.log`

### 3.3 Final Validation Reports (2026-02-20)

Generated once on final validation schedule:

- `logs/paper_soak/validation_7d_summary_YYYYMMDD_HHMMSS.md`
- `logs/paper_soak/validation_7d_summary_YYYYMMDD_HHMMSS.json`
- `logs/paper_soak/cron_final_validation_YYYYMMDD_HHMMSS.log`

### 3.4 Reminder Logs

- `logs/paper_soak/cron_validation_reminder_YYYYMMDD_HHMMSS.log`

## 4. Success / Alert Criteria

Use these checks during the 7-day window:

1. `early_exit_rate_pct` should remain stable and low (no sudden spike trend).
2. `up_market_alpha_pct` should improve versus baseline trend (less negative or turning positive).
3. No repeated wrapper failures in `cron_daily_*.log`.
4. No cron execution gaps (one run per day near 09:30 KST).

## 5. Daily Verification Commands

```bash
# Latest cron run log
ls -1t logs/paper_soak/cron_daily_*.log | head -n 1
tail -n 120 "$(ls -1t logs/paper_soak/cron_daily_*.log | head -n 1)"

# Last KPI rows
tail -n 20 logs/paper_soak/mlp_daily_metrics.csv

# Latest soak markdown report
ls -1t logs/paper_soak/paper_soak_vs_bnh_*.md | head -n 1
```

## 6. End-of-Window Evaluation (2026-02-20)

At the end time (09:40 KST), aggregate the 7 records per symbol from:

- `logs/paper_soak/mlp_daily_metrics.csv`

Produce:

1. mean/median `up_market_alpha_pct` by symbol,
2. mean `early_exit_rate_pct` by symbol,
3. pass/fail recommendation for threshold retuning or rollout.

Joint review checklist:

1. Open latest `validation_7d_summary_*.md`
2. Compare symbol means vs day-1 baseline
3. Confirm no repeated cron failures during the 7-day window
4. Decide: keep config / retune thresholds / partial rollback
