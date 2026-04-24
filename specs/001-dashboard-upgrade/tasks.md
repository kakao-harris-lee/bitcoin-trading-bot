# Tasks: Dashboard Upgrade

> Current scope note (2026-04-24): apply this spec to the Binance spot-only runtime. Any remaining references to Upbit, futures, short_v1, or sideways_v2 are historical draft context, not current implementation guidance.


**Input**: Design documents from `/specs/001-dashboard-upgrade/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/api.yaml

**Tests**: Tests are NOT included (not explicitly requested in specification).

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2)
- Include exact file paths in descriptions

## Path Conventions

Based on plan.md structure:
- **Backend**: `web/app.py` (Flask routes)
- **Frontend**: `web/templates/dashboard.html`, `web/static/js/dashboard.js`, `web/static/css/style.css`
- **Services**: `web/services/` (new directory for analytics and backtest services)

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Tab navigation UI infrastructure that all user stories depend on

- [ ] T001 Add Chart.js CDN script tag to web/templates/dashboard.html
- [ ] T002 Add tab navigation HTML structure (Positions, History, Signals, Analytics, Backtest) to web/templates/dashboard.html
- [ ] T003 [P] Add tab button styles to web/static/css/style.css
- [ ] T004 [P] Add tab content container styles to web/static/css/style.css
- [ ] T005 Implement tab switching JavaScript logic in web/static/js/dashboard.js
- [ ] T006 Create web/services/ directory structure for backend services

**Checkpoint**: Tab navigation functional - can switch between empty tab panels

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Shared API utilities and data access patterns

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

- [ ] T007 Add trade_logger import and initialization to web/app.py
- [ ] T008 Add JSON log file reading utility function to web/app.py
- [ ] T009 [P] Add common table styles for data display to web/static/css/style.css
- [ ] T010 [P] Add loading spinner and error state styles to web/static/css/style.css
- [ ] T011 Add API fetch utility with error handling to web/static/js/dashboard.js
- [ ] T012 Add common data formatting functions (date, currency, percent) to web/static/js/dashboard.js

**Checkpoint**: Foundation ready - user story implementation can now begin

---

## Phase 3: User Story 1 - View Current Positions (Priority: P1) 🎯 MVP

**Goal**: Display consolidated positions from Upbit and Binance with unrealized P&L

**Independent Test**: Open a position on either exchange, verify it appears with symbol, quantity, entry price, current price, and P&L

### Implementation for User Story 1

- [ ] T013 [US1] Create /api/positions endpoint in web/app.py that consolidates exchange data
- [ ] T014 [US1] Add PositionsResponse schema validation to web/app.py
- [ ] T015 [US1] Add position card HTML template to Positions tab in web/templates/dashboard.html
- [ ] T016 [P] [US1] Add position card styles (grid layout, P&L colors) to web/static/css/style.css
- [ ] T017 [US1] Implement fetchPositions() function in web/static/js/dashboard.js
- [ ] T018 [US1] Implement renderPositions() function with exchange grouping in web/static/js/dashboard.js
- [ ] T019 [US1] Add portfolio summary (total value, total P&L) to Positions tab in web/templates/dashboard.html
- [ ] T020 [US1] Add empty state message for no positions in web/static/js/dashboard.js
- [ ] T021 [US1] Connect positions auto-refresh to existing 30s polling in web/static/js/dashboard.js

**Checkpoint**: Positions tab fully functional - displays live positions from both exchanges

---

## Phase 4: User Story 2 - View Trade History (Priority: P1)

**Goal**: Display paginated, filterable trade history from SQLite database

**Independent Test**: View existing trades in History tab, apply date filter, verify pagination works

### Implementation for User Story 2

- [ ] T022 [US2] Create /api/trades endpoint with pagination and filters in web/app.py
- [ ] T023 [US2] Create /api/trades/<trade_id> endpoint for trade details in web/app.py
- [ ] T024 [US2] Add trade table HTML template to History tab in web/templates/dashboard.html
- [ ] T025 [US2] Add filter controls (date range, exchange, symbol) to History tab in web/templates/dashboard.html
- [ ] T026 [P] [US2] Add trade table styles (sortable headers, row hover) to web/static/css/style.css
- [ ] T027 [P] [US2] Add filter control styles to web/static/css/style.css
- [ ] T028 [US2] Implement fetchTrades(filters) function in web/static/js/dashboard.js
- [ ] T029 [US2] Implement renderTradeTable() with sortable columns in web/static/js/dashboard.js
- [ ] T030 [US2] Implement trade row expansion for details in web/static/js/dashboard.js
- [ ] T031 [US2] Add pagination controls and navigation in web/static/js/dashboard.js
- [ ] T032 [US2] Wire filter controls to fetchTrades() in web/static/js/dashboard.js

**Checkpoint**: History tab fully functional - paginated trade list with filtering

---

## Phase 5: User Story 3 - View Trading Signals (Priority: P2)

**Goal**: Display recent trading signals with status indicators

**Independent Test**: Wait for bot to generate signals, verify they appear with timestamp, strategy, action, and reason

### Implementation for User Story 3

- [ ] T033 [US3] Create /api/signals endpoint with filtering in web/app.py (extend existing)
- [ ] T034 [US3] Add signal list HTML template to Signals tab in web/templates/dashboard.html
- [ ] T035 [P] [US3] Add signal card styles (action colors, indicator badges) to web/static/css/style.css
- [ ] T036 [US3] Implement fetchSignals() function in web/static/js/dashboard.js
- [ ] T037 [US3] Implement renderSignals() with action type styling in web/static/js/dashboard.js
- [ ] T038 [US3] Add signal detail expansion (indicators, regime) in web/static/js/dashboard.js
- [ ] T039 [US3] Connect signals to auto-refresh polling in web/static/js/dashboard.js

**Checkpoint**: Signals tab fully functional - displays recent signals with status

---

## Phase 6: User Story 4 - View Analytics Dashboard (Priority: P2)

**Goal**: Display performance metrics with equity curve chart

**Independent Test**: Select period (7d/30d/90d), verify metrics update and chart renders

### Implementation for User Story 4

- [ ] T040 [US4] Create web/services/analytics.py with calculate_metrics() function
- [ ] T041 [US4] Create /api/analytics endpoint with period parameter in web/app.py
- [ ] T042 [US4] Create /api/analytics/equity-curve endpoint in web/app.py
- [ ] T043 [US4] Add metrics cards HTML template to Analytics tab in web/templates/dashboard.html
- [ ] T044 [US4] Add period selector (7d/30d/90d/all) to Analytics tab in web/templates/dashboard.html
- [ ] T045 [US4] Add chart container for equity curve in web/templates/dashboard.html
- [ ] T046 [P] [US4] Add metrics card styles (grid layout) to web/static/css/style.css
- [ ] T047 [P] [US4] Add chart container styles to web/static/css/style.css
- [ ] T048 [US4] Implement fetchAnalytics(period) function in web/static/js/dashboard.js
- [ ] T049 [US4] Implement renderMetricsCards() function in web/static/js/dashboard.js
- [ ] T050 [US4] Implement renderEquityCurve() with Chart.js in web/static/js/dashboard.js
- [ ] T051 [US4] Wire period selector to analytics refresh in web/static/js/dashboard.js
- [ ] T052 [US4] Add strategy breakdown display in web/static/js/dashboard.js

**Checkpoint**: Analytics tab fully functional - metrics and equity curve display

---

## Phase 7: User Story 5 - Run Backtesting from Dashboard (Priority: P3)

**Goal**: Allow running backtests with strategy/date selection and results display

**Independent Test**: Select strategy and date range, run backtest, verify results display with equity curve

### Implementation for User Story 5

- [ ] T053 [US5] Create web/services/backtest_runner.py with job management
- [ ] T054 [US5] Create /api/backtest/strategies endpoint in web/app.py
- [ ] T055 [US5] Create /api/backtest/run POST endpoint in web/app.py
- [ ] T056 [US5] Create /api/backtest/status/<job_id> endpoint in web/app.py
- [ ] T057 [US5] Add backtest form HTML (strategy select, date inputs, capital) to Backtest tab in web/templates/dashboard.html
- [ ] T058 [US5] Add results display area to Backtest tab in web/templates/dashboard.html
- [ ] T059 [P] [US5] Add backtest form styles to web/static/css/style.css
- [ ] T060 [P] [US5] Add progress indicator styles to web/static/css/style.css
- [ ] T061 [P] [US5] Add results display styles to web/static/css/style.css
- [ ] T062 [US5] Implement fetchStrategies() function in web/static/js/dashboard.js
- [ ] T063 [US5] Implement startBacktest(config) function in web/static/js/dashboard.js
- [ ] T064 [US5] Implement pollBacktestStatus(jobId) function in web/static/js/dashboard.js
- [ ] T065 [US5] Implement renderBacktestResults() with equity curve in web/static/js/dashboard.js
- [ ] T066 [US5] Add progress indicator during backtest run in web/static/js/dashboard.js
- [ ] T067 [US5] Add cancel backtest functionality in web/static/js/dashboard.js

**Checkpoint**: Backtest tab fully functional - can run and view backtest results

---

## Phase 8: User Story 6 - Daily vs Long-term Views (Priority: P3)

**Goal**: Toggle between daily and long-term performance aggregation

**Independent Test**: Switch between Daily/Long-term views, verify data aggregation changes appropriately

### Implementation for User Story 6

- [ ] T068 [US6] Create /api/analytics/daily endpoint in web/app.py
- [ ] T069 [US6] Add view toggle (Daily/Long-term) to Analytics tab in web/templates/dashboard.html
- [ ] T070 [P] [US6] Add view toggle styles to web/static/css/style.css
- [ ] T071 [US6] Implement fetchDailyAnalytics(period) function in web/static/js/dashboard.js
- [ ] T072 [US6] Implement renderDailyBreakdown() with bar chart in web/static/js/dashboard.js
- [ ] T073 [US6] Implement day detail drill-down (show trades/signals for clicked day) in web/static/js/dashboard.js
- [ ] T074 [US6] Wire view toggle to switch between summary and daily views in web/static/js/dashboard.js

**Checkpoint**: Analytics tab supports both long-term summary and daily breakdown views

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Improvements that affect multiple user stories

- [ ] T075 [P] Add staleness indicator for data older than 60s in web/static/js/dashboard.js
- [ ] T076 [P] Add error handling and retry logic for all API calls in web/static/js/dashboard.js
- [ ] T077 [P] Add mobile-responsive styles for all tabs in web/static/css/style.css
- [ ] T078 Add keyboard shortcuts for tab navigation in web/static/js/dashboard.js
- [ ] T079 Add loading states for all async operations in web/static/js/dashboard.js
- [ ] T080 Verify existing TOTP auth still works with new tabs in web/app.py
- [ ] T081 Add console logging for debugging in web/static/js/dashboard.js
- [ ] T082 Run manual testing per quickstart.md validation checklist

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup completion - BLOCKS all user stories
- **User Stories (Phases 3-8)**: All depend on Foundational phase completion
  - US1 & US2 (both P1) can proceed in parallel after Foundational
  - US3 & US4 (both P2) can proceed in parallel after Foundational
  - US5 & US6 (both P3) can proceed in parallel after Foundational
- **Polish (Phase 9)**: Depends on all desired user stories being complete

### User Story Dependencies

| Story | Depends On | Can Parallel With |
|-------|------------|-------------------|
| US1 (Positions) | Foundational only | US2, US3, US4, US5, US6 |
| US2 (History) | Foundational only | US1, US3, US4, US5, US6 |
| US3 (Signals) | Foundational only | US1, US2, US4, US5, US6 |
| US4 (Analytics) | Foundational only | US1, US2, US3, US5, US6 |
| US5 (Backtest) | Foundational only | US1, US2, US3, US4, US6 |
| US6 (Daily/Long-term) | US4 (shares Analytics tab) | US1, US2, US3, US5 |

### Within Each User Story

- Backend endpoint before frontend fetching
- HTML template before JavaScript rendering
- CSS styles can be parallel with implementation
- Complete story before moving to next priority

### Parallel Opportunities

Within Phase 1 (Setup):
- T003 and T004 (both CSS) can run in parallel

Within Phase 2 (Foundational):
- T009 and T010 (both CSS) can run in parallel

Within each User Story:
- CSS tasks marked [P] can run parallel with implementation
- All user stories can proceed in parallel after Foundational

---

## Parallel Example: User Story 1

```bash
# After T013-T014 (backend), these can run in parallel:
Task: "T015 [US1] Add position card HTML template"
Task: "T016 [P] [US1] Add position card styles"

