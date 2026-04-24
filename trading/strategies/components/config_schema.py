"""Configuration schema validation for strategy components.

Validates that configuration matches expected structure and that
referenced class names exist in the registry.

Usage:
    from .config_schema import validate_strategy_config, ConfigValidationError

    try:
        validate_strategy_config("my_strategy", config)
    except ConfigValidationError as e:
        logger.error(f"Invalid config: {e}")
"""

from __future__ import annotations

import logging
from dataclasses import fields
from typing import Any

from .registry import (
    is_entry_registered,
    is_exit_registered,
    get_entry_params_class,
    get_exit_params_class,
    get_registered_entry_names,
    get_registered_exit_names,
)

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """Raised when strategy configuration is invalid."""


def validate_strategy_config(
    strategy_name: str,
    config: dict[str, Any],
) -> list[str]:
    """Validate a strategy configuration block.

    Checks:
    1. If entry/exit blocks exist, validates class names are registered
    2. If params are provided, validates they match dataclass fields
    3. Market type is valid

    Args:
        strategy_name: Name of the strategy being configured.
        config: Configuration dict for the strategy.

    Returns:
        List of warning messages (empty if no issues).

    Raises:
        ConfigValidationError: If configuration is invalid.
    """
    warnings: list[str] = []

    # Validate market if specified (spot-only system)
    if "market" in config:
        market = config["market"]
        if market != "spot":
            raise ConfigValidationError(
                f"Strategy '{strategy_name}': Invalid market '{market}'. "
                f"Must be 'spot'."
            )

    # Validate leverage if specified
    if "leverage" in config:
        leverage = config["leverage"]
        if not isinstance(leverage, (int, float)) or leverage < 1:
            raise ConfigValidationError(
                f"Strategy '{strategy_name}': Invalid leverage '{leverage}'. "
                f"Must be a number >= 1."
            )

    # Validate entry block if present
    if "entry" in config:
        entry_config = config["entry"]
        _validate_entry_config(strategy_name, entry_config, warnings)

    # Validate exit block if present
    if "exit" in config:
        exit_config = config["exit"]
        _validate_exit_config(strategy_name, exit_config, warnings)

    return warnings


def _validate_entry_config(
    strategy_name: str,
    entry_config: dict[str, Any],
    warnings: list[str],
) -> None:
    """Validate entry configuration block.

    Args:
        strategy_name: Name of the strategy.
        entry_config: Entry configuration dict.
        warnings: List to append warnings to.

    Raises:
        ConfigValidationError: If entry config is invalid.
    """
    if not isinstance(entry_config, dict):
        raise ConfigValidationError(
            f"Strategy '{strategy_name}': Entry config must be a dict."
        )

    # Class name is required
    if "class" not in entry_config:
        raise ConfigValidationError(
            f"Strategy '{strategy_name}': Entry config missing required 'class' field."
        )

    class_name = entry_config["class"]

    # Check if class is registered
    if not is_entry_registered(class_name):
        available = get_registered_entry_names()
        raise ConfigValidationError(
            f"Strategy '{strategy_name}': Unknown entry class '{class_name}'. "
            f"Available: {available}"
        )

    # Validate params if provided
    if "params" in entry_config:
        params = entry_config["params"]
        if not isinstance(params, dict):
            raise ConfigValidationError(
                f"Strategy '{strategy_name}': Entry params must be a dict."
            )

        # Validate params match dataclass fields
        params_class = get_entry_params_class(class_name)
        if params_class:
            _validate_params_match_dataclass(
                strategy_name, "entry", class_name, params, params_class, warnings
            )


def _validate_exit_config(
    strategy_name: str,
    exit_config: dict[str, Any],
    warnings: list[str],
) -> None:
    """Validate exit configuration block.

    Args:
        strategy_name: Name of the strategy.
        exit_config: Exit configuration dict.
        warnings: List to append warnings to.

    Raises:
        ConfigValidationError: If exit config is invalid.
    """
    if not isinstance(exit_config, dict):
        raise ConfigValidationError(
            f"Strategy '{strategy_name}': Exit config must be a dict."
        )

    # Class name is required
    if "class" not in exit_config:
        raise ConfigValidationError(
            f"Strategy '{strategy_name}': Exit config missing required 'class' field."
        )

    class_name = exit_config["class"]

    # Check if class is registered
    if not is_exit_registered(class_name):
        available = get_registered_exit_names()
        raise ConfigValidationError(
            f"Strategy '{strategy_name}': Unknown exit class '{class_name}'. "
            f"Available: {available}"
        )

    # Validate persistent_class if provided
    if "persistent_class" in exit_config:
        persistent_name = exit_config["persistent_class"]
        if not is_exit_registered(persistent_name):
            available = get_registered_exit_names()
            raise ConfigValidationError(
                f"Strategy '{strategy_name}': Unknown persistent exit class '{persistent_name}'. "
                f"Available: {available}"
            )

    # Validate params if provided
    if "params" in exit_config:
        params = exit_config["params"]
        if not isinstance(params, dict):
            raise ConfigValidationError(
                f"Strategy '{strategy_name}': Exit params must be a dict."
            )

        # Validate params match dataclass fields
        params_class = get_exit_params_class(class_name)
        if params_class:
            _validate_params_match_dataclass(
                strategy_name, "exit", class_name, params, params_class, warnings
            )


def _validate_params_match_dataclass(
    strategy_name: str,
    component_type: str,
    class_name: str,
    params: dict[str, Any],
    params_class: type,
    warnings: list[str],
) -> None:
    """Validate that params keys match dataclass fields.

    Args:
        strategy_name: Name of the strategy.
        component_type: "entry" or "exit".
        class_name: Name of the strategy class.
        params: Params dict from config.
        params_class: The params dataclass.
        warnings: List to append warnings to.
    """
    # Get valid field names
    valid_fields = {f.name for f in fields(params_class)}

    # Check for unknown fields
    for key in params:
        if key not in valid_fields:
            warnings.append(
                f"Strategy '{strategy_name}' {component_type} ({class_name}): "
                f"Unknown param '{key}'. Valid fields: {sorted(valid_fields)}"
            )


def has_new_config_format(config: dict[str, Any]) -> bool:
    """Check if config uses the new entry/exit block format.

    Args:
        config: Strategy configuration dict.

    Returns:
        True if config has entry or exit blocks with class field.
    """
    if "entry" in config and isinstance(config["entry"], dict):
        if "class" in config["entry"]:
            return True

    if "exit" in config and isinstance(config["exit"], dict):
        if "class" in config["exit"]:
            return True

    return False
