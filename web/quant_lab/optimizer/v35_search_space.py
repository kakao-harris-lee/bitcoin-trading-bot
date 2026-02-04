"""V35-specific search space for parameter tuning.

Defines parameter groups and bounds for all V35 strategy variants.
Used by Optuna to sample hyperparameter configurations.
"""
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
        "max_consecutive_losses": (2.0, 5.0),
        "loss_pause_candles": (12.0, 72.0),
        "stop_loss_cooldown": (1.0, 12.0),
    },
    "sizing": {
        "position_pct": (0.10, 0.50),
        "position_size_high": (0.15, 0.55),
        "position_size_mid": (0.08, 0.35),
        "position_size_low": (0.03, 0.20),
        "position_conf_low": (0.40, 0.60),
        "position_conf_high": (0.60, 0.85),
    },
    "trailing": {
        "trailing_activation": (1.5, 25.0),
        "trailing_distance": (0.5, 15.0),
    },
    "take_profit": {
        "tp_bull_strong_1": (5.0, 35.0),
        "tp_bull_strong_2": (15.0, 80.0),
        "tp_bull_strong_3": (30.0, 150.0),
        "tp_bull_moderate_1": (4.0, 30.0),
        "tp_bull_moderate_2": (12.0, 70.0),
        "tp_bull_moderate_3": (25.0, 130.0),
        "tp_sideways_1": (2.0, 15.0),
        "tp_sideways_2": (5.0, 35.0),
        "tp_sideways_3": (10.0, 70.0),
        "exit_fraction_1": (0.05, 0.25),
        "exit_fraction_2": (0.05, 0.30),
        "exit_fraction_3": (0.50, 0.90),
    },
    "core_overlay": {
        "core_hold_pct": (0.40, 0.80),
        "core_drawdown_exit_pct": (15.0, 25.0),
        "core_drawdown_reentry_pct": (5.0, 15.0),
    },
    "regime_thresholds": {
        "mfi_bull_strong": (45.0, 60.0),
        "mfi_bull_moderate": (42.0, 55.0),
        "mfi_sideways_up": (40.0, 50.0),
        "mfi_bear_moderate": (30.0, 42.0),
        "mfi_bear_strong": (20.0, 35.0),
        "adx_strong_trend": (15.0, 30.0),
        "adx_moderate_trend": (8.0, 20.0),
    },
    "leverage": {
        "leverage_bull_strong": (2.0, 3.0),
        "leverage_bull_moderate": (1.5, 3.0),
        "leverage_sideways": (1.0, 2.0),
        "leverage_bear": (0.5, 1.5),
        "prob_leverage_max": (2.0, 3.0),
        "prob_leverage_high": (1.5, 3.0),
        "prob_leverage_mid": (1.0, 2.5),
        "prob_leverage_low": (0.5, 1.5),
        "prob_leverage_min": (0.25, 1.0),
    },
}

# Which parameter groups apply to each strategy
# Note: V35 strategies run on SPOT (no leverage) per CLAUDE.md
# Leverage parameters are only applicable to futures strategies
V35_STRATEGY_PARAMS: Dict[str, List[str]] = {
    "tuned_v35_long_v2_core_overlay_v2": [
        "risk", "sizing", "trailing", "take_profit", "core_overlay"
    ],
}


def get_strategy_param_groups(strategy_name: str) -> List[str]:
    """Get applicable parameter groups for a strategy.

    Args:
        strategy_name: Name of V35 strategy variant.

    Returns:
        List of parameter group names (e.g., ["risk", "sizing", "trailing"]).
    """
    return V35_STRATEGY_PARAMS.get(strategy_name, ["risk", "trailing"])


def get_all_strategies() -> List[str]:
    """Get all available V35 strategy names."""
    return list(V35_STRATEGY_PARAMS.keys())


def get_param_bounds(group_name: str) -> Dict[str, Tuple[float, float]]:
    """Get parameter bounds for a specific group.

    Args:
        group_name: Name of parameter group.

    Returns:
        Dict mapping param name to (min, max) tuple.
    """
    return V35_PARAM_GROUPS.get(group_name, {})


def sample_v35_config(
    trial: optuna.Trial,
    strategy_name: str,
    enabled_groups: List[str] | None = None,
) -> Dict[str, Any]:
    """Sample configuration from Optuna trial for V35 strategy.

    Args:
        trial: Optuna trial object.
        strategy_name: Name of V35 strategy to optimize.
        enabled_groups: Optional list of parameter groups to include.
            If None, uses default groups for the strategy.

    Returns:
        Dict of sampled parameter values.
    """
    if enabled_groups is None:
        enabled_groups = get_strategy_param_groups(strategy_name)

    config: Dict[str, Any] = {}

    for group_name in enabled_groups:
        if group_name not in V35_PARAM_GROUPS:
            continue

        for param_name, (low, high) in V35_PARAM_GROUPS[group_name].items():
            # Use int for parameters that should be integers
            if param_name in (
                "max_consecutive_losses",
                "loss_pause_candles",
                "stop_loss_cooldown",
            ):
                config[param_name] = trial.suggest_int(param_name, int(low), int(high))
            else:
                config[param_name] = trial.suggest_float(param_name, low, high)

    return config


def build_full_search_space(strategy_name: str) -> Dict[str, Dict[str, Any]]:
    """Build complete search space definition for a strategy.

    Useful for documentation and UI display.

    Args:
        strategy_name: Name of V35 strategy.

    Returns:
        Dict mapping group name to param definitions.
    """
    groups = get_strategy_param_groups(strategy_name)
    space = {}

    for group_name in groups:
        if group_name in V35_PARAM_GROUPS:
            space[group_name] = {
                param: {"low": low, "high": high}
                for param, (low, high) in V35_PARAM_GROUPS[group_name].items()
            }

    return space
