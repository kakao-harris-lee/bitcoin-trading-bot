# tests/trading/strategies/components/test_registry.py
"""Tests for strategy registry and new config format."""
import pytest
from dataclasses import dataclass
from typing import Literal

from trading.strategies.components.registry import (
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
    clear_registries,
)
from trading.strategies.components.config_schema import (
    validate_strategy_config,
    has_new_config_format,
    ConfigValidationError,
)
from trading.strategies.components.strategy_factory import StrategyFactory
from trading.strategies.components.v35_entry import V35EntryStrategy, V35EntryParams
from trading.strategies.components.v35_trailing_exit import V35TrailingExitStrategy, V35ExitParams
from trading.strategies.components.sideways_entry import SidewaysEntryStrategy
from trading.strategies.components.sideways_exit import SidewaysExitStrategy
from trading.strategies.components.models import MarketData, MarketContext, TradingContext


@pytest.fixture
def factory():
    """Create factory instance."""
    return StrategyFactory()


class TestRegistryBasics:
    """Test basic registry functionality."""

    def test_entry_strategies_registered(self):
        """Test that entry strategies are registered via decorators."""
        assert is_entry_registered("V35EntryStrategy")
        assert is_entry_registered("SidewaysEntryStrategy")
        assert is_entry_registered("ShortEntryStrategy")

    def test_exit_strategies_registered(self):
        """Test that exit strategies are registered via decorators."""
        assert is_exit_registered("V35TrailingExitStrategy")
        assert is_exit_registered("V35PersistentExitStrategy")
        assert is_exit_registered("SidewaysExitStrategy")
        assert is_exit_registered("ShortExitStrategy")
        assert is_exit_registered("ExperimentalExitStrategy")

    def test_get_entry_class(self):
        """Test getting entry class by name."""
        cls = get_entry_class("V35EntryStrategy")
        assert cls is V35EntryStrategy

    def test_get_exit_class(self):
        """Test getting exit class by name."""
        cls = get_exit_class("V35TrailingExitStrategy")
        assert cls is V35TrailingExitStrategy

    def test_get_params_class(self):
        """Test getting params class for strategies."""
        params_cls = get_entry_params_class("V35EntryStrategy")
        assert params_cls is V35EntryParams

        params_cls = get_exit_params_class("V35TrailingExitStrategy")
        assert params_cls is V35ExitParams

    def test_get_registered_names(self):
        """Test listing registered strategy names."""
        entry_names = get_registered_entry_names()
        assert "V35EntryStrategy" in entry_names
        assert "SidewaysEntryStrategy" in entry_names

        exit_names = get_registered_exit_names()
        assert "V35TrailingExitStrategy" in exit_names
        assert "SidewaysExitStrategy" in exit_names

    def test_unknown_class_returns_none(self):
        """Test that unknown class name returns None."""
        assert get_entry_class("UnknownStrategy") is None
        assert get_exit_class("UnknownStrategy") is None
        assert not is_entry_registered("UnknownStrategy")
        assert not is_exit_registered("UnknownStrategy")


class TestBuildParamsFromConfig:
    """Test parameter building from config dict."""

    def test_build_with_valid_params(self):
        """Test building params with valid config values."""
        config = {
            "mfi_bull_strong": 55.0,
            "position_size": 0.02,
            "market": "futures",
        }
        params = build_params_from_config(V35EntryParams, config)

        assert params.mfi_bull_strong == 55.0
        assert params.position_size == 0.02
        assert params.market == "futures"
        # Check defaults are preserved
        assert params.mfi_bear_strong == 34.0  # default
        assert params.adx_moderate_trend == 20.0  # default (raised from 18)

    def test_build_with_defaults_only(self):
        """Test building params with no config (use defaults)."""
        params = build_params_from_config(V35EntryParams, {})

        assert params.mfi_bull_strong == 54.0
        assert params.position_size == 0.5
        assert params.market == "spot"  # Default is spot for V35 strategies

    def test_build_with_partial_config(self):
        """Test building params with partial config."""
        config = {"market": "futures"}  # Override default
        params = build_params_from_config(V35EntryParams, config)

        assert params.market == "futures"  # Override applied
        assert params.mfi_bull_strong == 54.0  # default

    def test_build_with_extra_keys_ignored(self):
        """Test that extra keys in config are ignored."""
        config = {
            "mfi_bull_strong": 55.0,
            "unknown_param": "ignored",
        }
        # Should not raise, extra keys are ignored
        params = build_params_from_config(V35EntryParams, config)
        assert params.mfi_bull_strong == 55.0

    def test_build_with_none_params_class(self):
        """Test that None params_class returns None."""
        result = build_params_from_config(None, {"key": "value"})
        assert result is None


