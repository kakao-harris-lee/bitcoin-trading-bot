"""
FundingTracker - Fetches and applies Binance funding rates.

Binance perpetual futures have funding payments at 00:00, 08:00, 16:00 UTC.
Positive rate: longs pay shorts.
Negative rate: shorts pay longs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


@dataclass
class FundingRate:
    """Current funding rate information."""

    symbol: str
    rate: float               # e.g., 0.0001 = 0.01%
    next_funding_time: datetime


class FundingTracker:
    """Tracks and applies funding rates to futures positions."""

    # Funding times in UTC
    FUNDING_HOURS_UTC = [0, 8, 16]

    def __init__(self, binance_client=None):
        """Initialize FundingTracker.

        Args:
            binance_client: Optional BinanceClient for fetching live rates.
        """
        self._client = binance_client
        self._rate_cache: dict[str, FundingRate] = {}

    def calculate_funding_payment(
        self,
        position_value: float,
        rate: float,
        side: str,
    ) -> float:
        """Calculate funding payment for a position.

        Args:
            position_value: Position notional value in USDT.
            rate: Funding rate as decimal (e.g., 0.0001 for 0.01%).
            side: "buy" for long, "sell" for short.

        Returns:
            Payment amount (negative = you pay, positive = you receive).
        """
        # Funding payment formula:
        # Payment = Position Value × Funding Rate
        #
        # If rate > 0: longs pay shorts
        # If rate < 0: shorts pay longs

        if side == "buy":  # Long
            # Long pays when rate is positive (negative payment)
            # Long receives when rate is negative (positive payment)
            return -position_value * rate
        else:  # Short
            # Short receives when rate is positive (positive payment)
            # Short pays when rate is negative (negative payment)
            return position_value * rate

    async def get_funding_rate(self, symbol: str) -> Optional[FundingRate]:
        """Fetch current funding rate from Binance.

        Args:
            symbol: Trading symbol (e.g., "BTC" or "BTCUSDT").

        Returns:
            FundingRate or None if fetch fails.
        """
        if not self._client:
            logger.warning("No Binance client configured for funding rates")
            return None

        # Normalize symbol
        pair = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol

        try:
            # GET /fapi/v1/premiumIndex
            data = await self._client._futures_client.futures_mark_price(symbol=pair)

            rate = float(data.get("lastFundingRate", 0))
            next_time = int(data.get("nextFundingTime", 0))

            funding_rate = FundingRate(
                symbol=symbol,
                rate=rate,
                next_funding_time=datetime.fromtimestamp(next_time / 1000, tz=timezone.utc),
            )

            # Cache it
            self._rate_cache[symbol] = funding_rate

            logger.info(
                f"Funding rate for {symbol}: {rate*100:.4f}%, "
                f"next: {funding_rate.next_funding_time}"
            )

            return funding_rate

        except Exception as e:
            logger.error(f"Failed to fetch funding rate for {symbol}: {e}")
            # Return cached rate if available
            return self._rate_cache.get(symbol)

    def get_next_funding_time(self) -> datetime:
        """Get the next funding time in UTC.

        Returns:
            Next funding datetime.
        """
        now = datetime.now(timezone.utc)
        current_hour = now.hour

        # Find next funding hour
        for hour in self.FUNDING_HOURS_UTC:
            if hour > current_hour:
                return now.replace(hour=hour, minute=0, second=0, microsecond=0)

        # Next funding is tomorrow at 00:00 UTC
        tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0)
        return tomorrow + timedelta(days=1)

    def is_funding_time(self) -> bool:
        """Check if current time is within a funding window.

        Returns:
            True if within 1 minute of a funding time.
        """
        now = datetime.now(timezone.utc)
        return now.hour in self.FUNDING_HOURS_UTC and now.minute < 1
