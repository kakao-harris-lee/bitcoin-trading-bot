"""Tests for V35 objective function."""
import pytest
from unittest.mock import patch, MagicMock
import optuna

from web.quant_lab.optimizer.v35_objective import (
    calculate_growth_score,
    GrowthObjective,
    create_v35_study,
)


class TestCalculateGrowthScore:
    """Tests for growth score calculation."""

    def test_good_return_low_mdd(self):
        """High return with low MDD gets high score."""
        score = calculate_growth_score(
            total_return=1.20,  # 120%
            max_drawdown=0.18,  # 18%
            sharpe_ratio=1.5,
        )
        # 1.20 + 0.05 sharpe bonus = 1.25
        assert score > 1.20
        assert abs(score - 1.25) < 0.01

    def test_high_mdd_penalty(self):
        """MDD above 25% incurs penalty."""
        score = calculate_growth_score(
            total_return=1.50,
            max_drawdown=0.28,  # 28% > 25%
            sharpe_ratio=1.0,
        )
        # 1.50 - 0.06 penalty = 1.44
        assert score < 1.50
        assert abs(score - 1.44) < 0.01

    def test_sharpe_below_one_no_bonus(self):
        """Sharpe below 1.0 gives no bonus."""
        score = calculate_growth_score(
            total_return=1.00,
            max_drawdown=0.15,
            sharpe_ratio=0.8,
        )
        assert score == 1.00  # No bonus, no penalty

    def test_sharpe_above_one_gives_bonus(self):
        """Sharpe above 1.0 gives 10% bonus per point."""
        score = calculate_growth_score(
            total_return=1.00,
            max_drawdown=0.10,
            sharpe_ratio=2.0,
        )
        # 1.00 + 0.10 (for sharpe 2.0 - 1.0 = 1.0 * 0.1)
        assert abs(score - 1.10) < 0.01

    def test_extreme_mdd_pruned(self):
        """MDD above 30% raises TrialPruned."""
        with pytest.raises(optuna.TrialPruned, match="exceeded hard limit"):
            calculate_growth_score(
                total_return=2.0,
                max_drawdown=0.35,  # 35% > 30%
                sharpe_ratio=0.5,
            )

    def test_custom_mdd_limits(self):
        """Custom MDD limits are respected."""
        # With 20% soft limit, 0.22 MDD incurs penalty
        score = calculate_growth_score(
            total_return=1.00,
            max_drawdown=0.22,
            sharpe_ratio=1.0,
            mdd_soft_limit=0.20,
            mdd_hard_limit=0.25,
        )
        assert score < 1.00  # Penalty applied

        # With 25% hard limit, 0.26 MDD raises
        with pytest.raises(optuna.TrialPruned):
            calculate_growth_score(
                total_return=1.00,
                max_drawdown=0.26,
                sharpe_ratio=1.0,
                mdd_soft_limit=0.20,
                mdd_hard_limit=0.25,
            )

    def test_zero_return_zero_mdd(self):
        """Edge case: zero return, zero MDD."""
        score = calculate_growth_score(
            total_return=0.0,
            max_drawdown=0.0,
            sharpe_ratio=0.0,
        )
        assert score == 0.0

    def test_negative_return(self):
        """Negative return gives negative score."""
        score = calculate_growth_score(
            total_return=-0.20,  # -20%
            max_drawdown=0.30,  # At hard limit
            sharpe_ratio=0.0,
        )
        # -0.20 - 0.10 penalty = -0.30
        assert score < 0


