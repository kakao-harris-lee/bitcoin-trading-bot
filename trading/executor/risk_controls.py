"""
Risk Controls for Trade Executor

Centralized risk management:
- Kill switch (file-based, via Telegram)
- Daily loss limit
- Position size validation
"""

import logging
from datetime import date
from typing import Dict, Any

from trading.risk.risk_controls import (
    kill_switch_active,
    set_kill_switch as file_set_kill_switch,
)

logger = logging.getLogger(__name__)

# Default kill switch file path
DEFAULT_KILL_SWITCH_FILE = "analysis/KILL_SWITCH"


class RiskControls:
    """Centralized risk controls for the executor."""

    def __init__(self, config):
        self.config = config
        self.logger = logging.getLogger("risk_controls")

        # Kill switch file path (file-based for persistence and Telegram integration)
        self.kill_switch_file = getattr(
            config, 'kill_switch_file', DEFAULT_KILL_SWITCH_FILE
        )

        # Daily P&L tracking
        self._daily_pnl: Dict[str, float] = {}  # strategy -> pnl
        self._current_date = date.today()

        # Limits from config
        self.daily_loss_limit = getattr(config, 'daily_loss_limit_pct', 5.0)  # 5%
        self.max_position_size = getattr(config, 'max_position_size', 1.0)

    @property
    def kill_switch_on(self) -> bool:
        """Check if kill switch is active (file-based)."""
        return kill_switch_active(self.kill_switch_file)

    def set_kill_switch(self, on: bool):
        """Set kill switch state (file-based for Telegram integration)."""
        file_set_kill_switch(self.kill_switch_file, on)
        self.logger.warning(
            "Kill switch %s (%s)",
            "ON" if on else "OFF",
            self.kill_switch_file,
        )

    def allow_trade(self, strategy: str, signal: Dict[str, Any]) -> bool:
        """Check if trade is allowed based on risk controls.

        Args:
            strategy: Strategy name
            signal: Signal dict with action, price, size, etc.

        Returns:
            True if trade allowed, False otherwise
        """
        # Reset daily tracking if new day
        if date.today() != self._current_date:
            self._daily_pnl = {}
            self._current_date = date.today()

        # Kill switch check (file-based)
        if self.kill_switch_on:
            self.logger.warning("Trade blocked: kill switch ON (%s)", strategy)
            return False

        # Daily loss check
        total_daily_loss = sum(self._daily_pnl.values())
        if total_daily_loss <= -self.daily_loss_limit:
            self.logger.warning(
                "Trade blocked: daily loss limit (%.2f%% <= -%.2f%%)",
                total_daily_loss,
                self.daily_loss_limit,
            )
            return False

        # Position size check
        size = signal.get("size", 0)
        if size > self.max_position_size:
            self.logger.warning(
                "Trade blocked: position size %s > max %s",
                size,
                self.max_position_size,
            )
            return False

        return True

    def record_pnl(self, strategy: str, pnl_pct: float):
        """Record P&L for a closed trade."""
        current = self._daily_pnl.get(strategy, 0.0)
        self._daily_pnl[strategy] = current + pnl_pct
        self.logger.info(
            "Recorded P&L for %s: %+.2f%% (daily: %+.2f%%)",
            strategy,
            pnl_pct,
            self._daily_pnl[strategy],
        )

    def get_daily_pnl(self) -> Dict[str, float]:
        """Get current daily P&L by strategy."""
        return self._daily_pnl.copy()
