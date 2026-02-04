# Data Model: Backtest MLflow Visualization

**Date**: 2026-01-18
**Status**: Complete

## Entities

### 1. BacktestResult (Enhanced)

Extends existing backtest results with benchmark data and enhanced metrics.

```python
@dataclass
class BacktestResult:
    """Complete backtest result with benchmark comparison."""

    # Identification
    strategy_name: str
    symbol: str
    start_date: datetime
    end_date: datetime

    # Capital tracking
    initial_capital: float
    final_capital: float
    total_return_pct: float

    # Trade statistics
    total_trades: int
    winning_trades: int
    losing_trades: int
    win_rate: float  # 0.0 to 1.0

    # Risk metrics
    sharpe_ratio: float
    max_drawdown_pct: float
    profit_factor: float  # gross_profit / gross_loss

    # Time series data
    equity_curve: pd.DataFrame  # timestamp, cash, position_value, total_equity
    trades: List[Trade]  # Individual trade records

    # NEW: Benchmark data
    benchmark_curve: pd.Series  # timestamp -> benchmark_equity
    benchmark_return_pct: float

    # Strategy parameters (for MLflow logging)
    params: Dict[str, Any]
```

**Field Descriptions**:

| Field | Type | Description |
|-------|------|-------------|
| `strategy_name` | str | Strategy identifier (e.g., "v35_classic_wide") |
| `symbol` | str | Trading symbol (e.g., "BTC", "ETH") |
| `start_date` | datetime | Backtest start timestamp |
| `end_date` | datetime | Backtest end timestamp |
| `initial_capital` | float | Starting capital |
| `final_capital` | float | Ending capital |
| `total_return_pct` | float | Strategy return percentage |
| `sharpe_ratio` | float | Annualized Sharpe ratio |
| `max_drawdown_pct` | float | Maximum peak-to-trough decline % |
| `profit_factor` | float | Gross profit / gross loss |
| `equity_curve` | DataFrame | Time series of portfolio value |
| `benchmark_curve` | Series | Time series of buy-and-hold value |
| `benchmark_return_pct` | float | Buy-and-hold return percentage |
| `params` | Dict | Strategy parameters for logging |

---

### 2. MLflowConfig

Configuration for MLflow integration.

```python
@dataclass
class MLflowConfig:
    """MLflow tracking configuration."""

    enabled: bool = True
    tracking_uri: str = "./mlruns"
    experiment_name: str = "backtest-experiments"
    artifact_location: Optional[str] = None

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "MLflowConfig":
        """Create from configuration dictionary."""
        mlflow_config = config.get("mlflow", {})
        return cls(
            enabled=mlflow_config.get("enabled", True),
            tracking_uri=mlflow_config.get("tracking_uri", "./mlruns"),
            experiment_name=mlflow_config.get("experiment_name", "backtest-experiments"),
            artifact_location=mlflow_config.get("artifact_location"),
        )

    @classmethod
    def from_env(cls) -> "MLflowConfig":
        """Create from environment variables."""
        import os
        return cls(
            enabled=os.getenv("MLFLOW_ENABLED", "true").lower() == "true",
            tracking_uri=os.getenv("MLFLOW_TRACKING_URI", "./mlruns"),
            experiment_name=os.getenv("MLFLOW_EXPERIMENT_NAME", "backtest-experiments"),
            artifact_location=os.getenv("MLFLOW_ARTIFACT_LOCATION"),
        )
```

**Validation Rules**:
- `tracking_uri` must be valid path or URL
- `experiment_name` must be non-empty string
- `artifact_location` can be None (uses default)

---

### 3. ParameterSweep

Configuration for parameter grid search.

