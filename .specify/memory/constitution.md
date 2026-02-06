<!--
SYNC IMPACT REPORT
==================
Version change: 0.0.0 → 1.0.0 (MAJOR: Initial constitution adoption)

Modified principles: N/A (initial version)

Added sections:
- Core Principles (5 principles)
- Trading Constraints
- Development Workflow
- Governance

Removed sections: N/A (initial version)

Templates requiring updates:
- .specify/templates/plan-template.md ✅ Compatible (Constitution Check section exists)
- .specify/templates/spec-template.md ✅ Compatible (requirements structure aligns)
- .specify/templates/tasks-template.md ✅ Compatible (phased approach aligns)

Follow-up TODOs: None
-->

# Bitcoin Trading Bot Constitution

## Core Principles

### I. Backtesting-First Development

Every strategy MUST be validated through backtesting before deployment.

- **Training period**: 2020-01-01 to 2024-12-31
- **Validation period**: 2025-01-01 to present (out-of-sample)
- **Success criteria**: OOS return ≥15%, Sharpe ratio ≥1.5, Maximum drawdown ≤20%
- All strategy changes require backtesting validation before PR merge

**Rationale**: Historical validation prevents deploying untested strategies to live markets where real capital is at risk.

### II. Git-Based Development Workflow

All code changes MUST follow the branch-and-PR workflow.

- New features require feature branches: `feature/{name}`
- Direct commits to main are prohibited
- Deployment happens only via `git pull` on target servers
- SSH/rsync bulk transfers and direct file uploads are prohibited

**Rationale**: Version control discipline ensures traceability, enables rollback, and prevents deployment of untested code.

### III. Risk-Aware Trading Design

All strategies MUST account for real-world trading costs and risk limits.

- **Fee calculation**: Entry (0.05%) + Exit (0.05%) + Slippage (0.04%) = 0.14% per trade
- **Minimum profit target**: 1.4% (10x fees) to ensure profitability
- **Daily loss limit**: 5% maximum
- Kill-switch capability MUST be maintained for emergency stops
- Prefer larger, less frequent trades over many small trades

**Rationale**: Transaction costs compound rapidly; strategies that ignore fees appear profitable in backtests but fail in production.

### IV. Reactive Strategies Only

Strategies MUST follow market momentum, not predict reversals.

- **Allowed**: Momentum-following, trend-continuation, breakout strategies
- **Prohibited**: Mean-reversion, RSI-based reversal predictions, counter-trend entries
- Simple conditions only (2-3 maximum per strategy)
- Use minute60+ timeframes to reduce noise and fees

**Rationale**: Predictive strategies underperform in crypto markets; reactive approaches align with proven momentum effects.

### V. Simplicity and Anti-Over-Optimization

Strategies MUST remain simple and avoid overfitting.

- Maximum 3 indicators per strategy
- No complex indicator combinations (3+ indicators prohibited)
- Avoid parameter optimization beyond essential values
- Market regime filtering preferred (trade BULL conditions only)
- Split trading (fee explosion) is prohibited

**Rationale**: Overfitted strategies perform well in backtests but fail out-of-sample; simplicity improves robustness.

## Trading Constraints

Technical and operational boundaries for all trading activities:

- **Binance Spot**: MLP Direction for BULL, Sideways_V2 for SIDEWAYS regimes
- **Binance Futures**: Short positions (SHORT_V1 for BEAR regime)
- **RegimeRouter**: Market classification via MFI and ADX indicators
- **Paper trading**: Default mode; live trading requires explicit `ENABLE_LIVE_TRADING=1`
- **Notifications**: All critical events MUST be sent via Telegram

## Development Workflow

Required process for strategy and feature development:

1. **Planning**: Create design document at `docs/plans/{DATE}-{name}-design.md`
2. **Approval**: Wait for explicit user approval before implementation
3. **Branching**: Create feature branch `feature/{strategy-name}`
4. **Implementation**: Strategy in `trading/strategy/{name}.py`, config in `config/strategies/{name}.json`
5. **Validation**: Run backtesting with standard training/validation periods
6. **Documentation**: Document results and rationale
7. **Review**: Create PR for code review and merge

## Governance

This constitution establishes the foundational rules for the Bitcoin Trading Bot project.

- This constitution supersedes all other development practices
- All PRs MUST verify compliance with these principles
- Complexity beyond these guidelines MUST be justified in writing
- The CLAUDE.md file provides runtime development guidance

**Amendment procedure**:
1. Propose changes with rationale
2. Document impact on existing strategies
3. Update version according to semantic versioning
4. Update dependent documentation

**Version policy**:
- MAJOR: Principle removal or backward-incompatible changes
- MINOR: New principles or material expansions
- PATCH: Clarifications and non-semantic refinements

**Version**: 1.0.0 | **Ratified**: 2026-01-09 | **Last Amended**: 2026-01-09
