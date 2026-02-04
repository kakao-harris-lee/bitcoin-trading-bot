"""Tests for V35 search space module."""
import pytest
import optuna

from web.quant_lab.optimizer.v35_search_space import (
    V35_PARAM_GROUPS,
    V35_STRATEGY_PARAMS,
    get_strategy_param_groups,
    get_all_strategies,
    get_param_bounds,
    sample_v35_config,
    build_full_search_space,
)


class TestV35ParamGroups:
    """Tests for parameter group definitions."""

    def test_all_groups_defined(self):
        """All expected parameter groups exist."""
        assert "risk" in V35_PARAM_GROUPS
        assert "sizing" in V35_PARAM_GROUPS
        assert "trailing" in V35_PARAM_GROUPS
        assert "take_profit" in V35_PARAM_GROUPS
        assert "core_overlay" in V35_PARAM_GROUPS
        assert "regime_thresholds" in V35_PARAM_GROUPS
        assert "leverage" in V35_PARAM_GROUPS

    def test_risk_params_have_valid_bounds(self):
        """Risk parameters have valid (min, max) bounds."""
        risk = V35_PARAM_GROUPS["risk"]
        assert "stop_loss_pct" in risk
        low, high = risk["stop_loss_pct"]
        assert low == 2.0
        assert high == 10.0
        assert low < high

    def test_sizing_params_have_valid_bounds(self):
        """Sizing parameters have valid bounds."""
        sizing = V35_PARAM_GROUPS["sizing"]
        assert "position_size_high" in sizing
        low, high = sizing["position_size_high"]
        assert 0 < low < high <= 1.0

    def test_all_bounds_are_valid(self):
        """All parameter bounds are valid (min < max)."""
        for group_name, params in V35_PARAM_GROUPS.items():
            for param_name, (low, high) in params.items():
                assert low < high, f"{group_name}.{param_name}: {low} >= {high}"


class TestV35StrategyParams:
    """Tests for strategy-to-group mapping."""

    def test_all_strategies_defined(self):
        """All V35 strategies have parameter mappings."""
        assert "tuned_v35_long_v2_core_overlay_v2" in V35_STRATEGY_PARAMS

    def test_core_overlay_strategies_have_core_group(self):
        """Core overlay strategies include core_overlay group."""
        groups = V35_STRATEGY_PARAMS["tuned_v35_long_v2_core_overlay_v2"]
        assert "core_overlay" in groups


class TestGetStrategyParamGroups:
    """Tests for get_strategy_param_groups function."""

    def test_returns_correct_groups_for_v35_long_v2(self):
        """Returns correct groups for tuned_v35_long_v2_core_overlay_v2."""
        groups = get_strategy_param_groups("tuned_v35_long_v2_core_overlay_v2")
        assert "risk" in groups
        assert "sizing" in groups
        assert "trailing" in groups
        # V35 runs on spot with no leverage per CLAUDE.md
        assert "leverage" not in groups
        assert "core_overlay" in groups

    def test_unknown_strategy_returns_defaults(self):
        """Unknown strategy returns default groups."""
        groups = get_strategy_param_groups("unknown_strategy")
        assert groups == ["risk", "trailing"]


class TestGetAllStrategies:
    """Tests for get_all_strategies function."""

    def test_returns_all_strategies(self):
        """Returns all available V35 strategies."""
        strategies = get_all_strategies()
        assert len(strategies) == 1
        assert "tuned_v35_long_v2_core_overlay_v2" in strategies


class TestGetParamBounds:
    """Tests for get_param_bounds function."""

    def test_returns_bounds_for_valid_group(self):
        """Returns bounds for valid group name."""
        bounds = get_param_bounds("risk")
        assert "stop_loss_pct" in bounds
        assert bounds["stop_loss_pct"] == (2.0, 10.0)

    def test_returns_empty_for_invalid_group(self):
        """Returns empty dict for invalid group name."""
        bounds = get_param_bounds("invalid_group")
        assert bounds == {}


class TestSampleV35Config:
    """Tests for sample_v35_config function."""

    def test_samples_config_for_v35_long_v2(self):
        """Samples config with correct parameters."""
        study = optuna.create_study()
        trial = study.ask()

        config = sample_v35_config(trial, "tuned_v35_long_v2_core_overlay_v2")

        # Check risk params
        assert "stop_loss_pct" in config
        assert 2.0 <= config["stop_loss_pct"] <= 10.0

        # Check sizing params
        assert "position_size_high" in config
        assert 0.15 <= config["position_size_high"] <= 0.55

        # Check trailing params
        assert "trailing_activation" in config

    def test_respects_enabled_groups(self):
        """Only samples from enabled groups."""
        study = optuna.create_study()
        trial = study.ask()

        config = sample_v35_config(trial, "tuned_v35_long_v2_core_overlay_v2", enabled_groups=["risk"])

        assert "stop_loss_pct" in config
        assert "position_size_high" not in config
        assert "trailing_activation" not in config

    def test_integer_params_are_integers(self):
        """Integer parameters are sampled as integers."""
        study = optuna.create_study()
        trial = study.ask()

        config = sample_v35_config(trial, "tuned_v35_long_v2_core_overlay_v2", enabled_groups=["risk"])

        assert "max_consecutive_losses" in config
        assert isinstance(config["max_consecutive_losses"], int)
        assert "stop_loss_cooldown" in config
        assert isinstance(config["stop_loss_cooldown"], int)


class TestBuildFullSearchSpace:
    """Tests for build_full_search_space function."""

    def test_builds_space_for_v35_long_v2(self):
        """Builds complete search space for strategy."""
        space = build_full_search_space("tuned_v35_long_v2_core_overlay_v2")

        assert "risk" in space
        assert "sizing" in space
        assert "trailing" in space
        assert "core_overlay" in space

        # Check param format
        assert "stop_loss_pct" in space["risk"]
        assert space["risk"]["stop_loss_pct"] == {"low": 2.0, "high": 10.0}
