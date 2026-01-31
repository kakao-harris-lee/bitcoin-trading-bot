# V35 Unified Tuning Framework - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create unified V35 parameter tuning with $10k capital and spot fees.

**Architecture:** Extend Quant Lab with V35-specific optimization.

**Tech Stack:** Python, Optuna, Flask, RQ

---

## Task 1: Create V35 Search Space Module

**Files:**
- Create: `web/quant_lab/optimizer/v35_search_space.py`
- Test: `tests/web/quant_lab/test_v35_search_space.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_v35_search_space.py
import pytest
from web.quant_lab.optimizer.v35_search_space import (
    V35_PARAM_GROUPS,
    V35_STRATEGY_PARAMS,
    get_strategy_param_groups,
    sample_v35_config,
)

class TestV35ParamGroups:
    def test_param_groups_defined(self):
        assert "risk" in V35_PARAM_GROUPS
        assert "sizing" in V35_PARAM_GROUPS
        assert "trailing" in V35_PARAM_GROUPS
        assert "take_profit" in V35_PARAM_GROUPS
        assert "core_overlay" in V35_PARAM_GROUPS

    def test_risk_params_have_bounds(self):
        risk = V35_PARAM_GROUPS["risk"]
        assert "stop_loss_pct" in risk
        assert risk["stop_loss_pct"] == (2.0, 10.0)

class TestGetStrategyParamGroups:
    def test_v35_long_v2_returns_correct_groups(self):
        groups = get_strategy_param_groups("v35_long_v2")
        assert "risk" in groups
        assert "sizing" in groups
        assert "core_overlay" not in groups

    def test_core_overlay_includes_all_groups(self):
        groups = get_strategy_param_groups("tuned_v35_long_v2_core_overlay")
        assert "core_overlay" in groups
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/web/quant_lab/test_v35_search_space.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Write minimal implementation**

```python
# web/quant_lab/optimizer/v35_search_space.py
"""V35-specific search space for parameter tuning."""
from typing import Dict, List, Tuple, Any
import optuna

# Parameter groups with (min, max) bounds
V35_PARAM_GROUPS: Dict[str, Dict[str, Tuple[float, float]]] = {
    "risk": {
        "stop_loss_pct": (2.0, 10.0),
        "atr_stop_multiplier": (2.0, 5.0),
        "atr_stop_min_pct": (2.0, 6.0),
        "atr_stop_max_pct": (5.0, 18.0),
        "drawdown_warning_pct": (8.0, 15.0),
        "drawdown_reduce_pct": (10.0, 18.0),
        "drawdown_exit_pct": (15.0, 25.0),
        "drawdown_partial_exit_fraction": (0.15, 0.50),
    },
    "sizing": {
        "position_size_high": (0.15, 0.40),
        "position_size_mid": (0.08, 0.20),
        "position_size_low": (0.03, 0.10),
        "position_conf_low": (0.45, 0.60),
        "position_conf_high": (0.65, 0.80),
    },
    "trailing": {
        "trailing_activation": (2.0, 20.0),
        "trailing_distance": (1.0, 12.0),
    },
    "take_profit": {
        "tp_bull_strong_1": (5.0, 30.0),
        "tp_bull_strong_2": (15.0, 70.0),
        "tp_bull_strong_3": (30.0, 140.0),
        "tp_bull_moderate_1": (4.0, 25.0),
        "tp_bull_moderate_2": (12.0, 60.0),
        "tp_bull_moderate_3": (25.0, 120.0),
        "exit_fraction_1": (0.05, 0.25),
        "exit_fraction_2": (0.05, 0.30),
        "exit_fraction_3": (0.50, 0.90),
    },
    "core_overlay": {
        "core_hold_pct": (0.40, 0.80),
        "core_drawdown_exit_pct": (15.0, 25.0),
        "core_drawdown_reentry_pct": (5.0, 15.0),
    },
}

# Which parameter groups apply to each strategy
V35_STRATEGY_PARAMS: Dict[str, List[str]] = {
    "v35_long": ["risk", "trailing"],
    "v35_long_v2": ["risk", "sizing", "trailing"],
    "tuned_v35_long_v2_growth": ["risk", "sizing", "trailing", "take_profit"],
    "tuned_v35_long_v2_hold": ["risk", "sizing", "trailing", "take_profit"],
    "tuned_v35_long_v2_core_overlay": ["risk", "sizing", "trailing", "take_profit", "core_overlay"],
    "tuned_v35_long_v2_core_overlay_v2": ["risk", "sizing", "trailing", "take_profit", "core_overlay"],
}


