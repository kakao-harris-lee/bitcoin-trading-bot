"""
PriceHub - Central price cache with subscriber notification.

Receives real-time prices from FeedHandler and notifies subscribers
on significant price changes (>0.1%).
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class PriceEvent:
    """Event emitted when price changes significantly."""
    exchange: str
    price: float
    change_pct: float
    timestamp: datetime


@dataclass
class PremiumInfo:
    """Kimchi Premium calculation result."""
    premium_pct: float
    upbit_krw: float
    upbit_usd: float
    binance_usd: float
    usd_krw_rate: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class PriceMessage:
    """Price message from WebSocket."""
    exchange: str
    symbol: str
    price: float
    volume: float
    timestamp: datetime
    ohlcv: Optional[Dict[str, float]] = None


class PriceHub:
    """
    Central price cache with real-time updates and premium calculation.

    Thread-safe with asyncio - all updates happen in event loop.
    Notifies subscribers only on significant price changes (>0.1%).
    """

    def __init__(
        self,
        price_change_threshold: float = 0.001,  # 0.1%
        default_fx_rate: float = 1450.0,
    ):
        """
        Args:
            price_change_threshold: Minimum price change to trigger notification
            default_fx_rate: Default USD/KRW rate (updated by FXRateCache)
        """
        self._prices: Dict[str, PriceMessage] = {}
        self._last_notified_prices: Dict[str, float] = {}
        self._fx_rate: float = default_fx_rate
        self._cached_premium: Optional[PremiumInfo] = None
        self._subscribers: List[asyncio.Queue] = []
        self._subscriber_failures: Dict[int, int] = {}  # queue id -> consecutive failures
        self._max_failures = 10  # Remove after 10 consecutive failures
        self._price_change_threshold = price_change_threshold
        self._started_at = datetime.now()

        # Statistics
        self._update_count: Dict[str, int] = {"upbit": 0, "binance": 0}
        self._notification_count: int = 0

    async def update_price(self, exchange: str, msg: PriceMessage) -> bool:
        """
        Update price from FeedHandler.

        Args:
            exchange: "upbit" or "binance"
            msg: Price message from WebSocket

        Returns:
            True if subscribers were notified (significant change)
        """
        old_price = self._last_notified_prices.get(exchange, 0)
        new_price = msg.price

        # Store current price
        self._prices[exchange] = msg
        self._update_count[exchange] = self._update_count.get(exchange, 0) + 1

        # Recalculate premium
        self._recalculate_premium()

        # Check if change is significant
        if old_price > 0:
            change_pct = abs(new_price - old_price) / old_price
            if change_pct >= self._price_change_threshold:
                self._last_notified_prices[exchange] = new_price
                await self._notify_subscribers(exchange, new_price, change_pct)
                return True
        else:
            # First price - always notify
            self._last_notified_prices[exchange] = new_price
            await self._notify_subscribers(exchange, new_price, 0.0)
            return True

        return False

    def update_fx_rate(self, rate: float) -> None:
        """Update USD/KRW exchange rate (called by FXRateCache)."""
        self._fx_rate = rate
        self._recalculate_premium()

    def _recalculate_premium(self) -> None:
        """Recalculate Kimchi Premium from current prices."""
        upbit_msg = self._prices.get("upbit")
        binance_msg = self._prices.get("binance")

        if not upbit_msg or not binance_msg:
            return

        upbit_krw = upbit_msg.price
        binance_usd = binance_msg.price

        if binance_usd <= 0 or self._fx_rate <= 0:
            return

        # Convert Upbit KRW to USD
        upbit_usd = upbit_krw / self._fx_rate

        # Premium = (Upbit - Binance) / Binance * 100
        premium_pct = ((upbit_usd - binance_usd) / binance_usd) * 100

        self._cached_premium = PremiumInfo(
            premium_pct=round(premium_pct, 4),
            upbit_krw=upbit_krw,
            upbit_usd=round(upbit_usd, 2),
            binance_usd=round(binance_usd, 2),
            usd_krw_rate=self._fx_rate,
            timestamp=datetime.now(),
        )

    async def _notify_subscribers(
        self,
        exchange: str,
        price: float,
        change_pct: float
    ) -> None:
        """Notify all subscribers of significant price change."""
        event = PriceEvent(
            exchange=exchange,
            price=price,
            change_pct=change_pct,
            timestamp=datetime.now(),
        )

        self._notification_count += 1

        dead_subscribers = []
        for queue in self._subscribers:
            queue_id = id(queue)
            try:
                # Non-blocking put - drop if queue is full
                queue.put_nowait(event)
                # Reset failure count on success
                self._subscriber_failures[queue_id] = 0
            except asyncio.QueueFull:
                # Track consecutive failures
                failures = self._subscriber_failures.get(queue_id, 0) + 1
                self._subscriber_failures[queue_id] = failures
                if failures >= self._max_failures:
                    dead_subscribers.append(queue)
                    logger.warning(f"Removing dead subscriber (queue full {failures} times)")
                else:
                    logger.debug(f"Subscriber queue full ({failures}/{self._max_failures})")

        # Remove dead subscribers
        for queue in dead_subscribers:
            self._subscribers.remove(queue)
            self._subscriber_failures.pop(id(queue), None)

    def subscribe(self, maxsize: int = 100) -> asyncio.Queue:
        """
        Subscribe to price change events.

        Args:
            maxsize: Maximum queue size (events dropped if full)

        Returns:
            Queue that receives PriceEvent objects
        """
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(queue)
        logger.info(f"New subscriber added (total: {len(self._subscribers)})")
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> bool:
        """Remove a subscriber."""
        if queue in self._subscribers:
            self._subscribers.remove(queue)
            return True
        return False

    def get_prices(self) -> Dict[str, float]:
        """Get current prices (instant, no network)."""
        return {
            exchange: msg.price
            for exchange, msg in self._prices.items()
        }

    def get_price(self, exchange: str) -> Optional[float]:
        """Get price for specific exchange."""
        msg = self._prices.get(exchange)
        return msg.price if msg else None

    def get_premium(self) -> Optional[PremiumInfo]:
        """Get pre-calculated Kimchi Premium."""
        return self._cached_premium

    def get_price_age(self, exchange: str) -> Optional[float]:
        """Get age of price in seconds."""
        msg = self._prices.get(exchange)
        if not msg:
            return None
        return (datetime.now() - msg.timestamp).total_seconds()

    def is_price_fresh(self, exchange: str, max_age_seconds: float = 60.0) -> bool:
        """Check if price is fresh (less than max_age_seconds old)."""
        age = self.get_price_age(exchange)
        if age is None:
            return False
        return age < max_age_seconds

    def all_prices_fresh(self, max_age_seconds: float = 60.0) -> bool:
        """Check if all prices are fresh."""
        for exchange in ["upbit", "binance"]:
            if not self.is_price_fresh(exchange, max_age_seconds):
                return False
        return True

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for monitoring."""
        return {
            "uptime_seconds": (datetime.now() - self._started_at).total_seconds(),
            "prices": {
                exchange: {
                    "price": msg.price,
                    "age_seconds": self.get_price_age(exchange),
                    "update_count": self._update_count.get(exchange, 0),
                }
                for exchange, msg in self._prices.items()
            },
            "premium": {
                "premium_pct": self._cached_premium.premium_pct if self._cached_premium else None,
                "fx_rate": self._fx_rate,
            },
            "subscribers": len(self._subscribers),
            "notification_count": self._notification_count,
            "price_change_threshold": self._price_change_threshold,
        }
