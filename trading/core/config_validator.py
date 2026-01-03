"""
Configuration Validator for startup validation.

Validates configuration at startup to catch errors early,
before they cause runtime failures.
"""

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Result of a validation check."""
    valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)

    def add_error(self, message: str) -> None:
        """Add an error message."""
        self.errors.append(message)
        self.valid = False

    def add_warning(self, message: str) -> None:
        """Add a warning message."""
        self.warnings.append(message)

    def merge(self, other: "ValidationResult") -> None:
        """Merge another result into this one."""
        if not other.valid:
            self.valid = False
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)

    def __str__(self) -> str:
        parts = []
        if self.errors:
            parts.append(f"Errors ({len(self.errors)}):")
            for e in self.errors:
                parts.append(f"  - {e}")
        if self.warnings:
            parts.append(f"Warnings ({len(self.warnings)}):")
            for w in self.warnings:
                parts.append(f"  - {w}")
        if self.valid and not self.warnings:
            parts.append("Configuration valid")
        return "\n".join(parts)


class ConfigValidator:
    """
    Validates trading bot configuration.

    Usage:
        validator = ConfigValidator()
        result = validator.validate_all(allocation_config)
        if not result.valid:
            raise StartupError(str(result))
    """

    def __init__(self, config_dir: Optional[Path] = None, data_dir: Optional[Path] = None):
        """
        Args:
            config_dir: Path to config directory (default: config/)
            data_dir: Path to data directory (default: data/)
        """
        self._config_dir = config_dir or Path("config")
        self._data_dir = data_dir or Path("data")

    def validate_all(self, allocation_config: Dict[str, Any]) -> ValidationResult:
        """
        Run all validation checks.

        Args:
            allocation_config: The allocation configuration dict

        Returns:
            ValidationResult with all errors and warnings
        """
        result = ValidationResult(valid=True)

        # Run all validators
        result.merge(self.validate_allocation_structure(allocation_config))
        result.merge(self.validate_assets(allocation_config))
        result.merge(self.validate_strategy_configs(allocation_config))
        result.merge(self.validate_environment())

        return result

    def validate_allocation_structure(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate the basic structure of allocation config."""
        result = ValidationResult(valid=True)

        # Required top-level sections
        required_sections = ["assets"]
        for section in required_sections:
            if section not in config:
                result.add_error(f"Missing required section: '{section}'")

        # Check for common config sections
        optional_sections = ["hedge", "premium", "risk", "notification"]
        for section in optional_sections:
            if section not in config:
                result.add_warning(f"Missing optional section: '{section}'")

        return result

    def validate_assets(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate asset configurations."""
        result = ValidationResult(valid=True)

        assets = config.get("assets", {})
        if not assets:
            result.add_warning("No assets configured")
            return result

        enabled_count = 0
        for symbol, asset_config in assets.items():
            if not isinstance(asset_config, dict):
                result.add_error(f"{symbol}: asset config must be a dictionary")
                continue

            if not asset_config.get("enabled"):
                continue

            enabled_count += 1
            asset_result = self._validate_single_asset(symbol, asset_config)
            result.merge(asset_result)

        if enabled_count == 0:
            result.add_warning("No assets are enabled")

        return result

    def _validate_single_asset(self, symbol: str, config: Dict[str, Any]) -> ValidationResult:
        """Validate a single asset configuration."""
        result = ValidationResult(valid=True)

        # Required fields for enabled assets
        required_fields = ["upbit_symbol"]
        for field in required_fields:
            if not config.get(field):
                result.add_error(f"{symbol}: missing required field '{field}'")

        # Check database path
        db_path = config.get("db_path")
        if db_path:
            if not Path(db_path).exists():
                result.add_error(f"{symbol}: database not found at '{db_path}'")
        else:
            # Try default path
            default_db = self._data_dir / f"{symbol.lower()}_data.db"
            if not default_db.exists():
                result.add_warning(f"{symbol}: no db_path specified and default not found")

        # Validate capital allocation
        capital_krw = config.get("capital_krw", 0)
        if capital_krw <= 0:
            result.add_warning(f"{symbol}: no capital allocated (capital_krw={capital_krw})")

        # Validate strategy reference
        strategy = config.get("strategy")
        if strategy:
            strategy_result = self._validate_strategy_exists(symbol, strategy)
            result.merge(strategy_result)

        # Validate hedge configuration if enabled
        if config.get("hedge_enabled"):
            if not config.get("binance_symbol"):
                result.add_error(f"{symbol}: hedge_enabled but missing binance_symbol")

        return result

    def _validate_strategy_exists(self, symbol: str, strategy: str) -> ValidationResult:
        """Check if strategy config file exists."""
        result = ValidationResult(valid=True)

        config_path = self._config_dir / "strategies" / f"{strategy}.json"
        if not config_path.exists():
            result.add_error(
                f"{symbol}: strategy config not found at '{config_path}'"
            )

        return result

    def validate_strategy_configs(self, config: Dict[str, Any]) -> ValidationResult:
        """Validate strategy configuration files."""
        result = ValidationResult(valid=True)

        strategies_dir = self._config_dir / "strategies"
        if not strategies_dir.exists():
            result.add_warning(f"Strategies directory not found: {strategies_dir}")
            return result

        # Collect strategies referenced by enabled assets
        referenced_strategies = set()
        for symbol, asset_config in config.get("assets", {}).items():
            if asset_config.get("enabled") and asset_config.get("strategy"):
                referenced_strategies.add(asset_config["strategy"])

        # Validate each referenced strategy
        for strategy in referenced_strategies:
            strategy_result = self._validate_strategy_content(strategy)
            result.merge(strategy_result)

        return result

    def _validate_strategy_content(self, strategy: str) -> ValidationResult:
        """Validate contents of a strategy config file."""
        import json

        result = ValidationResult(valid=True)
        config_path = self._config_dir / "strategies" / f"{strategy}.json"

        if not config_path.exists():
            # Already reported by _validate_strategy_exists
            return result

        try:
            with open(config_path) as f:
                strategy_config = json.load(f)
        except json.JSONDecodeError as e:
            result.add_error(f"Strategy '{strategy}': invalid JSON - {e}")
            return result
        except Exception as e:
            result.add_error(f"Strategy '{strategy}': failed to read - {e}")
            return result

        # Validate common strategy fields
        if "entry" not in strategy_config and "exit" not in strategy_config:
            result.add_warning(
                f"Strategy '{strategy}': missing 'entry' or 'exit' sections"
            )

        return result

    def validate_environment(self) -> ValidationResult:
        """Validate environment variables and system requirements."""
        result = ValidationResult(valid=True)

        # Check for critical API keys (without exposing values)
        critical_env_vars = [
            ("UPBIT_ACCESS_KEY", "Upbit API"),
            ("UPBIT_SECRET_KEY", "Upbit API"),
        ]

        for var, service in critical_env_vars:
            if not os.getenv(var):
                result.add_error(f"Missing environment variable: {var} ({service})")

        # Optional but recommended env vars
        optional_env_vars = [
            ("BINANCE_API_KEY", "Binance API"),
            ("BINANCE_API_SECRET", "Binance API"),
            ("TELEGRAM_BOT_TOKEN", "Telegram notifications"),
            ("TELEGRAM_CHAT_ID", "Telegram notifications"),
        ]

        for var, service in optional_env_vars:
            if not os.getenv(var):
                result.add_warning(f"Missing optional environment variable: {var} ({service})")

        return result

    def validate_connections(
        self,
        upbit_test: Optional[callable] = None,
        binance_test: Optional[callable] = None,
        redis_test: Optional[callable] = None,
    ) -> ValidationResult:
        """
        Validate connectivity to external services.

        Args:
            upbit_test: Function to test Upbit connection
            binance_test: Function to test Binance connection
            redis_test: Function to test Redis connection

        Returns:
            ValidationResult with connection test results
        """
        result = ValidationResult(valid=True)

        if upbit_test:
            try:
                upbit_test()
                logger.info("Upbit connection: OK")
            except Exception as e:
                result.add_error(f"Upbit connection failed: {e}")

        if binance_test:
            try:
                binance_test()
                logger.info("Binance connection: OK")
            except Exception as e:
                result.add_warning(f"Binance connection failed: {e}")

        if redis_test:
            try:
                redis_test()
                logger.info("Redis connection: OK")
            except Exception as e:
                result.add_warning(f"Redis connection failed: {e}")

        return result


class StartupValidator:
    """
    Orchestrates all startup validation checks.

    Usage:
        validator = StartupValidator(allocation_config)
        validator.validate_or_raise()
    """

    def __init__(
        self,
        allocation_config: Dict[str, Any],
        config_dir: Optional[Path] = None,
        data_dir: Optional[Path] = None,
    ):
        self._config = allocation_config
        self._validator = ConfigValidator(config_dir, data_dir)
        self._result: Optional[ValidationResult] = None

    def validate(self) -> ValidationResult:
        """Run all validations and return result."""
        self._result = self._validator.validate_all(self._config)
        return self._result

    def validate_or_raise(self) -> None:
        """Run validations and raise exception if invalid."""
        result = self.validate()

        if result.errors:
            error_msg = f"Configuration validation failed:\n{result}"
            logger.error(error_msg)
            raise ConfigurationError(error_msg)

        if result.warnings:
            logger.warning(f"Configuration warnings:\n{result}")

        logger.info("Configuration validation passed")

    def get_result(self) -> Optional[ValidationResult]:
        """Get the last validation result."""
        return self._result


class ConfigurationError(Exception):
    """Raised when configuration validation fails."""
    pass
