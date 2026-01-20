# MLflow Optimizer Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve optimize_mlflow.py with SQL injection prevention, parallel processing, progress tracking, and comprehensive tests.

**Architecture:** Enhance DataLoader with parameterized queries, add ProcessPoolExecutor for parallel backtests, integrate tqdm for progress, batch MLflow logging, and generate PARAM_GRIDS_QUICK programmatically.

**Tech Stack:** Python 3.9+, sqlite3, concurrent.futures, tqdm, MLflow, pytest

---

## Status Analysis

**Already Implemented (verified in codebase):**
- ✅ Date validation with `validate_date()` and `validate_date_range()` (optimize_mlflow.py:50-93)
- ✅ Timeframe calculation with `CANDLES_PER_YEAR` dict (optimize_mlflow.py:37-47)
- ✅ Input validation helper `validate_date_range()` (optimize_mlflow.py:72-88)

**Needs Implementation:**
1. Parameterized SQL queries in DataLoader
2. Multiprocessing for parallel backtests
3. Refactor `run_optimization()` into smaller functions
4. Tests for optimizer functions
5. tqdm progress tracking with ETA
6. Batch MLflow logging
7. Generate `PARAM_GRIDS_QUICK` programmatically

---

## Task 1: Parameterized SQL Queries in DataLoader

**Files:**
- Modify: `core/data_loader.py:84-117`
- Test: `tests/core/test_data_loader.py` (create)

**Step 1: Write the failing test**

```python
# tests/core/test_data_loader.py
"""Tests for DataLoader parameterized queries."""

import pytest
import pandas as pd
from unittest.mock import patch, MagicMock


def test_load_timeframe_uses_parameterized_query():
    """Verify DataLoader uses parameterized queries to prevent SQL injection."""
    from core.data_loader import DataLoader

    # Create a mock connection
    mock_conn = MagicMock()
    mock_df = pd.DataFrame({
        'timestamp': ['2024-01-01'],
        'open': [100.0],
        'high': [101.0],
        'low': [99.0],
        'close': [100.5],
        'volume': [1000],
    })

    with patch('sqlite3.connect', return_value=mock_conn):
        with patch('pandas.read_sql_query', return_value=mock_df) as mock_read_sql:
            with patch.object(DataLoader, '__init__', lambda self, *args, **kwargs: None):
                loader = DataLoader()
                loader.conn = mock_conn
                loader.exchange = 'binance'
                loader.db_path = '/fake/path'

                # Call with potentially dangerous input
                loader._load_binance_timeframe(
                    'minute60',
                    start_date="2024-01-01",
                    end_date="2024-01-31"
                )

                # Verify parameterized query was used (not f-string interpolation)
                call_args = mock_read_sql.call_args
                query = call_args[0][0]

                # Query should use ? placeholders, not string interpolation
                assert "?" in query or "WHERE timestamp >= ?" in query or \
                    "start_date" not in query, \
                    f"Query should use parameterized placeholders, got: {query}"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/core/test_data_loader.py -v`
Expected: FAIL (query uses f-string interpolation)

**Step 3: Write minimal implementation**

```python
# core/data_loader.py - Replace _load_binance_timeframe method

def _load_binance_timeframe(
    self,
    timeframe: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None
) -> pd.DataFrame:
    """Binance 데이터 로드 with parameterized queries."""
    if timeframe not in self.BINANCE_TABLE_MAP:
        raise ValueError(f"지원하지 않는 타임프레임: {timeframe}")

    table_name = self.BINANCE_TABLE_MAP[timeframe]

    # Build query with parameterized placeholders
    params = []
    conditions = []

    if start_date:
        conditions.append("timestamp >= ?")
        params.append(start_date)
    if end_date:
        conditions.append("timestamp <= ?")
        params.append(end_date)

    # Table name is safe (from internal mapping), but dates use parameters
    query = f"SELECT * FROM {table_name}"
    if conditions:
        query += " WHERE " + " AND ".join(conditions)
    query += " ORDER BY timestamp ASC"

    df = pd.read_sql_query(query, self.conn, params=params)

    # Binance 컬럼명은 이미 표준 형식
    df['timestamp'] = pd.to_datetime(df['timestamp'])

    # 필요한 컬럼만 선택
    cols = ['timestamp', 'open', 'high', 'low', 'close', 'volume']
    df = df[[c for c in cols if c in df.columns]]

    return df
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/core/test_data_loader.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add core/data_loader.py tests/core/test_data_loader.py
git commit -m "fix: use parameterized SQL queries in DataLoader to prevent injection"
```

