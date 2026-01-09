# Feature Specification: Dashboard Upgrade

**Feature Branch**: `001-dashboard-upgrade`
**Created**: 2026-01-09
**Status**: Draft
**Input**: User description: "upgrade dashboard for show position, history, analytics, signal, backtesting of long term or daily"

## Clarifications

### Session 2026-01-09

- Q: How should the 5 new dashboard sections be organized? → A: Tabbed navigation - Tab bar at top to switch between sections

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Current Positions (Priority: P1)

As a trader, I want to see all my current open positions in one consolidated view so that I can monitor my exposure and unrealized P&L at a glance.

**Why this priority**: Core trading function - knowing current positions is essential for risk management and decision-making. Without this, traders cannot effectively manage their portfolio.

**Independent Test**: Can be fully tested by opening a position on either exchange and verifying it appears in the dashboard with correct entry price, current price, quantity, and P&L. Delivers immediate value for position monitoring.

**Acceptance Scenarios**:

1. **Given** I have an open position on Upbit, **When** I view the Positions section, **Then** I see the position with symbol, quantity, entry price, current price, unrealized P&L (amount and percentage), and position age
2. **Given** I have an open position on Binance Futures, **When** I view the Positions section, **Then** I see the position with symbol, size, entry price, liquidation price, unrealized P&L, and leverage
3. **Given** I have no open positions, **When** I view the Positions section, **Then** I see a clear message indicating no active positions
4. **Given** I have positions on both exchanges, **When** I view the dashboard, **Then** I see a combined portfolio view with total exposure and aggregate P&L

---

### User Story 2 - View Trade History (Priority: P1)

As a trader, I want to review my past trades so that I can analyze my trading performance and identify patterns.

**Why this priority**: Essential for learning from past decisions and tracking overall performance. Historical data is required for any meaningful analytics.

**Independent Test**: Can be tested by executing a trade (or viewing existing trade logs) and verifying it appears in the history with all relevant details. Delivers value by providing audit trail and performance tracking.

**Acceptance Scenarios**:

1. **Given** trades exist in the system, **When** I view the History section, **Then** I see a list of trades sorted by date (newest first) with timestamp, symbol, side (buy/sell), quantity, price, fees, and realized P&L
2. **Given** I want to filter trades, **When** I select filter criteria (date range, exchange, symbol), **Then** the list updates to show only matching trades
3. **Given** many trades exist, **When** I scroll the trade list, **Then** I can paginate through all historical trades (not limited to 50)
4. **Given** I view a trade, **When** I want more details, **Then** I can expand the row to see strategy name, signal reason, and market conditions at entry/exit

---

### User Story 3 - View Trading Signals (Priority: P2)

As a trader, I want to see current and recent trading signals so that I can understand what the bot is detecting and why.

**Why this priority**: Important for understanding bot behavior and building trust in the system. Helps identify when strategy needs adjustment.

**Independent Test**: Can be tested by waiting for a signal to be generated and verifying it appears in the dashboard. Delivers transparency into bot decision-making.

**Acceptance Scenarios**:

1. **Given** a signal is generated, **When** I view the Signals section, **Then** I see the signal with timestamp, symbol, strategy name, signal type (buy/sell/hold), confidence level, and reason
2. **Given** a signal was acted upon, **When** I view the signal, **Then** I can see whether an order was placed and its outcome
3. **Given** a signal was not acted upon (filtered/blocked), **When** I view the signal, **Then** I can see why it was filtered (risk limits, regime mismatch, etc.)
4. **Given** I want real-time updates, **When** new signals are generated, **Then** the signal list updates automatically without full page refresh

---

### User Story 4 - View Analytics Dashboard (Priority: P2)

As a trader, I want to see performance analytics so that I can evaluate my trading strategy effectiveness over time.

**Why this priority**: Analytics enable data-driven decisions about strategy adjustments. Builds confidence in the trading system.

**Independent Test**: Can be tested with historical trade data, verifying metrics calculate correctly. Delivers insight into trading performance.

**Acceptance Scenarios**:

1. **Given** trades exist, **When** I view the Analytics section, **Then** I see key metrics: total return (%), win rate, profit factor, Sharpe ratio, max drawdown, average trade duration
2. **Given** I select a time period (7d, 30d, 90d, all-time), **When** the selection changes, **Then** all metrics recalculate for that period
3. **Given** I view analytics, **When** I look at the equity curve chart, **Then** I see portfolio value over time with drawdown periods highlighted
4. **Given** multiple strategies are active, **When** I view analytics, **Then** I can see per-strategy breakdown of performance metrics

---

### User Story 5 - Run Backtesting from Dashboard (Priority: P3)

As a trader, I want to run backtests from the dashboard so that I can quickly evaluate strategy changes without using command-line tools.

**Why this priority**: Convenience feature that accelerates strategy development. Less critical than monitoring but valuable for iteration speed.

