# trading/executor/binance_client.py
"""Unified Binance client for spot and futures trading."""
from __future__ import annotations
import asyncio
import logging
from typing import Any, Callable, TypeVar
from dataclasses import dataclass
from functools import wraps

logger = logging.getLogger(__name__)

# Error codes that are safe to retry (transient issues)
RETRYABLE_ERROR_CODES = {
    -1021,  # Timestamp for this request is outside the recvWindow
    -1001,  # Disconnected
}

# Retry configuration
MAX_RETRIES = 3
INITIAL_BACKOFF_SEC = 0.5

T = TypeVar("T")


def with_retry(func: Callable[..., T]) -> Callable[..., T]:
    """Decorator to retry on transient Binance API errors with exponential backoff."""
    @wraps(func)
    async def wrapper(*args, **kwargs) -> T:
        last_exception = None
        backoff = INITIAL_BACKOFF_SEC

        for attempt in range(1, MAX_RETRIES + 1):
            try:
                return await func(*args, **kwargs)
            except Exception as e:
                # Check if it's a retryable Binance API error
                error_code = getattr(e, "code", None)
                if error_code in RETRYABLE_ERROR_CODES and attempt < MAX_RETRIES:
                    logger.warning(
                        f"Retryable error (code={error_code}), attempt {attempt}/{MAX_RETRIES}, "
                        f"retrying in {backoff}s: {e}"
                    )
                    last_exception = e
                    await asyncio.sleep(backoff)
                    backoff *= 2  # Exponential backoff
                else:
                    raise

        # Should not reach here, but raise last exception if it does
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
    """Account balance."""
    spot_usdt: float
    futures_usdt: float
    total_usdt: float


