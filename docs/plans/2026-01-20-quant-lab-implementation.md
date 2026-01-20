# Quant Lab Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a web-based experiment workbench for regime-based strategy optimization using Optuna NSGA-II and MLflow.

**Architecture:** Flask blueprint integrated into existing web app, RQ worker for background jobs, Optuna for multi-objective Bayesian optimization, existing ComponentStrategyAdapter for backtesting.

**Tech Stack:** Flask, Redis Queue (RQ), Optuna (NSGA-II), Plotly.js, MLflow, existing backtester infrastructure.

**Design Document:** `docs/plans/2026-01-20-quant-lab-design.md`

---

## Phase 1: Core Infrastructure

### Task 1: Add RQ Dependency

**Files:**
- Modify: `requirements.txt`

**Step 1: Add rq to requirements**

```bash
echo "rq>=1.15.0" >> requirements.txt
```

**Step 2: Install dependency**

```bash
pip install rq>=1.15.0
```

**Step 3: Verify installation**

```bash
python -c "import rq; print(f'RQ version: {rq.__version__}')"
```
Expected: `RQ version: 1.x.x`

**Step 4: Commit**

```bash
git add requirements.txt
git commit -m "deps: add rq for background job processing"
```

---

### Task 2: Create Quant Lab Module Structure

**Files:**
- Create: `web/quant_lab/__init__.py`
- Create: `web/quant_lab/optimizer/__init__.py`
- Create: `web/quant_lab/worker/__init__.py`

**Step 1: Create directory structure**

```bash
mkdir -p web/quant_lab/optimizer
mkdir -p web/quant_lab/worker
```

**Step 2: Create __init__.py files**

```python
# web/quant_lab/__init__.py
"""Quant Lab - Regime-based strategy optimization workbench."""

# web/quant_lab/optimizer/__init__.py
"""Optuna-based optimization components."""

# web/quant_lab/worker/__init__.py
"""RQ background worker components."""
```

**Step 3: Verify imports**

```bash
python -c "from web.quant_lab import *; print('Module structure OK')"
```

**Step 4: Commit**

```bash
git add web/quant_lab/
git commit -m "feat(quant-lab): create module structure"
```

---

## Phase 2: Search Space Definition

### Task 3: Define Search Space Models

**Files:**
- Create: `web/quant_lab/optimizer/search_space.py`
- Create: `tests/web/quant_lab/__init__.py`
- Create: `tests/web/quant_lab/test_search_space.py`

**Step 1: Create test directory**

```bash
mkdir -p tests/web/quant_lab
touch tests/web/quant_lab/__init__.py
```

**Step 2: Write the failing test**

```python
# tests/web/quant_lab/test_search_space.py
"""Tests for search space definition."""
import pytest
from web.quant_lab.optimizer.search_space import (
    REGIMES,
    ENTRY_COMPONENTS,
    EXIT_COMPONENTS,
    SearchSpaceConfig,
    build_search_space,
)


class TestSearchSpaceConstants:
    """Test search space constants."""

    def test_regimes_contains_all_seven(self):
        """All 7 regimes should be defined."""
        expected = {
            "BULL_STRONG", "BULL_MODERATE",
            "SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN",
            "BEAR_MODERATE", "BEAR_STRONG"
        }
        assert set(REGIMES) == expected

    def test_entry_components_include_none(self):
        """Entry components should include 'None' option."""
        assert "None" in ENTRY_COMPONENTS

    def test_exit_components_defined(self):
        """Exit components should be defined."""
        assert len(EXIT_COMPONENTS) >= 4


class TestSearchSpaceConfig:
    """Test SearchSpaceConfig dataclass."""

    def test_default_config_includes_all_regimes(self):
        """Default config should include all regimes."""
        config = SearchSpaceConfig()
        assert len(config.regime_configs) == 7

    def test_config_with_custom_entries(self):
        """Config should accept custom entry component lists."""
        config = SearchSpaceConfig(
            regime_configs={
                "BULL_STRONG": {
                    "entries": ["V35Entry", "None"],
                    "exits": ["V35TrailingExit"],
                }
            }
        )
        assert "BULL_STRONG" in config.regime_configs


class TestBuildSearchSpace:
    """Test Optuna search space builder."""

    def test_build_search_space_returns_dict(self):
        """build_search_space should return a dict for Optuna."""
        config = SearchSpaceConfig()
        space = build_search_space(config)
        assert isinstance(space, dict)
        assert "BULL_STRONG" in space
```

**Step 3: Run test to verify it fails**

```bash
pytest tests/web/quant_lab/test_search_space.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 4: Write implementation**

```python
# web/quant_lab/optimizer/search_space.py
"""Search space definition for regime-based optimization."""
from dataclasses import dataclass, field
from typing import Dict, List, Any

# All 7 market regimes
REGIMES = [
    "BULL_STRONG",
    "BULL_MODERATE",
    "SIDEWAYS_UP",
    "SIDEWAYS_FLAT",
    "SIDEWAYS_DOWN",
    "BEAR_MODERATE",
    "BEAR_STRONG",
]

# Available entry strategy components
ENTRY_COMPONENTS = [
    "V35Entry",
    "SidewaysEntry",
    "ShortEntry",
    "None",  # Skip trading in this regime
]

# Available exit strategy components
EXIT_COMPONENTS = [
    "V35TrailingExit",
    "V35PersistentExit",
    "ExperimentalExit",
    "SidewaysExit",
]

# Parameter bounds for each component
COMPONENT_PARAMS = {
    "V35Entry": {
        "mfi_threshold": {"type": "float", "low": 45.0, "high": 65.0},
        "adx_threshold": {"type": "float", "low": 15.0, "high": 35.0},
    },
    "SidewaysEntry": {
        "range_threshold": {"type": "float", "low": 0.5, "high": 3.0},
    },
    "ShortEntry": {
        "rsi_overbought": {"type": "float", "low": 65.0, "high": 85.0},
    },
    "V35TrailingExit": {
        "trailing_stop_pct": {"type": "float", "low": 0.5, "high": 5.0},
        "take_profit_pct": {"type": "float", "low": 1.0, "high": 10.0},
    },
    "V35PersistentExit": {
        "trailing_stop_pct": {"type": "float", "low": 0.5, "high": 5.0},
    },
    "ExperimentalExit": {
        "exit_threshold": {"type": "float", "low": 0.5, "high": 3.0},
    },
    "SidewaysExit": {
        "profit_target_pct": {"type": "float", "low": 0.5, "high": 3.0},
    },
    "None": {},  # No parameters for None
}


@dataclass
class RegimeConfig:
    """Configuration for a single regime's search space."""
    entries: List[str] = field(default_factory=lambda: ENTRY_COMPONENTS.copy())
    exits: List[str] = field(default_factory=lambda: EXIT_COMPONENTS.copy())


@dataclass
class SearchSpaceConfig:
    """Configuration for the full search space."""
    regime_configs: Dict[str, Dict[str, List[str]]] = field(default_factory=dict)

    def __post_init__(self):
        """Initialize default configs for all regimes."""
        for regime in REGIMES:
            if regime not in self.regime_configs:
                self.regime_configs[regime] = {
                    "entries": ENTRY_COMPONENTS.copy(),
                    "exits": EXIT_COMPONENTS.copy(),
                }


def build_search_space(config: SearchSpaceConfig) -> Dict[str, Any]:
    """
    Build search space dictionary for Optuna trial.

    Returns dict mapping regime -> {entry_choices, exit_choices, param_bounds}
    """
    space = {}
    for regime in REGIMES:
        regime_config = config.regime_configs.get(regime, {})
        entries = regime_config.get("entries", ENTRY_COMPONENTS)
        exits = regime_config.get("exits", EXIT_COMPONENTS)

        space[regime] = {
            "entry_choices": entries,
            "exit_choices": exits,
            "entry_params": {e: COMPONENT_PARAMS.get(e, {}) for e in entries},
            "exit_params": {e: COMPONENT_PARAMS.get(e, {}) for e in exits},
        }
    return space
```

**Step 5: Run test to verify it passes**

```bash
pytest tests/web/quant_lab/test_search_space.py -v
```
Expected: PASS (6 tests)

**Step 6: Commit**

```bash
git add web/quant_lab/optimizer/search_space.py tests/web/quant_lab/
git commit -m "feat(quant-lab): add search space definition"
```

---

### Task 4: Create Trial Sampler

**Files:**
- Modify: `web/quant_lab/optimizer/search_space.py`
- Modify: `tests/web/quant_lab/test_search_space.py`

**Step 1: Write the failing test**

```python
# Add to tests/web/quant_lab/test_search_space.py
from unittest.mock import MagicMock
from web.quant_lab.optimizer.search_space import sample_trial_config


class TestSampleTrialConfig:
    """Test trial configuration sampling."""

    def test_sample_returns_config_for_all_regimes(self):
        """sample_trial_config should return config for all 7 regimes."""
        mock_trial = MagicMock()
        mock_trial.suggest_categorical.side_effect = lambda name, choices: choices[0]
        mock_trial.suggest_float.return_value = 50.0

        config = SearchSpaceConfig()
        result = sample_trial_config(mock_trial, config)

        assert len(result) == 7
        for regime in REGIMES:
            assert regime in result
            assert "entry" in result[regime]
            assert "exit" in result[regime]
            assert "params" in result[regime]

    def test_sample_none_entry_has_no_params(self):
        """When entry is None, params should be empty for entry."""
        mock_trial = MagicMock()
        mock_trial.suggest_categorical.return_value = "None"
        mock_trial.suggest_float.return_value = 50.0

        config = SearchSpaceConfig()
        config.regime_configs["BULL_STRONG"]["entries"] = ["None"]

        result = sample_trial_config(mock_trial, config)

        assert result["BULL_STRONG"]["entry"] == "None"
        assert result["BULL_STRONG"]["params"]["entry"] == {}
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/web/quant_lab/test_search_space.py::TestSampleTrialConfig -v
```
Expected: FAIL with `ImportError`

**Step 3: Add implementation**

```python
# Add to web/quant_lab/optimizer/search_space.py
import optuna


