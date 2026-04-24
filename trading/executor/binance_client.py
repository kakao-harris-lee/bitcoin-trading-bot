"""Spot-only Binance client."""

# pylint: disable=logging-fstring-interpolation,broad-exception-caught

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from functools import wraps
from typing import Any, Callable, TypeVar

logger = logging.getLogger(__name__)

RETRYABLE_ERROR_CODES = {
    -1021,
    -1001,
}
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 0.5

T = TypeVar("T")


def with_retry(func: Callable[..., T]) -> Callable[..., T]:
    """Retry transient Binance API errors with exponential backoff."""

    @wraps(func)
    async def wrapper(*args, **kwargs) -> T:
        last_exception = None
        backoff = INITIAL_BACKOFF_SEC

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as exc:
                error_code = getattr(exc, "code", None)
                if error_code in RETRYABLE_ERROR_CODES and attempt < MAX_RETRIES:
                    logger.warning(
                        "Retryable Binance error code=%s attempt=%s/%s retry_in=%.1fs: %s",
                        error_code,
                        attempt,
                        MAX_RETRIES,
                        backoff,
                        exc,
                    )
                    last_exception = exc
                    await asyncio.sleep(backoff)
                    backoff *= 2
                else:
                    raise

        raise last_exception

    return wrapper


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


@dataclass
class Balance:
    """Spot account balance."""

    spot_usdt: float
    total_usdt: float


