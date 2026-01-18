# Tasks: Backtest MLflow Visualization

**Input**: Design documents from `/specs/001-backtest-mlflow-viz/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: Not explicitly requested in spec. Test tasks omitted for brevity.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3, US4)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: `core/`, `tests/` at repository root (per plan.md)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and configuration

- [ ] T001 Add mlflow dependency to requirements.txt
- [ ] T002 [P] Create MLflow configuration file at config/mlflow.json with schema from data-model.md
- [ ] T003 [P] Create VisualizationConfig dataclass in core/backtest_config.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T004 Create BacktestResult dataclass in core/backtest_result.py with all fields from data-model.md
- [ ] T005 Implement calculate_benchmark() function in core/metrics.py (buy-and-hold calculation from research.md)
- [ ] T006 [P] Implement calculate_sharpe_ratio() function in core/metrics.py (annualized, per research.md)
- [ ] T007 [P] Implement calculate_max_drawdown() function in core/metrics.py
- [ ] T008 Modify Backtester._generate_results() in core/backtester.py to return BacktestResult with benchmark_curve and enhanced metrics
- [ ] T009 Update Backtester.run_strategy() in core/backtester.py to calculate and populate benchmark data

**Checkpoint**: Foundation ready - user story implementation can now begin in parallel

---

## Phase 3: User Story 1 - Benchmark Visualization (Priority: P1) 🎯 MVP

**Goal**: Generate dual-axis chart showing strategy equity vs benchmark price

**Independent Test**: Run a single backtest and verify output includes dual-axis chart with strategy equity (left y-axis) and benchmark price (right y-axis)

### Implementation for User Story 1

- [ ] T010 [US1] Create BacktestVisualizer class in core/backtest_visualizer.py with __init__ accepting VisualizationConfig
- [ ] T011 [US1] Implement BacktestVisualizer.create_chart() using matplotlib twinx() pattern from research.md
- [ ] T012 [US1] Add chart styling: grid, legend, axis labels, colors per VisualizationConfig
- [ ] T013 [US1] Handle edge case: no trades (flat strategy line, moving benchmark)
- [ ] T014 [US1] Handle edge case: missing benchmark data (strategy-only chart with warning)
- [ ] T015 [US1] Implement BacktestVisualizer.create_comparison_chart() for comparing multiple results

**Checkpoint**: At this point, User Story 1 should be fully functional - run backtest and generate chart

---

## Phase 4: User Story 2 - MLflow Recording (Priority: P2)

**Goal**: Automatically log backtest runs to MLflow with parameters, metrics, and chart artifacts

**Independent Test**: Run backtest and verify MLflow UI shows run with correct parameters, metrics, and chart artifact

**Dependency**: US1 (charts to log as artifacts)

### Implementation for User Story 2

- [ ] T016 [US2] Create MLflowConfig dataclass in core/mlflow_config.py with from_dict() and from_env() methods
- [ ] T017 [US2] Create MLflowTracker class in core/mlflow_tracker.py with __init__ accepting MLflowConfig
- [ ] T018 [US2] Implement MLflowTracker.enabled property checking config and mlflow availability
- [ ] T019 [US2] Implement MLflowTracker.log_run() to log parameters (strategy_name, symbol, all config params)
- [ ] T020 [US2] Add metrics logging to log_run(): total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate, total_trades, profit_factor, benchmark_return_pct
- [ ] T021 [US2] Add artifact logging to log_run(): chart PNG file
- [ ] T022 [US2] Implement graceful degradation per research.md (try-except, log warnings, return None)
- [ ] T023 [US2] Implement MLflowTracker.get_experiment_url() to return MLflow UI link
- [ ] T024 [US2] Add mlflow_config parameter to Backtester.run_strategy() signature (backward compatible, defaults to None)
- [ ] T025 [US2] Integrate MLflowTracker into Backtester.run_strategy() - auto-log when mlflow_config provided

**Checkpoint**: At this point, User Stories 1 AND 2 should both work - backtest generates chart AND logs to MLflow

---

## Phase 5: User Story 3 - Compare Multiple Runs (Priority: P3)

**Goal**: Enable comparison of multiple backtest runs in MLflow UI with filtering and sorting

**Independent Test**: Run 3+ backtests, open MLflow UI, verify runs are filterable and comparable side-by-side

**Dependency**: US2 (runs must be logged to MLflow)

### Implementation for User Story 3

- [ ] T026 [US3] Add consistent tagging to MLflowTracker.log_run(): strategy_name, symbol as tags for filtering
- [ ] T027 [US3] Add run naming convention: "{strategy_name}_{symbol}_{timestamp}" for easy identification
- [ ] T028 [US3] Document MLflow UI comparison workflow in quickstart.md

**Checkpoint**: At this point, User Stories 1, 2, AND 3 should work - multiple runs are logged and comparable

---

## Phase 6: User Story 4 - Parameter Sweep (Priority: P4)

**Goal**: Run parameter grid search with automatic MLflow logging per combination

**Independent Test**: Define sweep config (2 params x 3 values = 9 combos), run sweep, verify 9 MLflow runs created

**Dependency**: US2 (MLflow logging)

### Implementation for User Story 4

- [ ] T029 [US4] Create ParameterSweep dataclass in core/parameter_sweep.py with fields from data-model.md
- [ ] T030 [US4] Implement ParameterSweep.generate_combinations() using itertools.product
- [ ] T031 [US4] Implement ParameterSweep.total_combinations property
- [ ] T032 [US4] Create ParameterSweepRunner class in core/parameter_sweep.py
- [ ] T033 [US4] Implement ParameterSweepRunner.__init__() accepting Backtester, MLflowTracker, BacktestVisualizer
- [ ] T034 [US4] Implement ParameterSweepRunner.run() to iterate combinations, run backtests, log to MLflow
- [ ] T035 [US4] Add progress_callback support to ParameterSweepRunner.run()
- [ ] T036 [US4] Implement ParameterSweepRunner.get_best_result() to find best by specified metric
- [ ] T037 [US4] Implement MLflowTracker.log_sweep() to tag all runs with sweep_id for grouping
- [ ] T038 [US4] Handle edge case: MLflow unavailable during sweep (continue without logging)

**Checkpoint**: All user stories should now be independently functional

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T039 [P] Update quickstart.md with complete examples for all user stories
- [ ] T040 [P] Add type hints to all new modules
- [ ] T041 Code cleanup: ensure all modules follow existing project style
- [ ] T042 [P] Performance validation: verify chart renders < 2 seconds for 500 trades (SC-001)
- [ ] T043 [P] Performance validation: verify MLflow logging < 5 seconds per run (SC-002)
- [ ] T044 Run quickstart.md validation end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup (T001) - BLOCKS all user stories
- **User Stories (Phase 3-6)**: All depend on Foundational phase completion
  - US1 (Phase 3): Can start after Foundational
  - US2 (Phase 4): Can start after Foundational, integrates with US1
  - US3 (Phase 5): Depends on US2
  - US4 (Phase 6): Depends on US2
- **Polish (Phase 7)**: Depends on all desired user stories being complete

### User Story Dependencies

```
Foundational (Phase 2)
         │
         ▼
    ┌────┴────┐
    │         │
    ▼         │
   US1 ───────┤
 (P1 MVP)     │
    │         │
    ▼         │
   US2 ◄──────┘
  (P2)
    │
    ├─────────┐
    │         │
    ▼         ▼
   US3       US4
  (P3)      (P4)
