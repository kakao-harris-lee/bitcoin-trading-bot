"""Search space definition for regime-based optimization."""
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
    "None",  # Skip trading in this regime
]

# Available exit strategy components
EXIT_COMPONENTS = [
    "SidewaysExit",
]

# Parameter bounds for each component
COMPONENT_PARAMS = {
    "SidewaysEntry": {
        "range_threshold": {"type": "float", "low": 0.5, "high": 3.0},
    },
    "SidewaysExit": {
        "profit_target_pct": {"type": "float", "low": 0.5, "high": 3.0},
    },
    "None": {},
}


@dataclass
class RegimeConfig:
    """Configuration for a single regime's search space."""
    entries: List[str] = field(default_factory=ENTRY_COMPONENTS.copy)
    exits: List[str] = field(default_factory=EXIT_COMPONENTS.copy)


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
    """Build search space dictionary for Optuna trial."""
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
    """Sample a complete configuration from Optuna trial."""
    result = {}
    space = build_search_space(config)

    for regime in REGIMES:
        regime_space = space[regime]

        entry = trial.suggest_categorical(
            f"{regime}_entry",
            regime_space["entry_choices"]
        )
        exit_comp = trial.suggest_categorical(
            f"{regime}_exit",
            regime_space["exit_choices"]
        )

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

    result["regime_thresholds"] = {}
    for name, spec in REGIME_THRESHOLD_PARAMS.items():
        result["regime_thresholds"][name] = trial.suggest_float(
            f"regime_{name}", spec["low"], spec["high"]
        )

    return result


REGIME_THRESHOLD_PARAMS = {
    "mfi_bull_strong": {"type": "float", "low": 50.0, "high": 60.0},
    "mfi_bull_moderate": {"type": "float", "low": 50.0, "high": 60.0},
    "mfi_sideways_up": {"type": "float", "low": 45.0, "high": 55.0},
    "mfi_bear_moderate": {"type": "float", "low": 35.0, "high": 48.0},
    "mfi_bear_strong": {"type": "float", "low": 28.0, "high": 42.0},
    "adx_strong_trend": {"type": "float", "low": 18.0, "high": 32.0},
    "adx_moderate_trend": {"type": "float", "low": 12.0, "high": 25.0},
}