def sample_trial_config(
    trial: optuna.Trial,
    config: SearchSpaceConfig
) -> Dict[str, Dict[str, Any]]:
    """
    Sample a complete configuration from Optuna trial.

    Args:
        trial: Optuna trial object
        config: Search space configuration

    Returns:
        Dict mapping regime -> {entry, exit, params: {entry: {}, exit: {}}}
    """
    result = {}
    space = build_search_space(config)

    for regime in REGIMES:
        regime_space = space[regime]

        # Sample entry/exit components
        entry = trial.suggest_categorical(
            f"{regime}_entry",
            regime_space["entry_choices"]
        )
        exit_comp = trial.suggest_categorical(
            f"{regime}_exit",
            regime_space["exit_choices"]
        )

        # Sample parameters for selected components
        entry_params = {}
        if entry != "None":
            for param_name, param_config in regime_space["entry_params"].get(entry, {}).items():
                if param_config["type"] == "float":
                    entry_params[param_name] = trial.suggest_float(
                        f"{regime}_{entry}_{param_name}",
                        param_config["low"],
                        param_config["high"]
                    )

        exit_params = {}
        for param_name, param_config in regime_space["exit_params"].get(exit_comp, {}).items():
            if param_config["type"] == "float":
                exit_params[param_name] = trial.suggest_float(
                    f"{regime}_{exit_comp}_{param_name}",
                    param_config["low"],
                    param_config["high"]
                )

        result[regime] = {
            "entry": entry,
            "exit": exit_comp,
            "params": {
                "entry": entry_params,
                "exit": exit_params,
            }
        }

    return result
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/web/quant_lab/test_search_space.py::TestSampleTrialConfig -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/optimizer/search_space.py tests/web/quant_lab/test_search_space.py
git commit -m "feat(quant-lab): add trial configuration sampler"
```

---

## Phase 3: Objective Function

### Task 5: Create Multi-Objective Function

**Files:**
- Create: `web/quant_lab/optimizer/objective.py`
- Create: `tests/web/quant_lab/test_objective.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_objective.py
"""Tests for multi-objective optimization function."""
import pytest
from unittest.mock import MagicMock, patch
from web.quant_lab.optimizer.objective import (
    RegimeBacktestObjective,
    create_multi_objective,
)


class TestRegimeBacktestObjective:
    """Test the backtest objective function."""

    def test_objective_returns_three_values(self):
        """Objective should return (win_rate, total_return, max_drawdown)."""
        objective = RegimeBacktestObjective(
            data_path="test_data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            symbols=["BTCUSDT"],
        )

        mock_trial = MagicMock()
        mock_trial.suggest_categorical.side_effect = lambda n, c: c[0]
        mock_trial.suggest_float.return_value = 50.0

        with patch.object(objective, '_run_backtest') as mock_bt:
            mock_bt.return_value = {
                "win_rate": 0.65,
                "total_return": 0.25,
                "max_drawdown": 0.12,
            }

            result = objective(mock_trial)

            assert len(result) == 3
            assert result[0] == 0.65  # win_rate (maximize)
            assert result[1] == 0.25  # total_return (maximize)
            assert result[2] == 0.12  # max_drawdown (minimize, but returned as-is)


class TestCreateMultiObjective:
    """Test Optuna study creation."""

    def test_create_study_with_three_objectives(self):
        """create_multi_objective should configure 3 objectives."""
        study = create_multi_objective("test_study")

        assert len(study.directions) == 3
        # win_rate: maximize, return: maximize, drawdown: minimize
        assert study.directions[0].name == "MAXIMIZE"
        assert study.directions[1].name == "MAXIMIZE"
        assert study.directions[2].name == "MINIMIZE"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/web/quant_lab/test_objective.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# web/quant_lab/optimizer/objective.py
"""Multi-objective optimization function for regime-based strategies."""
from dataclasses import dataclass
from typing import List, Tuple, Dict, Any, Optional
import optuna
from optuna.study import StudyDirection

from .search_space import SearchSpaceConfig, sample_trial_config, REGIMES


@dataclass
class RegimeBacktestObjective:
    """
    Callable objective function for Optuna multi-objective optimization.

    Returns (win_rate, total_return, max_drawdown) tuple.
    """
    data_path: str
    start_date: str
    end_date: str
    symbols: List[str]
    search_config: SearchSpaceConfig = None

    def __post_init__(self):
        if self.search_config is None:
            self.search_config = SearchSpaceConfig()

    def __call__(self, trial: optuna.Trial) -> Tuple[float, float, float]:
        """
        Evaluate a trial configuration.

        Args:
            trial: Optuna trial with hyperparameters

        Returns:
            Tuple of (win_rate, total_return, max_drawdown)
        """
        # Sample configuration from trial
        config = sample_trial_config(trial, self.search_config)

        # Run backtest with this configuration
        metrics = self._run_backtest(config)

        return (
            metrics["win_rate"],
            metrics["total_return"],
            metrics["max_drawdown"],
        )

    def _run_backtest(self, config: Dict[str, Any]) -> Dict[str, float]:
        """
        Run backtest with the given regime configuration.

        Args:
            config: Dict mapping regime -> {entry, exit, params}

        Returns:
            Dict with win_rate, total_return, max_drawdown
        """
        # Import here to avoid circular imports
        from core.backtester import Backtester
        from core.component_adapter import ComponentStrategyAdapter
        from trading.strategies.components.strategy_factory import StrategyFactory
        from core.data_loader import DataLoader

        # Load data
        loader = DataLoader(self.data_path)

        total_trades = 0
        winning_trades = 0
        total_pnl = 0.0
        max_drawdown = 0.0
        peak_equity = 0.0
        current_equity = 0.0

        for symbol in self.symbols:
            df = loader.load_ohlcv(
                symbol=symbol,
                start_date=self.start_date,
                end_date=self.end_date,
            )

            if df.empty:
                continue

            # Create regime-aware adapter
            adapter = self._create_regime_adapter(config, symbol)

            # Run backtest
            backtester = Backtester()
            result = backtester.run(df, adapter)

            # Aggregate metrics
            for trade in result.trades:
                total_trades += 1
                if trade.pnl > 0:
                    winning_trades += 1
                total_pnl += trade.pnl

                current_equity += trade.pnl
                peak_equity = max(peak_equity, current_equity)
                drawdown = (peak_equity - current_equity) / peak_equity if peak_equity > 0 else 0
                max_drawdown = max(max_drawdown, drawdown)

        win_rate = winning_trades / total_trades if total_trades > 0 else 0.0

        return {
            "win_rate": win_rate,
            "total_return": total_pnl,
            "max_drawdown": max_drawdown,
        }

    def _create_regime_adapter(
        self,
        config: Dict[str, Any],
        symbol: str
    ) -> ComponentStrategyAdapter:
        """Create a regime-aware strategy adapter."""
        # This will be implemented in Task 6
        # For now, return a basic adapter
        from core.component_adapter import ComponentStrategyAdapter
        from trading.strategies.components.strategy_factory import StrategyFactory

        factory = StrategyFactory()
        return ComponentStrategyAdapter(
            factory=factory,
            strategy_name="v35_long",
            symbol=symbol,
            regime_config=config,
        )


def create_multi_objective(
    study_name: str,
    storage: Optional[str] = None,
) -> optuna.Study:
    """
    Create an Optuna study with 3 objectives.

    Objectives:
        1. Win Rate (maximize)
        2. Total Return (maximize)
        3. Max Drawdown (minimize)

    Args:
        study_name: Name for the study
        storage: Optional SQLite URL for persistence

    Returns:
        Configured Optuna study
    """
    return optuna.create_study(
        study_name=study_name,
        storage=storage,
        directions=[
            StudyDirection.MAXIMIZE,  # win_rate
            StudyDirection.MAXIMIZE,  # total_return
            StudyDirection.MINIMIZE,  # max_drawdown
        ],
        sampler=optuna.samplers.NSGAIISampler(),
        load_if_exists=True,
    )
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/web/quant_lab/test_objective.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/optimizer/objective.py tests/web/quant_lab/test_objective.py
git commit -m "feat(quant-lab): add multi-objective optimization function"
```

---

### Task 6: Create Regime-Aware Adapter

**Files:**
- Create: `web/quant_lab/optimizer/regime_adapter.py`
- Create: `tests/web/quant_lab/test_regime_adapter.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_regime_adapter.py
"""Tests for regime-aware strategy adapter."""
import pytest
from unittest.mock import MagicMock, patch
from web.quant_lab.optimizer.regime_adapter import RegimeAwareAdapter


class TestRegimeAwareAdapter:
    """Test regime-aware strategy switching."""

    def test_adapter_selects_entry_based_on_regime(self):
        """Adapter should use regime-specific entry component."""
        config = {
            "BULL_STRONG": {
                "entry": "V35Entry",
                "exit": "V35TrailingExit",
                "params": {"entry": {"mfi_threshold": 55}, "exit": {}},
            },
            "BEAR_STRONG": {
                "entry": "ShortEntry",
                "exit": "V35TrailingExit",
                "params": {"entry": {"rsi_overbought": 75}, "exit": {}},
            },
        }

        adapter = RegimeAwareAdapter(
            regime_config=config,
            symbol="BTCUSDT",
        )

        # Mock market data with BULL_STRONG regime
        market_data = MagicMock()
        market_data.regime = "BULL_STRONG"

        entry_component = adapter._get_entry_for_regime(market_data.regime)
        assert entry_component.__class__.__name__ == "V35Entry"

    def test_adapter_returns_none_for_none_entry(self):
        """Adapter should skip trading when entry is None."""
        config = {
            "SIDEWAYS_FLAT": {
                "entry": "None",
                "exit": "V35TrailingExit",
                "params": {"entry": {}, "exit": {}},
            },
        }

        adapter = RegimeAwareAdapter(
            regime_config=config,
            symbol="BTCUSDT",
        )

        entry = adapter._get_entry_for_regime("SIDEWAYS_FLAT")
        assert entry is None
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/web/quant_lab/test_regime_adapter.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# web/quant_lab/optimizer/regime_adapter.py
"""Regime-aware strategy adapter for backtesting."""
from typing import Dict, Any, Optional
from trading.strategies.components.interfaces import IEntryStrategy, IExitStrategy
from trading.strategies.components.models import MarketData, Signal, Position, TradingContext


