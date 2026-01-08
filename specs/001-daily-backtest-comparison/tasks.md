# Tasks: Daily Backtest Comparison Report

**Input**: Design documents from `/specs/001-daily-backtest-comparison/`
**Prerequisites**: plan.md ✅, spec.md ✅, research.md ✅, data-model.md ✅, contracts/ ✅

**Tests**: Not explicitly requested in spec. Test tasks omitted.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

- **Single project**: Extends existing structure at repository root
- New files: `trading/risk/`, `scripts/`, `tests/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and data class definitions

- [x] T001 Create data classes module with enums and dataclasses in trading/risk/comparison_models.py
- [x] T002 Create custom exception classes in trading/risk/comparison_exceptions.py
- [x] T003 Create database migration script for comparison_reports table in scripts/migrations/001_comparison_reports.py

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that MUST be complete before ANY user story can be implemented

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [x] T004 Implement TradeComparer class with timestamp matching algorithm in trading/risk/trade_comparer.py
- [x] T005 Implement severity calculation logic in TradeComparer.calculate_severity() in trading/risk/trade_comparer.py
- [x] T006 Add method to read actual trades for date range from TradeLogger in trading/risk/trade_logger.py
- [x] T007 Run database migration to create comparison_reports table

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - View Daily Comparison Report (Priority: P1) 🎯 MVP

**Goal**: Generate comparison reports at midnight comparing actual trades with backtest results

**Independent Test**: Trigger report generation for a past day with known trades and verify comparison output matches expected values

### Implementation for User Story 1

- [x] T008 [P] [US1] Implement ComparisonReportGenerator.__init__() in trading/risk/comparison_report.py
- [x] T009 [P] [US1] Implement helper method to run single-day backtest using existing Backtester in trading/risk/comparison_report.py
- [x] T010 [US1] Implement ComparisonReportGenerator.generate_report() for single strategy in trading/risk/comparison_report.py
- [x] T011 [US1] Implement ComparisonReportGenerator.generate_all_reports() for all active strategies in trading/risk/comparison_report.py
- [x] T012 [US1] Implement metrics calculation (trades count, win rate, P/L, max drawdown) in trading/risk/comparison_report.py
- [x] T013 [US1] Implement ComparisonReportGenerator.save_report() with database persistence in trading/risk/comparison_report.py
- [x] T014 [US1] Create CLI entry point script with argparse in scripts/daily_comparison.py
- [x] T015 [US1] Implement run_with_retry() wrapper function in scripts/daily_comparison.py
- [x] T016 [US1] Add logging for report generation process in trading/risk/comparison_report.py

**Checkpoint**: User Story 1 complete - reports can be generated and saved via CLI

---

## Phase 4: User Story 2 - Receive Report via Telegram (Priority: P2)

**Goal**: Deliver formatted comparison report summaries via Telegram notification

**Independent Test**: Generate a sample report and verify it arrives in Telegram with proper formatting and severity indicators

### Implementation for User Story 2

- [x] T017 [P] [US2] Create ReportNotifier class with TelegramNotifier integration in trading/risk/report_notifier.py
- [x] T018 [US2] Implement ReportNotifier.format_report_message() with Markdown formatting in trading/risk/report_notifier.py
- [x] T019 [US2] Implement ReportNotifier.send_report() with severity emoji indicators in trading/risk/report_notifier.py
- [x] T020 [US2] Implement ReportNotifier.send_failure_notification() for error alerts in trading/risk/report_notifier.py
- [x] T021 [US2] Integrate ReportNotifier into daily_comparison.py main flow in scripts/daily_comparison.py
- [x] T022 [US2] Add warning indicator logic for >5% return difference in trading/risk/report_notifier.py

**Checkpoint**: User Story 2 complete - reports are generated AND sent via Telegram

---

## Phase 5: User Story 3 - Historical Report Access (Priority: P3)

**Goal**: Enable retrieval of past comparison reports for trend analysis

**Independent Test**: Generate reports for multiple days, then query and retrieve specific past reports

### Implementation for User Story 3

- [x] T023 [P] [US3] Implement ComparisonReportGenerator.get_report() for single report retrieval in trading/risk/comparison_report.py
- [x] T024 [P] [US3] Implement ComparisonReportGenerator.get_reports_in_range() for date range queries in trading/risk/comparison_report.py
- [x] T025 [US3] Add --history flag to CLI for retrieving past reports in scripts/daily_comparison.py
- [x] T026 [US3] Add JSON deserialization for stored report_json field in trading/risk/comparison_report.py

**Checkpoint**: User Story 3 complete - historical reports can be queried via CLI

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [x] T027 [P] Add cron setup instructions to docs/ or quickstart.md
- [x] T028 [P] Add __init__.py exports for new modules in trading/risk/__init__.py
- [x] T029 Validate all edge cases from spec (missing data, offline periods, carried positions)
- [x] T030 Run quickstart.md validation scenarios end-to-end

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phase 3+)**: All depend on Foundational phase completion
  - US1 must complete before US2 (Telegram needs reports to send)
  - US3 can run in parallel with US2 (both extend US1 independently)
- **Polish (Final Phase)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No dependencies on other stories
- **User Story 2 (P2)**: Depends on US1 (needs reports to format and send)
- **User Story 3 (P3)**: Depends on US1 (needs save_report() to query), can run parallel with US2

### Within Each User Story

- Models/data classes before services
- Services before CLI integration
- Core implementation before error handling

### Parallel Opportunities

- **Phase 1**: T001, T002, T003 can all run in parallel (different files)
- **Phase 3**: T008, T009 can run in parallel
- **Phase 4**: T017 can start while US1 completes
- **Phase 5**: T023, T024 can run in parallel
- **Phase 6**: T027, T028 can run in parallel

---

## Parallel Example: User Story 1

```bash
# Launch parallelizable US1 tasks together:
Task: "T008 [P] [US1] Implement ComparisonReportGenerator.__init__()"
Task: "T009 [P] [US1] Implement helper method to run single-day backtest"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T003)
2. Complete Phase 2: Foundational (T004-T007)
3. Complete Phase 3: User Story 1 (T008-T016)
4. **STOP and VALIDATE**: Run `python scripts/daily_comparison.py --dry-run` for yesterday
5. Verify report content matches expected format

### Incremental Delivery

1. Complete Setup + Foundational → Foundation ready
2. Add User Story 1 → Test with `--dry-run` → Save to database (MVP!)
3. Add User Story 2 → Test Telegram delivery → Reports auto-notify
4. Add User Story 3 → Test `--history` flag → Full feature complete
5. Each story adds value without breaking previous stories

### Cron Deployment

After all stories complete:
```cron
5 0 * * * cd /path/to/bitcoin-trading-bot && .venv/bin/python scripts/daily_comparison.py >> logs/comparison.log 2>&1
```

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
- US2 depends on US1 because it formats/sends reports (can't send nothing)
- US3 can run parallel with US2 since both just add capabilities to stored reports
