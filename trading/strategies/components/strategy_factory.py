"""Strategy Factory - assembles Entry/Exit components from configuration.

Implements the Factory Pattern for dynamic strategy assembly based on
allocation.json configuration.

Registry-default format:
    "llm_direction_btc": {
        "position_size": 0.2,
        "market": "spot"
    }

Explicit component format:
    "llm_direction_btc": {
        "market": "spot",
        "entry": {
            "class": "LLMDecisionEntryStrategy",
            "params": {
                "model": "llama3.1:8b",
                "position_size": 0.9
            }
        },
        "exit": {
            "class": "LLMDirectionExitStrategy",
            "params": {
                "stop_loss_pct": 10.0
            }
        }
    }

Usage:
    factory = StrategyFactory(redis_client)

    # Create individual components
    entry = factory.create_entry("llm_direction_btc", params)
    exit_strat = factory.create_exit("llm_direction_btc", params)

    # Create full strategy task
    task = await factory.create_strategy_task(
        name="llm_direction_btc",
        symbols=["BTC", "ETH"],
        config={"position_size": 0.2},
    )
"""

from __future__ import annotations

# pylint: disable=logging-fstring-interpolation

import logging
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from .interfaces import IEntryStrategy, IExitStrategy

# Entry strategies (imports trigger registration via decorators)
from .llm_direction_entry import LLMDecisionEntryStrategy, LLMDecisionEntryParams
from .regime_long_v2_entry import RegimeLongV2EntryStrategy, RegimeLongV2EntryParams

# Exit strategies (imports trigger registration via decorators)
from .llm_hybrid_exit import LLMHybridExitStrategy, LLMHybridExitParams
from .regime_long_v2_exit import RegimeLongV2ExitStrategy, RegimeLongV2ExitParams

# Registry and config validation
from .registry import (
    get_entry_class,
    get_exit_class,
    get_entry_params_class,
    get_exit_params_class,
    build_params_from_config,
    is_entry_registered,
    is_exit_registered,
)
from .config_schema import (
    has_new_config_format,
)

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


@dataclass
class StrategySpec:
    """Specification for a strategy's entry and exit components."""

    name: str
    entry_class: type
    entry_params_class: type
    exit_class: type
    exit_params_class: type
    persistent_exit_class: type | None = None
    market: str = "spot"
    timeframe: str = "day"


# Registry of available base strategy specs.
STRATEGY_REGISTRY: dict[str, StrategySpec] = {
    "llm_direction": StrategySpec(
        name="llm_direction",
        entry_class=LLMDecisionEntryStrategy,
        entry_params_class=LLMDecisionEntryParams,
        exit_class=LLMHybridExitStrategy,
        exit_params_class=LLMHybridExitParams,
        persistent_exit_class=None,
        market="spot",
        timeframe="hour4",
    ),
    "regime_long_v2": StrategySpec(
        name="regime_long_v2",
        entry_class=RegimeLongV2EntryStrategy,
        entry_params_class=RegimeLongV2EntryParams,
        exit_class=RegimeLongV2ExitStrategy,
        exit_params_class=RegimeLongV2ExitParams,
        persistent_exit_class=None,
        market="spot",
        timeframe="hour4",
    ),
}