def get_strategy_param_groups(strategy_name: str) -> List[str]:
    """Get applicable parameter groups for a strategy."""
    return V35_STRATEGY_PARAMS.get(strategy_name, ["risk", "trailing"])


def sample_v35_config(
    trial: optuna.Trial,
    strategy_name: str,
    enabled_groups: List[str] | None = None,
) -> Dict[str, Any]:
    """Sample configuration from Optuna trial for V35 strategy."""
    if enabled_groups is None:
        enabled_groups = get_strategy_param_groups(strategy_name)

    config = {}
    for group_name in enabled_groups:
        if group_name not in V35_PARAM_GROUPS:
            continue
        for param_name, (low, high) in V35_PARAM_GROUPS[group_name].items():
            config[param_name] = trial.suggest_float(param_name, low, high)

    return config
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/web/quant_lab/test_v35_search_space.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/optimizer/v35_search_space.py tests/web/quant_lab/test_v35_search_space.py
git commit -m "feat(quant-lab): add V35-specific search space module

- Define parameter groups: risk, sizing, trailing, take_profit, core_overlay
- Map strategies to applicable parameter groups
- Add sample_v35_config for Optuna integration

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 2: Create V35 Objective Function

**Files:**
- Create: `web/quant_lab/optimizer/v35_objective.py`
- Test: `tests/web/quant_lab/test_v35_objective.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_v35_objective.py
import pytest
from unittest.mock import patch, MagicMock
import optuna
from web.quant_lab.optimizer.v35_objective import (
    GrowthObjective,
    calculate_growth_score,
)

class TestCalculateGrowthScore:
    def test_good_return_low_mdd(self):
        score = calculate_growth_score(
            total_return=1.20,  # 120%
            max_drawdown=0.18,  # 18%
            sharpe_ratio=1.5,
        )
        # 1.20 + 0.05 sharpe bonus = 1.25
        assert score > 1.2

    def test_high_mdd_penalty(self):
        score = calculate_growth_score(
            total_return=1.50,
            max_drawdown=0.28,  # 28% > 25%
            sharpe_ratio=1.0,
        )
        # 1.50 - 0.06 penalty = 1.44
        assert score < 1.50

    def test_extreme_mdd_pruned(self):
        with pytest.raises(optuna.TrialPruned):
            calculate_growth_score(
                total_return=2.0,
                max_drawdown=0.35,  # 35% > 30%
                sharpe_ratio=0.5,
            )
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/web/quant_lab/test_v35_objective.py -v`
Expected: FAIL

**Step 3: Write implementation**