class TestGrowthObjective:
    """Tests for GrowthObjective class."""

    def test_objective_init(self):
        """Objective initializes with correct defaults."""
        obj = GrowthObjective(
            strategy_name="v35_long_v2",
            data_path="/path/to/data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )
        assert obj.strategy_name == "v35_long_v2"
        assert obj.capital == 10_000.0
        assert obj.symbol == "BTC"
        assert obj.mdd_soft_limit == 0.25
        assert obj.mdd_hard_limit == 0.30

    def test_objective_custom_capital(self):
        """Objective respects custom capital."""
        obj = GrowthObjective(
            strategy_name="v35_long_v2",
            data_path="/path/to/data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
            capital=5_000.0,
        )
        assert obj.capital == 5_000.0

    @patch("web.quant_lab.optimizer.v35_objective.GrowthObjective._run_backtest")
    @patch("web.quant_lab.optimizer.v35_objective.sample_v35_config")
    def test_objective_call_returns_score(self, mock_sample, mock_backtest):
        """Objective __call__ returns growth score."""
        mock_sample.return_value = {"stop_loss_pct": 5.0}
        mock_backtest.return_value = {
            "total_return": 1.20,
            "max_drawdown": 0.15,
            "sharpe_ratio": 1.5,
            "win_rate": 0.55,
            "total_trades": 50,
            "profit_factor": 2.0,
        }

        obj = GrowthObjective(
            strategy_name="v35_long_v2",
            data_path="/path/to/data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        study = optuna.create_study()
        trial = study.ask()

        score = obj(trial)

        assert score > 1.20  # Has sharpe bonus
        mock_sample.assert_called_once()
        mock_backtest.assert_called_once()

    @patch("web.quant_lab.optimizer.v35_objective.GrowthObjective._run_backtest")
    @patch("web.quant_lab.optimizer.v35_objective.sample_v35_config")
    def test_objective_prunes_on_backtest_error(self, mock_sample, mock_backtest):
        """Objective prunes trial on backtest error."""
        mock_sample.return_value = {"stop_loss_pct": 5.0}
        mock_backtest.side_effect = ValueError("Backtest failed")

        obj = GrowthObjective(
            strategy_name="v35_long_v2",
            data_path="/path/to/data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        study = optuna.create_study()
        trial = study.ask()

        with pytest.raises(optuna.TrialPruned, match="Backtest error"):
            obj(trial)

    @patch("web.quant_lab.optimizer.v35_objective.GrowthObjective._run_backtest")
    @patch("web.quant_lab.optimizer.v35_objective.sample_v35_config")
    def test_objective_prunes_on_high_mdd(self, mock_sample, mock_backtest):
        """Objective prunes trial when MDD exceeds limit."""
        mock_sample.return_value = {"stop_loss_pct": 5.0}
        mock_backtest.return_value = {
            "total_return": 2.00,
            "max_drawdown": 0.35,  # 35% > 30% hard limit
            "sharpe_ratio": 1.0,
            "win_rate": 0.50,
            "total_trades": 30,
            "profit_factor": 1.5,
        }

        obj = GrowthObjective(
            strategy_name="v35_long_v2",
            data_path="/path/to/data.db",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        study = optuna.create_study()
        trial = study.ask()

        with pytest.raises(optuna.TrialPruned, match="exceeded hard limit"):
            obj(trial)


class TestCreateV35Study:
    """Tests for create_v35_study function."""

    def test_creates_study_with_correct_direction(self):
        """Study is created with maximize direction."""
        study = create_v35_study(
            strategy_name="v35_long_v2",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert study.direction == optuna.study.StudyDirection.MAXIMIZE

    def test_study_name_includes_strategy(self):
        """Study name includes strategy and dates."""
        study = create_v35_study(
            strategy_name="v35_long_v2",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert "v35_long_v2" in study.study_name
        assert "2024-01-01" in study.study_name
        assert "2024-12-31" in study.study_name

    def test_uses_tpe_sampler(self):
        """Study uses TPE sampler."""
        study = create_v35_study(
            strategy_name="v35_long_v2",
            start_date="2024-01-01",
            end_date="2024-12-31",
        )

        assert isinstance(study.sampler, optuna.samplers.TPESampler)

    def test_sampler_accepts_seed(self):
        """Study sampler accepts seed parameter without error."""
        # Just verify no exception is raised when seed is provided
        study = create_v35_study(
            strategy_name="v35_long_v2",
            start_date="2024-01-01",
            end_date="2024-12-31",
            sampler_seed=42,
        )

        # Should be a TPE sampler
        assert isinstance(study.sampler, optuna.samplers.TPESampler)
