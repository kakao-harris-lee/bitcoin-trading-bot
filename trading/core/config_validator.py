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
        optional_sections = ["risk", "notification"]
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

            if not asset_config.get("binance_enabled"):
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
        required_fields = ["binance_symbol"]
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
            is_enabled = asset_config.get("binance_enabled")
            if is_enabled and asset_config.get("strategy"):
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

        # Validate entry conditions
        entry = strategy_config.get("entry", {})
        if entry:
            result.merge(self._validate_entry_config(strategy, entry))

        # Validate exit conditions
        exit_config = strategy_config.get("exit", {})
        if exit_config:
            result.merge(self._validate_exit_config(strategy, exit_config))

        # Validate risk parameters if present
        risk = strategy_config.get("risk", {})
        if risk:
            result.merge(self._validate_risk_config(strategy, risk))

        return result

    def _validate_entry_config(self, strategy: str, entry: Dict[str, Any]) -> ValidationResult:
        """Validate entry configuration."""
        result = ValidationResult(valid=True)

        # Check for at least one entry condition
        condition_keys = ["regime", "mfi", "rsi", "adx", "macd", "bb", "volume"]
        has_condition = any(k in entry for k in condition_keys)
        if not has_condition:
            result.add_warning(f"Strategy '{strategy}': entry has no recognized conditions")

        # Validate numeric ranges
        if "mfi" in entry:
            mfi_cfg = entry["mfi"]
            if isinstance(mfi_cfg, dict):
                low = mfi_cfg.get("low", 0)
                high = mfi_cfg.get("high", 100)
                if not (0 <= low <= 100) or not (0 <= high <= 100):
                    result.add_error(f"Strategy '{strategy}': MFI values must be 0-100")
                if low > high:
                    result.add_error(f"Strategy '{strategy}': MFI low > high")

        if "rsi" in entry:
            rsi_cfg = entry["rsi"]
            if isinstance(rsi_cfg, dict):
                low = rsi_cfg.get("low", 0)
                high = rsi_cfg.get("high", 100)
                if not (0 <= low <= 100) or not (0 <= high <= 100):
                    result.add_error(f"Strategy '{strategy}': RSI values must be 0-100")

        return result

    def _validate_exit_config(self, strategy: str, exit_config: Dict[str, Any]) -> ValidationResult:
        """Validate exit configuration."""
        result = ValidationResult(valid=True)

        # Check for take profit / stop loss
        tp = exit_config.get("take_profit_pct") or exit_config.get("tp_pct")
        sl = exit_config.get("stop_loss_pct") or exit_config.get("sl_pct")

        if tp is not None:
            if not isinstance(tp, (int, float)) or tp <= 0:
                result.add_error(f"Strategy '{strategy}': take_profit_pct must be positive")
            elif tp > 50:
                result.add_warning(f"Strategy '{strategy}': take_profit_pct={tp}% is very high")

        if sl is not None:
            if not isinstance(sl, (int, float)) or sl <= 0:
                result.add_error(f"Strategy '{strategy}': stop_loss_pct must be positive")
            elif sl > 20:
                result.add_warning(f"Strategy '{strategy}': stop_loss_pct={sl}% is very high")

        # Check trailing stop if present
        trailing = exit_config.get("trailing_stop_pct")
        if trailing is not None:
            if not isinstance(trailing, (int, float)) or trailing <= 0:
                result.add_error(f"Strategy '{strategy}': trailing_stop_pct must be positive")

        return result

    def _validate_risk_config(self, strategy: str, risk: Dict[str, Any]) -> ValidationResult:
        """Validate risk configuration."""
        result = ValidationResult(valid=True)

        # Max position size
        max_position = risk.get("max_position_pct")
        if max_position is not None:
            if not isinstance(max_position, (int, float)) or not (0 < max_position <= 100):
                result.add_error(f"Strategy '{strategy}': max_position_pct must be 0-100")

        # Max drawdown
        max_dd = risk.get("max_drawdown_pct")
        if max_dd is not None:
            if not isinstance(max_dd, (int, float)) or max_dd <= 0:
                result.add_error(f"Strategy '{strategy}': max_drawdown_pct must be positive")

        return result

    def validate_environment(self) -> ValidationResult:
        """Validate environment variables and system requirements."""
        result = ValidationResult(valid=True)

        # Check for critical API keys (without exposing values)
        critical_env_vars = [
            ("BINANCE_API_KEY", "Binance API"),
            ("BINANCE_API_SECRET", "Binance API"),
        ]

        for var, service in critical_env_vars:
            if not os.getenv(var):
                result.add_error(f"Missing environment variable: {var} ({service})")

        # Optional but recommended env vars
        optional_env_vars = [
            ("TELEGRAM_BOT_TOKEN", "Telegram notifications"),
            ("TELEGRAM_CHAT_ID", "Telegram notifications"),
        ]

        for var, service in optional_env_vars:
            if not os.getenv(var):
                result.add_warning(f"Missing optional environment variable: {var} ({service})")

        return result

    def validate_connections(
        self,
        binance_test: Optional[callable] = None,
        redis_test: Optional[callable] = None,
        telegram_test: Optional[callable] = None,
    ) -> ValidationResult:
        """
        Validate connectivity to external services.

        Args:
            binance_test: Function to test Binance connection
            redis_test: Function to test Redis connection
            telegram_test: Function to test Telegram connection

        Returns:
            ValidationResult with connection test results
        """
        result = ValidationResult(valid=True)

        if binance_test:
            try:
                binance_test()
                logger.info("Binance connection: OK")
            except Exception as e:
                result.add_error(f"Binance connection failed: {e}")

        if redis_test:
            try:
                redis_test()
                logger.info("Redis connection: OK")
            except Exception as e:
                result.add_warning(f"Redis connection failed: {e}")

        if telegram_test:
            try:
                telegram_test()
                logger.info("Telegram connection: OK")
            except Exception as e:
                result.add_warning(f"Telegram connection failed: {e}")

        return result

    @staticmethod
    def test_binance_connection() -> None:
        """Default Binance connection test."""
        from binance.client import Client
        api_key = os.getenv("BINANCE_API_KEY")
        api_secret = os.getenv("BINANCE_API_SECRET")
        if not api_key or not api_secret:
            raise ValueError("Binance API keys not configured")
        client = Client(api_key, api_secret)
        client.ping()

    @staticmethod
    def test_redis_connection() -> None:
        """Default Redis connection test."""
        import redis
        host = os.getenv("REDIS_HOST", "localhost")
        port = int(os.getenv("REDIS_PORT", 6379))
        r = redis.Redis(host=host, port=port, socket_timeout=5.0)
        r.ping()

    @staticmethod
    def test_telegram_connection() -> None:
        """Default Telegram connection test."""
        import requests
        token = os.getenv("TELEGRAM_BOT_TOKEN")
        if not token:
            raise ValueError("TELEGRAM_BOT_TOKEN not configured")
        response = requests.get(
            f"https://api.telegram.org/bot{token}/getMe",
            timeout=5.0,
        )
        if not response.ok:
            raise ConnectionError(f"Telegram API error: {response.status_code}")


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

    def validate_with_connections(
        self,
        test_binance: bool = True,
        test_redis: bool = False,
        test_telegram: bool = False,
    ) -> ValidationResult:
        """
        Run validations including connection tests.

        Args:
            test_binance: Test Binance connection (critical)
            test_redis: Test Redis connection (optional)
            test_telegram: Test Telegram connection (optional)

        Returns:
            Combined ValidationResult
        """
        # Run config validation first
        self._result = self._validator.validate_all(self._config)

        # Run connection tests
        connection_result = self._validator.validate_connections(
            binance_test=ConfigValidator.test_binance_connection if test_binance else None,
            redis_test=ConfigValidator.test_redis_connection if test_redis else None,
            telegram_test=ConfigValidator.test_telegram_connection if test_telegram else None,
        )

        self._result.merge(connection_result)
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

    def validate_connections_or_raise(
        self,
        test_binance: bool = True,
        test_redis: bool = False,
        test_telegram: bool = False,
    ) -> None:
        """
        Run validations with connections and raise if invalid.

        This is the recommended startup validation method.
        """
        result = self.validate_with_connections(
            test_binance=test_binance,
            test_redis=test_redis,
            test_telegram=test_telegram,
        )

        if result.errors:
            error_msg = f"Startup validation failed:\n{result}"
            logger.error(error_msg)
            raise ConfigurationError(error_msg)

        if result.warnings:
            logger.warning(f"Startup warnings:\n{result}")

        logger.info("Startup validation passed")

    def get_result(self) -> Optional[ValidationResult]:
        """Get the last validation result."""
        return self._result


class ConfigurationError(Exception):
    """Raised when configuration validation fails."""
    pass