```python
# web/quant_lab/optimizer/v35_objective.py
"""Growth-focused objective function for V35 optimization."""
from dataclasses import dataclass
from typing import Dict, Any, Optional
import optuna

from .v35_search_space import sample_v35_config


def calculate_growth_score(
    total_return: float,
    max_drawdown: float,
    sharpe_ratio: float,
    mdd_soft_limit: float = 0.25,
    mdd_hard_limit: float = 0.30,
) -> float:
    """
    Calculate growth-focused score with MDD constraints.

    Args:
        total_return: Total return as decimal (1.0 = 100%)
        max_drawdown: Max drawdown as decimal (0.25 = 25%)
        sharpe_ratio: Sharpe ratio
        mdd_soft_limit: MDD threshold for soft penalty
        mdd_hard_limit: MDD threshold for pruning

    Returns:
        Composite score (higher is better)

    Raises:
        optuna.TrialPruned: If MDD exceeds hard limit
    """
    if max_drawdown > mdd_hard_limit:
        raise optuna.TrialPruned(f"MDD {max_drawdown:.1%} exceeded {mdd_hard_limit:.0%}")

    # Soft penalty for MDD above soft limit
    mdd_penalty = max(0, (max_drawdown - mdd_soft_limit) * 2.0)

    # Sharpe bonus for risk-adjusted quality
    sharpe_bonus = max(0, (sharpe_ratio - 1.0) * 0.1)

    return total_return - mdd_penalty + sharpe_bonus


@dataclass
class GrowthObjective:
    """Optuna objective for V35 growth optimization."""

    strategy_name: str
    data_path: str
    start_date: str
    end_date: str
    symbol: str = "BTC"
    capital: float = 10_000.0
    enabled_groups: list = None

    def __call__(self, trial: optuna.Trial) -> float:
        """Evaluate trial and return growth score."""
        config = sample_v35_config(
            trial,
            self.strategy_name,
            self.enabled_groups,
        )

        results = self._run_backtest(config)

        return calculate_growth_score(
            total_return=results["total_return"],
            max_drawdown=results["max_drawdown"],
            sharpe_ratio=results["sharpe_ratio"],
        )

    def _run_backtest(self, config: Dict[str, Any]) -> Dict[str, float]:
        """Run backtest with ComponentStrategyAdapter."""
        import sys
        from pathlib import Path

        # Ensure project root in path
        project_root = Path(__file__).parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))

        from core.data_loader import DataLoader
        from core.backtester import Backtester
        from core.component_adapter import ComponentStrategyAdapter
        from trading.strategies.components import StrategyFactory
        from trading.indicators import add_all_indicators

        # Load data
        loader = DataLoader(db_path=self.data_path)
        df = loader.load_timeframe(
            timeframe="minute60",
            start_date=self.start_date,
            end_date=self.end_date,
        )
        df = add_all_indicators(df)

        # Merge trial config with base strategy config
        import json
        config_path = project_root / "config/strategies/allocation.json"
        with open(config_path) as f:
            allocation = json.load(f)

        base_config = allocation.get("strategies", {}).get(self.strategy_name, {})
        full_config = {**base_config, **config}

        # Create adapter
        factory = StrategyFactory()
        adapter = ComponentStrategyAdapter(
            factory=factory,
            strategy_name=self.strategy_name,
            config=full_config,
        )
        adapter.symbol = self.symbol

        # Pre-compute RF predictions if enabled
        if full_config.get("use_rf_probability", False):
            try:
                adapter.precompute_rf_predictions(df)
            except Exception:
                pass  # RF not available, continue without

        # Run backtest with spot settings
        backtester = Backtester(
            initial_capital=self.capital,
            fee_rate=0.001,  # 0.1% spot
            slippage=0.0004,
            market="spot",
        )

        results = backtester.run(df, adapter)

        return {
            "total_return": results["total_return"] / 100,
            "max_drawdown": abs(results.get("max_drawdown_pct", 0)) / 100,
            "sharpe_ratio": results.get("sharpe_ratio", 0),
            "win_rate": results.get("win_rate", 0),
            "total_trades": results.get("total_trades", 0),
        }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/web/quant_lab/test_v35_objective.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/optimizer/v35_objective.py tests/web/quant_lab/test_v35_objective.py
git commit -m "feat(quant-lab): add growth-focused V35 objective function

- Growth score: return - MDD penalty + Sharpe bonus
- Prune trials with MDD > 30%
- Use ComponentStrategyAdapter for full V35 feature support
- Auto-detect spot fees ($10k capital, 0.1% fee)

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 3: Add V35 API Endpoint

**Files:**
- Modify: `web/quant_lab/routes.py`
- Test: `tests/web/quant_lab/test_v35_routes.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_v35_routes.py
import pytest
from flask import Flask
from web.quant_lab.routes import quant_lab

@pytest.fixture
def client():
    app = Flask(__name__)
    app.register_blueprint(quant_lab, url_prefix="/quant-lab")
    app.config["TESTING"] = True
    return app.test_client()

class TestV35Routes:
    def test_v35_strategies_endpoint(self, client):
        response = client.get("/quant-lab/api/v35/strategies")
        assert response.status_code == 200
        data = response.get_json()
        assert "v35_long_v2" in data["strategies"]

    def test_v35_param_groups_endpoint(self, client):
        response = client.get("/quant-lab/api/v35/param-groups/v35_long_v2")
        assert response.status_code == 200
        data = response.get_json()
        assert "risk" in data["groups"]
        assert "sizing" in data["groups"]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/web/quant_lab/test_v35_routes.py -v`
Expected: FAIL

**Step 3: Add endpoints to routes.py**

```python
# Add to web/quant_lab/routes.py

from .optimizer.v35_search_space import (
    V35_STRATEGY_PARAMS,
    V35_PARAM_GROUPS,
    get_strategy_param_groups,
)

@quant_lab.route("/api/v35/strategies")
def get_v35_strategies():
    """List available V35 strategies for tuning."""
    return jsonify({
        "strategies": list(V35_STRATEGY_PARAMS.keys()),
    })

