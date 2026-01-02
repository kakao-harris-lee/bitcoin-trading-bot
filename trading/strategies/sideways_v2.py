"""
SIDEWAYS_V2 Strategy - Range Trading

Sideways market range trading strategy for Upbit.
Generates signals in ALL market states (no internal gating).
Uses regime info for position sizing only.
"""

from typing import Optional, List
from .base import StandaloneStrategy, Signal


class SidewaysV2Strategy(StandaloneStrategy):
    """Sideways market range trading strategy."""

    def __init__(self, redis_client, config):
        super().__init__(redis_client, config)

        # Strategy config
        self.strategy_config = getattr(config, 'sideways_v2', {})
        if isinstance(self.strategy_config, dict):
            cfg = self.strategy_config
        else:
            cfg = {}

        # State
        self._market_state = "UNKNOWN"
        self._current_regime = "UNKNOWN"
        self._indicators = {}

    @property
    def name(self) -> str:
        return "sideways_v2"

    @property
    def exchange(self) -> str:
        return "upbit"

    @property
    def subscribed_streams(self) -> List[str]:
        return ["market:upbit:prices", "market:regime"]

    async def on_regime(self, regime_data: dict) -> None:
        """Update regime info (advisory only)."""
        self._current_regime = regime_data.get("regime", "UNKNOWN")
        self._market_state = regime_data.get("market_state", "UNKNOWN")
        self.logger.debug(f"Regime update: {self._current_regime} ({self._market_state})")

    async def on_price(self, price_data: dict) -> Optional[Signal]:
        """Process price update and generate signal if conditions met.

        TODO: Implement from trading/strategy/sideways_v2.py
        """
        # Skeleton - to be implemented
        return None
