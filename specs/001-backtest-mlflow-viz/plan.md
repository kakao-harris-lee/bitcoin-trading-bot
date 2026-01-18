# Implementation Plan: Backtest MLflow Visualization

**Branch**: `001-backtest-mlflow-viz` | **Date**: 2026-01-18 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/001-backtest-mlflow-viz/spec.md`

## Summary

Enhance the existing backtesting system (`core/backtester.py`) with:
1. **Dual-axis visualization** showing strategy equity curve vs benchmark (buy-and-hold) price
2. **MLflow integration** for experiment tracking, parameter logging, and artifact storage
3. **Parameter sweep functionality** with automatic MLflow logging

## Technical Context

**Language/Version**: Python 3.9+ (per requirements.txt)
**Primary Dependencies**:
- Existing: pandas, numpy, matplotlib, plotly (visualization)
- New: mlflow (experiment tracking)
**Storage**: MLflow local file store (./mlruns) for development, configurable for production
**Testing**: pytest, pytest-asyncio (existing test infrastructure)
**Target Platform**: Linux server, macOS development
**Project Type**: Single project - CLI tools and libraries
**Performance Goals**:
- Visualization renders < 2 seconds for 500 trades
- MLflow logging < 5 seconds per run
**Constraints**:
- Graceful degradation when MLflow unavailable
- Backward compatible with existing backtest API
**Scale/Scope**: Individual developer use, 100s of experiment runs

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### Pre-Research Check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Backtesting-First | PASS | This feature enhances backtesting capabilities |
| II. Git-Based Workflow | PASS | Feature branch already created |
| III. Risk-Aware Design | N/A | Not trading logic, visualization only |
| IV. Reactive Strategies Only | N/A | Not strategy logic |
| V. Simplicity | PASS | Adding MLflow is standard, no over-engineering |

**Pre-Research Gate Result**: PASS - No violations

### Post-Design Re-check

| Principle | Status | Notes |
|-----------|--------|-------|
| I. Backtesting-First | PASS | Design includes Sharpe ratio calculation per constitution requirements (>=1.5) |
| II. Git-Based Workflow | PASS | Feature branch `001-backtest-mlflow-viz` in use |
| III. Risk-Aware Design | PASS | Max drawdown tracking included as per constitution (<=20%) |
| IV. Reactive Strategies Only | N/A | Feature is tooling, not strategy |
| V. Simplicity | PASS | 3 new modules (visualizer, tracker, sweep) - minimal, focused responsibilities |

**Post-Design Gate Result**: PASS - Design aligns with constitution

**Constitution Alignment**:
- Sharpe ratio calculation follows constitution requirement (Sharpe >= 1.5)
- Max drawdown tracking enables validation against 20% limit
- Benchmark comparison supports OOS return validation (>=15%)

## Project Structure

### Documentation (this feature)

```text
specs/001-backtest-mlflow-viz/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output (CLI interface)
└── tasks.md             # Phase 2 output
```

### Source Code (repository root)

```text
core/
├── backtester.py           # MODIFY: Add benchmark tracking, MLflow integration
├── backtest_visualizer.py  # NEW: Dual-axis chart generation
├── mlflow_tracker.py       # NEW: MLflow integration wrapper
└── parameter_sweep.py      # NEW: Grid search with MLflow logging

tests/
├── unit/
│   ├── test_backtest_visualizer.py  # NEW
│   ├── test_mlflow_tracker.py       # NEW
│   └── test_parameter_sweep.py      # NEW
└── integration/
    └── test_backtest_mlflow.py      # NEW: End-to-end tests

config/
└── mlflow.json             # NEW: MLflow configuration
```

**Structure Decision**: Single project structure. New modules added to `core/` alongside existing `backtester.py`. Tests follow existing pattern in `tests/`.

## Complexity Tracking

> No Constitution Check violations requiring justification.

## Phase 0: Research Items

1. **MLflow best practices** for local experiment tracking
2. **Matplotlib dual-axis** chart patterns for financial data
3. **Benchmark calculation** methodology (buy-and-hold return)
4. **Sharpe ratio** calculation from equity curve

## Phase 1: Design Deliverables

1. `research.md` - Resolved research questions
2. `data-model.md` - BacktestResult, MLflowConfig entities
3. `contracts/cli.md` - CLI interface specification
4. `quickstart.md` - Developer getting started guide