# Then sequential:
Task: "T017 [US1] Implement fetchPositions()"
Task: "T018 [US1] Implement renderPositions()"
```

---

## Implementation Strategy

### MVP First (User Stories 1 & 2 Only)

1. Complete Phase 1: Setup (tab navigation)
2. Complete Phase 2: Foundational (data utilities)
3. Complete Phase 3: User Story 1 (Positions)
4. Complete Phase 4: User Story 2 (History)
5. **STOP and VALIDATE**: Test positions and history independently
6. Deploy/demo if ready - core monitoring is functional

### Incremental Delivery

1. Setup + Foundational → Tab navigation works
2. Add US1 (Positions) → Live position monitoring (MVP!)
3. Add US2 (History) → Trade audit trail
4. Add US3 (Signals) → Strategy transparency
5. Add US4 (Analytics) → Performance insight
6. Add US5 (Backtest) → Strategy evaluation
7. Add US6 (Daily views) → Detailed analysis
8. Each story adds value without breaking previous stories

### Suggested Stopping Points

- **After US1+US2**: Minimum viable dashboard (positions + history)
- **After US4**: Full monitoring dashboard (adds signals + analytics)
- **After US6**: Complete feature set

---

## Notes

- All tasks extend existing files (no new component directories)
- Chart.js loaded via CDN (no npm build step)
- Auto-refresh uses existing 30s polling pattern
- TOTP authentication preserved (no auth changes)
- Backtest runs in background thread with status polling
- Trade history uses existing TradeLogger queries

---

## Summary

| Metric | Count |
|--------|-------|
| **Total Tasks** | 82 |
| **Setup Tasks** | 6 |
| **Foundational Tasks** | 6 |
| **US1 Tasks** | 9 |
| **US2 Tasks** | 11 |
| **US3 Tasks** | 7 |
| **US4 Tasks** | 13 |
| **US5 Tasks** | 15 |
| **US6 Tasks** | 7 |
| **Polish Tasks** | 8 |
| **Parallelizable [P]** | 18 |
| **MVP Scope** | US1 + US2 (26 tasks after foundational) |
