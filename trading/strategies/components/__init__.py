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

# MLP Direction strategy components (Parente & Rizzuti 2025)
from .mlp_direction_entry import MLPDirectionEntryParams, MLPDirectionEntryStrategy
from .mlp_direction_exit import MLPDirectionExitParams, MLPDirectionExitStrategy
from .regime_long_v2_entry import RegimeLongV2EntryParams, RegimeLongV2EntryStrategy
from .regime_long_v2_exit import RegimeLongV2ExitParams, RegimeLongV2ExitStrategy
from .hybrid_long_entry import HybridLongEntryParams, HybridLongEntryStrategy
from .hybrid_long_exit import HybridLongExitParams, HybridLongExitStrategy
from .symbol_selector import SymbolSelectorConfig, SymbolScore, DynamicSymbolSelector

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
    # MLP Direction implementations (Parente & Rizzuti 2025)
    "MLPDirectionEntryStrategy",
    "MLPDirectionEntryParams",
    "MLPDirectionExitStrategy",
    "MLPDirectionExitParams",
    # Regime long v2
    "RegimeLongV2EntryStrategy",
    "RegimeLongV2EntryParams",
    "RegimeLongV2ExitStrategy",
    "RegimeLongV2ExitParams",
    # Hybrid long v2
    "HybridLongEntryStrategy",
    "HybridLongEntryParams",
    "HybridLongExitStrategy",
    "HybridLongExitParams",
    # Symbol selector
    "SymbolSelectorConfig",
    "SymbolScore",
    "DynamicSymbolSelector",
]
