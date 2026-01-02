"""
Premium Arbitrage Strategy

Kimchi premium arbitrage strategy.
Subscribes to both Upbit and Binance price streams.
Generates signals for arbitrage opportunities.
"""

from typing import Optional, List
from .base import StandaloneStrategy, Signal


class PremiumStrategy(StandaloneStrategy):
    """Kimchi premium arbitrage strategy."""

    def __init__(self, redis_client, config):
        super().__init__(redis_client, config)

        # Strategy config
        self.strategy_config = getattr(config, 'premium', {})
        if isinstance(self.strategy_config, dict):
            cfg = self.strategy_config
        else:
            cfg = {}

        # Price tracking for both exchanges
        self._upbit_price = 0.0
        self._binance_price = 0.0

        # State
        self._market_state = "UNKNOWN"
        self._current_regime = "UNKNOWN"

    @property
    def name(self) -> str:
        return "premium"

    @property
    def exchange(self) -> str:
        return "both"

    @property
    def subscribed_streams(self) -> List[str]:
        # Subscribes to BOTH exchanges
        return ["market:upbit:prices", "market:binance:prices"]

    async def on_regime(self, regime_data: dict) -> None:
        """Update regime info (advisory only)."""
        self._current_regime = regime_data.get("regime", "UNKNOWN")
        self._market_state = regime_data.get("market_state", "UNKNOWN")
        self.logger.debug(f"Regime update: {self._current_regime} ({self._market_state})")

    async def on_price(self, price_data: dict) -> Optional[Signal]:
        """Process price update and generate signal if conditions met."""
        exchange = price_data.get("exchange", "")
        price = price_data.get("price", 0)

        if exchange == "upbit":
            self._upbit_price = price
        elif exchange == "binance":
            self._binance_price = price

        # Calculate premium
        if self._upbit_price > 0 and self._binance_price > 0:
            premium = (self._upbit_price - self._binance_price) / self._binance_price * 100
            # TODO: Implement premium trading logic

        return None