class BinanceClient:
    """Async client for Binance spot trading."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._spot_client = None
        self._is_mock = False

    @staticmethod
    def _ensure_spot_market(market: str) -> None:
        normalized = str(market or "spot").strip().lower()
        if normalized != "spot":
            raise NotImplementedError("Futures support has been removed; use market='spot'.")

    async def connect(self) -> None:
        """Initialize the Binance spot API client."""
        try:
            from binance import AsyncClient

            self._spot_client = await AsyncClient.create(self.api_key, self.api_secret)
            logger.info("Connected to Binance spot API")
        except ImportError:
            logger.warning("binance package not installed, using mock client")
            self._spot_client = MockBinanceClient()
            self._is_mock = True

    async def disconnect(self) -> None:
        """Close the underlying client connection."""
        if self._spot_client and hasattr(self._spot_client, "close_connection"):
            await self._spot_client.close_connection()

    async def get_balance(self) -> Balance:
        """Get USDT balance from the spot account."""
        spot_usdt = 0.0

        try:
            if self._is_mock:
                spot_usdt = 10000.0
            else:
                spot_account = await self._spot_client.get_account()
                for asset in spot_account.get("balances", []):
                    if asset["asset"] == "USDT":
                        spot_usdt = float(asset["free"]) + float(asset["locked"])
                        break

            return Balance(spot_usdt=spot_usdt, total_usdt=spot_usdt)
        except Exception as exc:
            logger.error("Failed to get spot balance: %s", exc)
            raise

    async def get_spot_positions(self) -> list[dict[str, Any]]:
        """Get non-zero spot holdings."""
        positions: list[dict[str, Any]] = []

        try:
            if self._is_mock:
                return []

            account = await self._spot_client.get_account()
            for asset in account.get("balances", []):
                free = float(asset["free"])
                locked = float(asset["locked"])
                total = free + locked
                if total > 0 and asset["asset"] not in {"USDT", "BUSD", "USDC"}:
                    positions.append(
                        {
                            "symbol": asset["asset"],
                            "market": "spot",
                            "quantity": total,
                            "side": "buy",
                        }
                    )
            return positions
        except Exception as exc:
            logger.error("Failed to get spot positions: %s", exc)
            return []

    async def get_all_positions(self) -> list[dict[str, Any]]:
        """Get all active positions. Spot-only system returns spot holdings."""
        return await self.get_spot_positions()

    @with_retry
    async def market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        market: str = "spot",
        position_side: str | None = None,
    ) -> dict[str, Any]:
        """Execute a spot market order."""
        del position_side
        self._ensure_spot_market(market)
        pair = f"{symbol}USDT"

        try:
            result = await self._spot_client.create_order(
                symbol=pair,
                side=side.upper(),
                type="MARKET",
                quantity=quantity,
            )
            executed_qty = float(result.get("executedQty", quantity) or quantity)
            cum_quote = float(result.get("cummulativeQuoteQty", 0) or 0)
            filled_price = cum_quote / executed_qty if executed_qty > 0 and cum_quote > 0 else float(result.get("price", 0) or 0)

            return {
                "order_id": result["orderId"],
                "symbol": symbol,
                "side": side,
                "market": "spot",
                "filled_qty": executed_qty,
                "filled_price": filled_price,
                "status": result["status"],
            }
        except Exception as exc:
            logger.error("Spot market order failed: %s", exc)
            raise

    @with_retry
    async def limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        market: str = "spot",
        position_side: str | None = None,
    ) -> dict[str, Any]:
        """Place a spot limit order."""
        del position_side
        self._ensure_spot_market(market)
        pair = f"{symbol}USDT"

        try:
            result = await self._spot_client.create_order(
                symbol=pair,
                side=side.upper(),
                type="LIMIT",
                quantity=quantity,
                price=price,
                timeInForce="GTC",
            )
            return {
                "order_id": result["orderId"],
                "symbol": symbol,
                "side": side,
                "market": "spot",
                "price": float(result.get("price", price)),
                "quantity": quantity,
                "filled_qty": float(result.get("executedQty", 0)),
                "status": result["status"],
            }
        except Exception as exc:
            logger.error("Spot limit order failed: %s", exc)
            raise

    @with_retry
    async def cancel_order(
        self,
        symbol: str,
        order_id: int,
        market: str = "spot",
    ) -> dict[str, Any]:
        """Cancel an open spot order."""
        self._ensure_spot_market(market)
        pair = f"{symbol}USDT"

        try:
            result = await self._spot_client.cancel_order(symbol=pair, orderId=order_id)
            return {"order_id": result["orderId"], "status": result["status"]}
        except Exception as exc:
            logger.error("Cancel order failed: %s", exc)
            raise

    @with_retry
    async def get_order(
        self,
        symbol: str,
        order_id: int,
        market: str = "spot",
    ) -> dict[str, Any]:
        """Get spot order status."""
        self._ensure_spot_market(market)
        pair = f"{symbol}USDT"

        try:
            result = await self._spot_client.get_order(symbol=pair, orderId=order_id)
            return {
                "order_id": result["orderId"],
                "status": result["status"],
                "filled_qty": float(result.get("executedQty", 0)),
                "price": float(result.get("price", 0)),
            }
        except Exception as exc:
            logger.error("Get order failed: %s", exc)
            raise

    @with_retry
    async def stop_loss_limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        stop_price: float,
        limit_price: float,
        market: str = "spot",
        position_side: str | None = None,
    ) -> dict[str, Any] | None:
        """Place a spot stop-loss limit order."""
        del position_side
        self._ensure_spot_market(market)
        pair = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol

        try:
            order = await self._spot_client.create_order(
                symbol=pair,
                side=side.upper(),
                type="STOP_LOSS_LIMIT",
                quantity=quantity,
                stopPrice=str(stop_price),
                price=str(limit_price),
                timeInForce="GTC",
            )
            return {
                "orderId": order["orderId"],
                "symbol": symbol,
                "side": side,
                "market": "spot",
                "stop_price": stop_price,
                "limit_price": limit_price,
                "status": order["status"],
            }
        except Exception as exc:
            logger.error("Stop-loss order failed for %s: %s", symbol, exc)
            return None

    @with_retry
    async def cancel_open_orders(
        self,
        symbol: str,
        market: str = "spot",
    ) -> list[dict[str, Any]]:
        """Cancel all open spot orders for a symbol."""
        self._ensure_spot_market(market)
        pair = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol
        cancelled_orders: list[dict[str, Any]] = []

        try:
            open_orders = await self._spot_client.get_open_orders(symbol=pair)
            for order in open_orders:
                try:
                    result = await self._spot_client.cancel_order(
                        symbol=pair,
                        orderId=order["orderId"],
                    )
                    cancelled_orders.append(
                        {"orderId": result["orderId"], "status": result["status"]}
                    )
                except Exception as exc:
                    logger.warning("Failed to cancel spot order %s: %s", order["orderId"], exc)

            if cancelled_orders:
                logger.info("Cancelled %d open spot orders for %s", len(cancelled_orders), symbol)
            return cancelled_orders
        except Exception as exc:
            logger.error("Failed to cancel orders for %s: %s", symbol, exc)
            return cancelled_orders


class MockBinanceClient:
    """Mock spot client for testing without real API."""

    async def get_account(self) -> dict[str, Any]:
        return {
            "balances": [
                {"asset": "USDT", "free": "10000.00", "locked": "0.00"},
                {"asset": "BTC", "free": "0.00", "locked": "0.00"},
            ]
        }

    async def create_order(self, **kwargs) -> dict[str, Any]:
        return {
            "orderId": 99999,
            "executedQty": str(kwargs.get("quantity", 0.01)),
            "cummulativeQuoteQty": "430.00",
            "status": "FILLED",
            "price": str(kwargs.get("price", 43000.0)),
        }

    async def get_open_orders(self, symbol: str) -> list[dict[str, Any]]:
        del symbol
        return []

    async def cancel_order(self, symbol: str, orderId: int) -> dict[str, Any]:
        del symbol
        return {"orderId": orderId, "status": "CANCELED"}

    async def get_order(self, symbol: str, orderId: int) -> dict[str, Any]:
        del symbol
        return {
            "orderId": orderId,
            "status": "FILLED",
            "executedQty": "0.01",
            "price": "43000.0",
        }
