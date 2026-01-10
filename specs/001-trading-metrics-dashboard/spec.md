# Feature Specification: Real-Time Trading Metrics Dashboard

**Feature Branch**: `001-trading-metrics-dashboard`
**Created**: 2026-01-09
**Status**: Draft
**Input**: User description: "Create a dashboard for real-time trading metrics, what strategies decisions now."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Current Strategy Decisions (Priority: P1)

As a trader, I want to see which trading strategies are currently active and what decisions they are making in real-time, so I can understand and monitor the bot's trading behavior.

**Why this priority**: This is the core value of the dashboard - without visibility into current strategy decisions, traders cannot effectively monitor or understand their bot's behavior.

**Independent Test**: Can be fully tested by viewing the dashboard when the trading bot is running and verifying that current strategy decisions (buy/sell/hold) are displayed with their reasoning.

**Acceptance Scenarios**:

1. **Given** the trading bot is running, **When** I open the dashboard, **Then** I see the current active strategy name and its latest decision (buy/sell/hold) with timestamp
2. **Given** a strategy makes a new decision, **When** I am viewing the dashboard, **Then** the display updates within 5 seconds to show the new decision
3. **Given** the trading bot is stopped, **When** I open the dashboard, **Then** I see a clear indication that no active trading session is running

---

### User Story 2 - View Real-Time Trading Metrics (Priority: P2)

As a trader, I want to see key trading metrics (current position, P&L, portfolio value) updating in real-time, so I can assess performance at a glance.

**Why this priority**: Real-time metrics provide essential context for strategy decisions, enabling traders to correlate decisions with actual performance outcomes.

**Independent Test**: Can be fully tested by viewing the dashboard while a position is open and verifying that P&L updates as market prices change.

**Acceptance Scenarios**:

1. **Given** I have an open position, **When** I view the dashboard, **Then** I see current unrealized P&L updating as market prices change
2. **Given** the market regime changes (BULL/SIDEWAYS/BEAR), **When** I view the dashboard, **Then** I see the current market regime classification displayed
3. **Given** I want to understand current risk exposure, **When** I view the dashboard, **Then** I see position size, entry price, and current market price

---

### User Story 3 - View Strategy Decision History (Priority: P3)

As a trader, I want to see a history of recent strategy decisions with their outcomes, so I can analyze patterns and understand strategy behavior over time.

**Why this priority**: Historical context helps traders understand strategy patterns, but is secondary to seeing current real-time state.

**Independent Test**: Can be fully tested by reviewing the decision history after the bot has made several decisions, verifying each shows timestamp, decision, and outcome.

**Acceptance Scenarios**:

1. **Given** the strategy has made decisions today, **When** I view the decision history section, **Then** I see a chronological list of decisions with timestamps, decision type, and market conditions at decision time
2. **Given** I want to see more detail about a specific decision, **When** I click on a decision entry, **Then** I see expanded details including the indicators and thresholds that triggered the decision

---

### Edge Cases

- What happens when the trading bot loses connection to the exchange? Dashboard shows a "connection lost" warning with last known data timestamp
- How does the dashboard handle when multiple strategies are active simultaneously (Upbit + Binance)? Display both in separate sections with clear labels
- What happens when the dashboard loads but no trading data exists yet? Display an empty state with guidance message
- How are stale data handled if the bot freezes? Show data freshness indicator; mark data as "stale" if not updated for more than 30 seconds

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST display the currently active trading strategy name and its current mode (paper/live)
- **FR-002**: System MUST show the latest strategy decision (buy/sell/hold) with timestamp and reasoning
- **FR-003**: System MUST display real-time market regime classification (BULL/SIDEWAYS/BEAR/BEAR_STRONG)
- **FR-004**: System MUST show current position information including: entry price, position size, current price, unrealized P&L
- **FR-005**: System MUST update displayed data automatically via polling (every 3-5 seconds) without requiring page refresh
- **FR-006**: System MUST clearly indicate when no active trading session exists
- **FR-007**: System MUST display connection status to exchanges (connected/disconnected)
- **FR-008**: System MUST show data freshness indicator (time since last update)
- **FR-009**: System MUST support viewing both Upbit (spot) and Binance (futures) trading data when both are active
- **FR-010**: System MUST display recent decision history (last 24 hours) with expandable details

### Key Entities

- **Strategy Decision**: Represents a trading decision made by a strategy - includes timestamp, decision type (buy/sell/hold), strategy name, market conditions at decision time, and reasoning/indicators that triggered it
- **Trading Position**: Current open position - includes entry price, size, direction (long/short), unrealized P&L, exchange
- **Market Regime**: Current market classification - includes regime type (BULL/SIDEWAYS/BEAR/BEAR_STRONG), confidence level, and contributing indicators (MFI, ADX values)
- **Trading Session**: Active bot session - includes mode (paper/live), start time, active strategies, exchange connections

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Traders can identify the current strategy decision and market regime within 5 seconds of opening the dashboard
- **SC-002**: Dashboard data updates within 5 seconds of any strategy decision or position change
- **SC-003**: 95% of dashboard page loads complete within 3 seconds
- **SC-004**: Traders can view decision history for the past 24 hours and understand why each decision was made
- **SC-005**: Dashboard correctly displays both Upbit and Binance trading data when both exchanges are active
- **SC-006**: Stale data (>30 seconds old) is clearly indicated to prevent traders from acting on outdated information

## Clarifications

### Session 2026-01-09

- Q: How should real-time updates reach the browser? → A: Polling (browser fetches new data every 3-5 seconds)
- Q: How does the dashboard access trading data? → A: File-based (reads from existing log files and SQLite databases)
- Q: How should new features integrate with existing dashboard? → A: Add new routes/pages within the existing Flask dashboard

## Assumptions

- The existing trading bot already logs decisions and their reasoning to SQLite databases and JSON log files that the dashboard can read directly
- Market regime classification is already computed by the RegimeRouter
- Position and P&L data are available from the existing execution/position management components
- An existing web dashboard infrastructure exists (Flask-based) that will be extended with new routes and pages
- The dashboard is for a single operator/trader (no multi-user authentication required)