class BinanceClient:
    """Async client for Binance spot and futures trading."""

    # Default leverage for futures trading
    DEFAULT_LEVERAGE = 1

    def __init__(self, api_key: str, api_secret: str, default_leverage: int = 1):
        self.api_key = api_key
        self.api_secret = api_secret
        self._spot_client = None
        self._futures_client = None
        self._is_mock = False
        self._default_leverage = default_leverage
        # Track configured leverage per symbol to avoid redundant API calls
        self._leverage_cache: dict[str, int] = {}
        # Track hedge mode status
        self._hedge_mode_enabled = False

    async def connect(self) -> None:
        """Initialize API clients."""
        try:
            from binance import AsyncClient
            self._spot_client = await AsyncClient.create(self.api_key, self.api_secret)
            self._futures_client = await AsyncClient.create(self.api_key, self.api_secret)
            logger.info("Connected to Binance API")

            # Enable hedge mode for futures (allows simultaneous long/short positions)
            await self.enable_hedge_mode()
        except ImportError:
            logger.warning("binance package not installed, using mock client")
            self._spot_client = MockBinanceClient()
            self._futures_client = MockBinanceClient()
            self._is_mock = True
            self._hedge_mode_enabled = True  # Mock assumes hedge mode enabled

    async def disconnect(self) -> None:
        """Close API clients."""
        if self._spot_client and hasattr(self._spot_client, 'close_connection'):
            await self._spot_client.close_connection()
        if self._futures_client and hasattr(self._futures_client, 'close_connection'):
            await self._futures_client.close_connection()

    async def enable_hedge_mode(self) -> bool:
        """Enable hedge mode for futures trading.

        Hedge mode allows holding both LONG and SHORT positions simultaneously
        on the same symbol. This is required when running long and short
        strategies concurrently.

        Returns:
            True if hedge mode is enabled successfully.
        """
        if self._hedge_mode_enabled:
            logger.debug("Hedge mode already enabled")
            return True

        try:
            if self._is_mock:
                self._hedge_mode_enabled = True
                logger.info("[Mock] Enabled hedge mode for futures")
                return True

            # Change position mode to hedge (dualSidePosition=true)
            await self._futures_client.futures_change_position_mode(dualSidePosition=True)
            self._hedge_mode_enabled = True
            logger.info("Enabled hedge mode for futures (dual position mode)")
            return True

        except Exception as e:
            # Error code -4059 means hedge mode is already enabled
            error_code = getattr(e, "code", None)
            if error_code == -4059:
                self._hedge_mode_enabled = True
                logger.debug("Hedge mode already enabled on Binance")
                return True

            logger.error(f"Failed to enable hedge mode: {e}")
            return False

    @property
    def hedge_mode_enabled(self) -> bool:
        """Check if hedge mode is enabled."""
        return self._hedge_mode_enabled

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
        """Get spot holdings (non-zero balances) - for balance info only, not trading."""
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
        """Get all positions (both spot and futures)."""
        spot = await self.get_spot_positions()
        futures = await self.get_futures_positions()
        return spot + futures

    async def set_leverage(self, symbol: str, leverage: int) -> bool:
        """Set leverage for a futures symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC" or "BTCUSDT").
            leverage: Leverage multiplier (1-125 depending on symbol).

        Returns:
            True if leverage was set successfully.
        """
        # Normalize symbol to pair format
        pair = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol

        # Check if already set to this leverage
        if self._leverage_cache.get(pair) == leverage:
            logger.debug(f"Leverage already set to {leverage}x for {pair}")
            return True

        try:
            if self._is_mock:
                self._leverage_cache[pair] = leverage
                logger.info(f"[Mock] Set leverage to {leverage}x for {pair}")
                return True

            result = await self._futures_client.futures_change_leverage(
                symbol=pair,
                leverage=leverage,
            )

            actual_leverage = int(result.get("leverage", leverage))
            self._leverage_cache[pair] = actual_leverage
            logger.info(f"Set leverage to {actual_leverage}x for {pair}")
            return True

        except Exception as e:
            logger.error(f"Failed to set leverage for {pair}: {e}")
            return False

    async def get_leverage(self, symbol: str) -> int:
        """Get current leverage for a futures symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC" or "BTCUSDT").

        Returns:
            Current leverage multiplier.
        """
        pair = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol

        # Return cached value if available
        if pair in self._leverage_cache:
            return self._leverage_cache[pair]

        try:
            if self._is_mock:
                return self._default_leverage

            # Fetch from account info
            account = await self._futures_client.futures_account()
            for pos in account.get("positions", []):
                if pos["symbol"] == pair:
                    leverage = int(pos.get("leverage", self._default_leverage))
                    self._leverage_cache[pair] = leverage
                    return leverage

            return self._default_leverage

        except Exception as e:
            logger.error(f"Failed to get leverage for {pair}: {e}")
            return self._default_leverage

    async def ensure_leverage(self, symbol: str, leverage: int | None = None) -> bool:
        """Ensure leverage is set for a symbol before trading.

        Args:
            symbol: Trading symbol.
            leverage: Desired leverage. If None, uses default_leverage.

        Returns:
            True if leverage is correctly set.
        """
        target_leverage = leverage if leverage is not None else self._default_leverage
        current = await self.get_leverage(symbol)

        if current != target_leverage:
            return await self.set_leverage(symbol, target_leverage)

        return True

    async def initialize_leverage(self, symbols: list[str], leverage: int | None = None) -> dict[str, bool]:
        """Initialize leverage for multiple symbols at startup.

        Args:
            symbols: List of symbols to configure.
            leverage: Leverage to set. If None, uses default_leverage.

        Returns:
            Dict mapping symbol to success status.
        """
        target_leverage = leverage if leverage is not None else self._default_leverage
        results = {}

        for symbol in symbols:
            results[symbol] = await self.set_leverage(symbol, target_leverage)

        success_count = sum(results.values())
        logger.info(f"Initialized leverage for {success_count}/{len(symbols)} symbols at {target_leverage}x")

        return results

    @with_retry
    async def market_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        market: str = "futures",
        position_side: str | None = None,
    ) -> dict[str, Any]:
        """Execute market order on spot or futures.

        Args:
            symbol: Trading symbol (e.g., "BTC").
            side: Order side ("buy" or "sell").
            quantity: Order quantity.
            market: Market type ("spot" or "futures").
            position_side: Position side for hedge mode ("LONG" or "SHORT").
                          Required for futures in hedge mode.
        """
        pair = f"{symbol}USDT"

        try:
            if market == "spot":
                # Spot market order
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
            else:
                # Futures market order
                order_params = {
                    "symbol": pair,
                    "side": side.upper(),
                    "type": "MARKET",
                    "quantity": quantity,
                }
                # Add positionSide for hedge mode
                if self._hedge_mode_enabled and position_side:
                    order_params["positionSide"] = position_side.upper()

                result = await self._futures_client.futures_create_order(**order_params)
                filled_price = float(result.get("avgPrice", 0)) or \
                               float(result["cumQuote"]) / float(result["executedQty"])

                return {
                    "order_id": result["orderId"],
                    "symbol": symbol,
                    "side": side,
                    "market": market,
                    "filled_qty": float(result["executedQty"]),
                    "filled_price": filled_price,
                    "status": result["status"],
                    "position_side": position_side,
                }

        except Exception as e:
            logger.error(f"Order failed: {e}")
            raise

    @with_retry
    async def limit_order(
        self,
        symbol: str,
        side: str,
        quantity: float,
        price: float,
        market: str = "futures",
        position_side: str | None = None,
    ) -> dict[str, Any]:
        """Place limit order on spot or futures.

        Args:
            symbol: Trading symbol (e.g., "BTC").
            side: Order side ("buy" or "sell").
            quantity: Order quantity.
            price: Limit price.
            market: Market type ("spot" or "futures").
            position_side: Position side for hedge mode ("LONG" or "SHORT").
                          Required for futures in hedge mode.
        """
        pair = f"{symbol}USDT"

        try:
            if market == "spot":
                # Spot limit order
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
            else:
                # Futures limit order
                order_params = {
                    "symbol": pair,
                    "side": side.upper(),
                    "type": "LIMIT",
                    "quantity": quantity,
                    "price": price,
                    "timeInForce": "GTC",
                }
                # Add positionSide for hedge mode
                if self._hedge_mode_enabled and position_side:
                    order_params["positionSide"] = position_side.upper()

                result = await self._futures_client.futures_create_order(**order_params)

                return {
                    "order_id": result["orderId"],
                    "symbol": symbol,
                    "side": side,
                    "market": market,
                    "price": float(result.get("price", price)),
                    "quantity": quantity,
                    "filled_qty": float(result.get("executedQty", 0)),
                    "status": result["status"],
                    "position_side": position_side,
                }

        except Exception as e:
            logger.error(f"Limit order failed: {e}")
            raise

    @with_retry
    async def cancel_order(
        self,
        symbol: str,
        order_id: int,
        market: str = "futures",
    ) -> dict[str, Any]:
        """Cancel an open spot or futures order."""
        pair = f"{symbol}USDT"

        try:
            if market == "spot":
                result = await self._spot_client.cancel_order(
                    symbol=pair,
                    orderId=order_id,
                )
            else:
                result = await self._futures_client.futures_cancel_order(
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

    @with_retry
    async def get_order(
        self,
        symbol: str,
        order_id: int,
        market: str = "futures",
    ) -> dict[str, Any]:
        """Get spot or futures order status."""
        pair = f"{symbol}USDT"

        try:
            if market == "spot":
                result = await self._spot_client.get_order(
                    symbol=pair,
                    orderId=order_id,
                )
            else:
                result = await self._futures_client.futures_get_order(
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

    async def get_funding_rate(self, symbol: str) -> dict[str, Any] | None:
        """Get current funding rate for a futures symbol.

        Args:
            symbol: Trading symbol (e.g., "BTC" or "BTCUSDT").

        Returns:
            Dict with funding rate info or None if failed.
        """
        pair = f"{symbol}USDT" if not symbol.endswith("USDT") else symbol

        try:
            if self._is_mock:
                # Return mock data for testing
                import time
                return {
                    "symbol": pair,
                    "lastFundingRate": "0.0001",
                    "nextFundingTime": str(int(time.time() * 1000) + 28800000),
                }

            result = await self._futures_client.futures_mark_price(symbol=pair)
            return result

        except Exception as e:
            logger.error(f"Failed to get funding rate for {pair}: {e}")
            return None


class MockBinanceClient:
    """Mock client for testing without real API."""

    def __init__(self):
        self._leverage: dict[str, int] = {}
        self._hedge_mode = False

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

    async def futures_change_leverage(self, symbol: str, leverage: int) -> dict:
        self._leverage[symbol] = leverage
        return {"leverage": leverage, "symbol": symbol}

    async def futures_change_position_mode(self, dualSidePosition: bool) -> dict:
        """Mock enabling/disabling hedge mode."""
        self._hedge_mode = dualSidePosition
        return {"dualSidePosition": dualSidePosition}

    async def create_order(self, **kwargs) -> dict:
        return {
            "orderId": 99999,
            "executedQty": str(kwargs.get("quantity", 0.01)),
            "cummulativeQuoteQty": "430.00",
            "status": "FILLED",
        }

    async def futures_create_order(self, **kwargs) -> dict:
        result = {
            "orderId": 99999,
            "executedQty": str(kwargs.get("quantity", 0.01)),
            "cumQuote": "430.00",
            "avgPrice": "43000.00",
            "status": "FILLED",
        }
        # Include positionSide in response if provided
        if "positionSide" in kwargs:
            result["positionSide"] = kwargs["positionSide"]
        return result
