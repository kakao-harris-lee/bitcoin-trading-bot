# trading/executor/paper_smart_executor.py
"""Paper smart executor - forwards exit signals to orders stream for paper trading."""
# pylint: disable=broad-exception-caught
from __future__ import annotations
import asyncio
import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)


class PaperSmartExecutor:
    """Consumes exit_signals and forwards to orders stream for paper trading.

    In live mode, SmartExecutor handles laddered execution with real orders.
    In paper mode, this simplified version forwards exit signals directly
    to the orders stream for immediate execution by PaperExecutor.
    """

    def __init__(self, redis: RedisStreams, config: dict):
        self.redis = redis
        self.config = config
        self._running = False

    async def run(self) -> None:
        """Main loop: consume exit_signals and forward to orders."""
        self._running = True
        group = "paper-smart-executor"
        consumer = "paper-smart-main"

        try:
            await self.redis.create_consumer_group("exit_signals", group)
        except Exception as e:
            logger.debug("Consumer group creation: %s", e)

        logger.info("PaperSmartExecutor started - forwarding exit_signals to orders")

        while self._running:
            try:
                messages = await self.redis.consume(
                    "exit_signals", group, consumer, count=10, block_ms=1000
                )

                for msg in messages:
                    await self._process_exit_signal(msg)
                    await self.redis.ack("exit_signals", group, msg["_id"])

            except Exception as e:
                logger.error("PaperSmartExecutor error: %s", e)
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal executor to stop."""
        self._running = False

    async def _process_exit_signal(self, signal: dict) -> None:
        """Convert exit signal to order and publish to orders stream."""
        # Extract signal fields
        symbol = signal.get("symbol")
        side = signal.get("side")
        market = signal.get("market")
        quantity = signal.get("quantity")
        strategy = signal.get("strategy")
        reason = signal.get("reason", "")
        leverage = signal.get("leverage", 1)

        if not all([symbol, side, market, quantity, strategy]):
            logger.warning("Invalid exit signal, missing fields: %s", signal)
            return

        # Create order from exit signal
        order = {
            "id": signal.get("id", f"exit-{int(time.time()*1000)}"),
            "symbol": symbol,
            "side": side,
            "market": market,
            "quantity": quantity,
            "strategy": strategy,
            "reason": reason,
            "leverage": leverage,
        }

        # Publish to orders stream for PaperExecutor to handle
        await self.redis.publish("orders", order)
        logger.info(
            "PaperSmartExecutor forwarded exit: %s %s %s (%s)",
            symbol,
            side,
            quantity,
            reason,
        )