@quant_lab.route("/api/v35/param-groups/<strategy_name>")
def get_v35_param_groups(strategy_name: str):
    """Get applicable parameter groups for a strategy."""
    groups = get_strategy_param_groups(strategy_name)
    return jsonify({
        "strategy": strategy_name,
        "groups": groups,
        "params": {g: V35_PARAM_GROUPS.get(g, {}) for g in groups},
    })

@quant_lab.route("/api/v35/optimize", methods=["POST"])
def start_v35_optimization():
    """Start V35 parameter optimization job."""
    from rq import Queue
    from redis import Redis
    from .worker.tasks import run_v35_optimization

    data = request.get_json()
    strategy_name = data.get("strategy")
    param_groups = data.get("param_groups", [])
    n_trials = data.get("n_trials", 100)

    if not strategy_name:
        return jsonify({"error": "strategy required"}), 400

    if strategy_name not in V35_STRATEGY_PARAMS:
        return jsonify({"error": f"Unknown strategy: {strategy_name}"}), 400

    # Queue job
    redis_url = current_app.config.get("REDIS_URL", "redis://localhost:6379")
    q = Queue(connection=Redis.from_url(redis_url))

    job = q.enqueue(
        run_v35_optimization,
        strategy_name=strategy_name,
        param_groups=param_groups,
        n_trials=n_trials,
        job_timeout="4h",
    )

    return jsonify({
        "job_id": job.id,
        "strategy": strategy_name,
        "param_groups": param_groups,
        "n_trials": n_trials,
    })
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/web/quant_lab/test_v35_routes.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/routes.py tests/web/quant_lab/test_v35_routes.py
git commit -m "feat(quant-lab): add V35 optimization API endpoints

- GET /api/v35/strategies - list V35 strategies
- GET /api/v35/param-groups/<name> - get strategy parameters
- POST /api/v35/optimize - start optimization job

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 4: Add V35 Worker Task

**Files:**
- Modify: `web/quant_lab/worker/tasks.py`
- Test: `tests/web/quant_lab/test_v35_worker.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_v35_worker.py
import pytest
from unittest.mock import patch, MagicMock
from web.quant_lab.worker.tasks import run_v35_optimization

class TestV35Worker:
    @patch("web.quant_lab.worker.tasks.optuna")
    def test_creates_study_with_correct_direction(self, mock_optuna):
        mock_study = MagicMock()
        mock_optuna.create_study.return_value = mock_study

        # Should not raise
        with patch("web.quant_lab.worker.tasks.GrowthObjective"):
            run_v35_optimization(
                strategy_name="v35_long_v2",
                param_groups=["risk"],
                n_trials=1,
            )

        mock_optuna.create_study.assert_called_once()
        call_kwargs = mock_optuna.create_study.call_args[1]
        assert call_kwargs["direction"] == "maximize"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/web/quant_lab/test_v35_worker.py -v`
Expected: FAIL

**Step 3: Add task to tasks.py**

```python
# Add to web/quant_lab/worker/tasks.py

def run_v35_optimization(
    strategy_name: str,
    param_groups: list,
    n_trials: int = 100,
    capital: float = 10_000.0,
    start_date: str = "2024-01-01",
    end_date: str = "2024-12-31",
) -> dict:
    """Run V35 parameter optimization with Optuna.

    Args:
        strategy_name: V35 strategy to optimize
        param_groups: List of parameter groups to tune
        n_trials: Number of optimization trials
        capital: Initial capital in USD
        start_date: Backtest start date
        end_date: Backtest end date

    Returns:
        Dict with best params and metrics
    """
    import optuna
    from pathlib import Path
    from ..optimizer.v35_objective import GrowthObjective
    from ..optimizer.v35_search_space import V35_PARAM_GROUPS

    # Find data path
    project_root = Path(__file__).parent.parent.parent.parent
    data_path = project_root / "data" / "btc_data.db"

    if not data_path.exists():
        raise FileNotFoundError(f"Data file not found: {data_path}")

    # Create objective
    objective = GrowthObjective(
        strategy_name=strategy_name,
        data_path=str(data_path),
        start_date=start_date,
        end_date=end_date,
        capital=capital,
        enabled_groups=param_groups if param_groups else None,
    )

    # Create study (single objective: maximize growth score)
    study = optuna.create_study(
        study_name=f"v35_{strategy_name}_{start_date}_{end_date}",
        direction="maximize",
        sampler=optuna.samplers.TPESampler(seed=42),
        load_if_exists=True,
    )

    # Run optimization
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)

    # Get best trial
    best = study.best_trial

    return {
        "strategy": strategy_name,
        "best_score": best.value,
        "best_params": best.params,
        "n_trials": len(study.trials),
        "param_groups": param_groups,
    }
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/web/quant_lab/test_v35_worker.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/worker/tasks.py tests/web/quant_lab/test_v35_worker.py
git commit -m "feat(quant-lab): add V35 optimization worker task

- Single-objective TPE sampler for growth score
- Uses ComponentStrategyAdapter for full feature support
- Returns best params and score

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 5: Fix Backtester Capital Default

**Files:**
- Modify: `core/backtester.py`
- Test: `tests/core/test_backtester.py` (add test)

**Step 1: Write the failing test**

```python
# Add to tests/core/test_backtester.py