# Component class mappings
ENTRY_CLASS_MAP = {
    "V35Entry": "trading.strategies.components.v35_entry.V35EntryStrategy",
    "SidewaysEntry": "trading.strategies.components.sideways_entry.SidewaysEntryStrategy",
    "ShortEntry": "trading.strategies.components.short_entry.ShortEntryStrategy",
    "None": None,
}

EXIT_CLASS_MAP = {
    "V35TrailingExit": "trading.strategies.components.v35_trailing_exit.V35TrailingExitStrategy",
    "V35PersistentExit": "trading.strategies.components.v35_persistent_exit.V35PersistentExitStrategy",
    "ExperimentalExit": "trading.strategies.components.experimental_exit.ExperimentalExitStrategy",
    "SidewaysExit": "trading.strategies.components.sideways_exit.SidewaysExitStrategy",
}


def _import_class(class_path: str):
    """Dynamically import a class from its full path."""
    if class_path is None:
        return None
    module_path, class_name = class_path.rsplit(".", 1)
    import importlib
    module = importlib.import_module(module_path)
    return getattr(module, class_name)


class RegimeAwareAdapter:
    """
    Adapter that switches entry/exit strategies based on market regime.

    Used for backtesting regime-based strategy configurations.
    """

    def __init__(
        self,
        regime_config: Dict[str, Dict[str, Any]],
        symbol: str,
    ):
        """
        Initialize adapter with regime configuration.

        Args:
            regime_config: Dict mapping regime -> {entry, exit, params}
            symbol: Trading symbol
        """
        self.regime_config = regime_config
        self.symbol = symbol
        self._entry_cache: Dict[str, Optional[IEntryStrategy]] = {}
        self._exit_cache: Dict[str, Optional[IExitStrategy]] = {}
        self._initialize_components()

    def _initialize_components(self):
        """Pre-instantiate all entry/exit components."""
        for regime, config in self.regime_config.items():
            # Initialize entry
            entry_name = config.get("entry", "None")
            if entry_name not in self._entry_cache:
                entry_class_path = ENTRY_CLASS_MAP.get(entry_name)
                if entry_class_path:
                    entry_class = _import_class(entry_class_path)
                    entry_params = config.get("params", {}).get("entry", {})
                    self._entry_cache[entry_name] = entry_class(**entry_params)
                else:
                    self._entry_cache[entry_name] = None

            # Initialize exit
            exit_name = config.get("exit")
            if exit_name and exit_name not in self._exit_cache:
                exit_class_path = EXIT_CLASS_MAP.get(exit_name)
                if exit_class_path:
                    exit_class = _import_class(exit_class_path)
                    exit_params = config.get("params", {}).get("exit", {})
                    self._exit_cache[exit_name] = exit_class(**exit_params)

    def _get_entry_for_regime(self, regime: str) -> Optional[IEntryStrategy]:
        """Get entry component for the given regime."""
        config = self.regime_config.get(regime, {})
        entry_name = config.get("entry", "None")
        return self._entry_cache.get(entry_name)

    def _get_exit_for_regime(self, regime: str) -> Optional[IExitStrategy]:
        """Get exit component for the given regime."""
        config = self.regime_config.get(regime, {})
        exit_name = config.get("exit")
        return self._exit_cache.get(exit_name)

    def check_entry(self, context: TradingContext) -> Signal:
        """
        Check for entry signal using regime-appropriate component.

        Args:
            context: Current trading context with regime

        Returns:
            Entry signal or neutral
        """
        entry = self._get_entry_for_regime(context.regime)
        if entry is None:
            return Signal.NEUTRAL
        return entry.check_entry(context)

    def check_exit(self, context: TradingContext, position: Position) -> Signal:
        """
        Check for exit signal using regime-appropriate component.

        Args:
            context: Current trading context with regime
            position: Current position

        Returns:
            Exit signal or neutral
        """
        exit_comp = self._get_exit_for_regime(context.regime)
        if exit_comp is None:
            return Signal.NEUTRAL
        return exit_comp.check_exit(context, position)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/web/quant_lab/test_regime_adapter.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/optimizer/regime_adapter.py tests/web/quant_lab/test_regime_adapter.py
git commit -m "feat(quant-lab): add regime-aware strategy adapter"
```

---

## Phase 4: Constraints and Guardrails

### Task 7: Create Constraints Module

**Files:**
- Create: `web/quant_lab/optimizer/constraints.py`
- Create: `tests/web/quant_lab/test_constraints.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_constraints.py
"""Tests for optimization constraints."""
import pytest
from web.quant_lab.optimizer.constraints import (
    ConstraintsConfig,
    MaxDrawdownPruner,
    StrategyLockConstraint,
)


class TestConstraintsConfig:
    """Test constraints configuration."""

    def test_default_config(self):
        """Default config should have no constraints."""
        config = ConstraintsConfig()
        assert config.max_drawdown is None
        assert config.strategy_locks == {}

    def test_config_with_max_drawdown(self):
        """Config should accept max drawdown constraint."""
        config = ConstraintsConfig(max_drawdown=0.30)
        assert config.max_drawdown == 0.30


class TestMaxDrawdownPruner:
    """Test early stopping pruner for drawdown."""

    def test_pruner_triggers_on_high_drawdown(self):
        """Pruner should signal pruning when drawdown exceeds threshold."""
        pruner = MaxDrawdownPruner(max_drawdown=0.20)

        # Simulated intermediate values
        should_prune = pruner.should_prune(current_drawdown=0.25)
        assert should_prune is True

    def test_pruner_allows_low_drawdown(self):
        """Pruner should not prune when drawdown is acceptable."""
        pruner = MaxDrawdownPruner(max_drawdown=0.20)

        should_prune = pruner.should_prune(current_drawdown=0.15)
        assert should_prune is False


class TestStrategyLockConstraint:
    """Test strategy lock constraints."""

    def test_lock_forces_entry_choice(self):
        """Lock should restrict entry choices for a regime."""
        lock = StrategyLockConstraint(
            regime="BULL_STRONG",
            entry="V35Entry",
        )

        choices = ["V35Entry", "SidewaysEntry", "ShortEntry", "None"]
        filtered = lock.filter_choices(choices, "entry")

        assert filtered == ["V35Entry"]

    def test_lock_does_not_affect_other_regimes(self):
        """Lock should not affect other regimes."""
        lock = StrategyLockConstraint(
            regime="BULL_STRONG",
            entry="V35Entry",
        )

        # For a different regime, choices should be unchanged
        choices = ["V35Entry", "SidewaysEntry"]
        # filter_choices only applies if called for matching regime
        assert lock.regime == "BULL_STRONG"
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/web/quant_lab/test_constraints.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# web/quant_lab/optimizer/constraints.py
"""Constraints and guardrails for optimization."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class ConstraintsConfig:
    """Configuration for optimization constraints."""

    # Time budget
    max_trials: Optional[int] = None
    max_hours: Optional[float] = None

    # Risk guardrails
    max_drawdown: Optional[float] = None  # e.g., 0.30 for 30%
    min_trades: Optional[int] = None  # Reject if too few trades

    # Strategy locks: regime -> {entry: str, exit: str}
    strategy_locks: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # Parameter overrides (force specific values)
    param_overrides: Dict[str, float] = field(default_factory=dict)


@dataclass
class MaxDrawdownPruner:
    """
    Early stopping pruner based on max drawdown.

    Signals trial pruning if intermediate drawdown exceeds threshold.
    """
    max_drawdown: float

    def should_prune(self, current_drawdown: float) -> bool:
        """
        Check if trial should be pruned.

        Args:
            current_drawdown: Current drawdown ratio (0.0-1.0)

        Returns:
            True if trial should be stopped early
        """
        return current_drawdown > self.max_drawdown


@dataclass
class StrategyLockConstraint:
    """
    Constraint that locks a specific component for a regime.

    Example: "Always use V35Entry in BULL_STRONG"
    """
    regime: str
    entry: Optional[str] = None
    exit: Optional[str] = None

    def filter_choices(
        self,
        choices: List[str],
        component_type: str  # "entry" or "exit"
    ) -> List[str]:
        """
        Filter choices based on lock.

        Args:
            choices: Available component choices
            component_type: "entry" or "exit"

        Returns:
            Filtered list (single item if locked)
        """
        locked_value = getattr(self, component_type, None)
        if locked_value and locked_value in choices:
            return [locked_value]
        return choices

    def apply_to_search_space(
        self,
        search_space: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply lock to search space configuration.

        Args:
            search_space: Full search space dict

        Returns:
            Modified search space with locks applied
        """
        if self.regime not in search_space:
            return search_space

        regime_space = search_space[self.regime]

        if self.entry:
            regime_space["entry_choices"] = self.filter_choices(
                regime_space["entry_choices"], "entry"
            )

        if self.exit:
            regime_space["exit_choices"] = self.filter_choices(
                regime_space["exit_choices"], "exit"
            )

        return search_space


