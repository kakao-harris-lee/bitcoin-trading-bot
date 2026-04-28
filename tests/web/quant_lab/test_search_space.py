"""Tests for search space definition."""
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
        expected = {
            "BULL_STRONG", "BULL_MODERATE",
            "SIDEWAYS_UP", "SIDEWAYS_FLAT", "SIDEWAYS_DOWN",
            "BEAR_MODERATE", "BEAR_STRONG"
        }
        assert set(REGIMES) == expected

    def test_entry_components_include_none(self):
        assert "None" in ENTRY_COMPONENTS

    def test_exit_components_defined(self):
        assert EXIT_COMPONENTS == ["SidewaysExit"]


class TestSearchSpaceConfig:
    """Test SearchSpaceConfig dataclass."""

    def test_default_config_includes_all_regimes(self):
        config = SearchSpaceConfig()
        assert len(config.regime_configs) == 7

    def test_config_with_custom_entries(self):
        config = SearchSpaceConfig(
            regime_configs={
                "BULL_STRONG": {
                    "entries": ["SidewaysEntry", "None"],
                    "exits": ["SidewaysExit"],
                }
            }
        )
        assert "BULL_STRONG" in config.regime_configs


class TestBuildSearchSpace:
    """Test Optuna search space builder."""

    def test_build_search_space_returns_dict(self):
        config = SearchSpaceConfig()
        space = build_search_space(config)
        assert isinstance(space, dict)
        assert "BULL_STRONG" in space


class TestSampleTrialConfig:
    """Test trial configuration sampling."""

    def test_sample_returns_config_for_all_regimes(self):
        mock_trial = MagicMock()
        mock_trial.suggest_categorical.side_effect = lambda name, choices: choices[0]
        mock_trial.suggest_float.return_value = 50.0

        config = SearchSpaceConfig()
        result = sample_trial_config(mock_trial, config)

        assert len(result) == 8
        assert "regime_thresholds" in result
        for regime in REGIMES:
            assert regime in result
            assert "entry" in result[regime]
            assert "exit" in result[regime]
            assert "params" in result[regime]

    def test_sample_none_entry_has_no_params(self):
        mock_trial = MagicMock()
        mock_trial.suggest_categorical.return_value = "None"
        mock_trial.suggest_float.return_value = 50.0

        config = SearchSpaceConfig()
        config.regime_configs["BULL_STRONG"]["entries"] = ["None"]

        result = sample_trial_config(mock_trial, config)

        assert result["BULL_STRONG"]["entry"] == "None"
        assert result["BULL_STRONG"]["params"]["entry"] == {}
