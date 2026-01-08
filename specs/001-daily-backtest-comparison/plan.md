# Implementation Plan: Daily Backtest Comparison Report

**Branch**: `001-daily-backtest-comparison` | **Date**: 2025-01-09 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-daily-backtest-comparison/spec.md`

## Summary

Implement a nightly automated system that runs backtests for the current day's market data and compares results against actual executed trades. The comparison report highlights discrepancies between expected (backtested) and actual trading behavior, enabling traders to identify strategy drift or execution issues. Reports are delivered via Telegram and stored for historical access.

## Technical Context

**Language/Version**: Python 3.10+ with type hints
**Primary Dependencies**: pandas, sqlite3, existing Backtester class, TelegramNotifier
**Storage**: SQLite (`trading_results.db` for trades, new table for reports)
**Testing**: pytest
**Target Platform**: Linux server (Ubuntu) with cron scheduling
**Project Type**: Single project (extends existing trading bot)
**Performance Goals**: Report generation < 5 minutes including backtest execution
**Constraints**: Must use existing data loaders and backtester; 5-minute timestamp tolerance for trade matching
**Scale/Scope**: Up to 50 trades per strategy per day; 90 days historical retention

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Git-First Development | ✅ PASS | Feature branch `001-daily-backtest-comparison` created |
| II. Backtesting-Validated | ✅ N/A | Not a trading strategy - monitoring/reporting feature |
| III. Fee-Aware | ✅ PASS | Uses same 0.14% fee model for comparison fairness |
| IV. Regime-Aware | ✅ N/A | Not a trading strategy |
| V. Simplicity | ✅ PASS | Single-purpose report generator, no complex conditions |

**Pre-Merge Checklist Alignment**:
- [ ] All tests pass (`pytest`)
- [ ] Feature branch used (not direct to main)
- [ ] No secrets in committed files

## Project Structure

### Documentation (this feature)

```text
specs/001-daily-backtest-comparison/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (internal APIs)
└── tasks.md             # Phase 2 output (/speckit.tasks command)
```

### Source Code (repository root)

```text
trading/
├── risk/
│   ├── trade_logger.py          # Existing - reads actual trades
│   └── comparison_report.py     # NEW - report generation logic
├── notification/
│   └── telegram.py              # Existing - extend for report delivery
└── core/
    └── config.py                # Existing - add report config

scripts/
├── backtest.py                  # Existing - reuse for daily backtest
└── daily_comparison.py          # NEW - cron entry point

core/
└── backtester.py                # Existing - reuse for comparison

tests/
└── test_comparison_report.py    # NEW - unit/integration tests

data/
└── trading_results.db           # Existing - add comparison_reports table
```

**Structure Decision**: Extends existing single-project structure. New modules added to `trading/risk/` for report logic and `scripts/` for cron entry point. Reuses existing backtester and notification infrastructure.

## Complexity Tracking

No constitution violations requiring justification. Feature is a straightforward extension of existing infrastructure.
