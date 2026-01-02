"""
SHORT_V1 Strategy - Binance Futures Short

Binance short strategy for BEAR markets.
Generates signals in ALL market states (no internal gating).
Uses regime info for position sizing only.
"""

from typing import Optional, List
from .base import StandaloneStrategy, Signal


class ShortV1Strategy(StandaloneStrategy):
    """Binance short strategy for BEAR markets."""

    def __init__(self, redis_client, config):
        super().__init__(redis_client, config)

        # Strategy config
        self.strategy_config = getattr(config, 'short_v1', {})
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
        return "short_v1"

    @property
    def exchange(self) -> str:
        return "binance"

    @property
    def subscribed_streams(self) -> List[str]:
        return ["market:binance:prices", "market:regime"]

    async def on_regime(self, regime_data: dict) -> None:
        """Update regime info (advisory only)."""
        self._current_regime = regime_data.get("regime", "UNKNOWN")
        self._market_state = regime_data.get("market_state", "UNKNOWN")
        self.logger.debug(f"Regime update: {self._current_regime} ({self._market_state})")

    async def on_price(self, price_data: dict) -> Optional[Signal]:
        """Process price update and generate signal if conditions met.

        TODO: Implement short logic from trading/strategy/short_v1.py
        """
        # Skeleton - to be implemented
        return None
