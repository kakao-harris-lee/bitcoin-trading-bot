# V35 Unified Tuning Framework Design

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create a unified parameter tuning framework for all V35 strategy variants with proper $10k USD capital and spot trading fees.

**Architecture:** Extend Quant Lab with V35-specific search space, growth-focused objective function, and ComponentStrategyAdapter integration.

**Tech Stack:** Optuna, RQ Worker, Flask, ComponentStrategyAdapter

---

## Context

- **Capital:** $10,000 USD
- **Market:** Spot trading (0.1% fee)
- **Optimization Goal:** Growth-focused (maximize return, MDD ≤ 25%)
- **Variants:** 6 V35 strategies (v35_long, v35_long_v2, tuned_v35_long_v2_growth, tuned_v35_long_v2_hold, tuned_v35_long_v2_core_overlay, tuned_v35_long_v2_core_overlay_v2)

## Current Problems

1. **Wrong Capital**: Quant Lab uses 10,000,000 KRW instead of $10,000 USD
2. **Wrong Fee Rate**: Uses 0.05% (futures) instead of 0.1% (spot)
3. **Limited Search Space**: Only 4-5 basic parameters per component
4. **Missing V35 v2 Parameters**: No drawdown protection, RF confidence, core-hold overlay parameters
5. **Manual Strategy Building**: Doesn't use ComponentStrategyAdapter which has all V35 features

## Solution Design

### 1. Core Infrastructure Fixes

Update `objective.py` to auto-detect market from strategy config:

```python
market = strategy_config.get("market", "futures")
backtester = Backtester(
    initial_capital=10_000,  # $10k USD
    fee_rate=0.001 if market == "spot" else 0.0005,
    market=market,
)
```

### 2. V35-Specific Search Space

Create parameter groups for different aspects:

```python
V35_PARAM_GROUPS = {
    "risk": {
        "stop_loss_pct": (2.0, 10.0),
        "atr_stop_multiplier": (2.0, 5.0),
        "drawdown_warning_pct": (8.0, 15.0),
        "drawdown_exit_pct": (15.0, 25.0),
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
    },
    "core_overlay": {
        "core_hold_pct": (0.40, 0.80),
        "core_drawdown_exit_pct": (15.0, 25.0),
    },
}
```

### 3. Growth-Focused Objective

Single composite score with MDD constraint:

```python
def growth_objective(trial) -> float:
    results = run_backtest(trial)

    total_return = results["total_return"]
    max_drawdown = results["max_drawdown"]
    sharpe = results["sharpe_ratio"]

    # Hard constraint: prune if MDD exceeds 30%
    if max_drawdown > 0.30:
        raise optuna.TrialPruned("MDD exceeded 30%")

    # Soft penalty: reduce score if MDD > 25%
    mdd_penalty = max(0, (max_drawdown - 0.25) * 2.0)

    # Bonus for good Sharpe
    sharpe_bonus = max(0, (sharpe - 1.0) * 0.1)

    score = total_return - mdd_penalty + sharpe_bonus
    return score
```

### 4. ComponentStrategyAdapter Integration

Use existing adapter that already implements all V35 features:

```python
from core.component_adapter import ComponentStrategyAdapter

adapter = ComponentStrategyAdapter(
    factory=factory,
    strategy_name=strategy_name,
    config=config,
)

# Pre-compute RF predictions for speed
if config.get("use_rf_probability", False):
    adapter.precompute_rf_predictions(df)

results = backtester.run(df, adapter)
```

### 5. UI Integration

Add V35 tab to Quant Lab with:
- Strategy selector dropdown
- Parameter group checkboxes
- Capital/fee display
- Optimization mode selector
- Results table with Apply button

## Files to Create

| File | Purpose |
|------|---------|
| `web/quant_lab/optimizer/v35_search_space.py` | V35 parameter groups and bounds |
| `web/quant_lab/optimizer/v35_objective.py` | Growth-focused scoring function |
| `web/templates/quant_lab_v35.html` | V35 tuning UI tab |

## Files to Modify

| File | Changes |
|------|---------|
| `web/quant_lab/routes.py` | Add `/api/v35/optimize` endpoint |
| `web/quant_lab/worker/tasks.py` | Add `run_v35_optimization` task |
| `core/backtester.py` | Fix capital default to $10k USD |

## Validation

1. Run backtest on 2024 data for v35_long_v2 with default params
2. Confirm $10k capital and 0.1% spot fees applied
3. Compare results with existing `backtest_risk_based_sizing.py`
4. Run 10-trial optimization, verify parameter sampling
5. Test Apply button writes to allocation.json correctly
