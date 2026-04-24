# Tasks: Real-Time Trading Metrics Dashboard

> Current scope note (2026-04-24): apply this spec to the Binance spot-only runtime. Any remaining references to Upbit, futures, short_v1, or sideways_v2 are historical draft context, not current implementation guidance.


**Input**: Design documents from `/specs/001-trading-metrics-dashboard/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: Tests will be added for API endpoints as mentioned in plan.md.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Path Conventions

This project uses the existing Flask web application structure:
- **Backend**: `web/` for Flask application
- **Templates**: `web/templates/` for Jinja2 templates
- **Static**: `web/static/` for JavaScript and CSS
- **Tests**: `tests/web/` for web-related tests

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Project initialization and directory structure

- [x] T001 Create `web/static/js/` directory if not exists
- [x] T002 [P] Create `web/services/` __init__.py if not exists
- [x] T003 [P] Create `tests/web/` directory structure if not exists

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core service that ALL user stories depend on

**Critical**: No user story work can begin until this phase is complete

- [x] T004 Create MetricsService class in `web/services/metrics_service.py` with JSON log file reading (loads `logs/v2_engine_upbit.json` and `logs/v2_engine_binance.json`)
- [x] T005 Implement `load_exchange_data(exchange: str)` method that parses JSON and returns ExchangeMetrics dict per data-model.md
- [x] T006 Implement `calculate_unrealized_pnl()` helper to compute P&L from position and current price
- [x] T007 Implement `get_connection_status()` method that checks file freshness and returns ConnectionStatus dict
- [x] T008 Add MetricsService import to `web/app.py`

**Checkpoint**: MetricsService can read and transform trading log data

---

## Phase 3: User Story 1 - View Current Strategy Decisions (Priority: P1) MVP

**Goal**: Display current active strategy and its latest decision (buy/sell/hold) with real-time updates

**Independent Test**: Open dashboard, verify strategy name and decision display, wait for polling update

### Implementation for User Story 1

- [x] T009 [US1] Implement `/api/metrics/realtime` endpoint in `web/app.py` that returns DashboardState JSON per contracts/api.yaml
- [x] T010 [US1] Create `web/templates/metrics.html` base template with strategy decision card section (strategy name, mode, latest decision, timestamp, reason)
- [x] T011 [US1] Create `web/static/js/metrics.js` with `fetchRealtimeMetrics()` function that calls `/api/metrics/realtime`
- [x] T012 [US1] Implement 4-second polling loop in `web/static/js/metrics.js` using `setInterval`
- [x] T013 [US1] Add `updateStrategyDecision(data)` function in `web/static/js/metrics.js` to update DOM with latest decision
- [x] T014 [US1] Implement no-data/bot-stopped state display in `web/templates/metrics.html` (FR-006)
- [x] T015 [US1] Add `/metrics` page route in `web/app.py` that renders `metrics.html` template
- [x] T016 [P] [US1] Write test for `/api/metrics/realtime` endpoint in `tests/web/test_metrics_api.py`

**Checkpoint**: User Story 1 complete - can view current strategy decisions with auto-refresh

---

## Phase 4: User Story 2 - View Real-Time Trading Metrics (Priority: P2)

**Goal**: Display current position, P&L, portfolio value, and market regime updating in real-time

**Independent Test**: Open dashboard with active position, verify P&L updates every 4 seconds

### Implementation for User Story 2

- [x] T017 [US2] Extend `web/templates/metrics.html` with position metrics section (entry price, position size, current price, unrealized P&L)
- [x] T018 [US2] Add market regime display card to `web/templates/metrics.html` (BULL/SIDEWAYS/BEAR/BEAR_STRONG with color coding)
- [x] T019 [US2] Implement `updatePositionMetrics(data)` function in `web/static/js/metrics.js`
- [x] T020 [US2] Implement `updateMarketRegime(data)` function in `web/static/js/metrics.js` with color styling
- [x] T021 [US2] Add connection status indicator to `web/templates/metrics.html` (FR-007)
- [x] T022 [US2] Implement stale data detection in `web/static/js/metrics.js` - add warning if data >30 seconds old (FR-008)
- [x] T023 [US2] Add multi-exchange support - display Upbit and Binance sections separately in `web/templates/metrics.html` (FR-009)
- [x] T024 [P] [US2] Write test for position and regime data in `tests/web/test_metrics_api.py`

**Checkpoint**: User Story 2 complete - can view positions, P&L, and regime with freshness indicators

---

## Phase 5: User Story 3 - View Strategy Decision History (Priority: P3)

**Goal**: Display chronological list of recent strategy decisions (last 24 hours) with expandable details

**Independent Test**: Open dashboard, verify decision history list shows, click to expand and see indicators

### Implementation for User Story 3

- [x] T025 [US3] Implement `/api/metrics/decisions` endpoint in `web/app.py` with filtering params (exchange, hours, limit) per contracts/api.yaml
- [x] T026 [US3] Add `get_recent_decisions(hours=24, limit=50)` method to MetricsService in `web/services/metrics_service.py`
- [x] T027 [US3] Add decision history section to `web/templates/metrics.html` with scrollable list
- [x] T028 [US3] Implement `updateDecisionHistory(data)` function in `web/static/js/metrics.js`
- [x] T029 [US3] Add expandable detail view for each decision row (shows indicators: RSI, MFI, ADX, score, tier)
- [x] T030 [US3] Implement decision expand/collapse toggle in `web/static/js/metrics.js`
- [x] T031 [P] [US3] Write test for `/api/metrics/decisions` endpoint in `tests/web/test_metrics_api.py`

**Checkpoint**: User Story 3 complete - can view and explore decision history with full indicator details

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final improvements affecting multiple user stories

- [x] T032 [P] Add responsive CSS styling to `web/templates/metrics.html` for mobile/tablet viewing
- [x] T033 [P] Add page title and navigation link to metrics page from existing dashboard
- [x] T034 Run all tests in `tests/web/test_metrics_api.py` and fix any failures
- [x] T035 Validate implementation against `specs/001-trading-metrics-dashboard/quickstart.md`
- [x] T036 Update `web/README.md` with metrics dashboard documentation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies - can start immediately
- **Foundational (Phase 2)**: Depends on Setup - BLOCKS all user stories
- **User Stories (Phase 3-5)**: All depend on Foundational phase completion
  - US1, US2, US3 can proceed sequentially in priority order
  - US2 extends US1 template, so must follow US1
  - US3 is independent and could theoretically parallel with US2
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

- **User Story 1 (P1)**: Can start after Foundational (Phase 2) - No other dependencies
- **User Story 2 (P2)**: Extends US1 template - should follow US1 completion
- **User Story 3 (P3)**: New API endpoint, extends template - should follow US2 completion

### Within Each User Story

- Service methods before API endpoints
- API endpoints before template updates
- Template sections before JavaScript functions
- Core implementation before tests

### Parallel Opportunities

- Setup tasks T002, T003 can run in parallel
- Test tasks T016, T024, T031 can run in parallel (different test functions)
- CSS styling T032 can run in parallel with T033

---

## Parallel Example: Phase 1 Setup

```bash
# Launch all setup tasks together:
Task: "Create web/static/js/ directory if not exists"
Task: "Create web/services/ __init__.py if not exists"  # [P]
Task: "Create tests/web/ directory structure"  # [P]
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup (T001-T003)
2. Complete Phase 2: Foundational (T004-T008)
3. Complete Phase 3: User Story 1 (T009-T016)
4. **STOP and VALIDATE**: Access `/metrics` page, verify strategy decisions display with polling
5. Deploy if ready - this delivers core value

### Incremental Delivery

1. Setup + Foundational → MetricsService ready
2. Add User Story 1 → Strategy decisions visible → **MVP Deploy**
3. Add User Story 2 → Position/P&L/Regime visible → Deploy
4. Add User Story 3 → Decision history visible → Deploy
5. Polish → Final refinements → Final Deploy

### Estimated Scope

- **Phase 1 (Setup)**: 3 tasks
- **Phase 2 (Foundational)**: 5 tasks
- **Phase 3 (US1)**: 8 tasks - **MVP**
- **Phase 4 (US2)**: 8 tasks
- **Phase 5 (US3)**: 7 tasks
- **Phase 6 (Polish)**: 5 tasks
- **Total**: 36 tasks

---

## Notes

- All paths are relative to repository root
- Existing patterns in `web/app.py` should be followed (see `/api/status` endpoint)
- Tailwind CSS classes used in existing `dashboard.html` should be reused
- JSON log files are the source of truth (no database queries needed)
- Single-user access means no authentication changes required