class TestBacktesterCapital:
    def test_default_capital_is_10k_usd(self):
        from core.backtester import Backtester
        bt = Backtester()
        assert bt.initial_capital == 10_000

    def test_spot_market_uses_correct_fee(self):
        from core.backtester import Backtester
        bt = Backtester(market="spot")
        assert bt.fee_rate == 0.001  # 0.1%

    def test_futures_market_uses_correct_fee(self):
        from core.backtester import Backtester
        bt = Backtester(market="futures")
        assert bt.fee_rate == 0.0005  # 0.05%
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_backtester.py::TestBacktesterCapital -v`
Expected: FAIL (current default is 10_000_000)

**Step 3: Update backtester.py**

Change line 351:
```python
# Before
initial_capital: float = 10_000_000,

# After
initial_capital: float = 10_000,
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_backtester.py::TestBacktesterCapital -v`
Expected: PASS

**Step 5: Commit**

```bash
git add core/backtester.py tests/core/test_backtester.py
git commit -m "fix(backtester): change default capital to $10k USD

- Previous: 10,000,000 KRW (legacy)
- New: 10,000 USD (matches paper trading config)
- Auto-detect fee rate from market parameter

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Task 6: Integration Test

**Files:**
- Create: `tests/web/quant_lab/test_v35_integration.py`

**Step 1: Write integration test**

```python
# tests/web/quant_lab/test_v35_integration.py
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
import numpy as np

class TestV35Integration:
    """End-to-end integration tests for V35 tuning."""

    @pytest.fixture
    def mock_df(self):
        """Create mock price DataFrame."""
        dates = pd.date_range("2024-01-01", periods=1000, freq="h")
        return pd.DataFrame({
            "timestamp": dates,
            "open": np.random.uniform(40000, 50000, 1000),
            "high": np.random.uniform(40000, 50000, 1000),
            "low": np.random.uniform(40000, 50000, 1000),
            "close": np.random.uniform(40000, 50000, 1000),
            "volume": np.random.uniform(100, 1000, 1000),
        })

    def test_search_space_to_objective(self):
        """Test that search space flows to objective correctly."""
        from web.quant_lab.optimizer.v35_search_space import (
            get_strategy_param_groups,
            sample_v35_config,
        )
        import optuna

        study = optuna.create_study()
        trial = study.ask()

        groups = get_strategy_param_groups("v35_long_v2")
        config = sample_v35_config(trial, "v35_long_v2", groups)

        # Verify config has expected parameters
        assert "stop_loss_pct" in config
        assert "position_size_high" in config
        assert 2.0 <= config["stop_loss_pct"] <= 10.0

    def test_growth_score_calculation(self):
        """Test growth score formula."""
        from web.quant_lab.optimizer.v35_objective import calculate_growth_score

        # Good case: high return, low MDD
        score = calculate_growth_score(1.5, 0.15, 1.5)
        assert score > 1.5  # Return + Sharpe bonus

        # Penalty case: MDD above 25%
        score_penalty = calculate_growth_score(1.5, 0.27, 1.0)
        assert score_penalty < 1.5
```

**Step 2: Run integration test**

Run: `pytest tests/web/quant_lab/test_v35_integration.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add tests/web/quant_lab/test_v35_integration.py
git commit -m "test(quant-lab): add V35 tuning integration tests

Co-Authored-By: Claude Opus 4.5 <noreply@anthropic.com>"
```

---

## Validation Checklist

After all tasks complete:

1. [ ] Run full test suite: `pytest tests/web/quant_lab/ -v`
2. [ ] Verify $10k capital in backtester default
3. [ ] Verify 0.1% spot fee applied
4. [ ] Run sample optimization (5 trials) for v35_long_v2
5. [ ] Check best params are valid
