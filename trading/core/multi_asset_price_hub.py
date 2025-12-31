"""
MultiAssetPriceHub - Central price cache for multiple assets.

Tracks prices and calculates Kimchi Premium per asset.
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
    symbol: str
    exchange: str
    price: float
    change_pct: float
    timestamp: datetime


@dataclass
class SymbolPremium:
    """Premium info for a single symbol."""
    symbol: str
    premium_pct: float
    upbit_krw: float
    upbit_usd: float
    binance_usd: float
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class SymbolPriceState:
    """Price state for a single symbol across exchanges."""
    symbol: str
    upbit_krw: float = 0.0
    upbit_usd: float = 0.0
    binance_usd: float = 0.0
    premium_pct: float = 0.0
    last_upbit_update: Optional[datetime] = None
    last_binance_update: Optional[datetime] = None
    last_notified_upbit: float = 0.0
    last_notified_binance: float = 0.0


class MultiAssetPriceHub:
    """
    Central price cache for multiple assets with premium calculation.

    Features:
    - Per-symbol price tracking
    - Per-symbol Kimchi Premium calculation
    - Per-symbol subscriber notification
    - Configurable price change threshold
    """

    def __init__(
        self,
        symbols: List[str],
        price_change_threshold: float = 0.001,  # 0.1%
        default_fx_rate: float = 1450.0,
    ):
        """
        Args:
            symbols: List of asset symbols to track
            price_change_threshold: Minimum change to trigger notification
            default_fx_rate: Default USD/KRW rate
        """
        self._symbols = symbols
        self._price_change_threshold = price_change_threshold
        self._fx_rate = default_fx_rate
        self._started_at = datetime.now()

        # Per-symbol state
        self._prices: Dict[str, SymbolPriceState] = {
            sym: SymbolPriceState(symbol=sym) for sym in symbols
        }

        # Per-symbol subscribers
        self._subscribers: Dict[str, List[asyncio.Queue]] = {
            sym: [] for sym in symbols
        }

        # Global subscribers (receive all symbol events)
        self._global_subscribers: List[asyncio.Queue] = []

        # Statistics
        self._update_counts: Dict[str, Dict[str, int]] = {
            sym: {"upbit": 0, "binance": 0} for sym in symbols
        }
        self._notification_count = 0

    @classmethod
    def from_config(cls, config: Dict[str, Any]) -> "MultiAssetPriceHub":
        """
        Create MultiAssetPriceHub from allocation config.

        Args:
            config: Allocation config with "assets" section

        Returns:
            Configured MultiAssetPriceHub
        """
        assets = config.get("assets", {})
        symbols = [
            symbol for symbol, cfg in assets.items()
            if cfg.get("enabled", False)
        ]

        fx_rate = config.get("premium_tracking", {}).get("usd_krw_rate", 1450)

        return cls(symbols=symbols, default_fx_rate=fx_rate)

    def add_symbol(self, symbol: str) -> None:
        """Add a new symbol to track."""
        if symbol not in self._prices:
            self._prices[symbol] = SymbolPriceState(symbol=symbol)
            self._subscribers[symbol] = []
            self._update_counts[symbol] = {"upbit": 0, "binance": 0}
            self._symbols.append(symbol)
            logger.info(f"Added symbol to price hub: {symbol}")

    async def update_price(
        self,
        symbol: str,
        exchange: str,
        price: float,
        timestamp: Optional[datetime] = None
    ) -> bool:
        """
        Update price for a symbol from an exchange.

        Args:
            symbol: Asset symbol (e.g., "BTC")
            exchange: "upbit" or "binance"
            price: Current price
            timestamp: Update timestamp

        Returns:
            True if subscribers were notified (significant change)
        """
        if symbol not in self._prices:
            logger.warning(f"Unknown symbol: {symbol}")
            return False

        timestamp = timestamp or datetime.now()
        state = self._prices[symbol]

        # Update price
        if exchange == "upbit":
            state.upbit_krw = price
            state.upbit_usd = price / self._fx_rate if self._fx_rate > 0 else 0
            state.last_upbit_update = timestamp
            old_notified = state.last_notified_upbit
        else:
            state.binance_usd = price
            state.last_binance_update = timestamp
            old_notified = state.last_notified_binance

        # Update statistics
        self._update_counts[symbol][exchange] += 1

        # Recalculate premium
        self._recalculate_premium(symbol)

        # Check if change is significant
        if old_notified > 0:
            change_pct = abs(price - old_notified) / old_notified
            if change_pct >= self._price_change_threshold:
                if exchange == "upbit":
                    state.last_notified_upbit = price
                else:
                    state.last_notified_binance = price
                await self._notify_subscribers(symbol, exchange, price, change_pct)
                return True
        else:
            # First price - always notify
            if exchange == "upbit":
                state.last_notified_upbit = price
            else:
                state.last_notified_binance = price
            await self._notify_subscribers(symbol, exchange, price, 0.0)
            return True

        return False

    def _recalculate_premium(self, symbol: str) -> None:
        """Recalculate premium for a symbol."""
        state = self._prices[symbol]

        if state.binance_usd > 0 and state.upbit_usd > 0:
            state.premium_pct = (
                (state.upbit_usd - state.binance_usd) / state.binance_usd * 100
            )
        else:
            state.premium_pct = 0.0

    async def _notify_subscribers(
        self,
        symbol: str,
        exchange: str,
        price: float,
        change_pct: float
    ) -> None:
        """Notify subscribers of price change."""
        event = PriceEvent(
            symbol=symbol,
            exchange=exchange,
            price=price,
            change_pct=change_pct,
            timestamp=datetime.now(),
        )

        self._notification_count += 1

        # Notify symbol-specific subscribers
        for queue in self._subscribers.get(symbol, []):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug(f"Subscriber queue full for {symbol}")

        # Notify global subscribers
        for queue in self._global_subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                logger.debug("Global subscriber queue full")

    def update_fx_rate(self, rate: float) -> None:
        """Update USD/KRW exchange rate."""
        self._fx_rate = rate
        # Recalculate all premiums
        for symbol in self._prices:
            state = self._prices[symbol]
            if state.upbit_krw > 0:
                state.upbit_usd = state.upbit_krw / rate
            self._recalculate_premium(symbol)

    def subscribe(self, symbol: str, maxsize: int = 100) -> asyncio.Queue:
        """Subscribe to price events for a specific symbol."""
        if symbol not in self._subscribers:
            self._subscribers[symbol] = []

        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._subscribers[symbol].append(queue)
        logger.info(f"New subscriber for {symbol}")
        return queue

    def subscribe_all(self, maxsize: int = 100) -> asyncio.Queue:
        """Subscribe to price events for all symbols."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=maxsize)
        self._global_subscribers.append(queue)
        logger.info("New global subscriber added")
        return queue

    def unsubscribe(self, symbol: str, queue: asyncio.Queue) -> bool:
        """Remove a symbol-specific subscriber."""
        if symbol in self._subscribers and queue in self._subscribers[symbol]:
            self._subscribers[symbol].remove(queue)
            return True
        return False

    def get_price(self, symbol: str, exchange: str) -> Optional[float]:
        """Get price for symbol and exchange."""
        state = self._prices.get(symbol)
        if not state:
            return None
        if exchange == "upbit":
            return state.upbit_krw
        return state.binance_usd

    def get_prices(self, symbol: str) -> Dict[str, float]:
        """Get all prices for a symbol."""
        state = self._prices.get(symbol)
        if not state:
            return {}
        return {
            "upbit_krw": state.upbit_krw,
            "upbit_usd": state.upbit_usd,
            "binance_usd": state.binance_usd,
        }

    def get_premium(self, symbol: str) -> Optional[SymbolPremium]:
        """Get premium info for a symbol."""
        state = self._prices.get(symbol)
        if not state:
            return None

        return SymbolPremium(
            symbol=symbol,
            premium_pct=round(state.premium_pct, 4),
            upbit_krw=state.upbit_krw,
            upbit_usd=round(state.upbit_usd, 2),
            binance_usd=round(state.binance_usd, 2),
        )

    def get_all_premiums(self) -> Dict[str, float]:
        """Get premium percentage for all symbols."""
        return {
            symbol: state.premium_pct
            for symbol, state in self._prices.items()
        }

    def get_best_premium(self) -> Optional[tuple]:
        """Get symbol with highest premium."""
        if not self._prices:
            return None

        best_symbol = max(
            self._prices.keys(),
            key=lambda s: self._prices[s].premium_pct
        )
        return (best_symbol, self._prices[best_symbol].premium_pct)

    def get_price_age(self, exchange: str, symbol: str = "BTC") -> Optional[float]:
        """Get age of price in seconds (for HealthMonitor compatibility)."""
        state = self._prices.get(symbol)
        if not state:
            # Try first available symbol
            if self._prices:
                symbol = next(iter(self._prices.keys()))
                state = self._prices[symbol]
            else:
                return None

        if exchange == "upbit":
            last_update = state.last_upbit_update
        else:
            last_update = state.last_binance_update

        if not last_update:
            return None

        return (datetime.now() - last_update).total_seconds()

    def is_price_fresh(
        self,
        symbol: str,
        exchange: str,
        max_age_seconds: float = 60.0
    ) -> bool:
        """Check if price is fresh."""
        state = self._prices.get(symbol)
        if not state:
            return False

        if exchange == "upbit":
            last_update = state.last_upbit_update
        else:
            last_update = state.last_binance_update

        if not last_update:
            return False

        age = (datetime.now() - last_update).total_seconds()
        return age < max_age_seconds

    def all_prices_fresh(
        self,
        symbol: str,
        max_age_seconds: float = 60.0
    ) -> bool:
        """Check if all prices for a symbol are fresh."""
        return (
            self.is_price_fresh(symbol, "upbit", max_age_seconds) and
            self.is_price_fresh(symbol, "binance", max_age_seconds)
        )

    def get_symbols(self) -> List[str]:
        """Get list of tracked symbols."""
        return self._symbols.copy()

    def get_stats(self) -> Dict[str, Any]:
        """Get statistics for monitoring."""
        return {
            "uptime_seconds": (datetime.now() - self._started_at).total_seconds(),
            "symbols": self._symbols,
            "fx_rate": self._fx_rate,
            "notification_count": self._notification_count,
            "price_change_threshold": self._price_change_threshold,
            "assets": {
                symbol: {
                    "upbit_krw": state.upbit_krw,
                    "binance_usd": state.binance_usd,
                    "premium_pct": round(state.premium_pct, 4),
                    "upbit_fresh": self.is_price_fresh(symbol, "upbit"),
                    "binance_fresh": self.is_price_fresh(symbol, "binance"),
                    "updates": self._update_counts.get(symbol, {}),
                }
                for symbol, state in self._prices.items()
            },
            "subscribers": {
                symbol: len(queues)
                for symbol, queues in self._subscribers.items()
            },
            "global_subscribers": len(self._global_subscribers),
        }
