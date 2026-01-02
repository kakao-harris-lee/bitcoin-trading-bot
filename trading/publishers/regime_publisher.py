"""
Regime Publisher - Publishes market regime classifications to Redis

Runs RegimeRouter periodically and publishes to market:regime stream.
Strategies can subscribe and use as advisory information (not gating).
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional

import pandas as pd

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
                    # Classify
                    decision = self.router.recommend(df_day)

                    # Extract MFI/ADX from last row
                    df_day["mfi"] = self._calc_mfi(df_day)
                    df_day["adx"] = self._calc_adx(df_day)
                    mfi = float(df_day["mfi"].iloc[-1])
                    adx = float(df_day["adx"].iloc[-1])

                    # Publish
                    await self.publish_regime(
                        regime=decision.regime,
                        market_state=decision.market_state,
                        mfi=mfi,
                        adx=adx
                    )

                # Wait for next interval
                await asyncio.sleep(self.publish_interval)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Regime publish error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Retry after 1 minute

        self.logger.info("Regime publisher stopped")

    def _calc_mfi(self, df, period: int = 14):
        """Calculate MFI (copied from regime_router for independence)."""
        tp = (df["high"] + df["low"] + df["close"]) / 3.0
        raw_mf = tp * df["volume"]
        direction = tp.diff()
        pos_mf = raw_mf.where(direction > 0, 0.0)
        neg_mf = raw_mf.where(direction < 0, 0.0).abs()
        pos_sum = pos_mf.rolling(period).sum()
        neg_sum = neg_mf.rolling(period).sum()
        mf_ratio = pos_sum / neg_sum.replace(0, pd.NA)
        mfi = 100.0 - (100.0 / (1.0 + mf_ratio))
        return mfi.fillna(100.0)

    def _calc_adx(self, df, period: int = 14):
        """Calculate ADX (copied from regime_router for independence)."""
        high = df["high"]
        low = df["low"]
        close = df["close"]
        prev_close = close.shift(1)
        tr = pd.concat([
            (high - low),
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ], axis=1).max(axis=1)
        up_move = high.diff()
        down_move = -low.diff()
        plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
        minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
        atr = tr.rolling(period).mean()
        plus_di = 100.0 * (plus_dm.rolling(period).mean() / atr.replace(0, pd.NA))
        minus_di = 100.0 * (minus_dm.rolling(period).mean() / atr.replace(0, pd.NA))
        dx = 100.0 * (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA)
        adx = dx.rolling(period).mean()
        return adx.fillna(0.0)

    def stop(self):
        """Stop the publisher gracefully."""
        self.running = False
