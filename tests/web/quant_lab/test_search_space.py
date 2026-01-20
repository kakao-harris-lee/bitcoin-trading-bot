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
        assert len(EXIT_COMPONENTS) >= 4


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
                    "entries": ["V35Entry", "None"],
                    "exits": ["V35TrailingExit"],
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

        assert len(result) == 7
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