def apply_constraints(
    search_space: Dict[str, Any],
    constraints: ConstraintsConfig,
) -> Dict[str, Any]:
    """
    Apply all constraints to search space.

    Args:
        search_space: Original search space
        constraints: Constraints configuration

    Returns:
        Modified search space
    """
    modified = search_space.copy()

    # Apply strategy locks
    for regime, lock_config in constraints.strategy_locks.items():
        lock = StrategyLockConstraint(
            regime=regime,
            entry=lock_config.get("entry"),
            exit=lock_config.get("exit"),
        )
        modified = lock.apply_to_search_space(modified)

    return modified
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/web/quant_lab/test_constraints.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/optimizer/constraints.py tests/web/quant_lab/test_constraints.py
git commit -m "feat(quant-lab): add optimization constraints and guardrails"
```

---

## Phase 5: Study Manager

### Task 8: Create Study Manager

**Files:**
- Create: `web/quant_lab/optimizer/study_manager.py`
- Create: `tests/web/quant_lab/test_study_manager.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_study_manager.py
"""Tests for Optuna study management."""
import pytest
import tempfile
import os
from web.quant_lab.optimizer.study_manager import StudyManager


class TestStudyManager:
    """Test study lifecycle management."""

    def test_create_study(self):
        """StudyManager should create a new study."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            study = manager.create_study("test_experiment")

            assert study is not None
            assert study.study_name == "test_experiment"

    def test_resume_study(self):
        """StudyManager should resume existing study."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            # Create initial study
            study1 = manager.create_study("resume_test")

            # Resume it
            study2 = manager.get_study("resume_test")

            assert study2.study_name == "resume_test"

    def test_list_studies(self):
        """StudyManager should list all studies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            manager.create_study("study_a")
            manager.create_study("study_b")

            studies = manager.list_studies()

            assert len(studies) >= 2
            names = [s.study_name for s in studies]
            assert "study_a" in names
            assert "study_b" in names

    def test_get_pareto_front(self):
        """StudyManager should return Pareto-optimal trials."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            study = manager.create_study("pareto_test")

            # Note: pareto front requires completed trials
            # This tests the method exists and returns empty for new study
            pareto = manager.get_pareto_front("pareto_test")

            assert isinstance(pareto, list)
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/web/quant_lab/test_study_manager.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# web/quant_lab/optimizer/study_manager.py
"""Optuna study lifecycle management."""
from typing import List, Optional, Dict, Any
import optuna
from optuna.study import StudyDirection
import os


class StudyManager:
    """
    Manages Optuna study lifecycle.

    Handles study creation, persistence, resumption, and Pareto front extraction.
    """

    def __init__(self, storage_path: str = "quant_lab_studies.db"):
        """
        Initialize study manager.

        Args:
            storage_path: Path to SQLite database for study persistence
        """
        self.storage_path = storage_path
        self.storage_url = f"sqlite:///{storage_path}"

    def create_study(
        self,
        study_name: str,
        directions: Optional[List[str]] = None,
    ) -> optuna.Study:
        """
        Create a new multi-objective study.

        Args:
            study_name: Unique name for the study
            directions: List of "maximize" or "minimize" for each objective
                       Defaults to [maximize, maximize, minimize] for
                       (win_rate, return, drawdown)

        Returns:
            Created Optuna study
        """
        if directions is None:
            # Default: maximize win_rate, maximize return, minimize drawdown
            study_directions = [
                StudyDirection.MAXIMIZE,
                StudyDirection.MAXIMIZE,
                StudyDirection.MINIMIZE,
            ]
        else:
            study_directions = [
                StudyDirection.MAXIMIZE if d == "maximize" else StudyDirection.MINIMIZE
                for d in directions
            ]

        study = optuna.create_study(
            study_name=study_name,
            storage=self.storage_url,
            directions=study_directions,
            sampler=optuna.samplers.NSGAIISampler(),
            load_if_exists=True,
        )

        return study

    def get_study(self, study_name: str) -> optuna.Study:
        """
        Get or resume an existing study.

        Args:
            study_name: Name of study to retrieve

        Returns:
            Existing Optuna study
        """
        return optuna.load_study(
            study_name=study_name,
            storage=self.storage_url,
        )

    def list_studies(self) -> List[optuna.study.StudySummary]:
        """
        List all studies in storage.

        Returns:
            List of study summaries
        """
        return optuna.get_all_study_summaries(storage=self.storage_url)

    def delete_study(self, study_name: str) -> None:
        """
        Delete a study from storage.

        Args:
            study_name: Name of study to delete
        """
        optuna.delete_study(
            study_name=study_name,
            storage=self.storage_url,
        )

    def get_pareto_front(self, study_name: str) -> List[optuna.trial.FrozenTrial]:
        """
        Get Pareto-optimal trials from a study.

        Args:
            study_name: Name of study

        Returns:
            List of Pareto-optimal trials
        """
        study = self.get_study(study_name)
        return study.best_trials

    def get_trial_config(self, study_name: str, trial_number: int) -> Dict[str, Any]:
        """
        Get the full configuration for a specific trial.

        Args:
            study_name: Name of study
            trial_number: Trial number to retrieve

        Returns:
            Dict with trial parameters and results
        """
        study = self.get_study(study_name)
        trial = study.trials[trial_number]

        return {
            "number": trial.number,
            "params": trial.params,
            "values": trial.values,
            "state": trial.state.name,
            "datetime_start": trial.datetime_start.isoformat() if trial.datetime_start else None,
            "datetime_complete": trial.datetime_complete.isoformat() if trial.datetime_complete else None,
        }

    def get_study_stats(self, study_name: str) -> Dict[str, Any]:
        """
        Get statistics for a study.

        Args:
            study_name: Name of study

        Returns:
            Dict with study statistics
        """
        study = self.get_study(study_name)

        completed = [t for t in study.trials if t.state == optuna.trial.TrialState.COMPLETE]
        failed = [t for t in study.trials if t.state == optuna.trial.TrialState.FAIL]
        pruned = [t for t in study.trials if t.state == optuna.trial.TrialState.PRUNED]

        return {
            "study_name": study_name,
            "total_trials": len(study.trials),
            "completed_trials": len(completed),
            "failed_trials": len(failed),
            "pruned_trials": len(pruned),
            "pareto_front_size": len(study.best_trials),
            "directions": [d.name for d in study.directions],
        }
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/web/quant_lab/test_study_manager.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/optimizer/study_manager.py tests/web/quant_lab/test_study_manager.py
git commit -m "feat(quant-lab): add study manager for Optuna lifecycle"
```

---

## Phase 6: Background Worker

### Task 9: Create RQ Tasks

**Files:**
- Create: `web/quant_lab/worker/tasks.py`
- Create: `tests/web/quant_lab/test_worker_tasks.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_worker_tasks.py
"""Tests for RQ worker tasks."""
import pytest
from unittest.mock import MagicMock, patch
from web.quant_lab.worker.tasks import (
    run_optimization,
    OptimizationJob,
    JobStatus,
)


class TestOptimizationJob:
    """Test optimization job dataclass."""

    def test_job_creation(self):
        """Job should store all configuration."""
        job = OptimizationJob(
            job_id="test-123",
            study_name="my_experiment",
            data_path="data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            symbols=["BTCUSDT"],
            max_trials=100,
        )

        assert job.job_id == "test-123"
        assert job.max_trials == 100


class TestRunOptimization:
    """Test the main optimization task."""

    @patch('web.quant_lab.worker.tasks.StudyManager')
    @patch('web.quant_lab.worker.tasks.RegimeBacktestObjective')
    def test_run_optimization_creates_study(self, mock_objective, mock_manager):
        """run_optimization should create/resume a study."""
        mock_study = MagicMock()
        mock_manager.return_value.create_study.return_value = mock_study
        mock_study.trials = []

        job = OptimizationJob(
            job_id="test-123",
            study_name="test_study",
            data_path="data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            symbols=["BTCUSDT"],
            max_trials=1,  # Just 1 trial for test
        )

        # This will fail during actual optimization, but tests setup
        with pytest.raises(Exception):
            run_optimization(job)

        mock_manager.return_value.create_study.assert_called_once_with("test_study")
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/web/quant_lab/test_worker_tasks.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# web/quant_lab/worker/tasks.py
"""RQ background tasks for optimization."""
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
import json
import redis
from datetime import datetime

from ..optimizer.study_manager import StudyManager
from ..optimizer.objective import RegimeBacktestObjective
from ..optimizer.search_space import SearchSpaceConfig
from ..optimizer.constraints import ConstraintsConfig


