"""Tests for configuration validator."""

import json
import os
import pytest
import tempfile
from pathlib import Path
from unittest.mock import patch

from trading.core.config_validator import (
    ConfigValidator,
    ConfigurationError,
    StartupValidator,
    ValidationResult,
)


class TestValidationResult:
    """Test ValidationResult class."""

    def test_initial_valid(self):
        """Result starts valid."""
        result = ValidationResult(valid=True)
        assert result.valid
        assert len(result.errors) == 0
        assert len(result.warnings) == 0

    def test_add_error_invalidates(self):
        """Adding error invalidates result."""
        result = ValidationResult(valid=True)
        result.add_error("Something wrong")

        assert not result.valid
        assert len(result.errors) == 1

    def test_add_warning_preserves_validity(self):
        """Adding warning doesn't invalidate result."""
        result = ValidationResult(valid=True)
        result.add_warning("Minor issue")

        assert result.valid
        assert len(result.warnings) == 1

    def test_merge_combines_results(self):
        """Merge combines errors and warnings."""
        result1 = ValidationResult(valid=True)
        result1.add_warning("warning 1")

        result2 = ValidationResult(valid=True)
        result2.add_error("error 1")
        result2.add_warning("warning 2")

        result1.merge(result2)

        assert not result1.valid
        assert len(result1.errors) == 1
        assert len(result1.warnings) == 2


class TestConfigValidator:
    """Test ConfigValidator class."""

    @pytest.fixture
    def temp_config_dir(self):
        """Create temporary config directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            config_dir = Path(tmpdir) / "config"
            strategies_dir = config_dir / "strategies"
            strategies_dir.mkdir(parents=True)

            # Create a valid strategy file
            with open(strategies_dir / "v35_long.json", "w") as f:
                json.dump({"entry": {}, "exit": {}}, f)

            yield config_dir

    @pytest.fixture
    def temp_data_dir(self):
        """Create temporary data directory."""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = Path(tmpdir) / "data"
            data_dir.mkdir(parents=True)

            # Create a mock database file
            (data_dir / "btc_data.db").touch()

            yield data_dir

    def test_validate_missing_assets_section(self, temp_config_dir, temp_data_dir):
        """Missing assets section is an error."""
        validator = ConfigValidator(temp_config_dir, temp_data_dir)
        result = validator.validate_allocation_structure({})

        assert not result.valid
        assert any("assets" in e for e in result.errors)

    def test_validate_valid_structure(self, temp_config_dir, temp_data_dir):
        """Valid structure passes validation."""
        config = {
            "assets": {
                "BTC": {
                    "enabled": True,
                    "upbit_symbol": "KRW-BTC",
                    "db_path": str(temp_data_dir / "btc_data.db"),
                    "capital_krw": 100000,
                    "strategy": "v35_long",
                }
            },
            "hedge": {},
            "risk": {},
            "notification": {},
        }

        validator = ConfigValidator(temp_config_dir, temp_data_dir)
        result = validator.validate_allocation_structure(config)

        assert result.valid

    def test_validate_missing_upbit_symbol(self, temp_config_dir, temp_data_dir):
        """Missing upbit_symbol is an error for enabled assets."""
        config = {
            "assets": {
                "BTC": {
                    "enabled": True,
                    "db_path": str(temp_data_dir / "btc_data.db"),
                }
            }
        }

        validator = ConfigValidator(temp_config_dir, temp_data_dir)
        result = validator.validate_assets(config)

        assert not result.valid
        assert any("upbit_symbol" in e for e in result.errors)

    def test_validate_missing_db_path(self, temp_config_dir, temp_data_dir):
        """Missing database file is an error."""
        config = {
            "assets": {
                "BTC": {
                    "enabled": True,
                    "upbit_symbol": "KRW-BTC",
                    "db_path": "/nonexistent/path.db",
                }
            }
        }

        validator = ConfigValidator(temp_config_dir, temp_data_dir)
        result = validator.validate_assets(config)

        assert not result.valid
        assert any("database not found" in e for e in result.errors)

    def test_validate_missing_strategy_config(self, temp_config_dir, temp_data_dir):
        """Missing strategy config file is an error."""
        config = {
            "assets": {
                "BTC": {
                    "enabled": True,
                    "upbit_symbol": "KRW-BTC",
                    "db_path": str(temp_data_dir / "btc_data.db"),
                    "strategy": "nonexistent_strategy",
                }
            }
        }

        validator = ConfigValidator(temp_config_dir, temp_data_dir)
        result = validator.validate_assets(config)

        assert not result.valid
        assert any("strategy config not found" in e for e in result.errors)

    def test_validate_hedge_without_binance_symbol(self, temp_config_dir, temp_data_dir):
        """Hedge enabled without binance_symbol is an error."""
        config = {
            "assets": {
                "BTC": {
                    "enabled": True,
                    "upbit_symbol": "KRW-BTC",
                    "db_path": str(temp_data_dir / "btc_data.db"),
                    "hedge_enabled": True,
                    # Missing binance_symbol
                }
            }
        }

        validator = ConfigValidator(temp_config_dir, temp_data_dir)
        result = validator.validate_assets(config)

        assert not result.valid
        assert any("binance_symbol" in e for e in result.errors)

    def test_validate_environment_missing_keys(self, temp_config_dir, temp_data_dir):
        """Missing API keys are errors."""
        # Clear environment
        with patch.dict(os.environ, {}, clear=True):
            validator = ConfigValidator(temp_config_dir, temp_data_dir)
            result = validator.validate_environment()

            assert not result.valid
            assert any("UPBIT_ACCESS_KEY" in e for e in result.errors)

    def test_validate_environment_with_keys(self, temp_config_dir, temp_data_dir):
        """Present API keys pass validation."""
        env = {
            "UPBIT_ACCESS_KEY": "test_key",
            "UPBIT_SECRET_KEY": "test_secret",
        }

        with patch.dict(os.environ, env, clear=True):
            validator = ConfigValidator(temp_config_dir, temp_data_dir)
            result = validator.validate_environment()

            assert result.valid


class TestStartupValidator:
    """Test StartupValidator class."""

    def test_validate_or_raise_on_error(self):
        """validate_or_raise raises on error."""
        config = {}  # Missing assets

        validator = StartupValidator(config)

        with pytest.raises(ConfigurationError) as exc_info:
            validator.validate_or_raise()

        assert "assets" in str(exc_info.value)

    def test_validate_returns_result(self):
        """validate returns ValidationResult."""
        config = {"assets": {}}

        validator = StartupValidator(config)
        result = validator.validate()

        assert isinstance(result, ValidationResult)
        assert result.valid  # Empty assets is valid (just warnings)
