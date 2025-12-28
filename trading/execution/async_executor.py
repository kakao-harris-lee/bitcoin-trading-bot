"""
AsyncExecutor - Async order execution queue.

Receives signals from StrategyRunners and executes orders asynchronously.
Supports both paper and live execution modes.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, Optional, Any, List, Callable
from uuid import uuid4

logger = logging.getLogger(__name__)


class OrderStatus(Enum):
    """Order status."""
    PENDING = "pending"
    SUBMITTED = "submitted"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    FAILED = "failed"
    EXPIRED = "expired"


@dataclass
class Order:
    """Order representation."""
    id: str
    exchange: str
    strategy: str
    action: str  # "buy" or "sell"
    price: float
    fraction: float
    status: OrderStatus = OrderStatus.PENDING
    created_at: datetime = field(default_factory=datetime.now)
    submitted_at: Optional[datetime] = None
    filled_at: Optional[datetime] = None
    fill_price: Optional[float] = None
    fill_size: Optional[float] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "exchange": self.exchange,
            "strategy": self.strategy,
            "action": self.action,
            "price": self.price,
            "fraction": self.fraction,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "submitted_at": self.submitted_at.isoformat() if self.submitted_at else None,
            "filled_at": self.filled_at.isoformat() if self.filled_at else None,
            "fill_price": self.fill_price,
            "fill_size": self.fill_size,
            "error": self.error,
            "metadata": self.metadata,
        }


class AsyncExecutor:
    """
    Async order executor with queue-based processing.

    Features:
    - In-process order queue (no Redis)
    - Paper and live execution modes
    - Order timeout handling
    - Callback for position updates
    """

    def __init__(
        self,
        execution_mode: str = "paper",
        order_timeout: float = 60.0,
        on_order_filled: Optional[Callable[[Order], None]] = None,
    ):
        """
        Args:
            execution_mode: "paper" or "live"
            order_timeout: Order expiry time in seconds
            on_order_filled: Callback when order is filled
        """
        self.execution_mode = execution_mode
        self.order_timeout = order_timeout
        self.on_order_filled = on_order_filled

        # Order queue
        self._queue: asyncio.Queue = asyncio.Queue()
        self._pending_orders: Dict[str, Order] = {}
        self._completed_orders: List[Order] = []
        self._max_completed: int = 100

        # Processing state
        self._started = False
        self._processor_task: Optional[asyncio.Task] = None

        # Paper trading accounts
        self._paper_accounts: Dict[str, Any] = {}

        # Live trading adapters
        self._live_adapters: Dict[str, Any] = {}

        # Statistics
        self._submitted_count: int = 0
        self._filled_count: int = 0
        self._failed_count: int = 0

    async def start(self) -> None:
        """Start order processor."""
        if self._started:
            return

        # Initialize accounts/adapters
        if self.execution_mode == "paper":
            await self._init_paper_accounts()
        else:
            await self._init_live_adapters()

        # Start processor
        self._processor_task = asyncio.create_task(self._process_loop())
        self._started = True

        logger.info(f"AsyncExecutor started in {self.execution_mode} mode")

    async def stop(self) -> None:
        """Stop order processor."""
        if self._processor_task:
            self._processor_task.cancel()
            try:
                await self._processor_task
            except asyncio.CancelledError:
                pass

        self._started = False
        logger.info("AsyncExecutor stopped")

    async def _init_paper_accounts(self) -> None:
        """Initialize paper trading accounts."""
        from trading.execution.paper_account import PaperTradingAccount

        self._paper_accounts["upbit"] = PaperTradingAccount(
            initial_capital=10_000_000,  # 10M KRW
            exchange="upbit",
        )
        self._paper_accounts["binance"] = PaperTradingAccount(
            initial_capital=10_000,  # 10K USDT
            exchange="binance",
        )

        logger.info("Initialized paper trading accounts")

    async def _init_live_adapters(self) -> None:
        """Initialize live trading adapters."""
        import os

        # Safety check
        if os.getenv("ENABLE_LIVE_TRADING") != "1":
            raise ValueError(
                "Live mode requires ENABLE_LIVE_TRADING=1 environment variable"
            )

        try:
            from trading.adapters.upbit import UpbitTrader
            from trading.adapters.binance import BinanceFuturesTrader

            self._live_adapters["upbit"] = UpbitTrader()
            self._live_adapters["binance"] = BinanceFuturesTrader()

            logger.info("Initialized live trading adapters")
        except Exception as e:
            logger.error(f"Failed to initialize live adapters: {e}")
            raise

    async def submit(self, signal: Any) -> str:
        """
        Submit a signal for execution.

        Args:
            signal: Signal from StrategyRunner

        Returns:
            Order ID
        """
        order = Order(
            id=str(uuid4())[:8],
            exchange=signal.exchange,
            strategy=signal.strategy,
            action=signal.action,
            price=signal.price,
            fraction=signal.fraction,
            metadata=signal.metadata if hasattr(signal, 'metadata') else {},
        )

        self._pending_orders[order.id] = order
        await self._queue.put(order)

        logger.info(f"Order submitted: {order.id} {order.exchange} {order.action}")
        return order.id

    async def _process_loop(self) -> None:
        """Main order processing loop."""
        while True:
            try:
                # Get order from queue with timeout
                order = await asyncio.wait_for(
                    self._queue.get(),
                    timeout=10.0
                )

                await self._execute_order(order)

            except asyncio.TimeoutError:
                # Check for expired orders
                await self._check_expired_orders()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Order processing error: {e}")
                await asyncio.sleep(1)

    async def _execute_order(self, order: Order) -> None:
        """Execute a single order."""
        order.submitted_at = datetime.now()
        order.status = OrderStatus.SUBMITTED
        self._submitted_count += 1

        try:
            if self.execution_mode == "paper":
                result = await self._execute_paper(order)
            else:
                result = await self._execute_live(order)

            if result["success"]:
                order.status = OrderStatus.FILLED
                order.filled_at = datetime.now()
                order.fill_price = result.get("price", order.price)
                order.fill_size = result.get("size", 0)
                self._filled_count += 1

                logger.info(
                    f"Order filled: {order.id} {order.exchange} {order.action} "
                    f"@ {order.fill_price}"
                )

                # Callback
                if self.on_order_filled:
                    self.on_order_filled(order)
            else:
                order.status = OrderStatus.FAILED
                order.error = result.get("error", "Unknown error")
                self._failed_count += 1

                logger.warning(f"Order failed: {order.id} - {order.error}")

        except Exception as e:
            order.status = OrderStatus.FAILED
            order.error = str(e)
            self._failed_count += 1
            logger.error(f"Order execution error: {order.id} - {e}")

        finally:
            # Move to completed
            self._move_to_completed(order)

    async def _execute_paper(self, order: Order) -> Dict[str, Any]:
        """Execute order in paper trading mode."""
        account = self._paper_accounts.get(order.exchange)
        if not account:
            return {"success": False, "error": f"No account for {order.exchange}"}

        try:
            if order.action == "buy":
                # Buy with fraction of available cash
                cash, _ = account.get_balance()
                amount = cash * order.fraction
                if amount < 10000 if order.exchange == "upbit" else 10:  # Minimum
                    return {"success": False, "error": "Insufficient funds"}

                result = account.buy(order.price, amount)
                return {
                    "success": True,
                    "price": order.price,
                    "size": result.get("size", amount / order.price),
                }

            elif order.action == "sell":
                # Sell position
                _, btc = account.get_balance()
                if btc <= 0:
                    return {"success": False, "error": "No position to sell"}

                result = account.sell(order.price, btc * order.fraction)
                return {
                    "success": True,
                    "price": order.price,
                    "size": btc * order.fraction,
                }

            else:
                return {"success": False, "error": f"Unknown action: {order.action}"}

        except Exception as e:
            return {"success": False, "error": str(e)}

    async def _execute_live(self, order: Order) -> Dict[str, Any]:
        """Execute order in live trading mode."""
        adapter = self._live_adapters.get(order.exchange)
        if not adapter:
            return {"success": False, "error": f"No adapter for {order.exchange}"}

        try:
            # Run in thread pool (adapters are sync)
            result = await asyncio.to_thread(
                self._execute_live_sync,
                adapter,
                order,
            )
            return result

        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_live_sync(self, adapter: Any, order: Order) -> Dict[str, Any]:
        """Execute live order (sync, runs in thread pool)."""
        try:
            if order.exchange == "upbit":
                return self._execute_upbit_live(adapter, order)
            else:
                return self._execute_binance_live(adapter, order)
        except Exception as e:
            return {"success": False, "error": str(e)}

    def _execute_upbit_live(self, adapter: Any, order: Order) -> Dict[str, Any]:
        """Execute Upbit live order."""
        if order.action == "buy":
            # Get available KRW
            balance = adapter.get_balance("KRW")
            if not balance:
                return {"success": False, "error": "Failed to get balance"}

            available = float(balance.get("balance", 0))
            amount = available * order.fraction

            if amount < 5000:  # Upbit minimum
                return {"success": False, "error": "Amount below minimum"}

            result = adapter.buy_market("KRW-BTC", amount)
            if result:
                return {
                    "success": True,
                    "price": order.price,
                    "size": amount / order.price,
                }
            return {"success": False, "error": "Buy order failed"}

        elif order.action == "sell":
            balance = adapter.get_balance("BTC")
            if not balance:
                return {"success": False, "error": "Failed to get balance"}

            available = float(balance.get("balance", 0))
            amount = available * order.fraction

            if amount < 0.0001:  # Minimum BTC
                return {"success": False, "error": "Amount below minimum"}

            result = adapter.sell_market("KRW-BTC", amount)
            if result:
                return {
                    "success": True,
                    "price": order.price,
                    "size": amount,
                }
            return {"success": False, "error": "Sell order failed"}

        return {"success": False, "error": f"Unknown action: {order.action}"}

    def _execute_binance_live(self, adapter: Any, order: Order) -> Dict[str, Any]:
        """Execute Binance futures live order."""
        if order.action == "buy":
            # Close short position (buy to cover)
            result = adapter.close_position("BTCUSDT")
            if result:
                return {"success": True, "price": order.price, "size": 0}
            return {"success": False, "error": "Failed to close position"}

        elif order.action == "sell":
            # Open short position
            account_info = adapter.get_account_info()
            if not account_info:
                return {"success": False, "error": "Failed to get account"}

            available = float(account_info.get("available_balance", 0))
            amount = available * order.fraction

            if amount < 10:  # Minimum USDT
                return {"success": False, "error": "Amount below minimum"}

            result = adapter.open_short("BTCUSDT", amount)
            if result:
                return {
                    "success": True,
                    "price": order.price,
                    "size": amount / order.price,
                }
            return {"success": False, "error": "Short order failed"}

        return {"success": False, "error": f"Unknown action: {order.action}"}

    async def _check_expired_orders(self) -> None:
        """Check for and expire old pending orders."""
        now = datetime.now()
        expired = []

        for order_id, order in self._pending_orders.items():
            if order.status == OrderStatus.PENDING:
                age = (now - order.created_at).total_seconds()
                if age > self.order_timeout:
                    order.status = OrderStatus.EXPIRED
                    expired.append(order_id)
                    logger.warning(f"Order expired: {order_id}")

        for order_id in expired:
            order = self._pending_orders.pop(order_id)
            self._move_to_completed(order)

    def _move_to_completed(self, order: Order) -> None:
        """Move order from pending to completed."""
        if order.id in self._pending_orders:
            del self._pending_orders[order.id]

        self._completed_orders.append(order)

        # Trim completed orders
        if len(self._completed_orders) > self._max_completed:
            self._completed_orders = self._completed_orders[-self._max_completed:]

    async def drain(self) -> None:
        """Wait for all pending orders to complete."""
        while not self._queue.empty() or self._pending_orders:
            await asyncio.sleep(0.1)

    def get_order(self, order_id: str) -> Optional[Order]:
        """Get order by ID."""
        if order_id in self._pending_orders:
            return self._pending_orders[order_id]

        for order in self._completed_orders:
            if order.id == order_id:
                return order

        return None

    def get_stats(self) -> Dict[str, Any]:
        """Get executor statistics."""
        return {
            "execution_mode": self.execution_mode,
            "started": self._started,
            "queue_size": self._queue.qsize(),
            "pending_count": len(self._pending_orders),
            "completed_count": len(self._completed_orders),
            "submitted_count": self._submitted_count,
            "filled_count": self._filled_count,
            "failed_count": self._failed_count,
            "order_timeout": self.order_timeout,
        }
