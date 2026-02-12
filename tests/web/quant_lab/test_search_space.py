"""Tests for search space definition."""
import pytest
from unittest.mock import MagicMock
from web.quant_lab.optimizer.search_space import (
    REGIMES,
    ENTRY_COMPONENTS,
    EXIT_COMPONENTS,
    SearchSpaceConfig,
    build_search_space,
    sample_trial_config,
    MLP_ENTRY_PARAMS,
    MLP_EXIT_PARAMS,
    MLP_ENSEMBLE_PARAMS,
    MLP_ADAPTER_PARAMS,
    sample_mlp_trial_config,
)


class TestSearchSpaceConstants:
    """Test search space constants."""

    def test_regimes_contains_all_seven(self):
        """All 7 regimes should be defined."""
        expected = {
            "BULL_STRONG", "BULL_MODERATE",
            "SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN",
            "BEAR_MODERATE", "BEAR_STRONG"
        }
        assert set(REGIMES) == expected

    def test_entry_components_include_none(self):
        """Entry components should include 'None' option."""
        assert "None" in ENTRY_COMPONENTS

    def test_exit_components_defined(self):
        """Exit components should be defined."""
        assert len(EXIT_COMPONENTS) >= 2


class TestSearchSpaceConfig:
    """Test SearchSpaceConfig dataclass."""

    def test_default_config_includes_all_regimes(self):
        """Default config should include all regimes."""
        config = SearchSpaceConfig()
        assert len(config.regime_configs) == 7

    def test_config_with_custom_entries(self):
        """Config should accept custom entry component lists."""
        config = SearchSpaceConfig(
            regime_configs={
                "BULL_STRONG": {
                    "entries": ["ShortEntry", "None"],
                    "exits": ["ShortExit"],
                }
            }
        )
        assert "BULL_STRONG" in config.regime_configs


class TestBuildSearchSpace:
    """Test Optuna search space builder."""

    def test_build_search_space_returns_dict(self):
        """build_search_space should return a dict for Optuna."""
        config = SearchSpaceConfig()
        space = build_search_space(config)
        assert isinstance(space, dict)
        assert "BULL_STRONG" in space


class TestSampleTrialConfig:
    """Test trial configuration sampling."""

    def test_sample_returns_config_for_all_regimes(self):
        """sample_trial_config should return config for all 7 regimes."""
        mock_trial = MagicMock()
        mock_trial.suggest_categorical.side_effect = lambda name, choices: choices[0]
        mock_trial.suggest_float.return_value = 50.0

        config = SearchSpaceConfig()
        result = sample_trial_config(mock_trial, config)

        assert len(result) == 8  # 7 regimes + regime_thresholds
        assert "regime_thresholds" in result
        for regime in REGIMES:
            assert regime in result
            assert "entry" in result[regime]
            assert "exit" in result[regime]
            assert "params" in result[regime]

    def test_sample_none_entry_has_no_params(self):
        """When entry is None, params should be empty for entry."""
        mock_trial = MagicMock()
        mock_trial.suggest_categorical.return_value = "None"
        mock_trial.suggest_float.return_value = 50.0

        config = SearchSpaceConfig()
        config.regime_configs["BULL_STRONG"]["entries"] = ["None"]

        result = sample_trial_config(mock_trial, config)

        assert result["BULL_STRONG"]["entry"] == "None"
        assert result["BULL_STRONG"]["params"]["entry"] == {}


class TestMLPSearchSpaceConstants:
    """Test MLP search space constants."""

    def test_mlp_entry_params_defined(self):
        """MLP entry params should contain expected keys."""
        assert "buy_confidence_threshold" in MLP_ENTRY_PARAMS
        assert "skip_bear_regime" in MLP_ENTRY_PARAMS
        assert "adx_min" in MLP_ENTRY_PARAMS
        assert "use_ema200_filter" in MLP_ENTRY_PARAMS

    def test_mlp_exit_params_defined(self):
        """MLP exit params should contain expected keys."""
        assert "stop_loss_pct" in MLP_EXIT_PARAMS
        assert "fwin_exit_enabled" in MLP_EXIT_PARAMS
        assert "trailing_enabled" in MLP_EXIT_PARAMS
        assert "take_profit_pct" in MLP_EXIT_PARAMS

    def test_mlp_ensemble_params_defined(self):
        """MLP ensemble params should have 4 weight keys."""
        assert len(MLP_ENSEMBLE_PARAMS) == 4
        for key in ("weight_bwin3", "weight_bwin4", "weight_bwin5", "weight_bwin7"):
            assert key in MLP_ENSEMBLE_PARAMS

    def test_mlp_adapter_params_defined(self):
        """MLP adapter params should contain expected keys."""
        assert "cash_in_bear" in MLP_ADAPTER_PARAMS
        assert "cash_below_ema200" in MLP_ADAPTER_PARAMS
        assert "stop_loss_cooldown" in MLP_ADAPTER_PARAMS
        assert "drawdown_bear_threshold" in MLP_ADAPTER_PARAMS


class TestSampleMLPTrialConfig:
    """Test MLP trial configuration sampling."""

    def test_sample_returns_all_sections(self):
        """sample_mlp_trial_config should return entry, exit, ensemble, adapter."""
        mock_trial = MagicMock()
        mock_trial.suggest_float.return_value = 0.5
        mock_trial.suggest_categorical.side_effect = lambda name, choices: choices[0]
        mock_trial.suggest_int.return_value = 5

        result = sample_mlp_trial_config(mock_trial)

        assert "entry" in result
        assert "exit" in result
        assert "ensemble" in result
        assert "adapter" in result

    def test_sample_entry_contains_all_params(self):
        """Entry section should contain all MLP entry params."""
        mock_trial = MagicMock()
        mock_trial.suggest_float.return_value = 0.5
        mock_trial.suggest_categorical.side_effect = lambda name, choices: choices[0]
        mock_trial.suggest_int.return_value = 5

        result = sample_mlp_trial_config(mock_trial)

        for key in MLP_ENTRY_PARAMS:
            assert key in result["entry"], f"Missing entry param: {key}"

    def test_sample_exit_contains_all_params(self):
        """Exit section should contain all MLP exit params."""
        mock_trial = MagicMock()
        mock_trial.suggest_float.return_value = 0.5
        mock_trial.suggest_categorical.side_effect = lambda name, choices: choices[0]
        mock_trial.suggest_int.return_value = 5

        result = sample_mlp_trial_config(mock_trial)

        for key in MLP_EXIT_PARAMS:
            assert key in result["exit"], f"Missing exit param: {key}"

    def test_sample_ensemble_contains_all_weights(self):
        """Ensemble section should contain all 4 weight keys."""
        mock_trial = MagicMock()
        mock_trial.suggest_float.return_value = 0.25
        mock_trial.suggest_categorical.side_effect = lambda name, choices: choices[0]
        mock_trial.suggest_int.return_value = 5

        result = sample_mlp_trial_config(mock_trial)

        for key in MLP_ENSEMBLE_PARAMS:
            assert key in result["ensemble"], f"Missing ensemble param: {key}"
