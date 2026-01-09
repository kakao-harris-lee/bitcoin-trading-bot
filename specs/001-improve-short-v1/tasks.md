# Tasks: Improve Short V1 Strategy

**Input**: Design documents from `/specs/001-improve-short-v1/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Tests**: Tests not explicitly requested. Backtest validation included as part of implementation.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Strategy**: `trading/strategy/short_v1.py`
- **Config**: `config/strategies/short_v1.json`
- **Tests**: `tests/trading/test_short_v1_improved.py`
- **Indicators**: `trading/indicators/technical.py` (existing, read-only)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Configuration updates and shared position state enhancements

- [x] T001 Update config/strategies/short_v1.json with new entry parameters (adx_slope_bars, require_adx_not_declining)
- [x] T002 [P] Update config/strategies/short_v1.json with new exit parameters (two_tier_enabled, first_tier_pct, trailing_stop_atr_multiplier)
- [x] T003 [P] Update config/strategies/short_v1.json with new stop_loss parameters (atr_buffer_multiplier, atr_period)
- [x] T004 [P] Update config/strategies/short_v1.json with new risk_management parameters (extreme_volatility_threshold, halt_entries_on_extreme_vol)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core enhancements to position state tracking that all user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T005 Add position_tier enum (FULL, HALF, CLOSED) to trading/strategy/short_v1.py
- [x] T006 Add two-tier position state fields (first_tp_hit, trailing_stop_active, trailing_stop_price, lowest_since_1r) to trading/strategy/short_v1.py
- [x] T007 Add ATR indicator calculation to add_indicators() method in trading/strategy/short_v1.py
- [x] T008 Add ADX slope detection (adx_prev, adx_declining) to add_indicators() method in trading/strategy/short_v1.py
- [x] T009 Update clear_position() method to reset all new state fields in trading/strategy/short_v1.py

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - Enhanced Bear Market Entry (Priority: P1) 🎯 MVP

**Goal**: Improve entry signal quality with ADX trend direction filter and multi-indicator confirmation

**Independent Test**: Run backtest on BEAR_STRONG regime periods, verify entries only occur when ADX not declining, confidence >= 0.7

### Implementation for User Story 1

- [x] T010 [US1] Add _check_extreme_volatility() method to detect >10% daily moves in trading/strategy/short_v1.py
- [x] T011 [US1] Update _check_entry() to skip entry when ADX is declining (FR-011) in trading/strategy/short_v1.py
- [x] T012 [US1] Update _check_entry() to skip entry during extreme volatility (FR-013) in trading/strategy/short_v1.py
- [x] T013 [US1] Update _check_entry() to require confidence >= 0.7 for entry signal in trading/strategy/short_v1.py
- [x] T014 [US1] Add adx_prev and adx_declining to entry signal metadata in trading/strategy/short_v1.py
- [x] T015 [US1] Run backtest to validate entry improvements: `python scripts/backtest.py --strategy short_v1 --start 2020-01-01 --end 2024-12-31`

**Checkpoint**: User Story 1 complete - enhanced entries filtering weak signals

---

## Phase 4: User Story 2 - Improved Stop Loss Management (Priority: P2)

**Goal**: ATR-based volatility-adjusted stop loss with 5% cap

**Independent Test**: Run backtest comparing stop loss hit rate before/after changes, verify fewer premature exits

### Implementation for User Story 2

- [x] T016 [US2] Add _calculate_stop_loss() method with ATR buffer formula in trading/strategy/short_v1.py
- [x] T017 [US2] Update _calculate_position_levels() to use new ATR-based stop loss calculation in trading/strategy/short_v1.py
- [x] T018 [US2] Ensure stop loss respects max_stop_loss_pct (5%) cap from config in trading/strategy/short_v1.py
- [x] T019 [US2] Add _check_gap_exit() method for gap opening handling (FR-012) in trading/strategy/short_v1.py
- [x] T020 [US2] Update _check_exit() to check for gap past stop loss first in trading/strategy/short_v1.py
- [x] T021 [US2] Add atr_value and atr_buffer to entry signal metadata in trading/strategy/short_v1.py
- [x] T022 [US2] Run backtest to validate stop loss improvements: compare SC-007 (10% reduction in stop loss hits)

**Checkpoint**: User Story 2 complete - volatility-adjusted stop losses active

---

## Phase 5: User Story 3 - Better Take Profit Strategy (Priority: P3)

**Goal**: Two-tier profit taking (50% at 1R, trailing stop for remaining 50%)

**Independent Test**: Run backtest verifying partial exits occur, trailing stop activates after 1R, R:R >= 2.0

### Implementation for User Story 3

- [x] T023 [US3] Add _check_first_tier_exit() method for 50% exit at 1R target in trading/strategy/short_v1.py
- [x] T024 [US3] Add _update_trailing_stop() method for ATR-based trailing stop in trading/strategy/short_v1.py
- [x] T025 [US3] Add _check_trailing_stop_exit() method for remaining 50% exit in trading/strategy/short_v1.py
- [x] T026 [US3] Update _check_exit() to handle two-tier exits with position_tier state in trading/strategy/short_v1.py
- [x] T027 [US3] Add exit_type field to exit signals (TAKE_PROFIT_1R, TRAILING_STOP, TAKE_PROFIT_2R) in trading/strategy/short_v1.py
- [x] T028 [US3] Update generate_signal() to return partial_close action with fraction=0.5 for first tier in trading/strategy/short_v1.py
- [x] T029 [US3] Run backtest to validate take profit improvements: verify SC-005 (R:R >= 2.0)

**Checkpoint**: User Story 3 complete - two-tier profit taking active

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation, documentation, and cleanup

- [x] T030 Run full backtest suite: training (2020-2024) and validation (2025+) periods
- [ ] T031 Verify SC-001: OOS return improvement >= 5pp over baseline (2025 had limited BEAR regime trades)
- [ ] T032 Verify SC-002: Sharpe ratio >= 1.5 on validation period (insufficient trades for measurement)
- [x] T033 Verify SC-003: Maximum drawdown <= 20% (MDD=-4.12% training, -3.02% validation)
- [x] T034 Verify SC-004: Win rate >= 45% (46.7% on training period)
- [x] T035 Verify SC-006: At least 10 trades in BEAR regime (15 trades on training)
- [x] T036 [P] Update specs/001-improve-short-v1/quickstart.md with final configuration values
- [x] T037 Run paper trading test to confirm signal generation in live environment
- [ ] T038 Create PR for review: `gh pr create --title "feat: improve Short V1 strategy for bear markets"`

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup (Phase 1) completion - BLOCKS all user stories
- **User Story 1 (Phase 3)**: Depends on Foundational (Phase 2) completion
- **User Story 2 (Phase 4)**: Depends on Foundational (Phase 2) completion - can run parallel to US1
- **User Story 3 (Phase 5)**: Depends on Foundational (Phase 2) completion - can run parallel to US1/US2
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Independent - entry logic only
- **User Story 2 (P2)**: Independent - stop loss logic only (can run parallel to US1)
- **User Story 3 (P3)**: Depends on US2 stop loss calculation for R-multiple targets

### Within Each User Story

- Config changes before code changes
- Method additions before method updates
- Core logic before metadata/logging
- Backtest validation at end of each story

### Parallel Opportunities

- T002, T003, T004 can run in parallel (different config sections)
- US1 and US2 can run in parallel (different code paths: entry vs exit)
- T036 can run in parallel with final validation tasks

---

## Parallel Example: Setup Phase

```bash
# Launch config updates in parallel:
Task: "Update config/strategies/short_v1.json with new entry parameters"
Task: "Update config/strategies/short_v1.json with new exit parameters"
Task: "Update config/strategies/short_v1.json with new stop_loss parameters"
Task: "Update config/strategies/short_v1.json with new risk_management parameters"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (config updates)
2. Complete Phase 2: Foundational (position state)
3. Complete Phase 3: User Story 1 (enhanced entries)
4. **STOP and VALIDATE**: Backtest entry improvements
5. Deploy to paper trading if metrics pass

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. Add User Story 1 → Backtest → Paper trading (MVP!)
3. Add User Story 2 → Backtest → Paper trading (better stops)
4. Add User Story 3 → Backtest → Paper trading (profit capture)
5. Final validation → Live trading

### Single Developer Strategy

1. Complete all phases sequentially
2. Validate at each checkpoint before proceeding
3. Commit after each completed phase

---

## Notes

- All tasks modify single file: `trading/strategy/short_v1.py` (except config)
- Backtest validation tasks verify success criteria from spec.md
- Constitution compliance: 3 indicators (EMA, ADX, ATR), 2x leverage, 5% max SL
- Gap exit handling is critical for risk management (FR-012)
- Trailing stop only tightens, never widens
