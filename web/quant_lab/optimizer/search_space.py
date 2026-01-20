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
