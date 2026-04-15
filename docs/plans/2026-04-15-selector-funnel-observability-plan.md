# Selector Funnel Observability Plan

Date: 2026-04-15
Goal: make the selector's "rising potential" signal traceable through the actual entry pipeline so we can tell whether failures come from selector quality, data quality, entry logic, or order construction.

## Problem Summary

Current selector monitoring mixes three different concerns into one report:

1. selector snapshot churn
2. data freshness / liquidity pressure
3. actual trading entry conversion

This makes investigation noisy.

Observed issues:

- `strategy:selector:events` is emitted every refresh, not only on meaningful selector changes.
- selector output is consumed by strategies mostly as a binary gate (`is_symbol_allowed`) rather than as a scored hint.
- `NEW_CANDIDATE` and `ENTRY_READY` are selector state events, not order-intent events.
- `dq_blocked_ratio` is a universe-level health metric, not a selector-candidate metric.
- current conversion logic can overcount because multiple selector events may map to one executed BUY.
- `observability.emit_events` is disabled, so post-selector bottlenecks are not visible by stage.

## Design Targets

1. Separate selector-quality metrics from entry-funnel metrics.
2. Preserve the selector as a lightweight top-N gate.
3. Add stage-by-stage attribution after selector approval.
4. Avoid changing live behavior in phase 1; improve observability first.
5. Make the dashboard and reports answer one question directly:
   "Where did the candidate die?"

## Proposed Funnel Model

Treat selector and entry as a staged funnel.

### Stage 0: Universe Snapshot

- Universe size
- Symbols with usable market data
- Symbols blocked by DQ
- Selected top-N symbols

Purpose:
- answer whether the feed is healthy enough for selector interpretation

### Stage 1: Selector Candidate Events

- `NEW_CANDIDATE`
- `ENTRY_READY`
- `SCORE_JUMP`
- `INVALIDATED`

Purpose:
- answer whether the selector is surfacing promising names

### Stage 2: Entry Gate Outcomes

Per evaluated symbol, record:

- `passed_data_quality`
- `passed_selector_gate`
- `passed_regime_cash_guard`
- `passed_loss_pause`
- `passed_cooldown`
- `passed_bull_prob`

Purpose:
- isolate hard gate failures before entry strategy logic

### Stage 3: Entry Strategy Outcomes

Per evaluated symbol, record:

- `entry_strategy_route`: `mlp`, `regime`, `regime_fallback`, `mlp_fallback`
- `entry_strategy_result`: `signal` or `no_signal`
- `entry_rejection_category`: `unavailable`, `non_buy`, `low_confidence`, `filter_block`
- `entry_rejection_reason`

Purpose:
- distinguish selector miss from MLP / fallback policy miss

### Stage 4: Order Build Outcomes

Per symbol with an entry signal, record:

- `order_build_result`: `built` or `dropped`
- `drop_reason`: `risk_cap`, `vol_sizing_zero`, `portfolio_risk_zero`, `dq_scale_zero`, `lot_size_round_zero`
- `data_quality_tier`
- `position_scale`
- `resolved_quantity`

Purpose:
- explain `DECISION=BUY` but `SIGNAL/ENTRY=0`

### Stage 5: Published / Filled Outcomes

- `order_published`
- `entry_filled`
- `entry_rejected`
- executor rejection reason

Purpose:
- close the loop from selector to actual trade

## Concrete Improvements

### 1. Split selector snapshot metrics from funnel conversion metrics

Keep current selector report, but narrow its meaning.

Rename or reinterpret:

- `selector_events_per_day` -> snapshot cadence / churn metric
- `avg_dq_blocked_ratio` -> universe DQ health metric
- `stale_reject_ratio` -> selector scoring freshness rejection mix

Add a second report for actual funnel conversion:

- `ENTRY_READY -> passed_dq`
- `ENTRY_READY -> passed_entry_strategy`
- `ENTRY_READY -> built_order`
- `ENTRY_READY -> published_order`
- `ENTRY_READY -> filled_buy`
- same chain for `NEW_CANDIDATE`

Why:
- avoids pretending selector events are the same as trade signals

### 2. Add a dedicated entry-funnel event stream

Add a new Redis stream:

- `strategy:entry:funnel`

Each event should include:

- timestamp
- strategy
- symbol
- regime
- selector_selected
- selector_score if available
- selector_signal_type if available
- dq_allowed
- dq_reason
- entry_route
- entry_signal_generated
- entry_rejection_category
- entry_rejection_reason
- order_build_result
- order_drop_reason
- order_published

Why:
- one stream should answer the full attribution question without stitching multiple partial streams

### 3. Pass selector context into the entry decision path

Current behavior:
- strategy only checks `is_symbol_allowed(symbol)`

Improve by retaining selector metadata for the current symbol:

- last selector score
- last selector rank
- last selector event type for symbol
- last selector reason / regime
- selector eligible streak
- entry_ready streak

Do not use these values to alter trading behavior in phase 1.
Use them only for observability and attribution.

Why:
- preserves the selector's actual rationale for downstream analysis

### 4. Categorize gate failures explicitly

Current gate reasons are string-based and partially spread across:

- `_last_entry_gate_reason`
- entry strategy rejection strings
- order build early returns

Standardize to enums / normalized reason codes:

- `dq_stale_price`
- `dq_low_tick_rate`
- `selector_not_selected`
- `cash_in_bear`
- `ema200_cash_guard`
- `loss_pause`
- `cooldown`
- `bull_prob_gate`
- `mlp_unavailable`
- `mlp_non_buy`
- `mlp_low_confidence`
- `mlp_filter_block`
- `risk_cap_block`
- `vol_sizing_zero`
- `portfolio_risk_zero`
- `lot_size_round_zero`

