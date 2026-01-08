# Feature Specification: Daily Backtest Comparison Report

**Feature Branch**: `001-daily-backtest-comparison`
**Created**: 2025-01-09
**Status**: Draft
**Input**: User description: "Every night at 12:00, we run the backtest for that day and report the results of the logging backtesting with the execution results of the strategies performed in actual trading on that day. It is designed to allow comparison between the actual trading logs on that day and the backtesting logs."

## Clarifications

### Session 2025-01-09

- Q: What tolerance window should be used when matching actual trades to backtest trades by timestamp? → A: 5-minute tolerance window
- Q: How should the system handle report generation failures? → A: Retry 3 times with 5-minute intervals, then notify failure via Telegram
- Q: How should discrepancy severity be classified? → A: Three tiers - Low (<1% P/L impact), Medium (1-5% impact), High (>5% impact or wrong direction)

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Daily Comparison Report (Priority: P1)

As a trader, I want to receive a daily report at midnight comparing my actual trades with what the backtest would have produced for that same day, so I can identify discrepancies between expected and actual strategy behavior.

**Why this priority**: This is the core value proposition - without the comparison report, the feature has no utility. Traders need visibility into whether their live trading matches theoretical backtested performance.

**Independent Test**: Can be fully tested by triggering the report generation for a past day with known trades and verifying the comparison output matches expected values.

**Acceptance Scenarios**:

1. **Given** the trading system has been running live for the day with at least one trade executed, **When** the clock reaches 00:00, **Then** a comparison report is generated showing side-by-side actual vs backtest results.

2. **Given** no trades were executed during the day (hold position), **When** the daily report runs, **Then** the report shows both actual and backtest as "no trades" with position status comparison.

3. **Given** actual trades differ from backtest recommendations, **When** the report is generated, **Then** each discrepancy is highlighted with the specific difference (timing, price, action type).

---

### User Story 2 - Receive Report via Telegram (Priority: P2)

As a trader, I want to receive the daily comparison report via Telegram notification, so I can review the results without logging into the server.

**Why this priority**: Delivery mechanism is secondary to report generation itself. Telegram is the existing notification channel, making this natural extension.

**Independent Test**: Can be tested by generating a sample report and verifying it arrives in Telegram with proper formatting.

**Acceptance Scenarios**:

1. **Given** a comparison report has been generated, **When** the report is ready, **Then** a formatted summary is sent to the configured Telegram chat with key metrics.

2. **Given** the report contains significant discrepancies (>5% difference in daily return), **When** the notification is sent, **Then** it includes a warning indicator to draw attention.

---

### User Story 3 - Historical Report Access (Priority: P3)

As a trader, I want to access historical comparison reports, so I can analyze patterns of discrepancy over time.

**Why this priority**: Historical access is valuable for long-term analysis but not essential for daily operations. The primary use case is immediate daily review.

**Independent Test**: Can be tested by generating reports for multiple days, then querying and retrieving specific past reports.

**Acceptance Scenarios**:

1. **Given** reports have been generated for multiple days, **When** I request a report for a specific date, **Then** the stored report is retrieved and displayed.

---

### Edge Cases

- What happens when the market data for that day is incomplete or missing?
  - Report generation should indicate data gaps and produce partial results where possible.

- How does the system handle days when the bot was offline for part of the day?
  - Report should show the offline period and only compare trading during active hours.

- What happens when backtest and live use different fee assumptions?
  - Both should use the same fee model (0.14% total per trade) for fair comparison.

- What happens when position was carried over from previous day?
  - Report should account for open positions at day start and include them in calculations.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST run backtest automatically at 00:00 daily using that day's market data (00:00 to 23:59).
- **FR-002**: System MUST retrieve all actual trades executed during the day from the trading log database.
- **FR-003**: System MUST align backtest results with actual trades by timestamp for comparison, using a 5-minute tolerance window to account for execution latency.
- **FR-004**: System MUST calculate and display key metrics for both actual and backtest:
  - Total trades count
  - Win rate
  - Total profit/loss (absolute and percentage)
  - Maximum drawdown during the day
- **FR-005**: System MUST identify and flag discrepancies where actual trade differs from backtest recommendation.
- **FR-006**: System MUST support comparison for all active strategies (Upbit long, Binance short, sideways strategies).
- **FR-007**: System MUST send report summary via Telegram notification.
- **FR-008**: System MUST store generated reports for historical access.
- **FR-009**: System MUST use the same fee model for both backtest and actual comparison (0.05% entry + 0.05% exit + 0.04% slippage = 0.14%).
- **FR-010**: System MUST retry report generation up to 3 times with 5-minute intervals on failure, then send a failure notification via Telegram if all retries fail.

### Key Entities

- **DailyComparisonReport**: Represents a single day's comparison between actual and backtest results. Contains date, strategy identifier, actual metrics, backtest metrics, discrepancies list, and generation timestamp.

- **TradeComparison**: Represents a single trade comparison point. Contains timestamp, expected action (from backtest), actual action (from live), price difference, and match status.

- **DiscrepancyRecord**: Represents a mismatch between expected and actual behavior. Contains timestamp, discrepancy type (missed trade, extra trade, wrong direction, timing difference), severity level (Low: <1% P/L impact, Medium: 1-5% impact, High: >5% impact or wrong direction), and explanation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Daily reports are generated and delivered within 5 minutes of midnight every day.
- **SC-002**: Comparison accuracy achieves 100% match when backtest and actual trades are identical (validation via known test data).
- **SC-003**: Traders can identify strategy drift within 1 day of occurrence through discrepancy flags.
- **SC-004**: Historical reports can be retrieved for any date within the past 90 days.
- **SC-005**: Report generation completes successfully for days with up to 50 trades per strategy.

## Assumptions

- The trading system already logs all executed trades to `trading_results.db`.
- Market data (OHLCV) is available for backtesting via existing data loaders.
- Telegram notification infrastructure is already in place and functional.
- Backtesting uses the same strategy parameters as live trading.
- The system runs on a server with cron or equivalent scheduling capability.
- Report timezone is KST (Korea Standard Time), matching the trading system.