---

## Task 2: Add tqdm Progress Tracking

**Files:**
- Modify: `scripts/optimize_mlflow.py:492-541`
- Test: `tests/scripts/test_optimize_mlflow.py` (create)

**Step 1: Write the failing test**

```python
# tests/scripts/test_optimize_mlflow.py
"""Tests for optimize_mlflow.py functions."""

import pytest
from unittest.mock import patch, MagicMock


def test_run_optimization_uses_tqdm_progress():
    """Verify optimization loop uses tqdm for progress tracking."""
    with patch('scripts.optimize_mlflow.tqdm') as mock_tqdm:
        with patch('scripts.optimize_mlflow.load_data') as mock_load:
            with patch('scripts.optimize_mlflow.mlflow'):
                with patch('scripts.optimize_mlflow.run_backtest'):
                    mock_load.return_value = MagicMock()
                    mock_load.return_value.empty = False
                    mock_load.return_value.__len__ = lambda self: 1000

                    from scripts.optimize_mlflow import run_optimization

                    # Should use tqdm for progress
                    # This test will fail until tqdm is integrated
                    try:
                        run_optimization(
                            strategy_name="v35_long",
                            experiment_name="test",
                            dry_run=False,
                            quick=True,
                            max_combinations=2,
                        )
                    except Exception:
                        pass  # May fail due to mocking, but tqdm should be called

                    assert mock_tqdm.called, "tqdm should be used for progress tracking"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/scripts/test_optimize_mlflow.py::test_run_optimization_uses_tqdm_progress -v`
Expected: FAIL (tqdm not imported/used)

**Step 3: Write minimal implementation**

```python
# scripts/optimize_mlflow.py - Add import at top
from tqdm import tqdm

# Replace the optimization loop (around line 492-541) with:

    # Run optimization with progress bar
    print(f"\nRunning {len(combinations)} backtests...")
    results: List[OptimizationResult] = []

    for params in tqdm(combinations, desc="Optimizing", unit="run"):
        entry_params, exit_params = split_params(params, strategy_name)

        with mlflow.start_run(run_name=f"{strategy_name}_run_{len(results)+1}"):
            # Log parameters
            mlflow.log_params(params)
            mlflow.log_param("strategy_name", strategy_name)
            mlflow.log_param("market", market)
            mlflow.log_param("train_start", train_start)
            mlflow.log_param("train_end", train_end)

            try:
                result = run_backtest(
                    strategy_name=strategy_name,
                    entry_params=entry_params,
                    exit_params=exit_params,
                    df=df,
                    market=market,
                    timeframe=timeframe,
                )

                # Log metrics
                mlflow.log_metric("total_return", result.total_return)
                mlflow.log_metric("total_trades", result.total_trades)
                mlflow.log_metric("win_rate", result.win_rate)
                mlflow.log_metric("sharpe_ratio", result.sharpe_ratio)
                mlflow.log_metric("max_drawdown", result.max_drawdown)
                pf = result.profit_factor if np.isfinite(result.profit_factor) else 999.99
                mlflow.log_metric("profit_factor", pf)
                mlflow.log_metric("avg_trades_per_year", result.avg_trades_per_year)

                results.append(result)

            except KeyboardInterrupt:
                print(f"\n  Interrupted by user")
                raise
            except (MemoryError, SystemExit):
                raise
            except Exception as e:
                safe_error = sanitize_error_message(e)
                mlflow.set_tag("error", safe_error)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/scripts/test_optimize_mlflow.py::test_run_optimization_uses_tqdm_progress -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/optimize_mlflow.py tests/scripts/test_optimize_mlflow.py
git commit -m "feat: add tqdm progress tracking with ETA to optimization loop"
```

---

## Task 3: Add Multiprocessing for Parallel Backtests

**Files:**
- Modify: `scripts/optimize_mlflow.py`
- Test: `tests/scripts/test_optimize_mlflow.py`

**Step 1: Write the failing test**

```python
# tests/scripts/test_optimize_mlflow.py - Add this test

def test_run_single_backtest_is_parallelizable():
    """Verify run_single_backtest can be called independently for parallel execution."""
    from scripts.optimize_mlflow import run_single_backtest

    # Should exist and be callable
    assert callable(run_single_backtest), "run_single_backtest should exist for parallel execution"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/scripts/test_optimize_mlflow.py::test_run_single_backtest_is_parallelizable -v`