Why:
- string parsing is fragile and makes reporting ambiguous

### 5. Make selector cadence metrics honest

Current KPI target `8~250/day` does not fit `refresh_seconds=60`.

Replace with two metrics:

- `snapshot_count_per_day`
- `changed_snapshot_count_per_day`

And optionally:

- `meaningful_selector_event_count_per_day`
  Definition: selector snapshots with `changed=true` or non-empty `signal_events`

Why:
- separates scheduler cadence from actual candidate discovery

### 6. Prevent overcounted conversion in reports

Current matching lets multiple selector events claim the same BUY.

Update report logic so each BUY fill is consumed at most once per symbol.

Recommended rule:

- sort selector events chronologically
- sort BUY trades chronologically
- assign each BUY trade to the nearest eligible prior selector event within window
- once matched, do not reuse the BUY trade

Why:
- conversion should represent unique downstream realization, not repeated pre-trade chatter

### 7. Expose funnel metrics to dashboard / API

Add API support for:

- recent funnel events
- aggregated rejection counts by stage
- selector-to-fill conversion breakdown
- DQ blocked top symbols during the same window

Why:
- avoid depending only on markdown reports during soak monitoring

## Implementation Plan

### Phase 1: Observability Only

Behavior change:
- none

Files:

- [trading/core/event_emitter.py](/home/deploy/project/bitcoin-trading-bot/trading/core/event_emitter.py)
- [trading/strategies/components/composite_task.py](/home/deploy/project/bitcoin-trading-bot/trading/strategies/components/composite_task.py)
- [trading/streams/redis_streams.py](/home/deploy/project/bitcoin-trading-bot/trading/streams/redis_streams.py)
- [web/services/metrics_service.py](/home/deploy/project/bitcoin-trading-bot/web/services/metrics_service.py)

Work:

1. Add `EntryFunnelEvent` dataclass and `strategy:entry:funnel` stream emitter.
2. Emit one funnel event per entry evaluation with normalized stage fields.
3. Attach selector metadata to the funnel event for the symbol under evaluation.
4. Emit `order_build_result` and `order_drop_reason` before any early `return None`.
5. Add metrics service methods to read recent funnel events and aggregate counts.

Acceptance:

- can answer, for the last 24h, how many symbols died at each stage
- no change to order behavior

### Phase 2: Report Split

Behavior change:
- none

Files:

- [scripts/paper/selector_signal_monitor_7d.py](/home/deploy/project/bitcoin-trading-bot/scripts/paper/selector_signal_monitor_7d.py)
- new script: `scripts/paper/entry_funnel_monitor.py`
- [scripts/paper/run_daily_selector_monitor_and_notify.sh](/home/deploy/project/bitcoin-trading-bot/scripts/paper/run_daily_selector_monitor_and_notify.sh)

Work:

1. Keep existing selector report, but rename metrics in markdown and JSON to reflect snapshot semantics.
2. Add a new funnel report:
   - selector event counts
   - stage pass/fail counts
   - unique conversion chain
   - top rejection reasons
3. Ensure trade matching is one-trade-to-one-selector-event.
4. Update daily cron wrapper to generate both reports.

Acceptance:

- operator can distinguish "selector noisy" from "selector good but DQ bad" from "selector and DQ good but MLP rejected"

### Phase 3: Dashboard Integration

Behavior change:
- none

Files:

- [web/services/metrics_service.py](/home/deploy/project/bitcoin-trading-bot/web/services/metrics_service.py)
- [web/app.py](/home/deploy/project/bitcoin-trading-bot/web/app.py)
- [web/static/js/dashboard.js](/home/deploy/project/bitcoin-trading-bot/web/static/js/dashboard.js)
- relevant dashboard template files

Work:

1. Add a funnel panel:
   - universe
   - dq blocked
   - selected
   - signal generated
   - order built
   - published
   - filled
2. Add top rejection reasons table.
3. Add per-symbol drilldown showing selector score + rejection reason chain.

Acceptance:

- same investigation can be done without manually opening logs and CSVs

### Phase 4: Optional Strategy Refinement

Behavior change:
- possible

Only after phase 1-3 confirm the dominant bottleneck.

Candidate actions:

1. shrink the universe for symbols with chronic stale / low-tick behavior
2. raise selector persistence further if churn remains dominant
3. allow selector score to influence downstream priority or sizing
4. revise fallback policy if selector quality is good but MLP blocks too often

## Recommended Order

1. Phase 1
2. Run 24-72h paper soak
3. Phase 2
4. If operationally useful, Phase 3
5. Only then consider Phase 4 strategy behavior changes

## Risks

- If we change strategy behavior before adding attribution, we will not know which bottleneck was real.
- If we keep relying on selector snapshot conversion only, we will continue to misdiagnose feed issues as signal-quality issues.
- If selector metadata is not attached to downstream funnel events, postmortems will remain log-heavy and slow.

## Success Criteria

The new observability should let us answer these quickly:

1. Did the selector nominate the symbol?
2. Was the symbol blocked by DQ?
3. Did the entry strategy generate a BUY?
4. If not, was it non-BUY, low-confidence, or filter-blocked?
5. If BUY existed, why was no order built?
6. If order was built, was it published and filled?

When those six questions are answerable from one report or one dashboard view, this plan is complete.
