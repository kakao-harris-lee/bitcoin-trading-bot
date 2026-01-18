# Feature Specification: Backtest MLflow Visualization

**Feature Branch**: `001-backtest-mlflow-viz`
**Created**: 2026-01-18
**Status**: Ready for Review
**Input**: User description: "Enhance the backtesting system with MLflow experiment tracking, parameter tuning history, and benchmark visualization showing price vs. return curves"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - View Backtest Results with Benchmark Comparison (Priority: P1)

As a trader running backtests, I want to see my strategy's equity curve plotted alongside the benchmark (buy-and-hold) price curve on a dual-axis chart, so I can visually compare strategy performance against simply holding the asset.

**Why this priority**: This is the core visualization need - understanding whether a strategy outperforms passive holding is the fundamental question every backtest must answer.

**Independent Test**: Run a single backtest and verify the output includes a dual-axis chart with strategy equity on the left y-axis and benchmark price on the right y-axis.

**Acceptance Scenarios**:

1. **Given** a completed backtest run, **When** I view the results, **Then** I see a chart with two y-axes: strategy equity (left) and benchmark price (right), both sharing the same x-axis (time).
2. **Given** a backtest where the strategy outperforms buy-and-hold, **When** I view the chart, **Then** the strategy line ends above its starting point relative to the benchmark line's proportional change.
3. **Given** a backtest with no trades executed, **When** I view the results, **Then** the strategy equity line remains flat while the benchmark shows actual price movement.

---

### User Story 2 - Record Experiments to MLflow (Priority: P2)

As a trader tuning strategy parameters, I want each backtest run automatically logged to MLflow with parameters, metrics, and artifacts, so I can track experiment history and compare different configurations.

**Why this priority**: MLflow tracking enables systematic parameter tuning and prevents losing valuable experiment data. This builds on P1 by persisting the visualizations.

**Independent Test**: Run a backtest and verify that MLflow UI shows the run with correct parameters, metrics (total return, Sharpe ratio, max drawdown), and the visualization chart as an artifact.

**Acceptance Scenarios**:

1. **Given** MLflow is configured, **When** I run a backtest, **Then** a new run is created in MLflow with strategy name, symbol, timeframe, and all strategy parameters logged.
2. **Given** a completed backtest, **When** the run is logged, **Then** metrics include: total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate, total_trades, and benchmark_return_pct.
3. **Given** a completed backtest with visualization, **When** I view the MLflow run, **Then** the dual-axis chart is saved as an artifact I can view/download.

---

### User Story 3 - Compare Multiple Experiment Runs (Priority: P3)

As a trader who has run multiple backtests with different parameters, I want to compare runs side-by-side in MLflow, filtering and sorting by metrics, so I can identify the best-performing configurations.

**Why this priority**: Comparison across runs is valuable but depends on P2 (recording) being complete first.

**Independent Test**: Run 3+ backtests with different parameters, open MLflow UI, select runs, and verify comparison view shows metrics side-by-side.

**Acceptance Scenarios**:

1. **Given** multiple backtest runs logged to MLflow, **When** I open the MLflow UI, **Then** I can filter runs by strategy name and sort by any metric (e.g., Sharpe ratio).
2. **Given** I select 2+ runs in MLflow, **When** I click compare, **Then** I see a table with parameters and metrics side-by-side and can identify differences.

---

### User Story 4 - Run Parameter Sweep with MLflow Tracking (Priority: P4)

As a trader exploring parameter space, I want to run a parameter sweep that automatically tests multiple parameter combinations and logs each to MLflow, so I can efficiently find optimal settings.

**Why this priority**: Parameter sweeps are an advanced use case that depends on all prior stories being complete.

**Independent Test**: Define a sweep config with 2 parameters x 3 values each (9 combinations), run sweep, verify 9 MLflow runs created with correct parameters.

**Acceptance Scenarios**:

1. **Given** a parameter sweep configuration, **When** I run the sweep, **Then** each parameter combination is tested and logged as a separate MLflow run.
2. **Given** a completed parameter sweep, **When** I view MLflow, **Then** all runs are grouped under the same experiment with consistent tagging for easy filtering.

---

### Edge Cases

- What happens when MLflow server is unavailable? System should log warning and continue backtest without tracking.
- How does system handle very long backtests (1000+ trades)? Charts should downsample data points for performance.
- What if benchmark data is unavailable for the backtest period? Show strategy-only chart with clear indication benchmark is missing.
- What happens on backtest failure mid-run? Partial results should still be logged with "failed" status.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST generate a dual-axis visualization showing strategy equity curve and benchmark price curve on shared time axis
- **FR-002**: System MUST calculate and display benchmark return (buy-and-hold) for the same period as the backtest
- **FR-003**: System MUST log backtest runs to MLflow when MLflow tracking is enabled
- **FR-004**: System MUST log these parameters to MLflow: strategy_name, symbol, timeframe, start_date, end_date, and all strategy-specific parameters
- **FR-005**: System MUST log these metrics to MLflow: total_return_pct, sharpe_ratio, max_drawdown_pct, win_rate, total_trades, profit_factor, benchmark_return_pct
- **FR-006**: System MUST save the visualization chart as an MLflow artifact (PNG format)
- **FR-007**: System MUST gracefully degrade when MLflow is unavailable (continue backtest, log warning)
- **FR-008**: System MUST support disabling MLflow tracking via configuration flag
- **FR-009**: System MUST organize runs under configurable MLflow experiment names
- **FR-010**: System MUST support parameter sweep execution with automatic MLflow logging per combination

### Key Entities

- **BacktestResult**: Contains equity_curve (time series), trades list, metrics dict, benchmark_curve (time series)
- **MLflowConfig**: tracking_uri, experiment_name, enabled flag, artifact_location
- **ParameterSweep**: strategy_name, parameter_grid (dict of param -> values list), base_config

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Backtest visualization renders in under 2 seconds for backtests with up to 500 trades
- **SC-002**: MLflow run logging completes within 5 seconds of backtest completion
- **SC-003**: Parameter sweep of 20 combinations completes and logs all runs without manual intervention
- **SC-004**: 100% of backtest runs are traceable in MLflow when tracking is enabled (no silent failures)
- **SC-005**: Visualization clearly shows both axes with appropriate labels, legend, and readable scales
