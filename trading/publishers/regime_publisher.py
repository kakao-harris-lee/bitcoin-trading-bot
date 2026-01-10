"""
Regime Publisher - Publishes market regime classifications to Redis

Runs RegimeRouter periodically and publishes to market:regime stream.
Strategies can subscribe and use as advisory information (not gating).
"""

import asyncio
import logging
from datetime import datetime
from typing import Optional

from trading.strategy.regime_router import RegimeRouter

logger = logging.getLogger(__name__)


class RegimePublisher:
    """Publishes market regime classifications to Redis stream."""

    def __init__(self, redis_client, config):
        """
        Args:
            redis_client: RedisClient instance
            config: Configuration with router settings
        """
        self.redis = redis_client
        self.config = config
        self.running = True
        self.logger = logging.getLogger("regime_publisher")

        # Initialize router
        router_config = getattr(config, 'router', {})
        if isinstance(router_config, dict):
            self.router = RegimeRouter(**router_config)
        else:
            self.router = RegimeRouter()

        # Publish interval (default: every hour)
        self.publish_interval = getattr(config, 'regime_publish_interval', 3600)

        self._last_regime = None
        self._last_publish_time = None

    @property
    def stream_name(self) -> str:
        return "market:regime"

    async def publish_regime(
        self,
        regime: str,
        market_state: str,
        mfi: float,
        adx: float
    ) -> str:
        """Publish regime update to Redis stream."""
        data = {
            "regime": regime,
            "market_state": market_state,
            "mfi": mfi,
            "adx": adx,
            "timestamp": datetime.now().isoformat(),
        }

        message_id = await self.redis.publish(self.stream_name, data)

        self._last_regime = regime
        self._last_publish_time = datetime.now()
        self.logger.info(f"Published regime: {regime} ({market_state}) MFI={mfi:.1f} ADX={adx:.1f}")

        return message_id

    async def run(self):
        """Main loop - periodically classify and publish regime."""
        self.logger.info("Starting regime publisher...")

        while self.running:
            try:
                # Get daily data
                df_day = self.router.get_recent_daily_df()

                if df_day is not None and len(df_day) > 0:
                    # Classify - RegimeContext includes mfi/adx values
                    context = self.router.recommend(df_day)

                    # Publish using values from RegimeContext
                    await self.publish_regime(
                        regime=context.regime,
                        market_state=context.market_state,
                        mfi=context.mfi,
                        adx=context.adx
                    )

                # Wait for next interval
                await asyncio.sleep(self.publish_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Regime publish error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Retry after 1 minute

        self.logger.info("Regime publisher stopped")

    def stop(self):
        """Stop the publisher gracefully."""
        self.running = False
