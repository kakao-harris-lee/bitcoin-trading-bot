# 2026-04-14 Monthly Follow-up Implementation Plan

## Goal
- Primary objective: find coins entering an upward phase early enough to participate in continuation, while cutting fallback-driven false positives and over-reactive protective exits.
- Secondary objective: reduce Telegram noise so operators only receive major trading information.

## Current Problems
- The BNB sleeve is still driven mostly by `regime_fallback` entries instead of selector-confirmed candidates.
- `regime_ema120` / bear-regime protection remains the largest realized loss bucket in the 30-day operating review.
- Symbol routing still leans on stale backtest evidence and weak real-time forward quality gating.
- Telegram is too chatty relative to trading value, especially around selector churn and low-value system alerts.

## Workstream 1: Tighten `regime_fallback` Entry Routing

### Objective
Reduce fallback entries that occur because selector/MLP quality is weak, and reserve fallback for symbols with recent forward evidence of trend capture quality.

### Code Scope
- `trading/strategies/components/hybrid_long_entry.py`
- `trading/strategies/components/symbol_selector.py`
- `config/strategies/allocation.json`
- new helper script under `scripts/paper/` or `scripts/maintenance/` for rolling symbol quality extraction

### Planned Changes
1. Add a forward-quality gate before allowing `regime_fallback` on the BNB sleeve.
- Inputs: last 30-day realized PnL, recent `alpha_pct`, recent `up_market_capture_ratio`, risk-exit share, fallback-entry share.
- Policy: allow fallback only if the symbol is not on a suppress list and meets minimum recent quality thresholds.

2. Split fallback policy by rejection reason more aggressively.
- Keep fallback for `unavailable/warmup` cases.
- Suppress fallback for `non_buy` and `low_confidence` unless the symbol has explicit boost status.
- Keep `filter_block` fallback only when the regime-quality score is strong and the symbol is in the current allowlist.

3. Push selector persistence harder.
- Raise `min_consecutive_eligible` and `entry_ready_min_consecutive` for BNB.
- Use per-symbol score multipliers generated from monthly forward results, not only static hand-tuned values.

### Validation
- Unit tests for routing reason/category handling.
- 30/60/90-day backtest comparison for BNB sleeve.
- 72h paper soak comparison:
  - fallback-entry share down
  - risk-exit share down
  - realized PnL and trailing-stop capture not degraded

## Workstream 2: Soften `regime_ema120` Protection in Bull Continuation

### Objective
Stop forcing exits on shallow or temporary pullbacks during ongoing bull phases.

### Code Scope
- `trading/strategies/components/regime_long_v2_exit.py`
- `config/strategies/allocation.json`
- tests under `tests/trading/strategies/components/`

### Planned Changes
1. Add EMA-protect qualifiers instead of exiting on `below ema_120 streak=N` alone.
- Candidate params:
  - `ema_slow_min_profit_pct_for_exit`
  - `ema_slow_min_drawdown_from_hwm_pct`
  - `ema_slow_require_fast_below_slow`
  - `ema_slow_blocked_regimes`
  - `ema_slow_grace_bars_after_entry`

2. Make bull-continuation handling asymmetric.
- In `BULL_STRONG` / `BULL_MODERATE`, require stronger bearish confirmation before the EMA120 exit can fire.
- Preserve current fast protection for actual bear transitions and deep peak-drawdown events.

3. Separate BNB sleeve protection from BTC/ETH defaults.
- BNB/universe names need looser continuation tolerance than BTC/ETH core sleeves.

### Validation
- New unit tests for EMA120 exit gating by regime, hold bars, and drawdown state.
- Replay recent worst offenders (`TRX`, `LINK`, `SOL`, `BNB`, `DOGE`, `APT`) through backtest slices.
- Post-change goal:
  - fewer `regime_ema120` exits
  - higher trailing-stop realization
  - no large increase in drawdown exits

## Workstream 3: Refresh Backtest + Routing Loop from Current Universe

### Objective
Replace stale symbol routing assumptions with a repeatable loop that blends current-universe backtest evidence and recent forward paper evidence.

### Code Scope
- `scripts/backtest.py` invocation wrapper or a new report script under `scripts/paper/` or `scripts/maintenance/`
- `reports/` output for current universe runs
- `config/strategies/allocation.json` score multipliers / denylist / boostlist updates

### Planned Changes
1. Run a new BNB universe backtest using the current allocation universe for the last 60-90 days.
- Output per-symbol return, alpha vs buy-and-hold, Sharpe, profit factor, trade count, win rate.

2. Join backtest output with recent forward metrics.
- Sources:
  - `logs/paper_soak/mlp_daily_metrics.csv`
  - `logs/paper_soak/paper_soak_vs_bnh_*.json`
  - realized trade log summary

3. Generate routing recommendations automatically.
- `boost`: positive recent alpha, acceptable capture ratio, positive realized PnL, acceptable risk-exit share
- `suppress`: negative realized PnL, high fallback-entry share, high risk-exit share, weak forward alpha
- `watchlist`: strong shadow-follow / transition capture but insufficient live trading volume

4. Update config from generated recommendations.
- Refresh `symbol_score_multipliers`
- optionally add explicit denylist / allowlist behavior if score multipliers are insufficient

### Validation
- Compare old vs refreshed routing candidates.
- Confirm that boosted names align with both backtest and forward evidence.
- Confirm that suppressed names are not being removed only because of temporary noise.

## Workstream 4: Telegram Major-Only Mode

### Objective
Keep Telegram focused on actions and exceptions that matter operationally.

### Planned Policy
- Keep:
  - trade entry/exit notifications
  - order rejections
  - startup notification
  - manual command responses
  - generic system alerts only at or above configured severity
- Suppress by default:
  - selector event push notifications
  - unknown executor alert types
  - generic INFO/WARNING/ERROR alerts below configured threshold

### Immediate Changes
- Default `TELEGRAM_NOTIFY_SELECTOR_EVENTS=false`
- Default `TELEGRAM_SYSTEM_ALERT_MIN_LEVEL=CRITICAL`
- Keep `TELEGRAM_NOTIFY_ORDER_REJECTED=true`
- Reformat trade notifications around symbol / qty / value / strategy / PnL / reason
- Preserve `/selector` command for on-demand inspection instead of push spam

## Execution Order
1. Telegram hardening and monitoring reduction
2. Workstream 2 (`regime_ema120` protection softening)
3. Workstream 3 (fresh backtest + routing dataset)
4. Workstream 1 (fallback routing policy using refreshed routing evidence)

## Success Criteria
- Telegram messages are dominated by entries, exits, and actual execution failures.
- BNB fallback-entry share drops materially from the current monthly level.
- `regime_ema120` realized loss share falls without replacing it with a worse drawdown bucket.
- Boosted symbols show better live trailing-stop realization and capture more early bull transitions.