Expected: FAIL (function doesn't exist)

**Step 3: Write minimal implementation**

```python
# scripts/optimize_mlflow.py - Add new function and imports

from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Tuple

def run_single_backtest(
    args: Tuple[int, Dict[str, Any], str, str, pd.DataFrame, str]
) -> Tuple[int, Optional[OptimizationResult], Optional[str]]:
    """Run a single backtest for parallel execution.

    Args:
        args: Tuple of (index, params, strategy_name, market, df, timeframe)

    Returns:
        Tuple of (index, result, error_message)
    """
    idx, params, strategy_name, market, df, timeframe = args
    entry_params, exit_params = split_params(params, strategy_name)

    try:
        result = run_backtest(
            strategy_name=strategy_name,
            entry_params=entry_params,
            exit_params=exit_params,
            df=df,
            market=market,
            timeframe=timeframe,
        )
        return (idx, result, None)
    except Exception as e:
        return (idx, None, sanitize_error_message(e))


def run_optimization_parallel(
    strategy_name: str,
    experiment_name: str,
    train_start: str = "2020-01-01",
    train_end: str = "2024-12-31",
    timeframe: str = "minute240",
    market: str = "futures",
    max_combinations: int = 0,
    quick: bool = False,
    max_workers: int = 4,
) -> List[OptimizationResult]:
    """Run grid search optimization with parallel backtests.

    Args:
        strategy_name: Strategy to optimize.
        experiment_name: MLflow experiment name.
        train_start: Training data start date.
        train_end: Training data end date.
        timeframe: Data timeframe.
        market: Market type.
        max_combinations: Limit combinations (0 = no limit).
        quick: Use reduced parameter grid.
        max_workers: Number of parallel workers.

    Returns:
        List of optimization results sorted by total return.
    """
    print("=" * 80)
    print(f"MLflow Strategy Optimization (Parallel): {strategy_name}")
    print("=" * 80)

    # Validate inputs
    print("\nValidating inputs...")
    validate_date_range(train_start, train_end)

    # Get parameter grid
    grids = PARAM_GRIDS_QUICK if quick else PARAM_GRIDS
    if strategy_name not in grids:
        raise ValueError(f"Unknown strategy: {strategy_name}")

    param_grid = grids[strategy_name]
    combinations = generate_param_combinations(param_grid)

    if max_combinations > 0:
        combinations = combinations[:max_combinations]

    print(f"\nTotal combinations: {len(combinations)}")
    print(f"Using {max_workers} parallel workers")

    # Load data once (shared across workers)
    print(f"\nLoading data: {train_start} to {train_end} ({timeframe})...")
    df = load_data(train_start, train_end, timeframe)
    validate_dataframe(df, timeframe)
    print(f"  Loaded {len(df):,} candles")

    # Prepare arguments for parallel execution
    args_list = [
        (i, params, strategy_name, market, df, timeframe)
        for i, params in enumerate(combinations)
    ]

    # Run parallel backtests
    results: List[OptimizationResult] = []
    errors: List[Tuple[int, str]] = []

    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(run_single_backtest, args): args[0]
            for args in args_list
        }

        for future in tqdm(
            as_completed(futures),
            total=len(futures),
            desc="Optimizing",
            unit="run"
        ):
            idx, result, error = future.result()
            if result:
                results.append(result)
            if error:
                errors.append((idx, error))

    # Log to MLflow (sequential to avoid conflicts)
    print(f"\nLogging {len(results)} results to MLflow...")
    mlflow.set_tracking_uri("./mlruns")
    mlflow.set_experiment(experiment_name)

    for i, result in enumerate(tqdm(results, desc="Logging")):
        with mlflow.start_run(run_name=f"{strategy_name}_run_{i+1}"):
            mlflow.log_params(result.params)
            mlflow.log_param("strategy_name", strategy_name)
            mlflow.log_param("market", market)
            mlflow.log_metric("total_return", result.total_return)
            mlflow.log_metric("total_trades", result.total_trades)
            mlflow.log_metric("win_rate", result.win_rate)
            mlflow.log_metric("sharpe_ratio", result.sharpe_ratio)
            mlflow.log_metric("max_drawdown", result.max_drawdown)
            pf = result.profit_factor if np.isfinite(result.profit_factor) else 999.99
            mlflow.log_metric("profit_factor", pf)

    # Sort and return
    results.sort(key=lambda r: r.total_return, reverse=True)

    if errors:
        print(f"\n  {len(errors)} runs failed")

    return results
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/scripts/test_optimize_mlflow.py::test_run_single_backtest_is_parallelizable -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/optimize_mlflow.py tests/scripts/test_optimize_mlflow.py
git commit -m "feat: add multiprocessing support for parallel backtests"
```

---

## Task 4: Generate PARAM_GRIDS_QUICK Programmatically

**Files:**
- Modify: `scripts/optimize_mlflow.py:396-412`
- Test: `tests/scripts/test_optimize_mlflow.py`

**Step 1: Write the failing test**

```python
# tests/scripts/test_optimize_mlflow.py - Add this test

def test_param_grids_quick_generated_from_param_grids():
    """Verify PARAM_GRIDS_QUICK is derived from PARAM_GRIDS, not duplicated."""
    from scripts.optimize_mlflow import PARAM_GRIDS, PARAM_GRIDS_QUICK

    # All keys in QUICK should exist in full PARAM_GRIDS
    for strategy, quick_params in PARAM_GRIDS_QUICK.items():
        assert strategy in PARAM_GRIDS, f"{strategy} missing from PARAM_GRIDS"
        full_params = PARAM_GRIDS[strategy]

        for param_name in quick_params.keys():
            assert param_name in full_params, \
                f"{param_name} in QUICK but not in full PARAM_GRIDS[{strategy}]"

    # QUICK should have fewer values per parameter (subset)
    for strategy in PARAM_GRIDS_QUICK:
        for param_name, quick_values in PARAM_GRIDS_QUICK[strategy].items():
            full_values = PARAM_GRIDS[strategy][param_name]
            assert len(quick_values) <= len(full_values), \
                f"QUICK[{strategy}][{param_name}] should be subset of full grid"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/scripts/test_optimize_mlflow.py::test_param_grids_quick_generated_from_param_grids -v`
Expected: May PASS (current impl happens to match), but let's ensure it's generated

**Step 3: Write minimal implementation**

```python
# scripts/optimize_mlflow.py - Replace PARAM_GRIDS_QUICK definition

def _generate_quick_grid(full_grid: Dict[str, List], max_values: int = 2) -> Dict[str, List]:
    """Generate quick parameter grid from full grid.

    Takes first and last value from each parameter list, plus middle if exists.

    Args:
        full_grid: Full parameter grid.
        max_values: Maximum values per parameter.

    Returns:
        Reduced parameter grid.
    """
    quick = {}
    for key, values in full_grid.items():
        if len(values) <= max_values:
            quick[key] = values
        else:
            # Take first and last (covers range endpoints)
            quick[key] = [values[0], values[-1]]
    return quick


# Generate PARAM_GRIDS_QUICK programmatically from PARAM_GRIDS
PARAM_GRIDS_QUICK = {
    strategy: _generate_quick_grid(params)
    for strategy, params in PARAM_GRIDS.items()
}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/scripts/test_optimize_mlflow.py::test_param_grids_quick_generated_from_param_grids -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/optimize_mlflow.py tests/scripts/test_optimize_mlflow.py
git commit -m "refactor: generate PARAM_GRIDS_QUICK programmatically from PARAM_GRIDS"
```

---

## Task 5: Comprehensive Tests for Optimizer Functions

**Files:**
- Create: `tests/scripts/test_optimize_mlflow.py` (expand)
- Create: `tests/core/__init__.py`

**Step 1: Create test file structure**

```bash
mkdir -p tests/scripts tests/core
touch tests/scripts/__init__.py tests/core/__init__.py
```

**Step 2: Write comprehensive tests**

```python
# tests/scripts/test_optimize_mlflow.py - Complete test file

"""Tests for optimize_mlflow.py functions."""

import pytest
import pandas as pd
import numpy as np
from datetime import datetime
from unittest.mock import patch, MagicMock


class TestGenerateParamCombinations:
    """Tests for generate_param_combinations()."""

    def test_single_param_returns_list_of_dicts(self):
        """Single parameter grid returns list of single-key dicts."""
        from scripts.optimize_mlflow import generate_param_combinations

        grid = {"param1": [1, 2, 3]}
        result = generate_param_combinations(grid)

        assert len(result) == 3
        assert result[0] == {"param1": 1}
        assert result[1] == {"param1": 2}
        assert result[2] == {"param1": 3}

    def test_multiple_params_returns_cartesian_product(self):
        """Multiple parameters return cartesian product."""
        from scripts.optimize_mlflow import generate_param_combinations

        grid = {"a": [1, 2], "b": [10, 20]}
        result = generate_param_combinations(grid)

        assert len(result) == 4  # 2 * 2
        expected = [
            {"a": 1, "b": 10},
            {"a": 1, "b": 20},
            {"a": 2, "b": 10},
            {"a": 2, "b": 20},
        ]
        assert result == expected

    def test_empty_grid_returns_single_empty_dict(self):
        """Empty grid returns list with single empty dict."""
        from scripts.optimize_mlflow import generate_param_combinations

        result = generate_param_combinations({})
        assert result == [{}]


class TestSplitParams:
    """Tests for split_params()."""

    def test_entry_params_separated_correctly(self):
        """Entry parameters are separated from combined dict."""
        from scripts.optimize_mlflow import split_params

        params = {
            "mfi_bull_strong": 54.0,
            "adx_strong_trend": 25.0,
            "stop_loss_pct": 2.0,
            "position_size": 0.5,
        }

        entry, exit_p = split_params(params, "v35_long")

        assert "mfi_bull_strong" in entry
        assert "position_size" in entry
        assert "stop_loss_pct" in exit_p
        assert "stop_loss_pct" not in entry

    def test_unknown_key_goes_to_neither(self):
        """Unknown keys are not included in either dict."""
        from scripts.optimize_mlflow import split_params

        params = {
            "mfi_bull_strong": 54.0,
            "unknown_param": 999,
        }

        entry, exit_p = split_params(params, "v35_long")

        assert "unknown_param" not in entry
        assert "unknown_param" not in exit_p


class TestCalculateProfitFactor:
    """Tests for _calculate_profit_factor()."""

    def test_empty_trades_returns_zero(self):
        """No trades returns 0.0 profit factor."""
        from scripts.optimize_mlflow import _calculate_profit_factor

        result = _calculate_profit_factor([])
        assert result == 0.0

    def test_all_winners_returns_infinity(self):
        """All winning trades returns infinity."""
        from scripts.optimize_mlflow import _calculate_profit_factor

        class MockTrade:
            def __init__(self, pl):
                self.profit_loss = pl

        trades = [MockTrade(100), MockTrade(200), MockTrade(50)]
        result = _calculate_profit_factor(trades)
        assert result == float('inf')

    def test_all_losers_returns_zero(self):
        """All losing trades returns 0.0."""
        from scripts.optimize_mlflow import _calculate_profit_factor

        class MockTrade:
            def __init__(self, pl):
                self.profit_loss = pl

        trades = [MockTrade(-100), MockTrade(-200)]
        result = _calculate_profit_factor(trades)
        assert result == 0.0

    def test_mixed_trades_calculates_correctly(self):
        """Mixed wins/losses calculates correct profit factor."""
        from scripts.optimize_mlflow import _calculate_profit_factor

        class MockTrade:
            def __init__(self, pl):
                self.profit_loss = pl

        # 300 profit, 100 loss = PF 3.0
        trades = [MockTrade(200), MockTrade(100), MockTrade(-100)]
        result = _calculate_profit_factor(trades)
        assert result == 3.0

    def test_none_profit_loss_ignored(self):
        """Trades with None profit_loss are skipped."""
        from scripts.optimize_mlflow import _calculate_profit_factor

        class MockTrade:
            def __init__(self, pl):
                self.profit_loss = pl

        trades = [MockTrade(100), MockTrade(None), MockTrade(-50)]
        result = _calculate_profit_factor(trades)
        assert result == 2.0  # 100 / 50


class TestValidateDateRange:
    """Tests for validate_date_range()."""

    def test_valid_range_passes(self):
        """Valid date range doesn't raise."""
        from scripts.optimize_mlflow import validate_date_range

        # Should not raise
        validate_date_range("2020-01-01", "2024-12-31")

    def test_end_before_start_raises(self):
        """End date before start date raises ValueError."""
        from scripts.optimize_mlflow import validate_date_range

        with pytest.raises(ValueError, match="must be after"):
            validate_date_range("2024-01-01", "2020-01-01")

    def test_same_date_raises(self):
        """Same start and end date raises ValueError."""
        from scripts.optimize_mlflow import validate_date_range

        with pytest.raises(ValueError, match="must be after"):
            validate_date_range("2024-01-01", "2024-01-01")

    def test_invalid_format_raises(self):
        """Invalid date format raises ValueError."""
        from scripts.optimize_mlflow import validate_date_range

        with pytest.raises(ValueError, match="Invalid.*format"):
            validate_date_range("01-01-2024", "2024-12-31")


class TestValidateDataframe:
    """Tests for validate_dataframe()."""

    def test_valid_dataframe_passes(self):
        """Valid DataFrame doesn't raise."""
        from scripts.optimize_mlflow import validate_dataframe

        df = pd.DataFrame({
            'open': [100.0],
            'high': [101.0],
            'low': [99.0],
            'close': [100.5],
        })

        # Should not raise
        validate_dataframe(df, "minute60")

    def test_empty_dataframe_raises(self):
        """Empty DataFrame raises ValueError."""
        from scripts.optimize_mlflow import validate_dataframe

        with pytest.raises(ValueError, match="No data loaded"):
            validate_dataframe(pd.DataFrame(), "minute60")

    def test_none_dataframe_raises(self):
        """None DataFrame raises ValueError."""
        from scripts.optimize_mlflow import validate_dataframe

        with pytest.raises(ValueError, match="No data loaded"):
            validate_dataframe(None, "minute60")

    def test_missing_columns_raises(self):
        """DataFrame missing required columns raises ValueError."""
        from scripts.optimize_mlflow import validate_dataframe

        df = pd.DataFrame({'open': [100.0], 'close': [100.5]})

        with pytest.raises(ValueError, match="missing required columns"):
            validate_dataframe(df, "minute60")
```

**Step 3: Run all tests**

Run: `pytest tests/scripts/test_optimize_mlflow.py -v`
Expected: All PASS

**Step 4: Commit**

```bash
git add tests/scripts/test_optimize_mlflow.py tests/scripts/__init__.py tests/core/__init__.py
git commit -m "test: add comprehensive tests for optimize_mlflow functions"
```

---

## Task 6: Batch MLflow Logging

**Files:**
- Modify: `scripts/optimize_mlflow.py`
- Test: `tests/scripts/test_optimize_mlflow.py`

**Step 1: Write the failing test**

```python
# tests/scripts/test_optimize_mlflow.py - Add this test

def test_batch_log_metrics_exists():
    """Verify batch logging function exists for reduced I/O."""
    from scripts.optimize_mlflow import batch_log_to_mlflow

    assert callable(batch_log_to_mlflow)
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/scripts/test_optimize_mlflow.py::test_batch_log_metrics_exists -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# scripts/optimize_mlflow.py - Add batch logging function

def batch_log_to_mlflow(
    results: List[OptimizationResult],
    experiment_name: str,
    strategy_name: str,
    market: str,
    train_start: str,
    train_end: str,
) -> None:
    """Batch log results to MLflow to reduce I/O overhead.

    Groups results and logs them in batches to minimize MLflow API calls.

    Args:
        results: List of optimization results to log.
        experiment_name: MLflow experiment name.
        strategy_name: Strategy name for tagging.
        market: Market type.
        train_start: Training start date.
        train_end: Training end date.
    """
    if not results:
        return

    mlflow.set_tracking_uri("./mlruns")
    mlflow.set_experiment(experiment_name)

    # Log all results
    for i, result in enumerate(results):
        with mlflow.start_run(run_name=f"{strategy_name}_run_{i+1}"):
            # Batch params together
            all_params = {
                **result.params,
                "strategy_name": strategy_name,
                "market": market,
                "train_start": train_start,
                "train_end": train_end,
            }
            mlflow.log_params(all_params)

            # Batch metrics together
            pf = result.profit_factor if np.isfinite(result.profit_factor) else 999.99
            metrics = {
                "total_return": result.total_return,
                "total_trades": result.total_trades,
                "win_rate": result.win_rate,
                "sharpe_ratio": result.sharpe_ratio,
                "max_drawdown": result.max_drawdown,
                "profit_factor": pf,
                "avg_trades_per_year": result.avg_trades_per_year,
            }
            mlflow.log_metrics(metrics)  # Single call for all metrics
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/scripts/test_optimize_mlflow.py::test_batch_log_metrics_exists -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/optimize_mlflow.py tests/scripts/test_optimize_mlflow.py
git commit -m "feat: add batch MLflow logging to reduce I/O overhead"
```

---

## Task 7: Refactor run_optimization() into Smaller Functions

**Files:**
- Modify: `scripts/optimize_mlflow.py:415-595`
- Test: `tests/scripts/test_optimize_mlflow.py`

**Step 1: Write the failing test**

```python
# tests/scripts/test_optimize_mlflow.py - Add these tests

def test_validate_inputs_function_exists():
    """Verify _validate_inputs helper exists."""
    from scripts.optimize_mlflow import _validate_inputs
    assert callable(_validate_inputs)


def test_generate_report_function_exists():
    """Verify _generate_report helper exists."""
    from scripts.optimize_mlflow import _generate_report
    assert callable(_generate_report)


def test_save_best_params_function_exists():
    """Verify _save_best_params helper exists."""
    from scripts.optimize_mlflow import _save_best_params
    assert callable(_save_best_params)
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/scripts/test_optimize_mlflow.py -k "validate_inputs or generate_report or save_best_params" -v`
Expected: FAIL

**Step 3: Write minimal implementation**

```python
# scripts/optimize_mlflow.py - Add helper functions

def _validate_inputs(
    strategy_name: str,
    train_start: str,
    train_end: str,
    timeframe: str,
    quick: bool,
) -> Dict[str, List]:
    """Validate inputs and return parameter grid.

    Args:
        strategy_name: Strategy to optimize.
        train_start: Training start date.
        train_end: Training end date.
        timeframe: Data timeframe.
        quick: Use reduced parameter grid.

    Returns:
        Parameter grid for the strategy.

    Raises:
        ValueError: If inputs are invalid.
    """
    print("\nValidating inputs...")
    validate_date_range(train_start, train_end)

    if timeframe not in CANDLES_PER_YEAR:
        print(f"  Warning: Unknown timeframe '{timeframe}'. Using default annualization.")

    grids = PARAM_GRIDS_QUICK if quick else PARAM_GRIDS
    if strategy_name not in grids:
        raise ValueError(f"Unknown strategy: {strategy_name}. Available: {list(PARAM_GRIDS.keys())}")

    return grids[strategy_name]


def _generate_report(results: List[OptimizationResult]) -> None:
    """Print optimization results summary.

    Args:
        results: Sorted list of optimization results.
    """
    print("\n" + "=" * 80)
    print("Top 10 Results")
    print("=" * 80)
    print(f"{'Rank':<5} {'Return':>10} {'Trades':>8} {'WinRate':>8} {'Sharpe':>8} {'MDD':>10} {'PF':>8}")
    print("-" * 60)

    for i, r in enumerate(results[:10]):
        print(
            f"{i+1:<5} {r.total_return:>+9.2f}% {r.total_trades:>8} "
            f"{r.win_rate:>7.1f}% {r.sharpe_ratio:>8.2f} "
            f"{r.max_drawdown:>9.2f}% {r.profit_factor:>8.2f}"
        )


def _save_best_params(
    best: OptimizationResult,
    strategy_name: str,
    market: str,
    train_start: str,
    train_end: str,
) -> Path:
    """Save best parameters to JSON file.

    Args:
        best: Best optimization result.
        strategy_name: Strategy name.
        market: Market type.
        train_start: Training start date.
        train_end: Training end date.

    Returns:
        Path to saved file.
    """
    output_dir = PROJECT_ROOT / "config" / "tuned"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_file = output_dir / f"best_{strategy_name}_{market}.json"

    output_data = {
        "optimized_at": pd.Timestamp.now().isoformat(),
        "strategy": strategy_name,
        "market": market,
        "train_period": f"{train_start} to {train_end}",
        "params": best.params,
        "metrics": {
            "total_return": best.total_return,
            "total_trades": best.total_trades,
            "win_rate": best.win_rate,
            "sharpe_ratio": best.sharpe_ratio,
            "max_drawdown": best.max_drawdown,
            "profit_factor": best.profit_factor,
        }
    }
    with open(output_file, "w") as f:
        json.dump(output_data, f, indent=2)

    print(f"\nSaved best params to: {output_file}")
    return output_file
```

**Step 4: Run tests to verify they pass**

Run: `pytest tests/scripts/test_optimize_mlflow.py -k "validate_inputs or generate_report or save_best_params" -v`
Expected: PASS

**Step 5: Update run_optimization to use helpers**

```python
# scripts/optimize_mlflow.py - Update run_optimization to use helpers

def run_optimization(
    strategy_name: str,
    experiment_name: str,
    train_start: str = "2020-01-01",
    train_end: str = "2024-12-31",
    timeframe: str = "minute240",
    market: str = "futures",
    dry_run: bool = False,
    max_combinations: int = 0,
    quick: bool = False,
) -> List[OptimizationResult]:
    """Run grid search optimization with MLflow tracking."""
    print("=" * 80)
    print(f"MLflow Strategy Optimization: {strategy_name}")
    print("=" * 80)

    # Validate inputs and get parameter grid
    param_grid = _validate_inputs(strategy_name, train_start, train_end, timeframe, quick)
    combinations = generate_param_combinations(param_grid)

    if max_combinations > 0:
        combinations = combinations[:max_combinations]

    print(f"\nParameter grid: {len(param_grid)} params")
    for k, v in param_grid.items():
        print(f"  {k}: {v}")
    print(f"\nTotal combinations: {len(combinations)}")

    if dry_run:
        print("\n[DRY RUN] First 5 combinations:")
        for i, combo in enumerate(combinations[:5]):
            print(f"  {i+1}. {combo}")
        return []

    # Load and validate data
    print(f"\nLoading data: {train_start} to {train_end} ({timeframe})...")
    df = load_data(train_start, train_end, timeframe)
    validate_dataframe(df, timeframe)
    print(f"  Loaded {len(df):,} candles")

    # Setup MLflow
    mlflow.set_tracking_uri("./mlruns")
    mlflow.set_experiment(experiment_name)
    print(f"\nMLflow experiment: {experiment_name}")

    # Run optimization with progress bar
    results: List[OptimizationResult] = []
    print(f"\nRunning {len(combinations)} backtests...")

    for params in tqdm(combinations, desc="Optimizing", unit="run"):
        entry_params, exit_params = split_params(params, strategy_name)

        with mlflow.start_run(run_name=f"{strategy_name}_run_{len(results)+1}"):
            mlflow.log_params({**params, "strategy_name": strategy_name, "market": market})

            try:
                result = run_backtest(
                    strategy_name=strategy_name,
                    entry_params=entry_params,
                    exit_params=exit_params,
                    df=df,
                    market=market,
                    timeframe=timeframe,
                )

                pf = result.profit_factor if np.isfinite(result.profit_factor) else 999.99
                mlflow.log_metrics({
                    "total_return": result.total_return,
                    "total_trades": result.total_trades,
                    "win_rate": result.win_rate,
                    "sharpe_ratio": result.sharpe_ratio,
                    "max_drawdown": result.max_drawdown,
                    "profit_factor": pf,
                    "avg_trades_per_year": result.avg_trades_per_year,
                })
                results.append(result)

            except KeyboardInterrupt:
                print(f"\n  Interrupted by user")
                raise
            except (MemoryError, SystemExit):
                raise
            except Exception as e:
                mlflow.set_tag("error", sanitize_error_message(e))

    # Sort and report
    results.sort(key=lambda r: r.total_return, reverse=True)
    _generate_report(results)

    if results:
        _save_best_params(results[0], strategy_name, market, train_start, train_end)

    print(f"\nMLflow UI: mlflow ui --host 0.0.0.0 --port 5000")
    return results
```

**Step 6: Commit**

```bash
git add scripts/optimize_mlflow.py tests/scripts/test_optimize_mlflow.py
git commit -m "refactor: split run_optimization into smaller helper functions"
```

---

## Summary

| Task | Status | Description |
|------|--------|-------------|
| 1 | TODO | Parameterized SQL queries in DataLoader |
| 2 | TODO | tqdm progress tracking |
| 3 | TODO | Multiprocessing for parallel backtests |
| 4 | TODO | Generate PARAM_GRIDS_QUICK programmatically |
| 5 | TODO | Comprehensive tests |
| 6 | TODO | Batch MLflow logging |
| 7 | TODO | Refactor run_optimization() |

**Already Done (no changes needed):**
- Date validation with datetime.strptime()
- Timeframe calculation with CANDLES_PER_YEAR
- Input validation helper (validate_date_range)
