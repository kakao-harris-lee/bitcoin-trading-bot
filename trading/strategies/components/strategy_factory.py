"""Strategy Factory - assembles Entry/Exit components from configuration.

Implements the Factory Pattern for dynamic strategy assembly based on
allocation.json configuration. Maps strategy names to component classes.

Usage:
    factory = StrategyFactory(redis_client)

    # Create individual components
    entry = factory.create_entry("v35_long", params)
    exit_strat = factory.create_exit("v35_long", params, persistent=True)

    # Create full strategy task
    task = await factory.create_strategy_task(
        name="v35_long",
        symbols=["BTC", "ETH"],
        config={"position_size": 0.01},
    )
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, TYPE_CHECKING

from .interfaces import IEntryStrategy, IExitStrategy
from .models import MarketData, Position, Signal

# Entry strategies
from .v35_entry import V35EntryStrategy, V35EntryParams
from .sideways_entry import SidewaysEntryStrategy, SidewaysEntryParams
from .short_entry import ShortEntryStrategy, ShortEntryParams

# Exit strategies
from .v35_trailing_exit import V35TrailingExitStrategy, V35ExitParams
from .v35_persistent_exit import V35PersistentExitStrategy
from .sideways_exit import SidewaysExitStrategy, SidewaysExitParams
from .short_exit import ShortExitStrategy, ShortExitParams
from .experimental_exit import ExperimentalExitStrategy, ExperimentalExitParams

# State management
from .state_manager import StateManager

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


# Registry of available strategies
STRATEGY_REGISTRY: dict[str, StrategySpec] = {
    "v35_long": StrategySpec(
        name="v35_long",
        entry_class=V35EntryStrategy,
        entry_params_class=V35EntryParams,
        exit_class=V35TrailingExitStrategy,
        exit_params_class=V35ExitParams,
        persistent_exit_class=V35PersistentExitStrategy,
        market="spot",
    ),
    "sideways_v2": StrategySpec(
        name="sideways_v2",
        entry_class=SidewaysEntryStrategy,
        entry_params_class=SidewaysEntryParams,
        exit_class=SidewaysExitStrategy,
        exit_params_class=SidewaysExitParams,
        persistent_exit_class=None,  # Stateless, no persistence needed
        market="spot",
    ),
    "short_v1": StrategySpec(
        name="short_v1",
        entry_class=ShortEntryStrategy,
        entry_params_class=ShortEntryParams,
        exit_class=ShortExitStrategy,
        exit_params_class=ShortExitParams,
        persistent_exit_class=None,  # Stateless, no persistence needed
        market="futures",
    ),
    "v35_experimental": StrategySpec(
        name="v35_experimental",
        entry_class=V35EntryStrategy,
        entry_params_class=V35EntryParams,
        exit_class=ExperimentalExitStrategy,
        exit_params_class=ExperimentalExitParams,
        persistent_exit_class=None,
        market="spot",
    ),
}


class StrategyFactory:
    """Factory for creating strategy components from configuration.

    Creates and assembles Entry/Exit strategy components based on
    strategy names and configuration parameters.
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
    ) -> IEntryStrategy:
        """Create an entry strategy component.

        Args:
            strategy_name: Name of the strategy (e.g., "v35_long").
            config: Configuration parameters.

        Returns:
            Entry strategy instance.

        Raises:
            ValueError: If strategy name is not registered.
        """
        if strategy_name not in self._registry:
            raise ValueError(
                f"Unknown strategy: {strategy_name}. "
                f"Available: {self.get_available_strategies()}"
            )

        spec = self._registry[strategy_name]
        config = config or {}

        # Build params from config
        params = self._build_entry_params(spec, config)

        # Create entry strategy
        entry = spec.entry_class(params=params)
        logger.debug(f"Created entry strategy: {strategy_name}")
        return entry

    def create_exit(
        self,
        strategy_name: str,
        config: dict[str, Any] | None = None,
        persistent: bool = False,
    ) -> IExitStrategy:
        """Create an exit strategy component.

        Args:
            strategy_name: Name of the strategy (e.g., "v35_long").
            config: Configuration parameters.
            persistent: Use Redis-backed persistence if available.

        Returns:
            Exit strategy instance.

        Raises:
            ValueError: If strategy name is not registered.
        """
        if strategy_name not in self._registry:
            raise ValueError(
                f"Unknown strategy: {strategy_name}. "
                f"Available: {self.get_available_strategies()}"
            )

        spec = self._registry[strategy_name]
        config = config or {}

        # Build params from config
        params = self._build_exit_params(spec, config)

        # Use persistent version if requested and available
        if persistent and spec.persistent_exit_class and self._redis:
            exit_strat = spec.persistent_exit_class(
                redis=self._redis,
                params=params,
                strategy_name=f"{strategy_name}_exit",
            )
            logger.debug(f"Created persistent exit strategy: {strategy_name}")
        else:
            exit_strat = spec.exit_class(params=params)
            logger.debug(f"Created exit strategy: {strategy_name}")

        return exit_strat

    def create_components(
        self,
        strategy_name: str,
        config: dict[str, Any] | None = None,
        persistent: bool = False,
    ) -> tuple[IEntryStrategy, IExitStrategy]:
        """Create both entry and exit components for a strategy.

        Args:
            strategy_name: Name of the strategy.
            config: Configuration parameters.
            persistent: Use Redis-backed persistence if available.

        Returns:
            Tuple of (entry_strategy, exit_strategy).
        """
        entry = self.create_entry(strategy_name, config)
        exit_strat = self.create_exit(strategy_name, config, persistent)
        return entry, exit_strat

    def get_market(self, strategy_name: str, config: dict[str, Any] | None = None) -> str:
        """Get the market type for a strategy.

        Args:
            strategy_name: Name of the strategy.
            config: Optional config that may override the default market.

        Returns:
            Market type ("spot" or "futures").
        """
        if strategy_name not in self._registry:
            raise ValueError(f"Unknown strategy: {strategy_name}")

        spec = self._registry[strategy_name]

        # Config market overrides spec default
        if config and "market" in config:
            return config["market"]

        return spec.market

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
            Market type ("spot" or "futures").
        """
        # Config market overrides spec default
        return config.get("market", spec.market)

    def _build_entry_params(
        self,
        spec: StrategySpec,
        config: dict[str, Any],
    ) -> Any:
        """Build entry params from config.

        Maps config keys to param fields.
        """
        # Get market from config (allows override of spec default)
        market = self._get_market(spec, config)
        param_kwargs = {"market": market}

        # Map config to params
        if "position_size" in config:
            param_kwargs["position_size"] = config["position_size"]

        # Strategy-specific params
        if spec.name == "v35_long" or spec.name == "v35_experimental":
            if "mfi_bull" in config:
                param_kwargs["mfi_bull"] = config["mfi_bull"]
            if "adx_trend" in config:
                param_kwargs["adx_trend"] = config["adx_trend"]
        elif spec.name == "sideways_v2":
            if "rsi_oversold" in config:
                param_kwargs["rsi_oversold"] = config["rsi_oversold"]
        elif spec.name == "short_v1":
            if "rsi_overbought" in config:
                param_kwargs["rsi_overbought"] = config["rsi_overbought"]

        return spec.entry_params_class(**param_kwargs)

    def _build_exit_params(
        self,
        spec: StrategySpec,
        config: dict[str, Any],
    ) -> Any:
        """Build exit params from config.

        Maps config keys to param fields.
        """
        # Get market from config (allows override of spec default)
        market = self._get_market(spec, config)
        param_kwargs = {"market": market}

        # Common exit params
        if "stop_loss_pct" in config:
            param_kwargs["stop_loss_pct"] = config["stop_loss_pct"]
        if "take_profit_pct" in config:
            param_kwargs["take_profit_pct"] = config["take_profit_pct"]

        # V35-specific trailing stop params
        if spec.name == "v35_long" or spec.name == "v35_experimental":
            if "trailing_enabled" in config:
                param_kwargs["trailing_enabled"] = config["trailing_enabled"]
            if "trailing_activation" in config:
                param_kwargs["trailing_activation"] = config["trailing_activation"]
            if "trailing_distance" in config:
                param_kwargs["trailing_distance"] = config["trailing_distance"]

        return spec.exit_params_class(**param_kwargs)


def create_factory(redis: Redis | None = None) -> StrategyFactory:
    """Create a StrategyFactory instance.

    Convenience function for creating a factory.

    Args:
        redis: Optional Redis client for persistent strategies.

    Returns:
        StrategyFactory instance.
    """
    return StrategyFactory(redis=redis)
