# trading/engine.py
"""Lightweight trading engine orchestrator."""
from __future__ import annotations
import asyncio
import json
import logging
import signal
from pathlib import Path
from typing import Any

from trading.streams import RedisStreams, BinanceFeedTask
from trading.strategies import V35LongTask, SidewaysV2Task, ShortV1Task
from trading.executor import BinanceClient, AsyncExecutor, PaperExecutor

logger = logging.getLogger(__name__)


def load_config(path: str) -> dict[str, Any]:
    """Load configuration from JSON file."""
    with open(path) as f:
        return json.load(f)


class TradingEngine:
    """Lightweight orchestrator for stream-based trading."""

    def __init__(self, config_path: str = "config/strategies/allocation.json"):
        self.config = load_config(config_path)
        self.redis: RedisStreams | None = None
        self.tasks: list[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

    async def start(self, mode: str = "paper") -> None:
        """Start all trading components."""
        logger.info(f"Starting TradingEngine in {mode} mode")

        # Connect to Redis
        self.redis = RedisStreams(url=self.config.get("redis_url", "redis://localhost:6379"))
        await self.redis.connect()

        # Initialize risk state
        await self.redis.set_risk({
            "kill_switch": "false",
            "blocked": "false",
            "daily_pnl": "0",
        })

        symbols = self.config.get("symbols", ["BTC"])

        # 1. Start feed tasks (one per symbol, for both spot and futures)
        for symbol in symbols:
            # Spot feed
            spot_feed = BinanceFeedTask(symbol=symbol, redis=self.redis, market="spot")
            self.tasks.append(asyncio.create_task(spot_feed.run()))

            # Futures feed
            futures_feed = BinanceFeedTask(symbol=symbol, redis=self.redis, market="futures")
            self.tasks.append(asyncio.create_task(futures_feed.run()))

        logger.info(f"Started {len(symbols) * 2} feed tasks")

        # 2. Start strategy tasks
        strategy_config = self.config.get("strategies", {})

        v35_long = V35LongTask(symbols=symbols, redis=self.redis, config=strategy_config.get("v35_long"))
        self.tasks.append(asyncio.create_task(v35_long.run()))

        sideways = SidewaysV2Task(symbols=symbols, redis=self.redis, config=strategy_config.get("sideways_v2"))
        self.tasks.append(asyncio.create_task(sideways.run()))

        short = ShortV1Task(symbols=symbols, redis=self.redis, config=strategy_config.get("short_v1"))
        self.tasks.append(asyncio.create_task(short.run()))

        logger.info("Started 3 strategy tasks")

        # 3. Start executor
        if mode == "paper":
            executor = PaperExecutor(
                redis=self.redis,
                config=self.config.get("paper", {"initial_balance": 10000}),
            )
        else:
            client = BinanceClient(
                api_key=self.config["binance"]["api_key"],
                api_secret=self.config["binance"]["api_secret"],
            )
            await client.connect()
            executor = AsyncExecutor(
                redis=self.redis,
                client=client,
                config=self.config.get("risk", {}),
            )

        self.tasks.append(asyncio.create_task(executor.run()))
        logger.info(f"Started {mode} executor")

        # 4. Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

        logger.info("TradingEngine started successfully")

        # Wait for shutdown
        await self._shutdown_event.wait()

        # Graceful shutdown
        await self._shutdown()

    def _signal_handler(self) -> None:
        """Handle shutdown signals."""
        logger.info("Shutdown signal received")
        self._shutdown_event.set()

    async def _shutdown(self) -> None:
        """Gracefully shut down all tasks."""
        logger.info("Shutting down...")

        # Cancel all tasks
        for task in self.tasks:
            task.cancel()

        # Wait for tasks to complete
        await asyncio.gather(*self.tasks, return_exceptions=True)

        # Disconnect Redis
        if self.redis:
            await self.redis.disconnect()

        logger.info("Shutdown complete")
