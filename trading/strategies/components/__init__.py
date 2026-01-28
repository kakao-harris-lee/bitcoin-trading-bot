"""Strategy components for modular entry/exit logic.

This module provides the interfaces and data classes for the component-based
strategy architecture. Entry and exit logic are separated into composable
components that implement IEntryStrategy and IExitStrategy protocols.

Usage:
    from trading.strategies.components import (
        IEntryStrategy,
        IExitStrategy,
        Signal,
        MarketData,
        Position,
    )

    # Factory and composite task
    from trading.strategies.components import (
        StrategyFactory,
        CompositeStrategyTask,
        create_composite_task,
    )

    # State persistence (Redis-backed)
    from trading.strategies.components import StateManager

    # Registry (new config format support)
    from trading.strategies.components import (
        entry_strategy,
        exit_strategy,
        get_entry_class,
        get_exit_class,
        build_params_from_config,
        validate_strategy_config,
        ConfigValidationError,
    )

    # V35 Long (spot, bullish)
    from trading.strategies.components import (
        V35EntryStrategy,
        V35EntryParams,
        V35TrailingExitStrategy,  # In-memory state
        V35PersistentExitStrategy,  # Redis-persisted state
        V35ExitParams,
    )

    # Sideways (spot, mean reversion)
    from trading.strategies.components import (
        SidewaysEntryStrategy,
        SidewaysEntryParams,
        SidewaysExitStrategy,
        SidewaysExitParams,
    )

    # Short (futures, bearish)
    from trading.strategies.components import (
        ShortEntryStrategy,
        ShortEntryParams,
        ShortExitStrategy,
        ShortExitParams,
    )

    # Experimental
    from trading.strategies.components import (
        ExperimentalExitStrategy,
        ExperimentalExitParams,
    )

    # Combo1-C (VBS + LSTM + RF)
    from trading.strategies.components import (
        Combo1CEntryStrategy,
        Combo1CEntryParams,
        Combo1CExitStrategy,
        Combo1CExitParams,
    )
"""

from .interfaces import IEntryStrategy, IExitStrategy
from .models import MarketData, Position, Signal

# Factory and composite task
from .strategy_factory import StrategyFactory, StrategySpec, create_factory
from .composite_task import CompositeStrategyTask, create_composite_task

# State persistence
from .state_manager import StateManager

# Registry (decorator-based auto-registration)
from .registry import (
    entry_strategy,
    exit_strategy,
    get_entry_class,
    get_exit_class,
    get_entry_params_class,
    get_exit_params_class,
    get_registered_entry_names,
    get_registered_exit_names,
    build_params_from_config,
    is_entry_registered,
    is_exit_registered,
)

# Config validation
from .config_schema import (
    validate_strategy_config,
    has_new_config_format,
    ConfigValidationError,
)

# V35 Long strategy components
from .v35_entry import V35EntryParams, V35EntryStrategy
from .v35_trailing_exit import V35ExitParams, V35TrailingExitStrategy
from .v35_persistent_exit import V35PersistentExitStrategy

# Sideways strategy components
from .sideways_entry import SidewaysEntryParams, SidewaysEntryStrategy
from .sideways_exit import SidewaysExitParams, SidewaysExitStrategy

# Short strategy components
from .short_entry import ShortEntryParams, ShortEntryStrategy
from .short_exit import ShortExitParams, ShortExitStrategy

# Experimental strategy components
from .experimental_exit import ExperimentalExitParams, ExperimentalExitStrategy

# Combined strategy components
from .combined_entry import CombinedEntryParams, CombinedEntryStrategy
from .combined_exit import CombinedExitParams, CombinedExitStrategy

# Combo1-C strategy components (VBS + LSTM + RF)
from .combo1c_entry import Combo1CEntryParams, Combo1CEntryStrategy
from .combo1c_exit import Combo1CExitParams, Combo1CExitStrategy

__all__ = [
    # Interfaces
    "IEntryStrategy",
    "IExitStrategy",
    # Data models
    "Signal",
    "MarketData",
    "Position",
    # Factory and composite task
    "StrategyFactory",
    "StrategySpec",
    "create_factory",
    "CompositeStrategyTask",
    "create_composite_task",
    # State persistence
    "StateManager",
    # Registry
    "entry_strategy",
    "exit_strategy",
    "get_entry_class",
    "get_exit_class",
    "get_entry_params_class",
    "get_exit_params_class",
    "get_registered_entry_names",
    "get_registered_exit_names",
    "build_params_from_config",
    "is_entry_registered",
    "is_exit_registered",
    # Config validation
    "validate_strategy_config",
    "has_new_config_format",
    "ConfigValidationError",
    # V35 Long implementations
    "V35EntryStrategy",
    "V35EntryParams",
    "V35TrailingExitStrategy",
    "V35PersistentExitStrategy",
    "V35ExitParams",
    # Sideways implementations
    "SidewaysEntryStrategy",
    "SidewaysEntryParams",
    "SidewaysExitStrategy",
    "SidewaysExitParams",
    # Short implementations
    "ShortEntryStrategy",
    "ShortEntryParams",
    "ShortExitStrategy",
    "ShortExitParams",
    # Experimental implementations
    "ExperimentalExitStrategy",
    "ExperimentalExitParams",
    # Combined implementations
    "CombinedEntryStrategy",
    "CombinedEntryParams",
    "CombinedExitStrategy",
    "CombinedExitParams",
    # Combo1-C implementations (VBS + LSTM + RF)
    "Combo1CEntryStrategy",
    "Combo1CEntryParams",
    "Combo1CExitStrategy",
    "Combo1CExitParams",
]
