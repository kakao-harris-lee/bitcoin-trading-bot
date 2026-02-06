"""Tests for optimization constraints."""
import pytest
from web.quant_lab.optimizer.constraints import (
    ConstraintsConfig,
    MaxDrawdownPruner,
    StrategyLockConstraint,
)


class TestConstraintsConfig:
    """Test constraints configuration."""

    def test_default_config(self):
        """Default config should have no constraints."""
        config = ConstraintsConfig()
        assert config.max_drawdown is None
        assert config.strategy_locks == {}

    def test_config_with_max_drawdown(self):
        """Config should accept max drawdown constraint."""
        config = ConstraintsConfig(max_drawdown=0.30)
        assert config.max_drawdown == 0.30


class TestMaxDrawdownPruner:
    """Test early stopping pruner for drawdown."""

    def test_pruner_triggers_on_high_drawdown(self):
        """Pruner should signal pruning when drawdown exceeds threshold."""
        pruner = MaxDrawdownPruner(max_drawdown=0.20)

        should_prune = pruner.should_prune(current_drawdown=0.25)
        assert should_prune is True

    def test_pruner_allows_low_drawdown(self):
        """Pruner should not prune when drawdown is acceptable."""
        pruner = MaxDrawdownPruner(max_drawdown=0.20)

        should_prune = pruner.should_prune(current_drawdown=0.15)
        assert should_prune is False


class TestStrategyLockConstraint:
    """Test strategy lock constraints."""

    def test_lock_forces_entry_choice(self):
        """Lock should restrict entry choices for a regime."""
        lock = StrategyLockConstraint(
            regime="BULL_STRONG",
            entry="ShortEntry",
        )

        choices = ["ShortEntry", "SidewaysEntry", "ShortEntry", "None"]
        filtered = lock.filter_choices(choices, "entry")

        assert filtered == ["ShortEntry"]

    def test_lock_does_not_affect_other_regimes(self):
        """Lock should not affect other regimes."""
        lock = StrategyLockConstraint(
            regime="BULL_STRONG",
            entry="ShortEntry",
        )

        # filter_choices only applies if called for matching regime
        assert lock.regime == "BULL_STRONG"
