"""Constraints and guardrails for optimization."""
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Any


@dataclass
class ConstraintsConfig:
    """Configuration for optimization constraints."""

    # Time budget
    max_trials: Optional[int] = None
    max_hours: Optional[float] = None

    # Risk guardrails
    max_drawdown: Optional[float] = None  # e.g., 0.30 for 30%
    min_trades: Optional[int] = None  # Reject if too few trades

    # Strategy locks: regime -> {entry: str, exit: str}
    strategy_locks: Dict[str, Dict[str, str]] = field(default_factory=dict)

    # Parameter overrides (force specific values)
    param_overrides: Dict[str, float] = field(default_factory=dict)


@dataclass
class MaxDrawdownPruner:
    """
    Early stopping pruner based on max drawdown.

    Signals trial pruning if intermediate drawdown exceeds threshold.
    """
    max_drawdown: float

    def should_prune(self, current_drawdown: float) -> bool:
        """
        Check if trial should be pruned.

        Args:
            current_drawdown: Current drawdown ratio (0.0-1.0)

        Returns:
            True if trial should be stopped early
        """
        return current_drawdown > self.max_drawdown


@dataclass
class StrategyLockConstraint:
    """
    Constraint that locks a specific component for a regime.

    Example: "Always use SidewaysEntry in BULL_STRONG"
    """
    regime: str
    entry: Optional[str] = None
    exit: Optional[str] = None

    def filter_choices(
        self,
        choices: List[str],
        component_type: str  # "entry" or "exit"
    ) -> List[str]:
        """
        Filter choices based on lock.

        Args:
            choices: Available component choices
            component_type: "entry" or "exit"

        Returns:
            Filtered list (single item if locked)
        """
        locked_value = getattr(self, component_type, None)
        if locked_value and locked_value in choices:
            return [locked_value]
        return choices

    def apply_to_search_space(
        self,
        search_space: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Apply lock to search space configuration.

        Args:
            search_space: Full search space dict

        Returns:
            Modified search space with locks applied
        """
        if self.regime not in search_space:
            return search_space

        regime_space = search_space[self.regime]

        if self.entry:
            regime_space["entry_choices"] = self.filter_choices(
                regime_space["entry_choices"], "entry"
            )

        if self.exit:
            regime_space["exit_choices"] = self.filter_choices(
                regime_space["exit_choices"], "exit"
            )

        return search_space


def apply_constraints(
    search_space: Dict[str, Any],
    constraints: ConstraintsConfig,
) -> Dict[str, Any]:
    """
    Apply all constraints to search space.

    Args:
        search_space: Original search space
        constraints: Constraints configuration

    Returns:
        Modified search space
    """
    modified = search_space.copy()

    # Apply strategy locks
    for regime, lock_config in constraints.strategy_locks.items():
        lock = StrategyLockConstraint(
            regime=regime,
            entry=lock_config.get("entry"),
            exit=lock_config.get("exit"),
        )
        modified = lock.apply_to_search_space(modified)

    return modified
