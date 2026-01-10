# Feature Specification: Improve Short V1 Strategy for Binance Bear Market

**Feature Branch**: `001-improve-short-v1`
**Created**: 2026-01-09
**Status**: Draft
**Input**: User description: "Improvement Short V1 for Binance bear market."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Enhanced Bear Market Entry (Priority: P1)

As a trader, I want the Short V1 strategy to identify stronger bear market opportunities so that I enter positions with higher conviction and better risk-adjusted returns.

**Why this priority**: Entry quality directly impacts profitability. The current strategy uses EMA death cross + ADX >= 30, but may miss optimal entry points or enter during weak bear signals.

**Independent Test**: Can be validated through backtesting on BEAR_STRONG regime periods from 2020-2024 training data, measuring entry timing and subsequent price movement.

**Acceptance Scenarios**:

1. **Given** the market is in BEAR_STRONG regime (MFI <= 48, ADX >= 20), **When** the strategy identifies an entry opportunity, **Then** the entry signal includes multiple confirming indicators and confidence score >= 0.7.

2. **Given** a potential death cross formation, **When** the cross occurs with weak volume or ADX below threshold, **Then** the strategy does NOT enter (avoids false signals).

3. **Given** the market transitions from SIDEWAYS to BEAR, **When** the strategy evaluates entry, **Then** it waits for trend confirmation (ADX trending up) before entering.

---

### User Story 2 - Improved Stop Loss Management (Priority: P2)

As a trader, I want smarter stop loss placement that adapts to market volatility so that I avoid premature exits while still protecting capital.

**Why this priority**: Current stop loss uses swing high with max 4.6% cap. In volatile bear markets, this may be hit by noise before the trend continues.

**Independent Test**: Can be validated by analyzing historical trades where stop loss was hit but price continued in profitable direction afterward.

**Acceptance Scenarios**:

1. **Given** a short position is opened, **When** calculating stop loss, **Then** the strategy considers recent volatility (ATR) to set appropriate buffer above swing high.

2. **Given** market volatility increases after position entry, **When** stop loss is evaluated, **Then** the strategy maintains the original stop (no widening) to preserve risk management.

3. **Given** a position has reached 1R profit target (first 50% exited), **When** managing the remaining position, **Then** the strategy activates trailing stop to lock in gains while targeting 2R or better.

---

### User Story 3 - Better Take Profit Strategy (Priority: P3)

As a trader, I want optimized take profit levels that capture more of the bear trend while avoiding premature exits so that I maximize profit per trade.

**Why this priority**: Current fixed R:R ratio (2.5:1) may leave profit on table during strong trends or exit too late during weak ones.

**Independent Test**: Can be validated by comparing current fixed-target performance vs partial-exit or adaptive-target approaches on historical data.

**Acceptance Scenarios**:

1. **Given** a short position is open and profitable, **When** take profit is evaluated, **Then** the strategy considers partial exits at intermediate targets (e.g., 1R, 2R, final target).

2. **Given** the bear trend shows signs of weakening (ADX declining), **When** position is profitable, **Then** the strategy may exit earlier than original take profit to preserve gains.

3. **Given** the bear trend remains strong (ADX stable/increasing), **When** first take profit is reached, **Then** the strategy may hold remaining position for extended target.

---

### Edge Cases

- **Conflicting signals (death cross + ADX declining)**: Do NOT enter. ADX decline overrides death cross signal; trend strength takes priority over crossover signal.
- **Gap openings past stop loss**: Exit immediately at market price. Accept slippage to limit further loss; do not hold hoping for recovery.
- **Extreme volatility (>10% daily move)**: Halt new entries only. Manage existing positions with normal stop loss/take profit rules.
- **Binance API delays**: Deferred to planning phase (operational concern, does not affect strategy logic).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: Strategy MUST only generate signals during BEAR_STRONG or BEAR_MODERATE market regimes as classified by RegimeRouter.

- **FR-002**: Strategy MUST require minimum ADX threshold for entry (configurable, default 25+) to ensure trend strength.

- **FR-003**: Strategy MUST confirm -DI > +DI (bearish momentum) before entering short positions.

- **FR-004**: Strategy MUST calculate stop loss based on swing high with volatility buffer (ATR-based).

- **FR-005**: Strategy MUST respect maximum stop loss percentage limit (configurable, default 5%) regardless of swing high calculation.

- **FR-006**: Strategy MUST implement two-tier profit taking: exit 50% of position at 1R target, activate trailing stop for remaining 50% (targeting 2R or better).

- **FR-007**: Strategy MUST exit on golden cross (EMA fast crosses above slow) as trend reversal signal.

- **FR-008**: Strategy MUST log all entry/exit decisions with reasoning and indicator values for analysis.

- **FR-009**: Strategy MUST maintain leverage limit of 2x maximum for risk management per constitution.

- **FR-010**: Strategy MUST achieve minimum profit target of 1.4% per trade to overcome fees (0.14% total).

- **FR-011**: Strategy MUST NOT enter when ADX is declining, even if death cross signal is present (trend strength priority).

- **FR-012**: Strategy MUST exit immediately at market price if price gaps past stop loss level (accept slippage to limit further loss).

- **FR-013**: Strategy MUST halt new entries during extreme volatility events (>10% daily price movement) while managing existing positions normally.

### Key Entities

- **TradeSignal**: Entry/exit decision with action type, confidence score, stop loss, take profit, leverage, and reasoning metadata.

- **PositionState**: Current position status including entry price, stop loss price, take profit price(s), leverage, and partial exit history.

- **MarketIndicators**: Calculated values for EMA fast/slow, ADX, +DI/-DI, ATR, swing high/low, and trend state.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Out-of-sample (2025-present) return improvement of at least 5 percentage points over current Short V1 implementation.

- **SC-002**: Sharpe ratio of 1.5 or higher on validation period (per constitution backtesting standards).

- **SC-003**: Maximum drawdown of 20% or less during bear market periods.

- **SC-004**: Win rate of 45% or higher (acceptable for trend-following strategy with positive R:R).

- **SC-005**: Average profit per winning trade at least 2x average loss per losing trade (R:R >= 2.0).

- **SC-006**: Strategy generates at least 10 trades during BEAR regime periods in backtest to ensure statistical significance.

- **SC-007**: Stop loss hit rate reduced by at least 10% compared to current implementation (fewer premature exits).

## Clarifications

### Session 2026-01-09

- Q: What partial exit structure should be used for profit taking? → A: Two-tier exit: 50% at 1R, 50% at 2R (or trailing stop)
- Q: What happens when signals conflict (death cross but ADX declining)? → A: Do NOT enter - ADX decline overrides death cross (trend strength priority)
- Q: When should trailing stop activate? → A: Activate trailing stop after 1R target is hit (for remaining 50%)
- Q: How to handle gap openings that skip stop loss? → A: Exit immediately at market price (accept slippage, limit further loss)
- Q: How to handle extreme volatility (>10% daily move)? → A: Halt new entries only; manage existing positions normally

## Assumptions

- The RegimeRouter correctly classifies BEAR_STRONG and BEAR_MODERATE market states.
- Binance API provides reliable 4H candle data with acceptable latency.
- Historical data from 2020-2024 includes sufficient bear market periods for training.
- Current fee structure (0.04% maker/taker + 0.05% slippage estimate) remains stable.
- Leverage is capped at 2x per existing configuration constraints.
