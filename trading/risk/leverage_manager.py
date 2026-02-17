"""
Leverage Manager - Risk-adjusted leverage based on drawdown.

Dynamically adjusts leverage based on account drawdown from peak equity.
Protects capital during losing periods by reducing position sizes.
"""

import logging
from dataclasses import dataclass
from datetime import datetime, date
from typing import Optional

import redis

logger = logging.getLogger(__name__)


@dataclass
class LeverageTier:
    """Leverage tier definition."""
    name: str
    drawdown_max: float  # Maximum drawdown for this tier (exclusive)
    leverage: int


# Default leverage tiers based on drawdown
DEFAULT_TIERS = [
    LeverageTier("full", 0.05, 5),      # 0-5% DD → 5x
    LeverageTier("reduced", 0.10, 3),   # 5-10% DD → 3x
    LeverageTier("cautious", 0.15, 2),  # 10-15% DD → 2x
    LeverageTier("minimal", 0.20, 1),   # 15-20% DD → 1x
    LeverageTier("halted", 1.00, 0),    # >20% DD → stop
]

# Daily loss limit (fraction of equity)
DAILY_LOSS_LIMIT = 0.05  # 5% daily loss → halt


class LeverageManager:
    """Manages risk-adjusted leverage based on account drawdown.

    Tracks peak equity and calculates drawdown to determine appropriate
    leverage for new positions. Persists state to Redis for recovery.

    Usage:
        manager = LeverageManager(redis_url)
        await manager.initialize(initial_equity=10000)

        # Before opening position
        leverage = await manager.get_allowed_leverage()
        if leverage == 0:
            # Trading halted, don't open position

        # After closing position
        await manager.update_equity(pnl=150.0)
    """

    REDIS_KEY = "leverage:state"

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379",
        tiers: list[LeverageTier] = None,
        daily_loss_limit: float = DAILY_LOSS_LIMIT,
    ):
        """Initialize leverage manager.

        Args:
            redis_url: Redis connection URL.
            tiers: Custom leverage tiers. Uses DEFAULT_TIERS if not provided.
            daily_loss_limit: Daily loss limit as fraction (0.05 = 5%).
        """
        self._redis_url = redis_url
        self._redis: Optional[redis.Redis] = None
        self.tiers = tiers or DEFAULT_TIERS
        self.daily_loss_limit = daily_loss_limit

        # State (loaded from Redis)
        self.peak_equity: float = 0.0
        self.current_equity: float = 0.0
        self.daily_starting_equity: float = 0.0
        self.daily_pnl: float = 0.0
        self.last_daily_reset: date = date.today()
        self.current_tier: LeverageTier = self.tiers[0]

    def _get_redis(self) -> redis.Redis:
        """Get Redis connection (lazy initialization)."""
        if self._redis is None:
            self._redis = redis.from_url(self._redis_url, decode_responses=True)
        return self._redis

    async def initialize(self, initial_equity: float = None) -> None:
        """Initialize or load state from Redis.

        Args:
            initial_equity: Starting equity if no state exists.
        """
        r = self._get_redis()
        state = r.hgetall(self.REDIS_KEY)

        if state:
            # Load existing state
            self.peak_equity = float(state.get("peak_equity", 0))
            self.current_equity = float(state.get("current_equity", 0))
            self.daily_starting_equity = float(state.get("daily_starting_equity", 0))
            self.daily_pnl = float(state.get("daily_pnl", 0))
            self.last_daily_reset = date.fromisoformat(
                state.get("last_daily_reset", date.today().isoformat())
            )

            # Check for daily reset
            self._check_daily_reset()

            # Calculate current tier
            self._update_tier()

            logger.info(
                "LeverageManager loaded: equity=$%s, peak=$%s, drawdown=%.1f%%, "
                "tier=%s (%dx)",
                format(self.current_equity, ",.2f"),
                format(self.peak_equity, ",.2f"),
                self.get_drawdown_pct(),
                self.current_tier.name,
                self.current_tier.leverage,
            )
        elif initial_equity:
            # Initialize fresh state
            self.peak_equity = initial_equity
            self.current_equity = initial_equity
            self.daily_starting_equity = initial_equity
            self.daily_pnl = 0.0
            self.last_daily_reset = date.today()
            self.current_tier = self.tiers[0]

            await self._save_state()
            logger.info(
                "LeverageManager initialized with equity=$%s",
                format(initial_equity, ",.2f"),
            )
        else:
            logger.warning("LeverageManager: No state found and no initial equity provided")

    def _check_daily_reset(self) -> None:
        """Reset daily P&L if new day."""
        today = date.today()
        if self.last_daily_reset < today:
            logger.info(
                "LeverageManager: Daily reset (previous day P&L: $%s)",
                format(self.daily_pnl, ",.2f"),
            )
            self.daily_starting_equity = self.current_equity
            self.daily_pnl = 0.0
            self.last_daily_reset = today

    def _update_tier(self) -> None:
        """Update current leverage tier based on drawdown."""
        drawdown = self.get_drawdown()

        old_tier = self.current_tier

        # Find appropriate tier
        for tier in self.tiers:
            if drawdown < tier.drawdown_max:
                self.current_tier = tier
                break
        else:
            # Beyond all tiers - use last (halted)
            self.current_tier = self.tiers[-1]

        if old_tier != self.current_tier:
            logger.warning(
                "LeverageManager: Tier changed %s->%s (drawdown=%.1f%%, leverage=%dx)",
                old_tier.name,
                self.current_tier.name,
                drawdown * 100,
                self.current_tier.leverage,
            )

    def get_drawdown(self) -> float:
        """Get current drawdown as fraction (0.0 to 1.0)."""
        if self.peak_equity <= 0:
            return 0.0
        return max(0, (self.peak_equity - self.current_equity) / self.peak_equity)

    def get_drawdown_pct(self) -> float:
        """Get current drawdown as percentage."""
        return self.get_drawdown() * 100

    def get_daily_loss_pct(self) -> float:
        """Get daily loss as percentage of starting equity."""
        if self.daily_starting_equity <= 0:
            return 0.0
        return (self.daily_pnl / self.daily_starting_equity) * 100

    async def get_allowed_leverage(self) -> int:
        """Get maximum allowed leverage for new positions.

        Returns:
            Allowed leverage (0 = trading halted).
        """
        self._check_daily_reset()

        # Check daily loss limit
        daily_loss_pct = abs(min(0, self.daily_pnl)) / self.daily_starting_equity \
            if self.daily_starting_equity > 0 else 0

        if daily_loss_pct >= self.daily_loss_limit:
            logger.warning(
                "LeverageManager: Trading halted - daily loss %.1f%% >= limit %.1f%%",
                daily_loss_pct * 100,
                self.daily_loss_limit * 100,
            )
            return 0

        # Return tier leverage
        return self.current_tier.leverage

    async def update_equity(self, pnl: float) -> None:
        """Update equity after a trade closes.

        Args:
            pnl: Profit/loss from the closed trade.
        """
        self._check_daily_reset()

        old_equity = self.current_equity
        self.current_equity += pnl
        self.daily_pnl += pnl

        # Update peak if new high
        if self.current_equity > self.peak_equity:
            old_peak = self.peak_equity
            self.peak_equity = self.current_equity
            logger.info(
                "LeverageManager: New peak equity $%s (+$%s)",
                format(self.peak_equity, ",.2f"),
                format(self.peak_equity - old_peak, ",.2f"),
            )

        # Update tier
        self._update_tier()

        # Log update
        logger.info(
            "LeverageManager: Equity $%s -> $%s (P&L: %s%s), drawdown=%.1f%%, tier=%s (%dx)",
            format(old_equity, ",.2f"),
            format(self.current_equity, ",.2f"),
            "+" if pnl >= 0 else "",
            format(pnl, ",.2f"),
            self.get_drawdown_pct(),
            self.current_tier.name,
            self.current_tier.leverage,
        )

        await self._save_state()

    async def set_equity(self, equity: float) -> None:
        """Set current equity directly (for syncing with exchange).

        Args:
            equity: Current account equity.
        """
        self.current_equity = equity

        if equity > self.peak_equity:
            self.peak_equity = equity

        self._update_tier()
        await self._save_state()

        logger.info(
            "LeverageManager: Equity set to $%s, drawdown=%.1f%%, tier=%s",
            format(equity, ",.2f"),
            self.get_drawdown_pct(),
            self.current_tier.name,
        )

    async def _save_state(self) -> None:
        """Save state to Redis."""
        r = self._get_redis()
        r.hset(self.REDIS_KEY, mapping={
            "peak_equity": str(self.peak_equity),
            "current_equity": str(self.current_equity),
            "daily_starting_equity": str(self.daily_starting_equity),
            "daily_pnl": str(self.daily_pnl),
            "last_daily_reset": self.last_daily_reset.isoformat(),
            "current_tier": self.current_tier.name,
            "current_leverage": str(self.current_tier.leverage),
            "drawdown_pct": str(self.get_drawdown_pct()),
            "last_updated": datetime.now().isoformat(),
        })

    def get_state(self) -> dict:
        """Get current state as dict (for API/dashboard)."""
        return {
            "peak_equity": self.peak_equity,
            "current_equity": self.current_equity,
            "drawdown_pct": self.get_drawdown_pct(),
            "daily_pnl": self.daily_pnl,
            "daily_loss_pct": self.get_daily_loss_pct(),
            "tier": self.current_tier.name,
            "leverage": self.current_tier.leverage,
            "daily_loss_limit_pct": self.daily_loss_limit * 100,
            "tiers": [
                {
                    "name": t.name,
                    "drawdown_max_pct": t.drawdown_max * 100,
                    "leverage": t.leverage,
                    "active": t == self.current_tier,
                }
                for t in self.tiers
            ],
        }


# Singleton state
_LEVERAGE_MANAGER_STATE: dict[str, Optional[LeverageManager]] = {"instance": None}


def get_leverage_manager(redis_url: str = None) -> LeverageManager:
    """Get or create singleton LeverageManager instance."""
    manager = _LEVERAGE_MANAGER_STATE["instance"]
    if manager is None:
        manager = LeverageManager(
            redis_url=redis_url or "redis://localhost:6379"
        )
        _LEVERAGE_MANAGER_STATE["instance"] = manager
    return manager