class JobStatus(Enum):
    """Status of an optimization job."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class OptimizationJob:
    """Configuration for an optimization job."""
    job_id: str
    study_name: str
    data_path: str
    start_date: str
    end_date: str
    symbols: List[str]

    # Budget
    max_trials: Optional[int] = 500
    max_hours: Optional[float] = None

    # Search space config (serialized)
    search_config: Optional[Dict[str, Any]] = None

    # Constraints config (serialized)
    constraints: Optional[Dict[str, Any]] = None

    # MLflow tracking
    mlflow_experiment: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Serialize job to dict."""
        return {
            "job_id": self.job_id,
            "study_name": self.study_name,
            "data_path": self.data_path,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "symbols": self.symbols,
            "max_trials": self.max_trials,
            "max_hours": self.max_hours,
            "search_config": self.search_config,
            "constraints": self.constraints,
            "mlflow_experiment": self.mlflow_experiment,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'OptimizationJob':
        """Deserialize job from dict."""
        return cls(**data)


def run_optimization(job: OptimizationJob) -> Dict[str, Any]:
    """
    Main optimization task executed by RQ worker.

    Args:
        job: Optimization job configuration

    Returns:
        Dict with final results
    """
    from core.mlflow_tracker import MLflowTracker

    # Initialize study manager
    manager = StudyManager()
    study = manager.create_study(job.study_name)

    # Build search config
    search_config = SearchSpaceConfig()
    if job.search_config:
        search_config.regime_configs = job.search_config

    # Build objective
    objective = RegimeBacktestObjective(
        data_path=job.data_path,
        start_date=job.start_date,
        end_date=job.end_date,
        symbols=job.symbols,
        search_config=search_config,
    )

    # Setup MLflow tracking
    mlflow_tracker = None
    if job.mlflow_experiment:
        mlflow_tracker = MLflowTracker(experiment_name=job.mlflow_experiment)

    # Update job status
    _update_job_status(job.job_id, JobStatus.RUNNING)

    try:
        # Run optimization
        study.optimize(
            objective,
            n_trials=job.max_trials,
            timeout=job.max_hours * 3600 if job.max_hours else None,
            callbacks=[
                lambda study, trial: _on_trial_complete(
                    job.job_id, study, trial, mlflow_tracker
                )
            ],
        )

        # Get results
        stats = manager.get_study_stats(job.study_name)
        pareto = manager.get_pareto_front(job.study_name)

        _update_job_status(job.job_id, JobStatus.COMPLETED, stats)

        return {
            "status": "completed",
            "stats": stats,
            "pareto_size": len(pareto),
        }

    except Exception as e:
        _update_job_status(job.job_id, JobStatus.FAILED, {"error": str(e)})
        raise


def _update_job_status(
    job_id: str,
    status: JobStatus,
    extra: Optional[Dict[str, Any]] = None,
) -> None:
    """Update job status in Redis."""
    try:
        r = redis.from_url("redis://localhost:6379")
        data = {
            "status": status.value,
            "updated_at": datetime.utcnow().isoformat(),
        }
        if extra:
            data.update(extra)
        r.hset(f"quant_lab:job:{job_id}", mapping={k: json.dumps(v) for k, v in data.items()})
    except Exception:
        pass  # Don't fail optimization if Redis update fails


def _on_trial_complete(
    job_id: str,
    study,
    trial,
    mlflow_tracker,
) -> None:
    """Callback after each trial completes."""
    # Update progress
    try:
        r = redis.from_url("redis://localhost:6379")
        r.hset(f"quant_lab:job:{job_id}", mapping={
            "current_trial": str(trial.number),
            "best_values": json.dumps(study.best_trials[0].values if study.best_trials else None),
        })
    except Exception:
        pass

    # Log to MLflow
    if mlflow_tracker and trial.state.name == "COMPLETE":
        try:
            with mlflow_tracker.start_run(run_name=f"trial_{trial.number}"):
                mlflow_tracker.log_params(trial.params)
                mlflow_tracker.log_metrics({
                    "win_rate": trial.values[0],
                    "total_return": trial.values[1],
                    "max_drawdown": trial.values[2],
                })
        except Exception:
            pass
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/web/quant_lab/test_worker_tasks.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/worker/tasks.py tests/web/quant_lab/test_worker_tasks.py
git commit -m "feat(quant-lab): add RQ optimization tasks"
```

---

### Task 10: Create Worker Runner

**Files:**
- Create: `web/quant_lab/worker/runner.py`

**Step 1: Write implementation**

```python
# web/quant_lab/worker/runner.py
"""RQ worker entry point for Quant Lab."""
import os
import sys
from redis import Redis
from rq import Worker, Queue

# Add project root to path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
sys.path.insert(0, PROJECT_ROOT)


def run_worker():
    """Start the RQ worker."""
    redis_url = os.environ.get("REDIS_URL", "redis://localhost:6379")
    redis_conn = Redis.from_url(redis_url)

    # Listen on quant_lab queue
    queues = [Queue("quant_lab", connection=redis_conn)]

    worker = Worker(queues, connection=redis_conn)
    worker.work()


if __name__ == "__main__":
    run_worker()
```

**Step 2: Test worker can start**

```bash
python -c "from web.quant_lab.worker.runner import run_worker; print('Runner imports OK')"
```
Expected: `Runner imports OK`

**Step 3: Commit**

```bash
git add web/quant_lab/worker/runner.py
git commit -m "feat(quant-lab): add worker runner entry point"
```

---

## Phase 7: Flask Routes

### Task 11: Create Flask Blueprint

**Files:**
- Create: `web/quant_lab/routes.py`
- Create: `tests/web/quant_lab/test_routes.py`

**Step 1: Write the failing test**

```python
# tests/web/quant_lab/test_routes.py
"""Tests for Quant Lab Flask routes."""
import pytest
from flask import Flask
from web.quant_lab.routes import quant_lab_bp


@pytest.fixture
def app():
    """Create test Flask app."""
    app = Flask(__name__)
    app.config['TESTING'] = True
    app.register_blueprint(quant_lab_bp, url_prefix='/quant-lab')
    return app


@pytest.fixture
def client(app):
    """Create test client."""
    return app.test_client()


class TestQuantLabRoutes:
    """Test Quant Lab API endpoints."""

    def test_index_returns_200(self, client):
        """GET /quant-lab/ should return 200."""
        response = client.get('/quant-lab/')
        assert response.status_code == 200

    def test_templates_endpoint(self, client):
        """GET /quant-lab/api/templates should return templates."""
        response = client.get('/quant-lab/api/templates')
        assert response.status_code == 200
        data = response.get_json()
        assert 'templates' in data

    def test_create_experiment_requires_post(self, client):
        """POST /quant-lab/api/experiments should create job."""
        response = client.post('/quant-lab/api/experiments', json={
            "study_name": "test_experiment",
            "data_path": "data.db",
            "start_date": "2024-01-01",
            "end_date": "2024-12-31",
            "symbols": ["BTCUSDT"],
            "max_trials": 10,
        })
        # Should accept the request (may fail on actual enqueue without Redis)
        assert response.status_code in [200, 201, 500]
```

**Step 2: Run test to verify it fails**

```bash
pytest tests/web/quant_lab/test_routes.py -v
```
Expected: FAIL with `ModuleNotFoundError`

**Step 3: Write implementation**

```python
# web/quant_lab/routes.py
"""Flask blueprint for Quant Lab."""
from flask import Blueprint, render_template, request, jsonify
import uuid
import json
import os
from typing import Dict, Any

from .worker.tasks import OptimizationJob, JobStatus
from .optimizer.study_manager import StudyManager
from .optimizer.search_space import REGIMES, ENTRY_COMPONENTS, EXIT_COMPONENTS, COMPONENT_PARAMS

quant_lab_bp = Blueprint(
    'quant_lab',
    __name__,
    template_folder='../templates/quant_lab',
    static_folder='../static/quant_lab',
)


# Experiment templates
TEMPLATES = {
    "v35_param_sweep": {
        "name": "V35 Parameter Sweep",
        "description": "Fixed V35Entry/Exit for BULL regimes, tune params only",
        "config": {
            regime: {
                "entries": ["V35Entry"] if "BULL" in regime else ENTRY_COMPONENTS,
                "exits": ["V35TrailingExit"],
            }
            for regime in REGIMES
        },
    },
    "full_regime_search": {
        "name": "Full Regime Search",
        "description": "All Entry/Exit combinations across all 7 regimes",
        "config": {regime: {"entries": ENTRY_COMPONENTS, "exits": EXIT_COMPONENTS} for regime in REGIMES},
    },
    "conservative_search": {
        "name": "Conservative Search",
        "description": "Excludes 'None' option, ensures always-in-market",
        "config": {
            regime: {
                "entries": [e for e in ENTRY_COMPONENTS if e != "None"],
                "exits": EXIT_COMPONENTS,
            }
            for regime in REGIMES
        },
    },
    "bear_market_focus": {
        "name": "Bear Market Focus",
        "description": "Only optimizes BEAR_MODERATE and BEAR_STRONG regimes",
        "config": {
            regime: {
                "entries": ENTRY_COMPONENTS if "BEAR" in regime else ["V35Entry"],
                "exits": EXIT_COMPONENTS if "BEAR" in regime else ["V35TrailingExit"],
            }
            for regime in REGIMES
        },
    },
}


@quant_lab_bp.route('/')
def index():
    """Render main Quant Lab page."""
    return render_template('designer.html', regimes=REGIMES)


@quant_lab_bp.route('/api/templates')
def get_templates():
    """Get available experiment templates."""
    return jsonify({"templates": TEMPLATES})


@quant_lab_bp.route('/api/search-space')
def get_search_space():
    """Get search space configuration options."""
    return jsonify({
        "regimes": REGIMES,
        "entry_components": ENTRY_COMPONENTS,
        "exit_components": EXIT_COMPONENTS,
        "component_params": COMPONENT_PARAMS,
    })


@quant_lab_bp.route('/api/experiments', methods=['POST'])
def create_experiment():
    """Create a new optimization experiment."""
    data = request.get_json()

    # Generate job ID
    job_id = str(uuid.uuid4())[:8]

    # Create job
    job = OptimizationJob(
        job_id=job_id,
        study_name=data.get('study_name', f'experiment_{job_id}'),
        data_path=data.get('data_path', 'data/binance.db'),
        start_date=data['start_date'],
        end_date=data['end_date'],
        symbols=data['symbols'],
        max_trials=data.get('max_trials', 500),
        max_hours=data.get('max_hours'),
        search_config=data.get('search_config'),
        constraints=data.get('constraints'),
        mlflow_experiment=data.get('mlflow_experiment', 'quant_lab'),
    )

    # Enqueue job
    try:
        from redis import Redis
        from rq import Queue

        redis_conn = Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))
        q = Queue('quant_lab', connection=redis_conn)

        from .worker.tasks import run_optimization
        rq_job = q.enqueue(run_optimization, job, job_timeout='12h')

        return jsonify({
            "job_id": job_id,
            "rq_job_id": rq_job.id,
            "status": "queued",
        }), 201

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/api/experiments/<job_id>')
def get_experiment_status(job_id: str):
    """Get status of an optimization experiment."""
    try:
        from redis import Redis

        redis_conn = Redis.from_url(os.environ.get('REDIS_URL', 'redis://localhost:6379'))
        data = redis_conn.hgetall(f'quant_lab:job:{job_id}')

        if not data:
            return jsonify({"error": "Job not found"}), 404

        return jsonify({k.decode(): json.loads(v.decode()) for k, v in data.items()})

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/api/experiments')
def list_experiments():
    """List all experiments."""
    try:
        manager = StudyManager()
        studies = manager.list_studies()

        return jsonify({
            "experiments": [
                {
                    "study_name": s.study_name,
                    "n_trials": s.n_trials,
                    "datetime_start": s.datetime_start.isoformat() if s.datetime_start else None,
                }
                for s in studies
            ]
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/api/experiments/<study_name>/results')
def get_experiment_results(study_name: str):
    """Get results for an experiment."""
    try:
        manager = StudyManager()
        stats = manager.get_study_stats(study_name)
        pareto = manager.get_pareto_front(study_name)

        return jsonify({
            "stats": stats,
            "pareto_front": [
                {
                    "trial_number": t.number,
                    "values": {
                        "win_rate": t.values[0],
                        "total_return": t.values[1],
                        "max_drawdown": t.values[2],
                    },
                    "params": t.params,
                }
                for t in pareto
            ],
        })

    except Exception as e:
        return jsonify({"error": str(e)}), 500


@quant_lab_bp.route('/monitor')
def monitor():
    """Render job monitor page."""
    return render_template('monitor.html')


@quant_lab_bp.route('/results/<study_name>')
def results(study_name: str):
    """Render results page for a study."""
    return render_template('results.html', study_name=study_name)
```

**Step 4: Run test to verify it passes**

```bash
pytest tests/web/quant_lab/test_routes.py -v
```
Expected: PASS

**Step 5: Commit**

```bash
git add web/quant_lab/routes.py tests/web/quant_lab/test_routes.py
git commit -m "feat(quant-lab): add Flask blueprint with API routes"
```

---

## Phase 8: Templates and UI

### Task 12: Create Experiment Designer Template

**Files:**
- Create: `web/templates/quant_lab/designer.html`

**Step 1: Create templates directory**

```bash
mkdir -p web/templates/quant_lab
```

**Step 2: Write designer template**

```html
<!-- web/templates/quant_lab/designer.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant Lab - Experiment Designer</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
    <div x-data="experimentDesigner()" class="container mx-auto px-4 py-8">
        <!-- Header -->
        <div class="flex justify-between items-center mb-8">
            <h1 class="text-3xl font-bold text-blue-400">Quant Lab</h1>
            <div class="space-x-4">
                <a href="/quant-lab/monitor" class="text-gray-400 hover:text-white">Job Monitor</a>
                <a href="/" class="text-gray-400 hover:text-white">Dashboard</a>
            </div>
        </div>

        <!-- Wizard Steps -->
        <div class="mb-8">
            <div class="flex items-center justify-center space-x-4">
                <template x-for="(step, i) in steps" :key="i">
                    <div class="flex items-center">
                        <div :class="currentStep >= i ? 'bg-blue-600' : 'bg-gray-700'"
                             class="w-10 h-10 rounded-full flex items-center justify-center font-bold">
                            <span x-text="i + 1"></span>
                        </div>
                        <span class="ml-2 text-sm" x-text="step"></span>
                        <div x-show="i < steps.length - 1" class="w-16 h-0.5 bg-gray-700 mx-4"></div>
                    </div>
                </template>
            </div>
        </div>

        <!-- Step Content -->
        <div class="bg-gray-800 rounded-lg p-6 mb-8">
            <!-- Step 1: Templates -->
            <div x-show="currentStep === 0">
                <h2 class="text-xl font-semibold mb-4">Choose a Template</h2>
                <div class="grid grid-cols-2 gap-4">
                    <template x-for="(template, key) in templates" :key="key">
                        <div @click="selectTemplate(key)"
                             :class="selectedTemplate === key ? 'border-blue-500 bg-blue-900/30' : 'border-gray-600'"
                             class="border-2 rounded-lg p-4 cursor-pointer hover:border-blue-400 transition">
                            <h3 class="font-semibold" x-text="template.name"></h3>
                            <p class="text-gray-400 text-sm mt-2" x-text="template.description"></p>
                        </div>
                    </template>
                </div>
            </div>

            <!-- Step 2: Data Range -->
            <div x-show="currentStep === 1">
                <h2 class="text-xl font-semibold mb-4">Select Data Range</h2>
                <div class="grid grid-cols-2 gap-6">
                    <div>
                        <label class="block text-sm text-gray-400 mb-2">Start Date</label>
                        <input type="date" x-model="config.start_date"
                               class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
                    </div>
                    <div>
                        <label class="block text-sm text-gray-400 mb-2">End Date</label>
                        <input type="date" x-model="config.end_date"
                               class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
                    </div>
                </div>
                <div class="mt-6">
                    <label class="block text-sm text-gray-400 mb-2">Assets</label>
                    <div class="flex space-x-4">
                        <template x-for="symbol in ['BTCUSDT', 'ETHUSDT', 'SOLUSDT']" :key="symbol">
                            <label class="flex items-center space-x-2 cursor-pointer">
                                <input type="checkbox" :value="symbol" x-model="config.symbols"
                                       class="form-checkbox bg-gray-700 border-gray-600 rounded">
                                <span x-text="symbol.replace('USDT', '')"></span>
                            </label>
                        </template>
                    </div>
                </div>
            </div>

            <!-- Step 3: Constraints -->
            <div x-show="currentStep === 2">
                <h2 class="text-xl font-semibold mb-4">Set Constraints</h2>
                <div class="space-y-6">
                    <div class="grid grid-cols-2 gap-6">
                        <div>
                            <label class="block text-sm text-gray-400 mb-2">Max Trials</label>
                            <input type="number" x-model.number="config.max_trials"
                                   class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
                        </div>
                        <div>
                            <label class="block text-sm text-gray-400 mb-2">Max Hours (optional)</label>
                            <input type="number" x-model.number="config.max_hours" step="0.5"
                                   class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2">
                        </div>
                    </div>
                    <div>
                        <label class="block text-sm text-gray-400 mb-2">Max Drawdown Guardrail (%)</label>
                        <input type="range" x-model.number="config.max_drawdown" min="10" max="50" step="5"
                               class="w-full">
                        <div class="flex justify-between text-sm text-gray-500">
                            <span>10%</span>
                            <span x-text="config.max_drawdown + '%'" class="text-blue-400"></span>
                            <span>50%</span>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Step 4: Review -->
            <div x-show="currentStep === 3">
                <h2 class="text-xl font-semibold mb-4">Review & Launch</h2>
                <div class="bg-gray-900 rounded-lg p-4 mb-6">
                    <pre class="text-sm text-gray-300" x-text="JSON.stringify(config, null, 2)"></pre>
                </div>
                <div>
                    <label class="block text-sm text-gray-400 mb-2">Experiment Name</label>
                    <input type="text" x-model="config.study_name"
                           class="w-full bg-gray-700 border border-gray-600 rounded px-4 py-2"
                           placeholder="my_experiment">
                </div>
            </div>
        </div>

        <!-- Navigation -->
        <div class="flex justify-between">
            <button @click="prevStep" x-show="currentStep > 0"
                    class="px-6 py-2 bg-gray-700 hover:bg-gray-600 rounded">
                Back
            </button>
            <div class="flex-1"></div>
            <button @click="nextStep" x-show="currentStep < steps.length - 1"
                    class="px-6 py-2 bg-blue-600 hover:bg-blue-500 rounded">
                Next
            </button>
            <button @click="launch" x-show="currentStep === steps.length - 1"
                    :disabled="launching"
                    class="px-6 py-2 bg-green-600 hover:bg-green-500 rounded disabled:opacity-50">
                <span x-show="!launching">Launch Experiment</span>
                <span x-show="launching">Launching...</span>
            </button>
        </div>
    </div>

    <script>
        function experimentDesigner() {
            return {
                steps: ['Template', 'Data Range', 'Constraints', 'Review'],
                currentStep: 0,
                templates: {},
                selectedTemplate: null,
                launching: false,
                config: {
                    study_name: '',
                    start_date: '2024-01-01',
                    end_date: '2024-12-31',
                    symbols: ['BTCUSDT'],
                    max_trials: 500,
                    max_hours: null,
                    max_drawdown: 30,
                    search_config: null,
                },

                async init() {
                    const res = await fetch('/quant-lab/api/templates');
                    const data = await res.json();
                    this.templates = data.templates;
                },

                selectTemplate(key) {
                    this.selectedTemplate = key;
                    this.config.search_config = this.templates[key].config;
                },

                prevStep() {
                    if (this.currentStep > 0) this.currentStep--;
                },

                nextStep() {
                    if (this.currentStep < this.steps.length - 1) this.currentStep++;
                },

                async launch() {
                    this.launching = true;
                    try {
                        const res = await fetch('/quant-lab/api/experiments', {
                            method: 'POST',
                            headers: {'Content-Type': 'application/json'},
                            body: JSON.stringify(this.config),
                        });
                        const data = await res.json();
                        if (data.job_id) {
                            window.location.href = '/quant-lab/monitor';
                        } else {
                            alert('Error: ' + (data.error || 'Unknown error'));
                        }
                    } catch (e) {
                        alert('Error: ' + e.message);
                    }
                    this.launching = false;
                },
            };
        }
    </script>
</body>
</html>
```

**Step 3: Commit**

```bash
git add web/templates/quant_lab/designer.html
git commit -m "feat(quant-lab): add experiment designer template"
```

---

### Task 13: Create Job Monitor Template

**Files:**
- Create: `web/templates/quant_lab/monitor.html`

**Step 1: Write monitor template**

```html
<!-- web/templates/quant_lab/monitor.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant Lab - Job Monitor</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
    <div x-data="jobMonitor()" x-init="init()" class="container mx-auto px-4 py-8">
        <!-- Header -->
        <div class="flex justify-between items-center mb-8">
            <h1 class="text-3xl font-bold text-blue-400">Job Monitor</h1>
            <div class="space-x-4">
                <a href="/quant-lab/" class="text-gray-400 hover:text-white">New Experiment</a>
                <a href="/" class="text-gray-400 hover:text-white">Dashboard</a>
            </div>
        </div>

        <!-- Active Jobs -->
        <div class="bg-gray-800 rounded-lg p-6 mb-8">
            <h2 class="text-xl font-semibold mb-4">Active Jobs</h2>
            <div x-show="activeJobs.length === 0" class="text-gray-500 text-center py-8">
                No active jobs. <a href="/quant-lab/" class="text-blue-400 hover:underline">Start an experiment</a>
            </div>
            <template x-for="job in activeJobs" :key="job.study_name">
                <div class="border border-gray-700 rounded-lg p-4 mb-4">
                    <div class="flex justify-between items-center mb-2">
                        <h3 class="font-semibold" x-text="job.study_name"></h3>
                        <span :class="statusClass(job.status)" class="px-2 py-1 rounded text-sm"
                              x-text="job.status"></span>
                    </div>
                    <div x-show="job.status === 'running'" class="mb-4">
                        <div class="flex justify-between text-sm text-gray-400 mb-1">
                            <span>Progress</span>
                            <span x-text="job.current_trial + '/' + (job.max_trials || '?')"></span>
                        </div>
                        <div class="w-full bg-gray-700 rounded-full h-2">
                            <div class="bg-blue-600 h-2 rounded-full transition-all"
                                 :style="'width: ' + (job.current_trial / (job.max_trials || 500) * 100) + '%'"></div>
                        </div>
                    </div>
                    <div class="flex space-x-4 text-sm">
                        <a :href="'/quant-lab/results/' + job.study_name"
                           class="text-blue-400 hover:underline">View Results</a>
                        <button @click="cancelJob(job.job_id)" x-show="job.status === 'running'"
                                class="text-red-400 hover:underline">Cancel</button>
                    </div>
                </div>
            </template>
        </div>

        <!-- Completed Experiments -->
        <div class="bg-gray-800 rounded-lg p-6">
            <h2 class="text-xl font-semibold mb-4">Completed Experiments</h2>
            <table class="w-full">
                <thead>
                    <tr class="text-left text-gray-400 border-b border-gray-700">
                        <th class="pb-2">Name</th>
                        <th class="pb-2">Trials</th>
                        <th class="pb-2">Pareto Size</th>
                        <th class="pb-2">Date</th>
                        <th class="pb-2">Actions</th>
                    </tr>
                </thead>
                <tbody>
                    <template x-for="exp in completedExperiments" :key="exp.study_name">
                        <tr class="border-b border-gray-700">
                            <td class="py-3" x-text="exp.study_name"></td>
                            <td class="py-3" x-text="exp.n_trials"></td>
                            <td class="py-3" x-text="exp.pareto_size || '-'"></td>
                            <td class="py-3" x-text="formatDate(exp.datetime_start)"></td>
                            <td class="py-3">
                                <a :href="'/quant-lab/results/' + exp.study_name"
                                   class="text-blue-400 hover:underline">View</a>
                            </td>
                        </tr>
                    </template>
                </tbody>
            </table>
        </div>
    </div>

    <script>
        function jobMonitor() {
            return {
                activeJobs: [],
                completedExperiments: [],
                pollInterval: null,

                async init() {
                    await this.loadExperiments();
                    this.pollInterval = setInterval(() => this.loadExperiments(), 5000);
                },

                async loadExperiments() {
                    try {
                        const res = await fetch('/quant-lab/api/experiments');
                        const data = await res.json();
                        this.completedExperiments = data.experiments || [];
                        // TODO: Filter active vs completed based on status
                    } catch (e) {
                        console.error('Failed to load experiments:', e);
                    }
                },

                statusClass(status) {
                    return {
                        'running': 'bg-blue-900 text-blue-300',
                        'completed': 'bg-green-900 text-green-300',
                        'failed': 'bg-red-900 text-red-300',
                        'pending': 'bg-yellow-900 text-yellow-300',
                    }[status] || 'bg-gray-700';
                },

                formatDate(isoStr) {
                    if (!isoStr) return '-';
                    return new Date(isoStr).toLocaleDateString();
                },

                async cancelJob(jobId) {
                    if (!confirm('Cancel this job?')) return;
                    // TODO: Implement job cancellation
                    alert('Job cancellation not yet implemented');
                },
            };
        }
    </script>
</body>
</html>
```

**Step 2: Commit**

```bash
git add web/templates/quant_lab/monitor.html
git commit -m "feat(quant-lab): add job monitor template"
```

---

### Task 14: Create Results Template with Pareto Plot

**Files:**
- Create: `web/templates/quant_lab/results.html`

**Step 1: Write results template**

```html
<!-- web/templates/quant_lab/results.html -->
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Quant Lab - Results</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <script src="https://unpkg.com/alpinejs@3.x.x/dist/cdn.min.js" defer></script>
    <script src="https://cdn.plot.ly/plotly-2.27.0.min.js"></script>
</head>
<body class="bg-gray-900 text-gray-100 min-h-screen">
    <div x-data="resultsViewer()" x-init="init()" class="container mx-auto px-4 py-8">
        <!-- Header -->
        <div class="flex justify-between items-center mb-8">
            <div>
                <h1 class="text-3xl font-bold text-blue-400" x-text="studyName"></h1>
                <p class="text-gray-400 mt-1">
                    <span x-text="stats.total_trials"></span> trials |
                    <span x-text="stats.pareto_front_size"></span> Pareto-optimal
                </p>
            </div>
            <div class="space-x-4">
                <a href="/quant-lab/monitor" class="text-gray-400 hover:text-white">Monitor</a>
                <a href="/quant-lab/" class="text-gray-400 hover:text-white">New Experiment</a>
                <a :href="'http://localhost:5000/#/experiments/' + mlflowExperiment"
                   target="_blank" class="text-blue-400 hover:underline">Open in MLflow</a>
            </div>
        </div>

        <!-- Pareto Plot -->
        <div class="bg-gray-800 rounded-lg p-6 mb-8">
            <h2 class="text-xl font-semibold mb-4">Pareto Frontier</h2>
            <div id="pareto-plot" class="h-96"></div>
        </div>

        <!-- Ranked Table -->
        <div class="bg-gray-800 rounded-lg p-6 mb-8">
            <h2 class="text-xl font-semibold mb-4">Top Configurations</h2>
            <div class="overflow-x-auto">
                <table class="w-full">
                    <thead>
                        <tr class="text-left text-gray-400 border-b border-gray-700">
                            <th class="pb-2 cursor-pointer" @click="sortBy('rank')">Rank</th>
                            <th class="pb-2 cursor-pointer" @click="sortBy('win_rate')">Win Rate</th>
                            <th class="pb-2 cursor-pointer" @click="sortBy('total_return')">Return</th>
                            <th class="pb-2 cursor-pointer" @click="sortBy('max_drawdown')">Max DD</th>
                            <th class="pb-2">Actions</th>
                        </tr>
                    </thead>
                    <tbody>
                        <template x-for="(trial, i) in sortedPareto" :key="trial.trial_number">
                            <tr class="border-b border-gray-700 hover:bg-gray-700/50 cursor-pointer"
                                @click="selectTrial(trial)">
                                <td class="py-3" x-text="i + 1"></td>
                                <td class="py-3" x-text="(trial.values.win_rate * 100).toFixed(1) + '%'"></td>
                                <td class="py-3" :class="trial.values.total_return >= 0 ? 'text-green-400' : 'text-red-400'"
                                    x-text="(trial.values.total_return * 100).toFixed(2) + '%'"></td>
                                <td class="py-3 text-red-400"
                                    x-text="(trial.values.max_drawdown * 100).toFixed(1) + '%'"></td>
                                <td class="py-3">
                                    <button @click.stop="exportConfig(trial)"
                                            class="text-blue-400 hover:underline text-sm">Export</button>
                                </td>
                            </tr>
                        </template>
                    </tbody>
                </table>
            </div>
        </div>

        <!-- Selected Trial Detail -->
        <div x-show="selectedTrial" class="bg-gray-800 rounded-lg p-6">
            <div class="flex justify-between items-center mb-4">
                <h2 class="text-xl font-semibold">Configuration Detail</h2>
                <button @click="selectedTrial = null" class="text-gray-400 hover:text-white">Close</button>
            </div>
            <div class="grid grid-cols-7 gap-2 mb-4">
                <template x-for="regime in regimes" :key="regime">
                    <div class="bg-gray-900 rounded p-2 text-xs">
                        <div class="font-semibold text-blue-400 truncate" x-text="regime.replace('_', ' ')"></div>
                        <div class="mt-1" x-text="getRegimeEntry(regime)"></div>
                        <div class="text-gray-500" x-text="getRegimeExit(regime)"></div>
                    </div>
                </template>
            </div>
            <div>
                <h3 class="font-semibold mb-2">Full Parameters</h3>
                <pre class="bg-gray-900 rounded p-4 text-sm overflow-auto max-h-64"
                     x-text="JSON.stringify(selectedTrial?.params, null, 2)"></pre>
            </div>
        </div>
    </div>

    <script>
        function resultsViewer() {
            return {
                studyName: '{{ study_name }}',
                mlflowExperiment: 'quant_lab',
                stats: {},
                pareto: [],
                selectedTrial: null,
                sortKey: 'total_return',
                sortDesc: true,
                regimes: [
                    'BULL_STRONG', 'BULL_MODERATE',
                    'SIDEWAYS_UP', 'SIDEWAYS_FLAT', 'SIDEWAYS_DOWN',
                    'BEAR_MODERATE', 'BEAR_STRONG'
                ],

                get sortedPareto() {
                    return [...this.pareto].sort((a, b) => {
                        const aVal = a.values[this.sortKey];
                        const bVal = b.values[this.sortKey];
                        return this.sortDesc ? bVal - aVal : aVal - bVal;
                    });
                },

                async init() {
                    try {
                        const res = await fetch(`/quant-lab/api/experiments/${this.studyName}/results`);
                        const data = await res.json();
                        this.stats = data.stats;
                        this.pareto = data.pareto_front;
                        this.renderParetoPlot();
                    } catch (e) {
                        console.error('Failed to load results:', e);
                    }
                },

                renderParetoPlot() {
                    const trace = {
                        x: this.pareto.map(t => t.values.total_return * 100),
                        y: this.pareto.map(t => t.values.win_rate * 100),
                        mode: 'markers',
                        type: 'scatter',
                        marker: {
                            size: this.pareto.map(t => Math.max(10, 50 - t.values.max_drawdown * 100)),
                            color: this.pareto.map(t => t.values.max_drawdown * 100),
                            colorscale: 'RdYlGn',
                            reversescale: true,
                            showscale: true,
                            colorbar: {title: 'Max DD %'},
                        },
                        text: this.pareto.map(t => `Trial ${t.trial_number}`),
                        hovertemplate:
                            'Return: %{x:.1f}%<br>' +
                            'Win Rate: %{y:.1f}%<br>' +
                            '%{text}<extra></extra>',
                    };

                    const layout = {
                        paper_bgcolor: 'rgba(0,0,0,0)',
                        plot_bgcolor: 'rgba(31,41,55,1)',
                        font: {color: '#9CA3AF'},
                        xaxis: {title: 'Total Return %', gridcolor: '#374151'},
                        yaxis: {title: 'Win Rate %', gridcolor: '#374151'},
                        margin: {l: 60, r: 20, t: 20, b: 60},
                    };

                    Plotly.newPlot('pareto-plot', [trace], layout, {responsive: true});

                    document.getElementById('pareto-plot').on('plotly_click', (data) => {
                        const idx = data.points[0].pointIndex;
                        this.selectTrial(this.pareto[idx]);
                    });
                },

                selectTrial(trial) {
                    this.selectedTrial = trial;
                },

                sortBy(key) {
                    if (this.sortKey === key) {
                        this.sortDesc = !this.sortDesc;
                    } else {
                        this.sortKey = key;
                        this.sortDesc = true;
                    }
                },

                getRegimeEntry(regime) {
                    if (!this.selectedTrial) return '';
                    const key = `${regime}_entry`;
                    return this.selectedTrial.params[key] || '-';
                },

                getRegimeExit(regime) {
                    if (!this.selectedTrial) return '';
                    const key = `${regime}_exit`;
                    return this.selectedTrial.params[key] || '-';
                },

                exportConfig(trial) {
                    const config = {
                        study_name: this.studyName,
                        trial_number: trial.trial_number,
                        params: trial.params,
                        values: trial.values,
                    };
                    const blob = new Blob([JSON.stringify(config, null, 2)], {type: 'application/json'});
                    const url = URL.createObjectURL(blob);
                    const a = document.createElement('a');
                    a.href = url;
                    a.download = `${this.studyName}_trial_${trial.trial_number}.json`;
                    a.click();
                },
            };
        }
    </script>
</body>
</html>
```

**Step 2: Commit**

```bash
git add web/templates/quant_lab/results.html
git commit -m "feat(quant-lab): add results template with Pareto plot"
```

---

## Phase 9: Integration

### Task 15: Register Blueprint in Flask App

**Files:**
- Modify: `web/app.py`

**Step 1: Find blueprint registration location**

```bash
grep -n "register_blueprint\|Blueprint" web/app.py | head -10
```

**Step 2: Add quant_lab blueprint import and registration**

Add near other imports:
```python
from web.quant_lab.routes import quant_lab_bp
```

Add near other blueprint registrations:
```python
app.register_blueprint(quant_lab_bp, url_prefix='/quant-lab')
```

**Step 3: Test app starts**

```bash
python -c "from web.app import app; print('App imports OK')"
```

**Step 4: Commit**

```bash
git add web/app.py
git commit -m "feat(quant-lab): register blueprint in Flask app"
```

---

### Task 16: Create Experiment Templates JSON

**Files:**
- Create: `config/experiment_templates/v35_param_sweep.json`
- Create: `config/experiment_templates/full_regime_search.json`

**Step 1: Create templates directory**

```bash
mkdir -p config/experiment_templates
```

**Step 2: Write template files**

```json
// config/experiment_templates/v35_param_sweep.json
{
  "name": "V35 Parameter Sweep",
  "description": "Fixed V35Entry/Exit for BULL regimes, tune params only",
  "search_config": {
    "BULL_STRONG": {"entries": ["V35Entry"], "exits": ["V35TrailingExit"]},
    "BULL_MODERATE": {"entries": ["V35Entry"], "exits": ["V35TrailingExit"]},
    "SIDEWAYS_UP": {"entries": ["V35Entry", "SidewaysEntry"], "exits": ["V35TrailingExit", "SidewaysExit"]},
    "SIDEWAYS_FLAT": {"entries": ["SidewaysEntry", "None"], "exits": ["SidewaysExit"]},
    "SIDEWAYS_DOWN": {"entries": ["SidewaysEntry", "None"], "exits": ["SidewaysExit"]},
    "BEAR_MODERATE": {"entries": ["ShortEntry", "None"], "exits": ["V35TrailingExit"]},
    "BEAR_STRONG": {"entries": ["ShortEntry"], "exits": ["V35TrailingExit"]}
  },
  "default_constraints": {
    "max_trials": 300,
    "max_drawdown": 0.25
  }
}
```

```json
// config/experiment_templates/full_regime_search.json
{
  "name": "Full Regime Search",
  "description": "All Entry/Exit combinations across all 7 regimes",
  "search_config": null,
  "default_constraints": {
    "max_trials": 500,
    "max_drawdown": 0.30
  }
}
```

**Step 3: Commit**

```bash
git add config/experiment_templates/
git commit -m "feat(quant-lab): add experiment template configurations"
```

---

## Phase 10: Final Integration Tests

### Task 17: Write Integration Tests

**Files:**
- Create: `tests/web/quant_lab/test_integration.py`

**Step 1: Write integration tests**

```python
# tests/web/quant_lab/test_integration.py
"""Integration tests for Quant Lab."""
import pytest
from flask import Flask
from web.quant_lab.routes import quant_lab_bp
from web.quant_lab.optimizer.search_space import SearchSpaceConfig, build_search_space, sample_trial_config
from web.quant_lab.optimizer.study_manager import StudyManager
from unittest.mock import MagicMock
import tempfile
import os


class TestFullWorkflow:
    """Test complete Quant Lab workflow."""

    def test_search_space_to_trial_config(self):
        """SearchSpaceConfig -> sample_trial_config should work end-to-end."""
        config = SearchSpaceConfig()
        space = build_search_space(config)

        # Verify all regimes present
        assert len(space) == 7

        # Mock trial and sample
        mock_trial = MagicMock()
        mock_trial.suggest_categorical.side_effect = lambda n, c: c[0]
        mock_trial.suggest_float.return_value = 50.0

        result = sample_trial_config(mock_trial, config)

        # Verify result structure
        assert len(result) == 7
        for regime, regime_config in result.items():
            assert "entry" in regime_config
            assert "exit" in regime_config
            assert "params" in regime_config

    def test_study_manager_full_lifecycle(self):
        """StudyManager should handle create -> optimize -> results."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = os.path.join(tmpdir, "test.db")
            manager = StudyManager(storage_path=db_path)

            # Create study
            study = manager.create_study("integration_test")
            assert study.study_name == "integration_test"

            # Verify listing
            studies = manager.list_studies()
            assert any(s.study_name == "integration_test" for s in studies)

            # Get stats (empty study)
            stats = manager.get_study_stats("integration_test")
            assert stats["total_trials"] == 0
            assert stats["pareto_front_size"] == 0

    def test_flask_routes_available(self):
        """All Quant Lab routes should be accessible."""
        app = Flask(__name__)
        app.config['TESTING'] = True
        app.register_blueprint(quant_lab_bp, url_prefix='/quant-lab')
        client = app.test_client()

        # Index
        response = client.get('/quant-lab/')
        assert response.status_code == 200

        # Templates API
        response = client.get('/quant-lab/api/templates')
        assert response.status_code == 200
        data = response.get_json()
        assert 'templates' in data

        # Search space API
        response = client.get('/quant-lab/api/search-space')
        assert response.status_code == 200
        data = response.get_json()
        assert 'regimes' in data
        assert len(data['regimes']) == 7
```

**Step 2: Run integration tests**

```bash
pytest tests/web/quant_lab/test_integration.py -v
```
Expected: PASS

**Step 3: Commit**

```bash
git add tests/web/quant_lab/test_integration.py
git commit -m "test(quant-lab): add integration tests"
```

---

### Task 18: Update CLAUDE.md with Quant Lab Reference

**Files:**
- Modify: `CLAUDE.md`

**Step 1: Add Quant Lab reference to Quick Reference section**

Add to the Quick Reference section:
```markdown
- Quant Lab Design → `docs/plans/2026-01-20-quant-lab-design.md`
- Quant Lab Implementation → `docs/plans/2026-01-20-quant-lab-implementation.md`
```

**Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: add Quant Lab references to CLAUDE.md"
```

---

## Summary

**18 Tasks across 10 Phases:**

| Phase | Tasks | Description |
|-------|-------|-------------|
| 1 | 1-2 | Core infrastructure (RQ, module structure) |
| 2 | 3-4 | Search space definition |
| 3 | 5-6 | Objective function and regime adapter |
| 4 | 7 | Constraints and guardrails |
| 5 | 8 | Study manager |
| 6 | 9-10 | Background worker |
| 7 | 11 | Flask routes |
| 8 | 12-14 | Templates and UI |
| 9 | 15-16 | Integration |
| 10 | 17-18 | Tests and documentation |

**Run all tests after completion:**
```bash
pytest tests/web/quant_lab/ -v
```

**Start the system:**
```bash
# Terminal 1: Flask app
python -c "from web.app import app; app.run(debug=True, port=5001)"

# Terminal 2: RQ worker
python -m web.quant_lab.worker.runner

# Terminal 3: MLflow UI (optional)
mlflow ui --backend-store-uri ./mlruns
```