```

### Parallel Opportunities

**Phase 1 (Setup)**:
- T002, T003 can run in parallel

**Phase 2 (Foundational)**:
- T006, T007 can run in parallel (independent metric calculations)

**Phase 3 (US1)**:
- After T011, tasks T012-T015 can be developed incrementally

**Phase 4 (US2)**:
- T016-T023 are sequential (building MLflowTracker class)
- T024-T025 depend on MLflowTracker being complete

**Phase 6 (US4)**:
- T029-T031 (ParameterSweep dataclass) can run parallel to T032-T036 (runner)

**Phase 7 (Polish)**:
- T039, T040, T042, T043 can all run in parallel

---

## Parallel Example: Phase 2 Foundational

```bash
# Sequential dependency chain:
T004 (BacktestResult)
  → T005 (benchmark calc)
    → T008 (integrate into backtester)
      → T009 (run_strategy changes)

# These can run in parallel after T004:
Task: "T006 Implement calculate_sharpe_ratio() in core/metrics.py"
Task: "T007 Implement calculate_max_drawdown() in core/metrics.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup
2. Complete Phase 2: Foundational (CRITICAL - blocks all stories)
3. Complete Phase 3: User Story 1 (Visualization)
4. **STOP and VALIDATE**: Run backtest, verify dual-axis chart generated
5. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 (Visualization) → Test → **MVP Complete!**
3. Add User Story 2 (MLflow) → Test → Runs now tracked
4. Add User Story 3 (Compare) → Test → Comparison enabled
5. Add User Story 4 (Sweep) → Test → Full feature complete

### Single Developer Strategy

Work in priority order:
1. Setup → Foundational → US1 → Validate MVP
2. US2 → Validate logging works
3. US3 → Quick phase (mostly tagging)
4. US4 → Final functionality
5. Polish → Performance validation

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- FR-007 (graceful degradation) handled in T022, T038
- Constitution compliance: Sharpe ratio and max drawdown calculations in T006-T007
