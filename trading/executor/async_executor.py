# trading/executor/async_executor.py
"""Async executor for processing order stream."""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.executor.binance_client import BinanceClient

logger = logging.getLogger(__name__)


class AsyncExecutor:
    """Consumes orders stream and executes via Binance API."""

    def __init__(
        self,
        redis: RedisStreams,
        client: BinanceClient,
        config: dict,
    ):
        self.redis = redis
        self.client = client
        self.config = config
        self.max_daily_loss = config.get("max_daily_loss", 500)  # USDT
        self._running = False

    async def run(self) -> None:
        """Main loop: consume and execute orders."""
        self._running = True
        group = "executor"
        consumer = "executor-main"

        await self.redis.create_consumer_group("orders", group)
        logger.info("AsyncExecutor started")

        while self._running:
            try:
                messages = await self.redis.consume(
                    "orders", group, consumer, count=1, block_ms=1000
                )

                for msg in messages:
                    await self._process_order(msg)
                    await self.redis.ack("orders", group, msg["_id"])

            except Exception as e:
                logger.error(f"Executor error: {e}")
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal executor to stop."""
        self._running = False

    async def _process_order(self, order: dict[str, Any]) -> dict | None:
        """Process single order."""
        # Check risk gates
        if not await self._pass_risk_gates():
            logger.warning(f"Order {order['id']} blocked by risk gates")
            await self._publish_rejection(order, "risk_blocked")
            return None

        try:
            # Execute order
            fill = await self.client.market_order(
                symbol=order["symbol"],
                side=order["side"],
                quantity=float(order["quantity"]),
                market=order["market"],
            )

            # Update position
            await self._update_position(order, fill)

            # Update daily P&L tracking
            await self._update_daily_pnl(order, fill)

            # Publish trade notification
            await self._publish_trade(order, fill)

            logger.info(f"Order {order['id']} filled: {fill}")
            return fill

        except Exception as e:
            logger.error(f"Order {order['id']} failed: {e}")
            await self._publish_rejection(order, str(e))
            return None

    async def _pass_risk_gates(self) -> bool:
        """Check all risk conditions."""
        risk = await self.redis.get_risk()

        # Kill switch
        if risk.get("kill_switch") == "true":
            logger.warning("Kill switch is ON")
            return False

        # Blocked flag
        if risk.get("blocked") == "true":
            logger.warning("Trading is blocked")
            return False

        # Daily loss limit
        daily_pnl = float(risk.get("daily_pnl", 0))
        if daily_pnl < -self.max_daily_loss:
            logger.warning(f"Daily loss limit exceeded: {daily_pnl}")
            return False

        return True

    async def _update_position(self, order: dict, fill: dict) -> None:
        """Update position in Redis."""
        await self.redis.set_position(order["symbol"], order["market"], {
            "quantity": str(fill["filled_qty"]),
            "entry_price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "entry_time": str(int(time.time() * 1000)),
            "side": order["side"],
        })

    async def _update_daily_pnl(self, order: dict, fill: dict) -> None:
        """Update daily P&L tracking."""
        # For now, just track costs (entry has no realized P&L)
        # Real P&L tracking happens on exit
        pass

    async def _publish_trade(self, order: dict, fill: dict) -> None:
        """Publish trade to trades stream."""
        await self.redis.publish("trades", {
            "order_id": str(fill["order_id"]),
            "symbol": order["symbol"],
            "side": order["side"],
            "market": order["market"],
            "quantity": str(fill["filled_qty"]),
            "price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "timestamp": str(int(time.time() * 1000)),
        })

    async def _publish_rejection(self, order: dict, reason: str) -> None:
        """Publish order rejection to alerts stream."""
        await self.redis.publish("alerts", {
            "type": "order_rejected",
            "order_id": order["id"],
            "symbol": order["symbol"],
            "reason": reason,
            "timestamp": str(int(time.time() * 1000)),
        })