class TestConfigSchemaValidation:
    """Test config schema validation."""

    def test_has_new_config_format_true(self):
        """Test detecting new config format."""
        config = {
            "entry": {"class": "V35EntryStrategy"},
            "exit": {"class": "V35TrailingExitStrategy"},
        }
        assert has_new_config_format(config) is True

    def test_has_new_config_format_false_legacy(self):
        """Test detecting legacy config format."""
        config = {
            "position_size": 0.01,
            "market": "futures",
        }
        assert has_new_config_format(config) is False

    def test_has_new_config_format_false_empty(self):
        """Test empty config is not new format."""
        assert has_new_config_format({}) is False

    def test_validate_valid_entry_config(self):
        """Test validation of valid entry config."""
        config = {
            "entry": {
                "class": "V35EntryStrategy",
                "params": {"mfi_bull_strong": 55.0},
            }
        }
        warnings = validate_strategy_config("test", config)
        assert len(warnings) == 0

    def test_validate_valid_exit_config(self):
        """Test validation of valid exit config."""
        config = {
            "exit": {
                "class": "V35TrailingExitStrategy",
                "params": {"stop_loss_pct": 2.0},
            }
        }
        warnings = validate_strategy_config("test", config)
        assert len(warnings) == 0

    def test_validate_unknown_entry_class(self):
        """Test error for unknown entry class."""
        config = {
            "entry": {"class": "UnknownEntryStrategy"}
        }
        with pytest.raises(ConfigValidationError, match="Unknown entry class"):
            validate_strategy_config("test", config)

    def test_validate_unknown_exit_class(self):
        """Test error for unknown exit class."""
        config = {
            "exit": {"class": "UnknownExitStrategy"}
        }
        with pytest.raises(ConfigValidationError, match="Unknown exit class"):
            validate_strategy_config("test", config)

    def test_validate_missing_class_field(self):
        """Test error for missing class field."""
        config = {
            "entry": {"params": {"mfi_bull_strong": 55.0}}
        }
        with pytest.raises(ConfigValidationError, match="missing required 'class' field"):
            validate_strategy_config("test", config)

    def test_validate_invalid_market(self):
        """Test error for invalid market type."""
        config = {"market": "invalid"}
        with pytest.raises(ConfigValidationError, match="Invalid market"):
            validate_strategy_config("test", config)

    def test_validate_warns_unknown_params(self):
        """Test warning for unknown params."""
        config = {
            "entry": {
                "class": "V35EntryStrategy",
                "params": {"unknown_param": 123},
            }
        }
        warnings = validate_strategy_config("test", config)
        assert len(warnings) == 1
        assert "Unknown param 'unknown_param'" in warnings[0]


class TestNewConfigFormat:
    """Test factory with new config format."""

    def test_create_entry_with_new_format(self, factory):
        """Test creating entry with new config format."""
        config = {
            "market": "futures",
            "entry": {
                "class": "V35EntryStrategy",
                "params": {
                    "mfi_bull_strong": 55.0,
                    "position_size": 0.02,
                },
            },
            "exit": {"class": "V35TrailingExitStrategy"},
        }

        entry = factory.create_entry("custom_strategy", config)

        assert isinstance(entry, V35EntryStrategy)
        assert entry.params.mfi_bull_strong == 55.0
        assert entry.params.position_size == 0.02
        assert entry.params.market == "futures"

    def test_create_exit_with_new_format(self, factory):
        """Test creating exit with new config format."""
        config = {
            "market": "futures",
            "entry": {"class": "V35EntryStrategy"},
            "exit": {
                "class": "V35TrailingExitStrategy",
                "params": {
                    "stop_loss_pct": 2.5,
                    "trailing_enabled": False,
                },
            },
        }

        exit_strat = factory.create_exit("custom_strategy", config)

        assert isinstance(exit_strat, V35TrailingExitStrategy)
        assert exit_strat.params.stop_loss_pct == 2.5
        assert exit_strat.params.trailing_enabled is False
        assert exit_strat.params.market == "futures"

    def test_create_components_with_new_format(self, factory):
        """Test creating both components with new format."""
        config = {
            "market": "futures",
            "position_size": 0.015,
            "entry": {"class": "V35EntryStrategy"},
            "exit": {"class": "SidewaysExitStrategy"},
        }

        entry, exit_strat = factory.create_components("mixed_strategy", config)

        assert isinstance(entry, V35EntryStrategy)
        assert isinstance(exit_strat, SidewaysExitStrategy)
        assert entry.params.market == "futures"
        assert exit_strat.params.market == "futures"

    def test_mixed_entry_exit_pairing(self, factory):
        """Test mixing V35 entry with Sideways exit."""
        config = {
            "market": "futures",
            "entry": {"class": "V35EntryStrategy"},
            "exit": {"class": "SidewaysExitStrategy"},
        }

        entry, exit_strat = factory.create_components("hybrid", config)

        # Verify both are created correctly
        assert isinstance(entry, V35EntryStrategy)
        assert isinstance(exit_strat, SidewaysExitStrategy)

        # Test entry generates signal - V35 requires MACD crossover + RSI above threshold
        market_data = MarketData(
            symbol="BTC",
            close=95000.0,
            mfi=55.0,
            adx=25.0,
            rsi=58.0,  # Above momentum_rsi_bull_strong (57.0)
            timestamp=1000000,
            macd=1.5,  # MACD crossover (above signal)
            macd_signal=1.0,
        )
        # Build context for BULL trend (MFI >= 52)
        context = MarketContext(
            trend="BULL",
            regime="BULL_STRONG",
            volatility_score=0.01,
            is_extreme_volatility=False,
            adx=25.0,
        )
        signal = entry.check_entry(TradingContext(symbol="BTC", timestamp=1000, market=market_data, regime=context, positions={}))
        assert signal is not None
        assert signal.market == "futures"

    def test_unknown_entry_class_error(self, factory):
        """Test error for unknown entry class in new format."""
        config = {
            "entry": {"class": "NonexistentEntry"},
            "exit": {"class": "V35TrailingExitStrategy"},
        }

        with pytest.raises(ValueError, match="Unknown entry class"):
            factory.create_entry("test", config)

    def test_unknown_exit_class_error(self, factory):
        """Test error for unknown exit class in new format."""
        config = {
            "entry": {"class": "V35EntryStrategy"},
            "exit": {"class": "NonexistentExit"},
        }

        with pytest.raises(ValueError, match="Unknown exit class"):
            factory.create_exit("test", config)

    def test_top_level_market_merged_into_params(self, factory):
        """Test that top-level market is merged into component params."""
        config = {
            "market": "futures",
            "entry": {"class": "V35EntryStrategy"},
            "exit": {"class": "V35TrailingExitStrategy"},
        }

        entry = factory.create_entry("test", config)
        assert entry.params.market == "futures"

    def test_component_params_override_top_level(self, factory):
        """Test that component params override top-level config."""
        config = {
            "market": "futures",  # Top-level
            "entry": {
                "class": "V35EntryStrategy",
                "params": {"market": "futures"},  # Override
            },
            "exit": {"class": "V35TrailingExitStrategy"},
        }

        entry = factory.create_entry("test", config)
        assert entry.params.market == "futures"  # Override wins


