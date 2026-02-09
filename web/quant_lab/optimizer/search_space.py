"""Search space definition for regime-based and MLP optimization."""
from dataclasses import dataclass, field
from typing import Dict, List, Any
import optuna

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
    "SidewaysEntry",
    "ShortEntry",
    "None",  # Skip trading in this regime
]

# Available exit strategy components
EXIT_COMPONENTS = [
    "SidewaysExit",
    "ShortExit",
]

# Parameter bounds for each component
COMPONENT_PARAMS = {
    "SidewaysEntry": {
        "range_threshold": {"type": "float", "low": 0.5, "high": 3.0},
    },
    "ShortEntry": {
        "rsi_overbought": {"type": "float", "low": 65.0, "high": 85.0},
    },
    "SidewaysExit": {
        "profit_target_pct": {"type": "float", "low": 0.5, "high": 3.0},
    },
    "ShortExit": {
        "stop_loss_pct": {"type": "float", "low": 0.5, "high": 5.0},
        "take_profit_pct": {"type": "float", "low": 0.5, "high": 8.0},
        "rsi_oversold": {"type": "float", "low": 20.0, "high": 40.0},
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


# =============================================================================
# MLP Direction Strategy Search Space
# =============================================================================

MLP_ENTRY_PARAMS = {
    "buy_confidence_threshold": {"type": "float", "low": 0.0, "high": 0.8},
    "skip_bear_regime": {"type": "categorical", "choices": [True, False]},
    "adx_min": {"type": "float", "low": 0.0, "high": 30.0},
    "use_ema200_filter": {"type": "categorical", "choices": [True, False]},
}

MLP_EXIT_PARAMS = {
    "stop_loss_pct": {"type": "float", "low": 3.0, "high": 25.0},
    "fwin_exit_enabled": {"type": "categorical", "choices": [True, False]},
    "fwin_periods": {"type": "int", "low": 1, "high": 10},
    "use_mlp_sell_exit": {"type": "categorical", "choices": [True, False]},
    "sell_confidence_threshold": {"type": "float", "low": 0.0, "high": 0.8},
    "trailing_enabled": {"type": "categorical", "choices": [True, False]},
    "trailing_activation": {"type": "float", "low": 3.0, "high": 30.0},
    "trailing_distance": {"type": "float", "low": 1.0, "high": 15.0},
    "take_profit_enabled": {"type": "categorical", "choices": [True, False]},
    "take_profit_pct": {"type": "float", "low": 5.0, "high": 50.0},
}

MLP_ENSEMBLE_PARAMS = {
    "weight_bwin3": {"type": "float", "low": 0.0, "high": 1.0},
    "weight_bwin4": {"type": "float", "low": 0.0, "high": 1.0},
    "weight_bwin5": {"type": "float", "low": 0.0, "high": 1.0},
    "weight_bwin7": {"type": "float", "low": 0.0, "high": 1.0},
}

MLP_ADAPTER_PARAMS = {
    "cash_in_bear": {"type": "categorical", "choices": [True, False]},
    "cash_below_ema200": {"type": "categorical", "choices": [True, False]},
    "stop_loss_cooldown": {"type": "int", "low": 0, "high": 24},
    "drawdown_bear_threshold": {"type": "float", "low": 0.05, "high": 1.0},
}


def sample_mlp_trial_config(trial: optuna.Trial) -> Dict[str, Any]:
    """Sample a complete MLP Direction configuration from Optuna trial.

    Args:
        trial: Optuna trial object

    Returns:
        Dict with entry, exit, ensemble, and adapter params.
    """
    config: Dict[str, Any] = {"entry": {}, "exit": {}, "ensemble": {}, "adapter": {}}

    # Entry params
    for name, spec in MLP_ENTRY_PARAMS.items():
        if spec["type"] == "float":
            config["entry"][name] = trial.suggest_float(f"entry_{name}", spec["low"], spec["high"])
        elif spec["type"] == "categorical":
            config["entry"][name] = trial.suggest_categorical(f"entry_{name}", spec["choices"])
        elif spec["type"] == "int":
            config["entry"][name] = trial.suggest_int(f"entry_{name}", spec["low"], spec["high"])

    # Exit params
    for name, spec in MLP_EXIT_PARAMS.items():
        if spec["type"] == "float":
            config["exit"][name] = trial.suggest_float(f"exit_{name}", spec["low"], spec["high"])
        elif spec["type"] == "categorical":
            config["exit"][name] = trial.suggest_categorical(f"exit_{name}", spec["choices"])
        elif spec["type"] == "int":
            config["exit"][name] = trial.suggest_int(f"exit_{name}", spec["low"], spec["high"])

    # Ensemble weights
    for name, spec in MLP_ENSEMBLE_PARAMS.items():
        config["ensemble"][name] = trial.suggest_float(f"ensemble_{name}", spec["low"], spec["high"])

    # Adapter params
    for name, spec in MLP_ADAPTER_PARAMS.items():
        if spec["type"] == "float":
            config["adapter"][name] = trial.suggest_float(f"adapter_{name}", spec["low"], spec["high"])
        elif spec["type"] == "categorical":
            config["adapter"][name] = trial.suggest_categorical(f"adapter_{name}", spec["choices"])
        elif spec["type"] == "int":
            config["adapter"][name] = trial.suggest_int(f"adapter_{name}", spec["low"], spec["high"])

    return config