class StrategyFactory:
    """Factory for creating strategy components from configuration.

    Creates and assembles Entry/Exit strategy components based on
    strategy names and configuration parameters.

    Supports two config styles:
    1. Registry-default: Strategy name maps to predefined components
    2. Explicit component blocks: config declares entry/exit classes directly
    """

    def __init__(self, redis: Redis | None = None):
        """Initialize factory.

        Args:
            redis: Optional Redis client for persistent strategies.
        """
        self._redis = redis
        self._registry = STRATEGY_REGISTRY.copy()

    def register_strategy(self, spec: StrategySpec) -> None:
        """Register a new strategy specification.

        Args:
            spec: Strategy specification to register.
        """
        self._registry[spec.name] = spec
        logger.info(f"Registered strategy: {spec.name}")

    def get_available_strategies(self) -> list[str]:
        """Get list of available strategy names."""
        return list(self._registry.keys())

    def create_entry(
        self,
        strategy_name: str,
        config: dict[str, Any] | None = None,
        param_overrides: dict[str, Any] | None = None,
    ) -> IEntryStrategy:
        """Create an entry strategy component.

        Supports both registry-default and explicit component config:
        - Registry-default: Uses predefined class from STRATEGY_REGISTRY
        - Explicit component config: Uses "entry.class" from config

        Args:
            strategy_name: Name of the strategy (e.g., "llm_direction_btc").
            config: Configuration parameters.
            param_overrides: Parameter overrides for MLflow optimization.
                These override values from config and dataclass defaults.

        Returns:
            Entry strategy instance.

        Raises:
            ValueError: If strategy name is not registered.
        """
        config = config or {}
        param_overrides = param_overrides or {}

        # Merge param_overrides into config for processing
        if param_overrides:
            config = self._apply_param_overrides(config, param_overrides)

        # Explicit component config overrides registry defaults.
        if has_new_config_format(config) and "entry" in config:
            return self._create_entry_from_config(strategy_name, config)

        return self._create_entry_from_spec(strategy_name, config)

    def create_exit(
        self,
        strategy_name: str,
        config: dict[str, Any] | None = None,
        persistent: bool = False,
        param_overrides: dict[str, Any] | None = None,
    ) -> IExitStrategy:
        """Create an exit strategy component.

        Supports both registry-default and explicit component config:
        - Registry-default: Uses predefined class from STRATEGY_REGISTRY
        - Explicit component config: Uses "exit.class" from config

        Args:
            strategy_name: Name of the strategy (e.g., "llm_direction_btc").
            config: Configuration parameters.
            persistent: Use Redis-backed persistence if available.
            param_overrides: Parameter overrides for MLflow optimization.
                These override values from config and dataclass defaults.

        Returns:
            Exit strategy instance.

        Raises:
            ValueError: If strategy name is not registered.
        """
        config = config or {}
        param_overrides = param_overrides or {}

        # Merge param_overrides into config for processing
        if param_overrides:
            config = self._apply_param_overrides(config, param_overrides)

        # Explicit component config overrides registry defaults.
        if has_new_config_format(config) and "exit" in config:
            return self._create_exit_from_config(strategy_name, config, persistent)

        return self._create_exit_from_spec(strategy_name, config, persistent)

    def create_components(
        self,
        strategy_name: str,
        config: dict[str, Any] | None = None,
        persistent: bool = False,
        entry_overrides: dict[str, Any] | None = None,
        exit_overrides: dict[str, Any] | None = None,
    ) -> tuple[IEntryStrategy, IExitStrategy]:
        """Create both entry and exit components for a strategy.

        Args:
            strategy_name: Name of the strategy.
            config: Configuration parameters.
            persistent: Use Redis-backed persistence if available.
            entry_overrides: Parameter overrides for entry strategy.
            exit_overrides: Parameter overrides for exit strategy.

        Returns:
            Tuple of (entry_strategy, exit_strategy).

        Example:
            entry, exit_strat = factory.create_components("llm_direction_btc")
        """
        entry = self.create_entry(
            strategy_name, config, param_overrides=entry_overrides
        )
        exit_strat = self.create_exit(
            strategy_name, config, persistent, param_overrides=exit_overrides
        )
        return entry, exit_strat

    def get_market(
        self, strategy_name: str, config: dict[str, Any] | None = None
    ) -> str:
        """Get the market type for a strategy.

        Args:
            strategy_name: Name of the strategy.
            config: Optional config that may override the default market.

        Returns:
            Market type ("spot").
        """
        config = config or {}

        # Config market overrides spec default
        if "market" in config:
            return config["market"]

        if strategy_name in self._registry:
            return self._registry[strategy_name].market

        # Default to spot
        return "spot"

    # --- Explicit component config methods ---

    def _create_entry_from_config(
        self,
        strategy_name: str,
        config: dict[str, Any],
    ) -> IEntryStrategy:
        """Create entry strategy using explicit component config.

        Args:
            strategy_name: Strategy name for logging.
            config: Config with entry.class and entry.params.

        Returns:
            Entry strategy instance.

        Raises:
            ValueError: If class not found in registry.
        """
        _ = strategy_name
        entry_config = config["entry"]
        class_name = entry_config["class"]

        # Validate and get class from registry
        if not is_entry_registered(class_name):
            from .registry import get_registered_entry_names

            available = get_registered_entry_names()
            raise ValueError(
                f"Unknown entry class: {class_name}. " f"Available: {available}"
            )

        entry_class = get_entry_class(class_name)
        params_class = get_entry_params_class(class_name)

        # Build params from config
        entry_params = entry_config.get("params", {})
        # Merge top-level config (market, position_size) with entry params
        merged_params = self._merge_params(config, entry_params)

        if params_class:
            params = build_params_from_config(params_class, merged_params)
        else:
            params = None

        entry = entry_class(params=params)
        logger.debug(f"Created entry strategy: {class_name} (explicit component config)")
        return entry

    def _create_exit_from_config(
        self,
        strategy_name: str,
        config: dict[str, Any],
        persistent: bool,
    ) -> IExitStrategy:
        """Create exit strategy using explicit component config.

        Args:
            strategy_name: Strategy name for logging.
            config: Config with exit.class and exit.params.
            persistent: Use persistent class if available.

        Returns:
            Exit strategy instance.

        Raises:
            ValueError: If class not found in registry.
        """
        exit_config = config["exit"]
        class_name = exit_config["class"]

        # Check for persistent class override
        persistent_class_name = exit_config.get("persistent_class")
        if persistent and persistent_class_name and self._redis:
            class_name = persistent_class_name

        # Validate and get class from registry
        if not is_exit_registered(class_name):
            from .registry import get_registered_exit_names

            available = get_registered_exit_names()
            raise ValueError(
                f"Unknown exit class: {class_name}. " f"Available: {available}"
            )

        exit_class = get_exit_class(class_name)
        params_class = get_exit_params_class(class_name)

        # Build params from config
        exit_params = exit_config.get("params", {})
        # Merge top-level config (market) with exit params
        merged_params = self._merge_params(config, exit_params)

        if params_class:
            params = build_params_from_config(params_class, merged_params)
        else:
            params = None

        # Check if this is a persistent strategy (needs redis)
        if persistent and persistent_class_name and self._redis:
            exit_strat = exit_class(
                redis=self._redis,
                params=params,
                strategy_name=f"{strategy_name}_exit",
            )
            logger.debug(f"Created persistent exit strategy: {class_name} (explicit component config)")
        else:
            exit_strat = exit_class(params=params)
            logger.debug(f"Created exit strategy: {class_name} (explicit component config)")

        return exit_strat

    def _merge_params(
        self,
        config: dict[str, Any],
        component_params: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge top-level config with component-specific params.

        Component params take precedence over top-level config.

        Args:
            config: Top-level strategy config.
            component_params: Component-specific params.

        Returns:
            Merged params dict.
        """
        merged = {}

        # Add relevant top-level fields
        if "market" in config:
            merged["market"] = config["market"]
        if "position_size" in config:
            merged["position_size"] = config["position_size"]

        # Component params override top-level
        merged.update(component_params)

        return merged

    def _apply_param_overrides(
        self,
        config: dict[str, Any],
        param_overrides: dict[str, Any],
    ) -> dict[str, Any]:
        """Apply parameter overrides to config for MLflow optimization.

        Creates a new config dict with param_overrides merged in.
        Overrides are applied at the top level for registry-default configs,
        or into entry/exit.params for explicit component configs.

        Optimized to minimize dict copies for MLflow hyperparameter sweeps.

        Args:
            config: Original configuration.
            param_overrides: Parameter values to override.

        Returns:
            New config dict with overrides applied.
        """
        # Early return if no overrides - avoid unnecessary copies
        if not param_overrides:
            return config

        if has_new_config_format(config):
            # Explicit component config: merge into entry.params or exit.params
            # Use single dict comprehension to reduce copies
            result = {k: v for k, v in config.items() if k not in ("entry", "exit")}

            if "entry" in config and isinstance(config["entry"], dict):
                entry = config["entry"]
                result["entry"] = {
                    **entry,
                    "params": {**entry.get("params", {}), **param_overrides},
                }

            if "exit" in config and isinstance(config["exit"], dict):
                exit_cfg = config["exit"]
                result["exit"] = {
                    **exit_cfg,
                    "params": {**exit_cfg.get("params", {}), **param_overrides},
                }

            return result
        else:
            # Registry-default config: single merged dict
            return {**config, **param_overrides}

    # --- Registry-default methods ---

    def _create_entry_from_spec(
        self,
        strategy_name: str,
        config: dict[str, Any],
    ) -> IEntryStrategy:
        """Create entry strategy using the registered base spec.

        Args:
            strategy_name: Strategy name from STRATEGY_REGISTRY.
            config: Configuration parameters.

        Returns:
            Entry strategy instance.

        Raises:
            ValueError: If strategy name not in registry.
        """
        if strategy_name not in self._registry:
            raise ValueError(
                f"Unknown strategy: {strategy_name}. "
                f"Available: {self.get_available_strategies()}"
            )

        spec = self._registry[strategy_name]

        # Build params using registry-based builder
        params = self._build_entry_params(spec, config)

        # Create entry strategy
        entry = spec.entry_class(params=params)
        logger.debug(f"Created entry strategy: {strategy_name} (registry default)")
        return entry

    def _create_exit_from_spec(
        self,
        strategy_name: str,
        config: dict[str, Any],
        persistent: bool,
    ) -> IExitStrategy:
        """Create exit strategy using the registered base spec.

        Args:
            strategy_name: Strategy name from STRATEGY_REGISTRY.
            config: Configuration parameters.
            persistent: Use Redis-backed persistence if available.

        Returns:
            Exit strategy instance.

        Raises:
            ValueError: If strategy name not in registry.
        """
        if strategy_name not in self._registry:
            raise ValueError(
                f"Unknown strategy: {strategy_name}. "
                f"Available: {self.get_available_strategies()}"
            )

        spec = self._registry[strategy_name]

        # Build params using registry-based builder
        params = self._build_exit_params(spec, config)

        # Use persistent version if requested and available
        if persistent and spec.persistent_exit_class and self._redis:
            exit_strat = spec.persistent_exit_class(
                redis=self._redis,
                params=params,
                strategy_name=f"{strategy_name}_exit",
            )
            logger.debug(
                f"Created persistent exit strategy: {strategy_name} (registry default)"
            )
        else:
            exit_strat = spec.exit_class(params=params)
            logger.debug(f"Created exit strategy: {strategy_name} (registry default)")

        return exit_strat

    def _get_market(
        self,
        spec: StrategySpec,
        config: dict[str, Any],
    ) -> str:
        """Get market type from config or spec default.

        Args:
            spec: Strategy specification.
            config: Configuration parameters.

        Returns:
            Market type ("spot").
        """
        # Config market overrides spec default
        return config.get("market", spec.market)

    def _build_entry_params(
        self,
        spec: StrategySpec,
        config: dict[str, Any],
    ) -> Any:
        """Build entry params from registry-default config.

        Uses registry-based param building for full flexibility.
        All params defined in the dataclass can be overridden via config.
        """
        # Get market from config (allows override of spec default)
        market = self._get_market(spec, config)

        # Use registry builder which handles all dataclass fields
        merged_config = {"market": market, **config}
        return build_params_from_config(spec.entry_params_class, merged_config)

    def _build_exit_params(
        self,
        spec: StrategySpec,
        config: dict[str, Any],
    ) -> Any:
        """Build exit params from registry-default config.

        Uses registry-based param building for full flexibility.
        All params defined in the dataclass can be overridden via config.
        """
        # Get market from config (allows override of spec default)
        market = self._get_market(spec, config)

        # Use registry builder which handles all dataclass fields
        merged_config = {"market": market, **config}
        return build_params_from_config(spec.exit_params_class, merged_config)


def create_factory(redis: Redis | None = None) -> StrategyFactory:
    """Create a StrategyFactory instance.

    Convenience function for creating a factory.

    Args:
        redis: Optional Redis client for persistent strategies.

    Returns:
        StrategyFactory instance.
    """
    return StrategyFactory(redis=redis)
