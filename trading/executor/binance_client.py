# trading/executor/binance_client.py
"""Unified Binance client for spot and futures."""
from __future__ import annotations
import logging
from typing import Any
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class Fill:
    """Order fill result."""
    order_id: int
    symbol: str
    side: str
    market: str
    filled_qty: float
    filled_price: float
    status: str


class BinanceClient:
    """Unified async client for Binance spot and futures."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._spot_client = None
        self._futures_client = None

    async def connect(self) -> None:
        """Initialize API clients."""
        # Import here to avoid import errors when binance not installed
        try:
            from binance import AsyncClient
            self._spot_client = await AsyncClient.create(self.api_key, self.api_secret)
            self._futures_client = await AsyncClient.create(self.api_key, self.api_secret)
        except ImportError:
            logger.warning("binance package not installed, using mock client")
            self._spot_client = MockBinanceClient()
            self._futures_client = MockBinanceClient()

    async def disconnect(self) -> None:
        """Close API clients."""
        if self._spot_client and hasattr(self._spot_client, 'close_connection'):
            await self._spot_client.close_connection()
        if self._futures_client and hasattr(self._futures_client, 'close_connection'):
            await self._futures_client.close_connection()

    async def market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        market: str,
    ) -> dict[str, Any]:
        """Execute market order on spot or futures."""
        pair = f"{symbol}USDT"

        try:
            if market == "futures":
                result = await self._futures_client.futures_create_order(
                    symbol=pair,
                    side=side.upper(),
                    type="MARKET",
                    quantity=quantity,
                )
                filled_price = float(result.get("avgPrice", 0)) or \
                               float(result["cumQuote"]) / float(result["executedQty"])
            else:
                result = await self._spot_client.create_order(
                    symbol=pair,
                    side=side.upper(),
                    type="MARKET",
                    quantity=quantity,
                )
                filled_price = float(result["cummulativeQuoteQty"]) / float(result["executedQty"])

            return {
                "order_id": result["orderId"],
                "symbol": symbol,
                "side": side,
                "market": market,
                "filled_qty": float(result["executedQty"]),
                "filled_price": filled_price,
                "status": result["status"],
            }

        except Exception as e:
            logger.error(f"Order failed: {e}")
            raise


class MockBinanceClient:
    """Mock client for testing without real API."""

    async def create_order(self, **kwargs) -> dict:
        return {
            "orderId": 99999,
            "executedQty": str(kwargs.get("quantity", 0.01)),
            "cummulativeQuoteQty": "430.00",
            "status": "FILLED",
        }

    async def futures_create_order(self, **kwargs) -> dict:
        return {
            "orderId": 99999,
            "executedQty": str(kwargs.get("quantity", 0.01)),
            "cumQuote": "430.00",
            "avgPrice": "43000.00",
            "status": "FILLED",
        }
