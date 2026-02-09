"""Tests for multi-objective optimization function."""
import pytest
from unittest.mock import MagicMock, patch
from web.quant_lab.optimizer.objective import (
    RegimeBacktestObjective,
    MLPDirectionObjective,
    create_multi_objective,
)


class TestRegimeBacktestObjective:
    """Test the backtest objective function."""

    def test_objective_returns_three_values(self):
        """Objective should return (win_rate, total_return, max_drawdown)."""
        objective = RegimeBacktestObjective(
            data_path="test_data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            symbols=["BTCUSDT"],
        )

        mock_trial = MagicMock()
        mock_trial.suggest_categorical.side_effect = lambda n, c: c[0]
        mock_trial.suggest_float.return_value = 50.0

        with patch.object(objective, '_run_backtest') as mock_bt:
            mock_bt.return_value = {
                "win_rate": 0.65,
                "total_return": 0.25,
                "max_drawdown": 0.12,
            }

            result = objective(mock_trial)

            assert len(result) == 3
            assert result[0] == 0.65  # win_rate (maximize)
            assert result[1] == 0.25  # total_return (maximize)
            assert result[2] == 0.12  # max_drawdown (minimize, but returned as-is)


class TestMLPDirectionObjective:
    """Test the MLP Direction objective function."""

    def test_mlp_objective_returns_three_values(self):
        """MLP objective should return (win_rate, total_return, max_drawdown)."""
        objective = MLPDirectionObjective(
            asset="BTC",
            config_path="config/strategies/allocation.json",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        mock_trial = MagicMock()
        mock_trial.suggest_float.return_value = 0.5
        mock_trial.suggest_categorical.side_effect = lambda n, c: c[0]
        mock_trial.suggest_int.return_value = 5

        with patch.object(objective, '_run_backtest') as mock_bt:
            mock_bt.return_value = {
                "win_rate": 0.55,
                "total_return": 0.30,
                "max_drawdown": 0.15,
            }

            result = objective(mock_trial)

            assert len(result) == 3
            assert result[0] == 0.55
            assert result[1] == 0.30
            assert result[2] == 0.15

    def test_mlp_objective_fields(self):
        """MLP objective should store asset and config_path."""
        objective = MLPDirectionObjective(
            asset="ETH",
            config_path="/path/to/allocation.json",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert objective.asset == "ETH"
        assert objective.config_path == "/path/to/allocation.json"
        assert objective.start_date == "2024-01-01"
        assert objective.end_date == "2024-12-31"


class TestCreateMultiObjective:
    """Test Optuna study creation."""

    def test_create_study_with_three_objectives(self):
        """create_multi_objective should configure 3 objectives."""
        study = create_multi_objective("test_study")

        assert len(study.directions) == 3
        # win_rate: maximize, return: maximize, drawdown: minimize
        assert study.directions[0].name == "MAXIMIZE"
        assert study.directions[1].name == "MAXIMIZE"
        assert study.directions[2].name == "MINIMIZE"