class TestLegacyConfigFormat:
    """Test that legacy config format still works."""

    def test_legacy_format_creates_v35(self, factory):
        """Test legacy format creates correct V35 strategy."""
        config = {"position_size": 0.02, "market": "futures"}

        entry = factory.create_entry("tuned_v35_long_v2_core_overlay_v2", config)
        exit_strat = factory.create_exit("tuned_v35_long_v2_core_overlay_v2", config)

        assert isinstance(entry, V35EntryStrategy)
        assert isinstance(exit_strat, V35TrailingExitStrategy)
        assert entry.params.position_size == 0.02
        assert entry.params.market == "futures"

    def test_legacy_format_creates_sideways(self, factory):
        """Test legacy format creates correct Sideways strategy."""
        config = {"position_size": 0.01, "rsi_oversold": 30.0}

        entry = factory.create_entry("sideways_v2", config)
        exit_strat = factory.create_exit("sideways_v2", config)

        assert isinstance(entry, SidewaysEntryStrategy)
        assert isinstance(exit_strat, SidewaysExitStrategy)
        assert entry.params.rsi_oversold == 30.0

    def test_legacy_format_unknown_strategy_error(self, factory):
        """Test error for unknown strategy in legacy format."""
        with pytest.raises(ValueError, match="Unknown strategy"):
            factory.create_entry("nonexistent_strategy", {})

    def test_legacy_format_with_empty_config(self, factory):
        """Test legacy format with empty config uses defaults."""
        entry = factory.create_entry("tuned_v35_long_v2_core_overlay_v2")

        assert isinstance(entry, V35EntryStrategy)
        assert entry.params.position_size == 0.5  # default
        assert entry.params.market == "spot"  # V35 now uses spot (no leverage benefit)


class TestBackwardCompatibility:
    """Ensure backward compatibility with existing tests."""

    def test_existing_factory_api_unchanged(self, factory):
        """Test that existing factory API still works."""
        # These are the existing ways to use the factory
        strategies = factory.get_available_strategies()
        assert "v35_classic_wide" in strategies
        assert "tuned_v35_long_v2_core_overlay_v2" in strategies

        entry = factory.create_entry("v35_classic_wide", {"position_size": 0.01})
        assert entry is not None

        exit_strat = factory.create_exit("v35_classic_wide", {"stop_loss_pct": 1.5})
        assert exit_strat is not None

        entry2, exit2 = factory.create_components("v35_classic_wide")
        assert entry2 is not None
        assert exit2 is not None

        market = factory.get_market("v35_classic_wide")
        assert market == "spot"  # V35 now uses spot (no leverage benefit)

    def test_strategy_registry_unchanged(self, factory):
        """Test that STRATEGY_REGISTRY entries still work."""
        from trading.strategies.components.strategy_factory import STRATEGY_REGISTRY

        assert "v35_classic_wide" in STRATEGY_REGISTRY
        assert "sideways_v2" in STRATEGY_REGISTRY
        assert "short_v1" in STRATEGY_REGISTRY
