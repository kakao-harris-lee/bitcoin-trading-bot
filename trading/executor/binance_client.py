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


@dataclass
class Balance:
    """Account balance."""
    spot_usdt: float
    futures_usdt: float
    total_usdt: float


class BinanceClient:
    """Unified async client for Binance spot and futures."""

    def __init__(self, api_key: str, api_secret: str):
        self.api_key = api_key
        self.api_secret = api_secret
        self._spot_client = None
        self._futures_client = None
        self._is_mock = False

    async def connect(self) -> None:
        """Initialize API clients."""
        try:
            from binance import AsyncClient
            self._spot_client = await AsyncClient.create(self.api_key, self.api_secret)
            self._futures_client = await AsyncClient.create(self.api_key, self.api_secret)
            logger.info("Connected to Binance API")
        except ImportError:
            logger.warning("binance package not installed, using mock client")
            self._spot_client = MockBinanceClient()
            self._futures_client = MockBinanceClient()
            self._is_mock = True

    async def disconnect(self) -> None:
        """Close API clients."""
        if self._spot_client and hasattr(self._spot_client, 'close_connection'):
            await self._spot_client.close_connection()
        if self._futures_client and hasattr(self._futures_client, 'close_connection'):
            await self._futures_client.close_connection()

    async def get_balance(self) -> Balance:
        """Get USDT balance from spot and futures accounts."""
        spot_usdt = 0.0
        futures_usdt = 0.0

        try:
            # Spot balance
            if self._is_mock:
                spot_usdt = 10000.0
            else:
                spot_account = await self._spot_client.get_account()
                for asset in spot_account.get("balances", []):
                    if asset["asset"] == "USDT":
                        spot_usdt = float(asset["free"]) + float(asset["locked"])
                        break

            # Futures balance
            if self._is_mock:
                futures_usdt = 10000.0
            else:
                futures_account = await self._futures_client.futures_account_balance()
                for asset in futures_account:
                    if asset["asset"] == "USDT":
                        futures_usdt = float(asset["balance"])
                        break

            return Balance(
                spot_usdt=spot_usdt,
                futures_usdt=futures_usdt,
                total_usdt=spot_usdt + futures_usdt,
            )

        except Exception as e:
            logger.error(f"Failed to get balance: {e}")
            raise

    async def get_spot_positions(self) -> list[dict[str, Any]]:
        """Get spot positions (non-zero balances)."""
        positions = []

        try:
            if self._is_mock:
                return []

            account = await self._spot_client.get_account()
            for asset in account.get("balances", []):
                free = float(asset["free"])
                locked = float(asset["locked"])
                total = free + locked
                if total > 0 and asset["asset"] not in ["USDT", "BUSD", "USDC"]:
                    positions.append({
                        "symbol": asset["asset"],
                        "market": "spot",
                        "quantity": total,
                        "side": "buy",  # Spot is always long
                    })

            return positions

        except Exception as e:
            logger.error(f"Failed to get spot positions: {e}")
            return []

    async def get_futures_positions(self) -> list[dict[str, Any]]:
        """Get futures positions."""
        positions = []

        try:
            if self._is_mock:
                return []

            account = await self._futures_client.futures_account()
            for pos in account.get("positions", []):
                qty = float(pos["positionAmt"])
                if qty != 0:
                    symbol = pos["symbol"].replace("USDT", "")
                    positions.append({
                        "symbol": symbol,
                        "market": "futures",
                        "quantity": abs(qty),
                        "side": "buy" if qty > 0 else "sell",
                        "entry_price": float(pos["entryPrice"]),
                        "unrealized_pnl": float(pos["unrealizedProfit"]),
                    })

            return positions

        except Exception as e:
            logger.error(f"Failed to get futures positions: {e}")
            return []

    async def get_all_positions(self) -> list[dict[str, Any]]:
        """Get all positions from both spot and futures."""
        spot = await self.get_spot_positions()
        futures = await self.get_futures_positions()
        return spot + futures

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

    async def limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        market: str,
    ) -> dict[str, Any]:
        """Place limit order on spot or futures."""
        pair = f"{symbol}USDT"

        try:
            if market == "futures":
                result = await self._futures_client.futures_create_order(
                    symbol=pair,
                    side=side.upper(),
                    type="LIMIT",
                    quantity=quantity,
                    price=price,
                    timeInForce="GTC",
                )
            else:
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
                "market": market,
                "price": float(result.get("price", price)),
                "quantity": quantity,
                "filled_qty": float(result.get("executedQty", 0)),
                "status": result["status"],
            }

        except Exception as e:
            logger.error(f"Limit order failed: {e}")
            raise

    async def cancel_order(
        self,
        symbol: str,
        order_id: int,
        market: str,
    ) -> dict[str, Any]:
        """Cancel an open order."""
        pair = f"{symbol}USDT"

        try:
            if market == "futures":
                result = await self._futures_client.futures_cancel_order(
                    symbol=pair,
                    orderId=order_id,
                )
            else:
                result = await self._spot_client.cancel_order(
                    symbol=pair,
                    orderId=order_id,
                )

            return {
                "order_id": result["orderId"],
                "status": result["status"],
            }

        except Exception as e:
            logger.error(f"Cancel order failed: {e}")
            raise

    async def get_order(
        self,
        symbol: str,
        order_id: int,
        market: str,
    ) -> dict[str, Any]:
        """Get order status."""
        pair = f"{symbol}USDT"

        try:
            if market == "futures":
                result = await self._futures_client.futures_get_order(
                    symbol=pair,
                    orderId=order_id,
                )
            else:
                result = await self._spot_client.get_order(
                    symbol=pair,
                    orderId=order_id,
                )

            return {
                "order_id": result["orderId"],
                "status": result["status"],
                "filled_qty": float(result.get("executedQty", 0)),
                "price": float(result.get("price", 0)),
            }

        except Exception as e:
            logger.error(f"Get order failed: {e}")
            raise


class MockBinanceClient:
    """Mock client for testing without real API."""

    async def get_account(self) -> dict:
        return {
            "balances": [
                {"asset": "USDT", "free": "10000.00", "locked": "0.00"},
                {"asset": "BTC", "free": "0.00", "locked": "0.00"},
            ]
        }

    async def futures_account_balance(self) -> list:
        return [
            {"asset": "USDT", "balance": "10000.00"},
        ]

    async def futures_account(self) -> dict:
        return {"positions": []}

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
