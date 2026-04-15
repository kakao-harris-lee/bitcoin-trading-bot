# Stream Re-Alignment (Phase 1-3)

**Date**: 2026-02-23  
**Status**: Phase 1-3 Implemented (low/medium complexity scope)

## Objective

Move runtime-critical paths back toward Redis Stream-first architecture, while explicitly excluding high-difficulty event-sourcing migrations for this phase.

## Drift Analysis (Current)

| Area | Current dominant pattern | Stream drift | Complexity |
|---|---|---|---|
| Feed -> Strategy -> Orders -> Executor | Redis Streams (`market:prices`, `orders`, `trades`) | Low | Low |
| Position/Account/Risk state writes | Hash (`hset`) + partial stream use | Medium | Low |
| Regime snapshot freshness (dashboard) | `strategy:decisions` + `regime:latest` hash | Medium | Low |
| Selector latest state | Hash snapshot + event stream split | Medium | Low |
| Symbol discovery for context | `keys("positions:*:*")` scan | Medium | Low |
| Global risk/leverage internals (`risk:state:*`, `leverage:*`) | Hash state stores | High | High |
| Dashboard-wide reads (many endpoints) | Hash polling (`hgetall`, `keys`) | High | High |

## Phase 1 Changes (Implemented)

### 1) State write mirroring APIs (RedisStreams)
- File: `trading/streams/redis_streams.py`
- Added:
  - `set_account(...)` -> writes hash + emits `account:events`
  - `set_risk(...)` -> writes hash + emits `risk:events`
  - `set_position(...)`/`clear_position(...)` stream-mirrored via `positions:events`
  - `patch_position(...)` for partial updates (stream-mirrored)
  - `set_regime_snapshot(...)` -> writes `regime:latest` + emits `regime:snapshots`
  - `set_selector_snapshot(...)` -> writes `strategy:selector:latest:*` + emits `strategy:selector:snapshots`
  - `read_latest(...)` helper for stream-first readers

### 2) Executor write path stream-first
- Files:
  - `trading/executor/paper_executor.py`
  - `trading/executor/async_executor.py`
- Replaced direct `hset` writes for account/risk with stream-mirror wrappers.
- Replaced stop-loss metadata direct hash write with `patch_position(...)`.
- Added compatibility fallback (legacy/mocks): if wrapper methods are unavailable, fallback to existing `hset` path.

### 3) Strategy snapshot persistence
- File: `trading/strategies/components/composite_task.py`
- Replaced direct hash writes with:
  - `set_selector_snapshot(...)`
  - `set_regime_snapshot(...)`

### 4) Stream-first reads in dashboard status/fallback
- File: `web/app.py`
- Added stream reader for regime snapshots:
  - `_read_regime_snapshots_stream(...)` from `regime:snapshots`
- Status merge order now prefers freshest among:
  - `strategy:decisions`, `regime:latest`, `regime:snapshots`
- Selector fallback now checks stream snapshots first:
  - `strategy:selector:snapshots` -> fallback to hash keys only if needed
- Kill-switch write now emits `risk:events` alongside hash update.

### 5) Position symbol discovery optimization
- File: `trading/strategies/components/context_builder.py`
- `PositionManager._discover_symbols()` now:
  - tries `positions:events` stream first
  - falls back to `keys("positions:*:*")` only when needed

## Phase 2 Changes (Implemented)

### 6) Position discovery in dashboard: stream-first, keys fallback
- File: `web/app.py`
- `_discover_position_symbols(...)` now:
  - discovers candidates from `positions:events` first
  - verifies active quantity via `positions:{symbol}:{market}` hashes
  - falls back to `keys("positions:*:*")` only when stream discovery yields no active symbols
- Added helper:
  - `_discover_position_symbols_from_stream(...)`

### 7) Metrics position collection widened by stream discovery
- File: `web/services/metrics_service.py`
- `_collect_positions(...)` now iterates symbols from `_discover_position_symbols()`, not only static allocation symbols.
- `_discover_position_symbols()`:
  - starts from configured symbols
  - appends recent symbols seen in `positions:events`
  - preserves compatibility if stream unavailable

### 8) Stream reader hardening for test/legacy compatibility
- File: `web/app.py`
- `_load_selector_symbols_from_stream(...)` now validates Redis return type before iteration.

## Phase 3 Changes (Implemented)

### 9) Strategy live-state lookup without Redis key scan
- Files:
  - `trading/strategies/components/state_manager.py`
  - `web/app.py`
- `StateManager` now records:
  - `state:index:{strategy}:{symbol}` set membership (`sadd/srem`) for tracked variables
  - `state:events` stream events (`state_set`, `state_delete`)
- Dashboard strategy-state read path now:
  - reads freshest values from `state:events`
  - hydrates remaining variables from `state:index:*` + direct `get`
  - no longer uses `keys("state:...:*")`

### 10) Context refresh path no longer depends on key-scan discovery
- Files:
  - `trading/strategies/components/composite_task.py`
  - `trading/strategies/components/context_builder.py`
- `CompositeStrategyTask` now passes `symbols=self.symbols` to `refresh_positions(...)`.
- `PositionManager._discover_symbols()` now uses stream discovery only.

### 11) Selector and position symbol fallbacks avoid Redis `keys(...)`
- File: `web/app.py`
- Selector fallback now reads deterministic per-strategy snapshot keys from config strategy names instead of wildcard `keys`.
- Position symbol discovery now relies on `positions:events` + active position hash verification only.

## Explicitly Deferred (High Complexity)

1. Full event-sourced replacement of hash state (`risk:state:*`, `leverage:*`, account/position canonical source migration).  
2. Dashboard-wide conversion of all endpoints from hash polling to stream projections.  
3. Historical replay/projection worker for deterministic materialized views.  
4. Data migration strategy for existing operational keys and backward compatibility across all tools.

## Verification

- Command:
  - `pytest -q tests/trading/streams/test_redis_streams.py tests/trading/executor/test_async_executor.py tests/trading/executor/test_paper_executor.py tests/trading/strategies/components/test_context_builder.py tests/trading/strategies/components/test_composite_task_events.py tests/trading/strategies/components/test_composite_task_exit_quantity.py`
- Result:
  - `92 passed`

- Additional check:
  - `pytest -q tests/test_web_api.py tests/web/test_metrics_api.py tests/web/test_events_api.py`
- Result:
  - environment skipped these tests (`3 skipped`) in current runtime.
