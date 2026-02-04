# Quant Lab Design

**Date:** 2026-01-20
**Status:** Approved
**Purpose:** Web-based experiment workbench for regime-based strategy optimization

## Overview

The Quant Lab designs experiments in a web UI (Input), performs Bayesian optimization in the background (Process), and analyzes results with MLflow (Output) to select optimal strategy configurations.

### Core Problem

Regime-Based Strategy Combination Optimization has a vast search space:
- 7 market regimes (BULL_STRONG → BEAR_STRONG)
- Multiple Entry/Exit component combinations per regime
- Continuous parameter tuning within each component
- ~268 million discrete combinations before parameter tuning

Grid search is infeasible. Bayesian optimization (Optuna) efficiently explores this space.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        QUANT LAB                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│   ┌──────────────┐    ┌──────────────┐    ┌──────────────┐     │
│   │   WEB UI     │    │   WORKER     │    │   MLFLOW     │     │
│   │  (Flask)     │───▶│  (RQ/Redis)  │───▶│  (Tracking)  │     │
│   └──────────────┘    └──────────────┘    └──────────────┘     │
│          │                   │                   │              │
│          │            ┌──────┴──────┐            │              │
│          │            │   OPTUNA    │            │              │
│          │            │  NSGA-II    │            │              │
│          │            └──────┬──────┘            │              │
│          │                   │                   │              │
│          │            ┌──────┴──────┐            │              │
│          │            │ BACKTESTER  │            │              │
│          │            │ + Adapter   │            │              │
│          └────────────┴─────────────┴────────────┘              │
│                              │                                  │
│                    Existing Infrastructure                      │
└─────────────────────────────────────────────────────────────────┘
```

### Components

| Component | Technology | Purpose |
|-----------|------------|---------|
| Web UI | Flask (existing) | Experiment designer, job monitor, results viewer |
| Worker | RQ + Redis | Background job execution, survives restarts |
| Optimizer | Optuna NSGA-II | Multi-objective Bayesian search |
| Backtester | ComponentStrategyAdapter | Evaluates each trial configuration |
| Tracking | MLflowTracker | Logs all trials, metrics, configurations |

## Search Space

### Structure

For each of the 7 regimes, select an Entry/Exit component pair and tune parameters:

```python
{
    "BULL_STRONG": {
        "entry": Choice(["V35Entry", "SidewaysEntry", "ShortEntry", "None"]),
        "exit": Choice(["V35TrailingExit", "V35PersistentExit", "ExperimentalExit", "SidewaysExit"]),
        "params": {
            "mfi_threshold": Float(45, 65),
            "adx_threshold": Float(15, 35),
            "trailing_stop_pct": Float(0.5, 5.0),
            # ... component-specific params
        }
    },
    "BULL_MODERATE": { ... },
    "SIDEWAYS_UP": { ... },
    "SIDEWAYS_FLAT": { ... },
    "SIDEWAYS_DOWN": { ... },
    "BEAR_MODERATE": { ... },
    "BEAR_STRONG": { ... }
}
```

### Key Decisions

- **Joint optimization**: All 7 regimes optimized together (captures regime transitions)
- **"None" option**: Allows optimizer to skip trading in certain regimes
- **Conditional parameters**: Only expose params relevant to selected Entry/Exit

## Optimization

### Multi-Objective Pareto

Three objectives define the Pareto frontier:

| Metric | Direction | Purpose |
|--------|-----------|---------|
| Win Rate % | Maximize | Consistency |
| Total Return % | Maximize | Profitability |
| Max Drawdown % | Minimize | Risk control |

Optuna's NSGA-II sampler finds non-dominated solutions. Users select their preferred tradeoff from the Pareto frontier.

### Constraints

Users can set:

1. **Time budget**: Max trials (e.g., 500) or max hours (e.g., 2)
2. **Parameter bounds**: e.g., "Trailing stop must be 1-5%"
3. **Strategy constraints**: e.g., "Always use V35Entry in BULL_STRONG"
4. **Risk guardrails**: e.g., "Reject trials with >30% max drawdown"
5. **Data range**: Backtest period selection

## Web UI

### Hybrid Approach

Templates for quick start, Advanced mode for full control.

### Templates

| Template | Description |
|----------|-------------|
| V35 Parameter Sweep | Fixed V35Entry/Exit for BULL regimes, tune params only |
| Full Regime Search | All Entry/Exit combinations across all 7 regimes |
| Conservative Search | Excludes "None", ensures always-in-market |
| Bear Market Focus | Only optimizes BEAR_MODERATE and BEAR_STRONG |

### Advanced Mode (Wizard)

```
Step 1: Data Range
  - Start/End dates
  - Asset selection (BTC, ETH, SOL)

