"""
Portfolio Hedge Manager - Drawdown-triggered bear short activation.

Monitors combined portfolio equity and toggles hedge mode (bear short)
when drawdown exceeds a threshold. Uses hysteresis to prevent oscillation.

State Machine:
    NORMAL → HEDGE  when drawdown >= activate_pct
    HEDGE  → NORMAL when drawdown <  deactivate_pct
"""

import logging
from dataclasses import dataclass, field
from typing import Literal

logger = logging.getLogger(__name__)


@dataclass
class HedgeState:
    """Snapshot of hedge manager state after each update."""

    mode: Literal["normal", "hedge"]
    drawdown_pct: float
    peak_equity: float
    current_equity: float
    hedge_activated_at: float  # drawdown % when last activated (0 if never)
    activation_count: int


class PortfolioHedgeManager:
    """Tracks portfolio equity and determines hedge activation state.

    Capital model:
        - MLP Direction gets 100% of spot capital (never reduced).
        - Bear Short uses a reserved futures hedge budget.
        - When hedge activates: bear_short opens shorts from reserved cash.
        - When hedge deactivates: bear_short closes positions.

    Args:
        initial_capital: Total starting capital for hedge budget calculation.
        activate_drawdown_pct: Activate hedge at this drawdown % (default 10).
        deactivate_drawdown_pct: Deactivate hedge below this drawdown % (default 5).
        hedge_budget_pct: Fraction of initial capital reserved for hedge (default 0.20).
    """

    def __init__(
        self,
        initial_capital: float = 10_000,
        activate_drawdown_pct: float = 10.0,
        deactivate_drawdown_pct: float = 5.0,
        hedge_budget_pct: float = 0.20,
    ):
        if deactivate_drawdown_pct >= activate_drawdown_pct:
            raise ValueError(
                f"deactivate_drawdown_pct ({deactivate_drawdown_pct}) must be "
                f"less than activate_drawdown_pct ({activate_drawdown_pct})"
            )

        self._activate_pct = activate_drawdown_pct
        self._deactivate_pct = deactivate_drawdown_pct
        self._hedge_budget_pct = hedge_budget_pct
        self._initial_capital = initial_capital

        self._peak_equity: float = 0.0
        self._current_equity: float = 0.0
        self._drawdown_pct: float = 0.0
        self._mode: Literal["normal", "hedge"] = "normal"
        self._hedge_activated_at: float = 0.0
        self._activation_count: int = 0

    def update(self, equity: float) -> HedgeState:
        """Update with current combined equity. Returns new state.

        Call this once per candle with:
            equity = spot_equity + futures_equity

        Args:
            equity: Current combined portfolio equity.

        Returns:
            HedgeState snapshot after this update.
        """
        self._current_equity = equity

        # Update peak (only on increase)
        if equity > self._peak_equity:
            self._peak_equity = equity

        # Calculate drawdown percentage
        if self._peak_equity > 0:
            self._drawdown_pct = (
                (self._peak_equity - equity) / self._peak_equity * 100
            )
        else:
            self._drawdown_pct = 0.0

        # State transitions with hysteresis
        old_mode = self._mode

        if self._mode == "normal" and self._drawdown_pct >= self._activate_pct:
            self._mode = "hedge"
            self._hedge_activated_at = self._drawdown_pct
            self._activation_count += 1
            logger.info(
                f"PortfolioHedgeManager: NORMAL→HEDGE "
                f"(drawdown={self._drawdown_pct:.1f}% >= {self._activate_pct:.1f}%, "
                f"activation #{self._activation_count})"
            )

        elif self._mode == "hedge" and self._drawdown_pct < self._deactivate_pct:
            self._mode = "normal"
            logger.info(
                f"PortfolioHedgeManager: HEDGE→NORMAL "
                f"(drawdown={self._drawdown_pct:.1f}% < {self._deactivate_pct:.1f}%)"
            )

        return HedgeState(
            mode=self._mode,
            drawdown_pct=self._drawdown_pct,
            peak_equity=self._peak_equity,
            current_equity=self._current_equity,
            hedge_activated_at=self._hedge_activated_at,
            activation_count=self._activation_count,
        )

    @property
    def hedge_active(self) -> bool:
        """Whether hedge mode is currently active."""
        return self._mode == "hedge"

    @property
    def hedge_budget(self) -> float:
        """Capital reserved for hedge (futures margin)."""
        return self._initial_capital * self._hedge_budget_pct

    @property
    def mode(self) -> str:
        return self._mode

    @property
    def drawdown_pct(self) -> float:
        return self._drawdown_pct

    @property
    def peak_equity(self) -> float:
        return self._peak_equity

    @property
    def activation_count(self) -> int:
        return self._activation_count

    def reset(self) -> None:
        """Reset all state (for new backtest run)."""
        self._peak_equity = 0.0
        self._current_equity = 0.0
        self._drawdown_pct = 0.0
        self._mode = "normal"
        self._hedge_activated_at = 0.0
        self._activation_count = 0
