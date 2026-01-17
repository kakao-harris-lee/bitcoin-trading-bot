# trading/engine.py
"""Lightweight trading engine orchestrator."""
from __future__ import annotations
import asyncio
import json
import logging
import os
import signal
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent / ".env")

from trading.streams import RedisStreams, BinanceFeedTask
from trading.strategies import V35LongTask, SidewaysV2Task, ShortV1Task
from trading.strategies.components import StrategyFactory, create_composite_task
from trading.executor import BinanceClient, AsyncExecutor, PaperExecutor
from trading.notification import TelegramTask

logger = logging.getLogger(__name__)


def _expand_env_vars(obj: Any) -> Any:
    """Recursively expand environment variables in config values."""
    if isinstance(obj, str):
        return os.path.expandvars(obj)
    elif isinstance(obj, dict):
        return {k: _expand_env_vars(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [_expand_env_vars(item) for item in obj]
    return obj


def load_config(path: str) -> dict[str, Any]:
    """Load configuration from JSON file with environment variable expansion."""
    with open(path) as f:
        config = json.load(f)
    return _expand_env_vars(config)


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

        # Initialize risk state (only if not exists)
        current_risk = await self.redis.get_risk()
        if not current_risk:
            await self.redis.set_risk({
                "kill_switch": "false",
                "blocked": "false",
                "daily_pnl": "0",
            })
        else:
            logger.info(f"Loaded existing risk state: daily_pnl={current_risk.get('daily_pnl')}")

        symbols = self.config.get("symbols", ["BTC"])

        # 1. Create feed instances and run warmup BEFORE starting strategies
        # This ensures warmup data is in Redis before strategy consumer groups are created
        feeds: list[BinanceFeedTask] = []
        for symbol in symbols:
            # Spot feed
            spot_feed = BinanceFeedTask(symbol=symbol, redis=self.redis, market="spot")
            feeds.append(spot_feed)

            # Futures feed
            futures_feed = BinanceFeedTask(symbol=symbol, redis=self.redis, market="futures")
            feeds.append(futures_feed)

        # Run warmup for all feeds concurrently and wait for completion
        warmup_tasks = [feed.warmup() for feed in feeds]
        await asyncio.gather(*warmup_tasks, return_exceptions=True)
        logger.info(f"Completed warmup for {len(feeds)} feeds")

        # Now start feed run tasks (warmup already done, will skip to WebSocket streaming)
        for feed in feeds:
            self.tasks.append(asyncio.create_task(feed.run()))

        logger.info(f"Started {len(feeds)} feed tasks")

        # 2. Start strategy tasks (AFTER warmup is complete)
        strategy_config = self.config.get("strategies", {})
        use_components = self.config.get("use_component_strategies", False)

        if use_components:
            # Use new component-based strategy architecture
            await self._start_component_strategies(symbols, strategy_config, mode)
        else:
            # Use legacy strategy tasks (backward compatible)
            v35_long = V35LongTask(symbols=symbols, redis=self.redis, config=strategy_config.get("v35_long"))
            self.tasks.append(asyncio.create_task(v35_long.run()))

            sideways = SidewaysV2Task(symbols=symbols, redis=self.redis, config=strategy_config.get("sideways_v2"))
            self.tasks.append(asyncio.create_task(sideways.run()))

            short = ShortV1Task(symbols=symbols, redis=self.redis, config=strategy_config.get("short_v1"))
            self.tasks.append(asyncio.create_task(short.run()))

            logger.info("Started 3 legacy strategy tasks")

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

        # 3b. Start SmartExecutor if enabled (live mode only)
        if mode == "live" and self.config.get("smart_executor", {}).get("enabled", False):
            from trading.executor.smart_executor import SmartExecutor
            smart_executor = SmartExecutor(
                redis=self.redis,
                binance_client=client,
                config=self.config,
            )
            self.tasks.append(asyncio.create_task(smart_executor.run()))
            logger.info("Started SmartExecutor")

        # 4. Start Telegram notification task
        try:
            telegram = TelegramTask(redis=self.redis)
            self.tasks.append(asyncio.create_task(telegram.run()))
            await telegram.send_start_notification(mode=mode, symbols=symbols)
            logger.info("Started Telegram notification task")
        except ValueError as e:
            logger.warning(f"Telegram notifications disabled: {e}")

        # 5. Set up signal handlers
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

    async def _start_component_strategies(
        self,
        symbols: list[str],
        strategy_config: dict,
        mode: str,
    ) -> None:
        """Start strategies using the component-based architecture.

        Uses StrategyFactory to create Entry/Exit components and
        CompositeStrategyTask to run them.

        Args:
            symbols: List of trading symbols.
            strategy_config: Strategy configuration from allocation.json.
            mode: Trading mode ("paper" or "live").
        """
        # Create factory with Redis client for persistent strategies
        factory = StrategyFactory(redis=self.redis._client)

        # Determine if we should use persistence (live mode)
        use_persistence = mode == "live"

        strategy_names = ["v35_long", "sideways_v2", "short_v1"]
        started = 0

        for name in strategy_names:
            config = strategy_config.get(name, {})

            try:
                # Create entry and exit components
                entry, exit_strat = factory.create_components(
                    strategy_name=name,
                    config=config,
                    persistent=use_persistence,
                )

                # Create composite task
                task = await create_composite_task(
                    name=name,
                    symbols=symbols,
                    redis=self.redis,
                    entry_strategy=entry,
                    exit_strategy=exit_strat,
                    config=config,
                    market=factory.get_market(name),
                    use_smart_exit=config.get("use_smart_exit", False),
                )

                self.tasks.append(asyncio.create_task(task.run()))
                started += 1
                logger.info(f"Started component strategy: {name} (persistent={use_persistence})")

            except Exception as e:
                logger.error(f"Failed to create strategy {name}: {e}")

        logger.info(f"Started {started} component strategy tasks")