Step 2: Search Space
  - Per-regime Entry/Exit checkboxes
  - Include/exclude "None" option

Step 3: Parameter Bounds
  - Sliders for each parameter range

Step 4: Constraints & Budget
  - Max trials or max hours
  - Risk guardrails
  - Strategy locks

Step 5: Review & Launch
```

## Results Visualization

### Three-Tier Display

**Tier 1: Pareto Frontier Plot**
- Interactive 3D scatter (Plotly.js)
- Axes: Win Rate vs Total Return
- Bubble size: inverse Max Drawdown
- Click point to see configuration

**Tier 2: Ranked Table**
- Sortable by any metric
- Expandable rows show regime-by-regime breakdown
- [View] details, [Apply] exports to allocation.json

**Tier 3: MLflow Integration**
- "Open in MLflow" button
- Full parameter comparison, metric charts, artifacts

## Job Management

### Background Worker

```
Flask Web UI ──▶ Redis Queue ──▶ RQ Worker (separate process)
      ▲                              │
      └──── Job Status Updates ──────┘
```

### Job Lifecycle

1. **Created** - User clicks "Launch Experiment"
2. **Queued** - Job added to Redis queue
3. **Running** - Worker executes, Optuna begins trials
4. **Progress** - Real-time updates via Redis pub/sub
5. **Completed** - Results in MLflow, notification shown
6. **Failed** - Error logged, partial results preserved

### Persistence

- Job definitions: Redis hash
- Optuna study: SQLite (survives restarts)
- Worker can resume interrupted jobs

### Job Control

- Pause/Resume
- Cancel (preserves partial results)
- View partial results during run

## File Structure

```
bitcoin-trading-bot/
├── web/
│   ├── app.py                          # Register quant_lab blueprint
│   ├── quant_lab/                      # New submodule
│   │   ├── __init__.py
│   │   ├── routes.py                   # /quant-lab/* endpoints
│   │   ├── optimizer/
│   │   │   ├── __init__.py
│   │   │   ├── search_space.py         # Regime-based search space definition
│   │   │   ├── objective.py            # Multi-objective function
│   │   │   ├── constraints.py          # Risk guardrails, early pruning
│   │   │   └── study_manager.py        # Optuna study lifecycle
│   │   └── worker/
│   │       ├── __init__.py
│   │       ├── tasks.py                # RQ task definitions
│   │       └── runner.py               # Worker entry point
│   ├── templates/
│   │   └── quant_lab/
│   │       ├── designer.html           # Experiment wizard
│   │       ├── monitor.html            # Job status dashboard
│   │       └── results.html            # Pareto plot + table
│   └── static/
│       └── quant_lab/
│           ├── pareto_plot.js          # Plotly visualization
│           └── quant_lab.css
├── config/
│   └── experiment_templates/           # Pre-built experiment configs
│       ├── full_regime_search.json
│       └── conservative_search.json
```

## Integration Points

| Existing Component | Integration |
|--------------------|-------------|
| Backtester | Uses `ComponentStrategyAdapter` unchanged |
| MLflow | Uses `MLflowTracker` unchanged |
| Strategy Factory | Uses `param_overrides` mechanism |
| Flask App | Register blueprint at `/quant-lab` |
| Redis | Reuses connection, adds `quant_lab:*` namespace |

## Access Model

- Single-user system
- No authentication required
- Local deployment

## Out of Scope

- Multi-user accounts
- Distributed workers
- Real-time collaboration
- Strategy code editor in UI

## Dependencies

New packages required:
- `rq` - Redis Queue for background jobs
- `plotly` - Interactive Pareto visualization (if not already installed)

Existing packages used:
- `optuna` - Already used in optimize scripts
- `mlflow` - Already integrated
- `flask` - Already used for dashboard

## Success Criteria

1. User can design experiment via templates or wizard
2. Optimization runs in background without blocking UI
3. Jobs survive server restarts
4. Pareto frontier clearly visualizes tradeoffs
5. Selected configuration can be exported to allocation.json
6. All trials logged to MLflow for analysis