**Independent Test**: Can be tested by selecting a strategy and date range, running a backtest, and verifying results display correctly. Delivers convenience for strategy evaluation.

**Acceptance Scenarios**:

1. **Given** I want to backtest, **When** I open the Backtest section, **Then** I can select strategy, date range, and initial capital
2. **Given** I configure a backtest, **When** I click "Run Backtest", **Then** I see a progress indicator and the backtest runs in the background
3. **Given** a backtest completes, **When** I view results, **Then** I see equity curve, drawdown chart, trade list, and summary statistics (return, Sharpe, MDD, win rate)
4. **Given** I want to compare strategies, **When** I run multiple backtests, **Then** I can view results side-by-side

---

### User Story 6 - View Long-term vs Daily Performance (Priority: P3)

As a trader, I want to toggle between long-term and daily performance views so that I can analyze performance at different time scales.

**Why this priority**: Useful for understanding performance patterns but depends on analytics being implemented first.

**Independent Test**: Can be tested by selecting different time views and verifying data aggregation changes appropriately. Delivers multi-timeframe insight.

**Acceptance Scenarios**:

1. **Given** I view analytics, **When** I select "Daily" view, **Then** I see day-by-day P&L, trade count, and metrics
2. **Given** I view analytics, **When** I select "Long-term" view, **Then** I see monthly/yearly aggregated data with cumulative metrics
3. **Given** I view daily performance, **When** I click on a specific day, **Then** I see detailed trades and signals for that day
4. **Given** I view long-term performance, **When** I look at the chart, **Then** I see trend lines and moving averages for key metrics

---

### Edge Cases

- What happens when the trading engine is not running? Dashboard should show clear "Engine Offline" status and display last known data with timestamps.
- How does the system handle missing historical data? Show "Data unavailable" for gaps with explanation.
- What happens during exchange API outages? Cache last known data and show staleness indicator.
- What happens when a backtest takes too long? Provide timeout notification and option to cancel.
- How to handle very large trade histories? Implement pagination and date range limits to prevent performance issues.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST display all open positions from both Upbit and Binance exchanges with real-time price updates
- **FR-002**: System MUST show unrealized P&L for each position in both absolute and percentage terms
- **FR-003**: System MUST maintain a searchable, filterable trade history with all executed trades
- **FR-004**: System MUST display trading signals with generation timestamp, strategy source, and action taken
- **FR-005**: System MUST calculate and display performance analytics including return, win rate, Sharpe ratio, and max drawdown
- **FR-006**: System MUST provide equity curve visualization over configurable time periods
- **FR-007**: System MUST allow users to run backtests with configurable parameters (strategy, date range, capital)
- **FR-008**: System MUST display backtest results with equity curve, trade list, and summary statistics
- **FR-009**: System MUST support toggling between daily and long-term performance views
- **FR-010**: System MUST auto-refresh data at configurable intervals (default: 30 seconds for live data)
- **FR-011**: System MUST show clear status indicators when data is stale or unavailable
- **FR-012**: System MUST preserve existing TOTP authentication for dashboard access
- **FR-013**: System MUST organize sections (Positions, History, Signals, Analytics, Backtest) using tabbed navigation with a tab bar at the top

### Key Entities

- **Position**: Represents an open trading position - symbol, exchange, quantity, entry price, current price, unrealized P&L, entry timestamp, strategy
- **Trade**: Represents a completed trade - symbol, exchange, side, quantity, entry/exit prices, fees, realized P&L, timestamps, strategy
- **Signal**: Represents a trading signal - timestamp, symbol, strategy, signal type, confidence, reason, action taken, outcome
- **Analytics Period**: Represents aggregated metrics for a time period - start/end dates, return, win rate, trade count, Sharpe, MDD
- **Backtest Result**: Represents backtest output - configuration, equity curve data points, trade list, summary statistics

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can view all open positions across both exchanges within 3 seconds of page load
- **SC-002**: Trade history loads and displays the most recent 100 trades within 2 seconds
- **SC-003**: Users can filter trade history by date range and see results within 1 second
- **SC-004**: Analytics dashboard displays all key metrics (return, win rate, Sharpe, MDD) within 3 seconds
- **SC-005**: Backtests for 1-year periods complete and display results within 60 seconds
- **SC-006**: Dashboard updates position and P&L data automatically without user intervention
- **SC-007**: 95% of users can locate and understand position, history, and analytics sections without guidance
- **SC-008**: Daily/Long-term view toggle updates display within 1 second

## Assumptions

- Existing trading log files (`v2_engine_*.json`, `paper_trading_*.json`) contain sufficient data for history and analytics
- Exchange API credentials are properly configured for real-time balance/position fetching
- The existing `core/backtester.py` module can be invoked for on-demand backtesting
- SQLite database (`trading_results.db`) is available for persistent trade storage
- Users access the dashboard from modern browsers (Chrome, Firefox, Safari, Edge - latest 2 versions)
- Dashboard will be accessed by 1-3 concurrent users maximum (personal trading bot)
