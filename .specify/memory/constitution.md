<!--
SYNC IMPACT REPORT
==================
Version change: 0.0.0 → 1.0.0 (MAJOR - initial adoption)
Modified principles: N/A (initial version)
Added sections:
  - Core Principles (5 principles)
  - Development Constraints
  - Quality Gates
  - Governance
Removed sections: N/A
Templates requiring updates:
  - .specify/templates/plan-template.md ✅ (Constitution Check section already present)
  - .specify/templates/spec-template.md ✅ (Requirements section compatible)
  - .specify/templates/tasks-template.md ✅ (Checkpoint structure compatible)
Follow-up TODOs: None
-->

# Bitcoin Trading Bot Constitution

## Core Principles

### I. Git-First Development (NON-NEGOTIABLE)

All code changes MUST flow through git version control with proper branch management:

- New features MUST be developed on feature branches (`feature/{name}`)
- Direct commits to `main` are PROHIBITED for new features
- Deployment MUST use `git pull` only—SSH/rsync bulk transfers are PROHIBITED
- Every feature requires a PR before merging to main

**Rationale**: Enforces traceability, enables code review, and prevents deployment drift between environments.

### II. Backtesting-Validated Strategies

Every trading strategy MUST pass rigorous backtesting before live deployment:

- **Training period**: 2020-01-01 to 2024-12-31
- **Validation period**: 2025-01-01 to present (out-of-sample)
- **Success criteria**:
  - OOS return ≥ 15%
  - Sharpe ratio ≥ 1.5
  - Maximum drawdown ≤ 20%

Strategies failing validation MUST NOT be deployed to live trading.

**Rationale**: Prevents deploying strategies that only work on historical data (overfitting) and ensures statistical robustness.

### III. Fee-Aware Position Sizing

All strategies MUST account for real trading costs:

- **Cost per trade**: 0.05% (entry) + 0.05% (exit) + 0.04% (slippage) = **0.14% total**
- **Minimum profit target**: 1.4% (10× fees)
- Split trading (multiple small trades) is PROHIBITED due to fee multiplication

**Rationale**: Many strategies appear profitable in backtests but fail live due to underestimated transaction costs.

### IV. Regime-Aware Trading

Strategies MUST respect market regime classification:

- **BULL regime**: Long strategies only (v35_long on Upbit)
- **SIDEWAYS regime**: Sideways strategies (sideways_v2, h4_conservative)
- **BEAR regime**: Short strategies only (short_v1, h4_short on Binance)

Trading against the classified regime is PROHIBITED without explicit override.

**Rationale**: Different market conditions require fundamentally different approaches; trend-following fails in ranging markets and vice versa.

### V. Simplicity Over Complexity

Strategy design MUST favor simplicity:

**DO**:
- Reactive strategies (momentum-following)
- Simple conditions (2-3 max)
- Market filtering (trade aligned with regime)
- Large targets (1.5%+ to overcome fees)
- Timeframes of minute60 or higher

**DO NOT**:
- Predictive strategies (e.g., RSI < 30 → buy)
- Complex indicator combinations (3+ indicators)
- Over-optimization (overfitting to historical data)
- Day-level active trading

**Rationale**: Complex strategies overfit to noise; simple, robust strategies generalize better to unseen market conditions.

## Development Constraints

### Strategy Development Workflow

1. Create design plan: `docs/plans/{DATE}-{name}-design.md`
2. Wait for user approval before implementation
3. Create feature branch: `git checkout -b feature/{strategy-name}`
4. Implement in `trading/strategy/{name}.py`
5. Add configuration in `config/strategies/{name}.json`
6. Run backtesting with training/validation split
7. Document results with metrics
8. Create PR and merge after review

### Technology Stack

- **Language**: Python 3.x with type hints
- **Data**: SQLite databases (`data/*.db`)
- **Configuration**: JSON files in `config/`
- **Testing**: pytest
- **Dependencies**: TA-Lib for technical indicators

### Prohibited Practices

- Committing API keys or secrets (use `.env`)
- Running untested strategies in live mode
- Bypassing the kill-switch during active positions
- Modifying production data databases directly

## Quality Gates

### Pre-Merge Checklist

- [ ] All tests pass (`pytest`)
- [ ] Backtesting results documented
- [ ] OOS metrics meet thresholds (if strategy change)
- [ ] No secrets in committed files
- [ ] Feature branch used (not direct to main)

### Pre-Live Checklist

- [ ] Paper trading validates expected behavior
- [ ] Risk controls configured (daily loss limit, kill-switch)
- [ ] Telegram notifications working
- [ ] Deployment via `git pull` only

## Governance

This constitution supersedes all other development practices for the Bitcoin Trading Bot project.

### Amendment Process

1. Propose changes via PR to this file
2. Document rationale for changes
3. Increment version appropriately:
   - **MAJOR**: Principle removal or fundamental redefinition
   - **MINOR**: New principle or material expansion
   - **PATCH**: Clarification or typo fixes
4. Update dependent templates if principles change

### Compliance

- All PRs MUST verify compliance with these principles
- Complexity beyond these guidelines MUST be explicitly justified
- Runtime development guidance is in `CLAUDE.md`

**Version**: 1.0.0 | **Ratified**: 2025-01-09 | **Last Amended**: 2025-01-09
