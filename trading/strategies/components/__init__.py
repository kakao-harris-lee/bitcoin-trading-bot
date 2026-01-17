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
"""

from .interfaces import IEntryStrategy, IExitStrategy
from .models import MarketData, Position, Signal

# Factory and composite task
from .strategy_factory import StrategyFactory, StrategySpec, create_factory
from .composite_task import CompositeStrategyTask, create_composite_task

# State persistence
from .state_manager import StateManager

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
]