```python
@dataclass
class ParameterSweep:
    """Parameter sweep configuration."""

    strategy_name: str
    symbol: str
    parameter_grid: Dict[str, List[Any]]
    base_config: Dict[str, Any]

    # Execution settings
    parallel: bool = False  # Future: parallel execution
    max_combinations: Optional[int] = None  # Limit total runs

    def generate_combinations(self) -> Iterator[Dict[str, Any]]:
        """Generate all parameter combinations."""
        from itertools import product

        keys = list(self.parameter_grid.keys())
        values = list(self.parameter_grid.values())

        count = 0
        for combo in product(*values):
            if self.max_combinations and count >= self.max_combinations:
                break

            config = self.base_config.copy()
            for key, value in zip(keys, combo):
                config[key] = value

            yield config
            count += 1

    @property
    def total_combinations(self) -> int:
        """Calculate total number of combinations."""
        from functools import reduce
        from operator import mul

        total = reduce(mul, (len(v) for v in self.parameter_grid.values()), 1)
        if self.max_combinations:
            return min(total, self.max_combinations)
        return total
```

**Example Usage**:
```python
sweep = ParameterSweep(
    strategy_name="v35_classic_wide",
    symbol="BTC",
    parameter_grid={
        "stop_loss_pct": [1.0, 1.5, 2.0],
        "take_profit_pct": [2.0, 3.0, 4.0],
    },
    base_config={
        "position_size": 0.01,
        "trailing_enabled": True,
    },
)

# Generates 9 combinations
for config in sweep.generate_combinations():
    result = backtester.run_strategy(df, "v35_classic_wide", config)
```

---

### 4. VisualizationConfig

Configuration for chart generation.

```python
@dataclass
class VisualizationConfig:
    """Chart visualization settings."""

    width: int = 12  # inches
    height: int = 6  # inches
    dpi: int = 150
    format: str = "png"  # png, svg, pdf

    # Colors
    strategy_color: str = "#1f77b4"  # Blue
    benchmark_color: str = "#ff7f0e"  # Orange

    # Style
    strategy_linestyle: str = "-"
    benchmark_linestyle: str = "--"
    grid: bool = True
    legend_location: str = "upper left"

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "VisualizationConfig":
        """Create from configuration dictionary."""
        viz_config = config.get("visualization", {})
        return cls(
            width=viz_config.get("chart_width", 12),
            height=viz_config.get("chart_height", 6),
            dpi=viz_config.get("dpi", 150),
            format=viz_config.get("format", "png"),
        )
```

---

## Entity Relationships

```
┌─────────────────┐
│ BacktestResult  │
├─────────────────┤
│ equity_curve    │──────┐
│ benchmark_curve │──────┼──► Chart Generation
│ trades          │      │
│ params          │──────┼──► MLflow Logging
└─────────────────┘      │
                         │
┌─────────────────┐      │
│ MLflowConfig    │──────┘
├─────────────────┤
│ tracking_uri    │──► MLflow Tracking Server
│ experiment_name │
└─────────────────┘

┌─────────────────┐
│ ParameterSweep  │
├─────────────────┤
│ parameter_grid  │──► Generates configs
│ base_config     │
└───────┬─────────┘
        │
        ▼ (1 to N)
┌─────────────────┐
│ BacktestResult  │
└─────────────────┘
```

---

## State Transitions

### BacktestResult Lifecycle

```
[Created] ──► [Metrics Calculated] ──► [Chart Generated] ──► [Logged to MLflow]
    │                 │                      │                      │
    └── equity_curve  └── sharpe_ratio       └── chart_path         └── run_id
        populated         max_drawdown            saved                 returned
                          profit_factor
```

### ParameterSweep Execution

```
[Configured] ──► [Generating] ──► [Running] ──► [Complete]
      │               │              │              │
      └── grid        └── combos     └── results    └── all runs
          defined         yielded        collected       logged
```

---

## JSON Schema

### config/mlflow.json

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "type": "object",
  "properties": {
    "mlflow": {
      "type": "object",
      "properties": {
        "enabled": { "type": "boolean", "default": true },
        "tracking_uri": { "type": "string", "default": "./mlruns" },
        "experiment_name": { "type": "string", "default": "backtest-experiments" },
        "artifact_location": { "type": ["string", "null"], "default": null }
      }
    },
    "visualization": {
      "type": "object",
      "properties": {
        "chart_width": { "type": "integer", "default": 12, "minimum": 4 },
        "chart_height": { "type": "integer", "default": 6, "minimum": 3 },
        "dpi": { "type": "integer", "default": 150, "minimum": 72 },
        "format": { "type": "string", "enum": ["png", "svg", "pdf"], "default": "png" }
      }
    }
  }
}
```
