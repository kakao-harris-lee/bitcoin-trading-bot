# Altcoin Ignition Monitoring v2

## Goal
- Detect early-stage ALT uptrends before full trend confirmation.
- Keep selection actionable for paper/live by combining tradeability + trend ignition.
- Reduce noisy minute-by-minute notifications by sending only state transitions.

## Scope
- Component strategy selector (`mlp_direction_bnb`) rotation layer.
- Selector event stream + Telegram selector alerts.
- Dashboard Selector Monitor visibility.

## v2 Signal Stack
1. Market/Regime Gate
- Keep `skip_bear_regime=true` as hard gate.
- Regime remains a score component and a rejection reason.

2. Tradeability Gate
- Existing data quality blocks (stale/low tick-rate) remain unchanged.
- Selector keeps `max_price_age_seconds` hard rejection.

3. Ignition Score (new emphasis)
- Existing: regime, momentum, volume, adx
- Added components:
  - `breakout`: distance vs `prev_high_20`
  - `compression`: Bollinger bandwidth squeeze score
  - `ema_alignment`: EMA5/EMA20 acceleration proxy
  - `mfi`: money-flow bias
  - `volume_burst`: relative burst vs `volume_burst_ratio`

4. Transition Events (new)
- `NEW_CANDIDATE`: symbol newly entered selected set.
- `SCORE_JUMP`: score increase over `score_jump_threshold`.
- `INVALIDATED`: symbol dropped from selected set.
- `ENTRY_READY`: selected symbol score >= `entry_ready_score`.

## Current Default Parameters (allocation)
- `volume_burst_ratio`: `1.15`
- `compression_bbw_threshold`: `0.11`
- `score_jump_threshold`: `0.22`
- `entry_ready_score`: `0.35`
- `max_signal_events`: `8`
- weights:
  - `regime 0.12`
  - `momentum 0.38`
  - `volume 0.10`
  - `adx 0.05`
  - `breakout 0.15`
  - `compression 0.08`
  - `ema_alignment 0.07`
  - `mfi 0.03`
  - `volume_burst 0.12`

## Telemetry / Runtime Keys
- `strategy:selector:latest:<strategy>` hash
  - new field: `signal_events` (json array)
- `strategy:selector:events` stream
  - new field: `signal_events`
  - `top_scores` now includes `ignition`, `breakout_ratio`, `volume_ratio`, `compression`

## Alerting Policy
- Keep existing DQ/churn anomaly logic.
- Add transition-based trigger:
  - notify on `entry_ready` (new signature only)
  - notify on `new_candidate` (new signature only)
- Prevent spam by snapshot signature comparison + cooldown.

## Dashboard Monitor
- Selector cards now show:
  - `score` + `ignition`
  - recent `signal_events`
- Selector event timeline includes signal event summary.

## Validation Checklist
1. Unit tests
- `tests/trading/strategies/components/test_symbol_selector.py`
- `tests/trading/notification/test_telegram_task_selector.py`

2. Runtime sanity
- Confirm Redis updates every refresh:
  - `HGET strategy:selector:latest:mlp_direction_bnb signal_events`
  - `XREVRANGE strategy:selector:events + - COUNT 5`

3. Dashboard
- `/btc-dashboard` -> Selector Monitor shows ignition and event chips.

## Tuning Order (if too noisy or too conservative)
1. `entry_ready_score` (higher = stricter)
2. `score_jump_threshold` (higher = fewer jump alerts)
3. `breakout` and `volume_burst` weights
4. `compression_bbw_threshold`
