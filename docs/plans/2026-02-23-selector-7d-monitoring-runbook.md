# Selector 7D Monitoring Runbook

## Purpose
- Validate whether "early altcoin ignition" alerts are actionable in paper mode.
- Track alert quality with concrete conversion KPIs:
  - alert frequency
  - signal-to-buy conversion
  - data quality / stale rejection pressure

## Commands
```bash
# One-shot report (7d, mlp_direction_bnb, 240m conversion window)
python scripts/paper/selector_signal_monitor_7d.py \
  --lookback-days 7 \
  --strategy mlp_direction_bnb \
  --entry-window-minutes 240 \
  --report-dir logs/paper_soak

# One-shot report (12h window)
python scripts/paper/selector_signal_monitor_7d.py \
  --lookback-hours 12 \
  --strategy mlp_direction_bnb \
  --entry-window-minutes 240 \
  --report-dir logs/paper_soak

# Daily run + Telegram notification
bash scripts/paper/run_daily_selector_monitor_and_notify.sh
```

## Output Artifacts
- `logs/paper_soak/selector_monitor_7d_*_summary.md`
- `logs/paper_soak/selector_monitor_7d_*_summary.json`
- `logs/paper_soak/selector_monitor_7d_*_daily.csv`
- `logs/paper_soak/selector_monitor_7d_*_signals.csv`

## KPI Criteria (Default)
| Criterion | Target |
|---|---|
| `entry_ready_conversion` | `>= 15%` |
| `new_candidate_conversion` | `>= 8%` |
| `avg_dq_blocked_ratio` | `<= 40%` |
| `stale_reject_ratio` | `<= 50%` |
| `selector_events_per_day` | `8 ~ 250` |
| `lookback_coverage` | `>= 70%` |

## Interpretation Notes
- `lookback_coverage` is important because selector stream retention may be shorter than 7d.
- Recommended selector retention: `symbol_selector.event_maxlen >= 50000` (60s refresh 기준 약 34일 보존 여유).
- For aggressive alt universe, keep `symbol_selector.max_price_age_seconds >= 90` to avoid over-rejecting symbols that update near 1-minute cadence.
- For restart stability, use startup warmup:
  - `symbol_selector.startup_grace_seconds: 180`
  - `data_quality.startup_grace_seconds: 180`
- If coverage is low, treat conversion/frequency as provisional.
- If `stale_reject_ratio` is high, fix data freshness first; strategy signal quality is not yet the bottleneck.
- If conversion is low but DQ is healthy, tune selector ignition thresholds/weights first.

## Suggested Cron (12h + 24h checks)
```cron
# 12h rolling check (09:15 / 21:15 KST)
15 9,21 * * * cd /home/deploy/project/bitcoin-trading-bot && LOOKBACK_HOURS=12 STRATEGY_NAME=mlp_direction_bnb ENTRY_WINDOW_MINUTES=240 bash scripts/paper/run_daily_selector_monitor_and_notify.sh >> logs/paper_soak/cron_selector_monitor_scheduler.log 2>&1

# 24h rolling check (09:25 KST)
25 9 * * * cd /home/deploy/project/bitcoin-trading-bot && LOOKBACK_HOURS=24 STRATEGY_NAME=mlp_direction_bnb ENTRY_WINDOW_MINUTES=240 bash scripts/paper/run_daily_selector_monitor_and_notify.sh >> logs/paper_soak/cron_selector_monitor_scheduler.log 2>&1
```
