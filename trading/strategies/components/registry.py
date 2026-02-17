"""Strategy Component Registry - decorator-based auto-registration.

Provides decorator-based registration for entry and exit strategies,
enabling dynamic class lookup and parameter building from config.

Usage:
    from .registry import entry_strategy, exit_strategy, get_entry_class, get_exit_class

    @entry_strategy(params_class=ShortEntryParams)
    class ShortEntryStrategy:
        ...

    @exit_strategy(params_class=ShortExitParams)
    class ShortExitStrategy:
        ...

    # Later, lookup by class name
    entry_cls = get_entry_class("ShortEntryStrategy")
    exit_cls = get_exit_class("ShortExitStrategy")
"""

from __future__ import annotations

import logging
from dataclasses import fields
from typing import Any, TypeVar

logger = logging.getLogger(__name__)

# Type variable for strategy classes
T = TypeVar("T")

# Registries store class info by class name
_ENTRY_REGISTRY: dict[str, dict[str, Any]] = {}
_EXIT_REGISTRY: dict[str, dict[str, Any]] = {}


def entry_strategy(params_class: type | None = None):
    """Decorator to register an entry strategy class.

    Args:
        params_class: The dataclass used for this strategy's parameters.

    Returns:
        Decorator function that registers the class.

    Example:
        @entry_strategy(params_class=ShortEntryParams)
        class ShortEntryStrategy:
            def __init__(self, params: ShortEntryParams | None = None):
                ...
    """

    def decorator(cls: type[T]) -> type[T]:
        class_name = cls.__name__
        _ENTRY_REGISTRY[class_name] = {
            "class": cls,
            "params_class": params_class,
        }
        logger.debug("Registered entry strategy: %s", class_name)
        return cls

    return decorator


def exit_strategy(
    params_class: type | None = None,
    persistent_class: type | None = None,
):
    """Decorator to register an exit strategy class.

    Args:
        params_class: The dataclass used for this strategy's parameters.
        persistent_class: Optional Redis-backed version of this strategy.

    Returns:
        Decorator function that registers the class.

    Example:
        @exit_strategy(params_class=ShortExitParams)
        class ShortExitStrategy:
            def __init__(self, params: ShortExitParams | None = None):
                ...
    """

    def decorator(cls: type[T]) -> type[T]:
        class_name = cls.__name__
        _EXIT_REGISTRY[class_name] = {
            "class": cls,
            "params_class": params_class,
            "persistent_class": persistent_class,
        }
        logger.debug("Registered exit strategy: %s", class_name)
        return cls

    return decorator


def get_entry_class(class_name: str) -> type | None:
    """Get an entry strategy class by name.

    Args:
        class_name: Name of the entry strategy class.

    Returns:
        The strategy class, or None if not found.
    """
    entry = _ENTRY_REGISTRY.get(class_name)
    return entry["class"] if entry else None


def get_exit_class(class_name: str) -> type | None:
    """Get an exit strategy class by name.

    Args:
        class_name: Name of the exit strategy class.

    Returns:
        The strategy class, or None if not found.
    """
    entry = _EXIT_REGISTRY.get(class_name)
    return entry["class"] if entry else None


def get_entry_params_class(class_name: str) -> type | None:
    """Get the params class for an entry strategy.

    Args:
        class_name: Name of the entry strategy class.

    Returns:
        The params dataclass, or None if not found.
    """
    entry = _ENTRY_REGISTRY.get(class_name)
    return entry["params_class"] if entry else None


def get_exit_params_class(class_name: str) -> type | None:
    """Get the params class for an exit strategy.

    Args:
        class_name: Name of the exit strategy class.

    Returns:
        The params dataclass, or None if not found.
    """
    entry = _EXIT_REGISTRY.get(class_name)
    return entry["params_class"] if entry else None


def get_exit_persistent_class(class_name: str) -> type | None:
    """Get the persistent class for an exit strategy.

    Args:
        class_name: Name of the exit strategy class.

    Returns:
        The persistent strategy class, or None if not available.
    """
    entry = _EXIT_REGISTRY.get(class_name)
    return entry["persistent_class"] if entry else None


def get_registered_entry_names() -> list[str]:
    """Get all registered entry strategy class names."""
    return list(_ENTRY_REGISTRY.keys())


def get_registered_exit_names() -> list[str]:
    """Get all registered exit strategy class names."""
    return list(_EXIT_REGISTRY.keys())


def build_params_from_config(
    params_class: type,
    config: dict[str, Any],
    defaults: dict[str, Any] | None = None,
) -> Any:
    """Build a params dataclass instance from config dict.

    Uses field introspection to:
    1. Extract matching keys from config
    2. Apply any provided defaults
    3. Skip fields that have defaults in the dataclass

    Args:
        params_class: The dataclass to instantiate.
        config: Configuration dict with values.
        defaults: Optional default values to apply.

    Returns:
        Instance of params_class with values from config.

    Raises:
        TypeError: If required fields are missing from config.

    Example:
        @dataclass
        class ShortEntryParams:
            adx_threshold: float = 25.0
            position_size: float = 0.01
            market: str = "futures"

        params = build_params_from_config(
            ShortEntryParams,
            {"adx_threshold": 30.0, "market": "futures"},
        )
        # Results in ShortEntryParams(adx_threshold=30.0, position_size=0.01, market="futures")
    """
    if params_class is None:
        return None

    defaults = defaults or {}
    kwargs: dict[str, Any] = {}

    # Get all fields from the dataclass
    for field in fields(params_class):
        field_name = field.name

        # Check if value is in config
        if field_name in config:
            kwargs[field_name] = config[field_name]
        # Check if value is in defaults
        elif field_name in defaults:
            kwargs[field_name] = defaults[field_name]
        # If field has no default and not provided, it will raise on init
        # Let the dataclass handle required field validation

    return params_class(**kwargs)


def is_entry_registered(class_name: str) -> bool:
    """Check if an entry strategy is registered.

    Args:
        class_name: Name of the entry strategy class.

    Returns:
        True if registered, False otherwise.
    """
    return class_name in _ENTRY_REGISTRY


def is_exit_registered(class_name: str) -> bool:
    """Check if an exit strategy is registered.

    Args:
        class_name: Name of the exit strategy class.

    Returns:
        True if registered, False otherwise.
    """
    return class_name in _EXIT_REGISTRY


def clear_registries() -> None:
    """Clear all registries. Used for testing."""
    _ENTRY_REGISTRY.clear()
    _EXIT_REGISTRY.clear()
