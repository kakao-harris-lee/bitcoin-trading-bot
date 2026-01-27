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
from trading.strategies.components import StrategyFactory, create_composite_task
from trading.executor import BinanceClient, AsyncExecutor, PaperExecutor
from trading.executor.paper_smart_executor import PaperSmartExecutor
from trading.notification import TelegramTask
from trading.risk.leverage_manager import LeverageManager
from trading.observability import PeriodicLoggerTask
from trading.indicators.indicator_service import IndicatorService
from trading.strategies.components.context_builder import TradingContextBuilder, PositionManager

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
                "mode": mode,
            })
        else:
            # Always update mode on startup
            await self.redis._client.hset("risk", "mode", mode)
            logger.info(f"Loaded existing risk state: daily_pnl={current_risk.get('daily_pnl')}")

        symbols = self.config.get("symbols", ["BTC"])

        # 1. Create feed instances and run warmup BEFORE starting strategies
        # This ensures warmup data is in Redis before strategy consumer groups are created
        feeds: list[BinanceFeedTask] = []
        for symbol in symbols:
            # Futures feed only (spot trading removed)
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

        # Always use component-based strategy architecture
        await self._start_component_strategies(symbols, strategy_config, mode)

        # 3. Start executor
        if mode == "paper":
            # Create LeverageManager for paper trading (same as live)
            leverage_manager = None
            leverage_config = self.config.get("leverage_manager", {})
            if leverage_config.get("enabled", True):
                leverage_manager = LeverageManager(
                    redis_url=self.config.get("redis_url", "redis://localhost:6379"),
                    daily_loss_limit=leverage_config.get("daily_loss_limit", 0.05),
                )
                logger.info("LeverageManager created for paper trading")

            executor = PaperExecutor(
                redis=self.redis,
                config=self.config.get("paper", {"initial_balance": 10000}),
                leverage_manager=leverage_manager,
            )
        else:
            # Get futures config for leverage
            futures_config = self.config.get("futures", {})
            default_leverage = futures_config.get("default_leverage", 1)

            client = BinanceClient(
                api_key=self.config["binance"]["api_key"],
                api_secret=self.config["binance"]["api_secret"],
                default_leverage=default_leverage,
            )
            await client.connect()

            # Initialize leverage for all trading symbols
            if futures_config.get("enabled", False) and symbols:
                await client.initialize_leverage(symbols, leverage=default_leverage)
                logger.info(f"Initialized {default_leverage}x leverage for {symbols}")

            # Create LeverageManager for risk-adjusted leverage
            leverage_manager = None
            leverage_config = self.config.get("leverage_manager", {})
            if leverage_config.get("enabled", True):
                leverage_manager = LeverageManager(
                    redis_url=self.config.get("redis_url", "redis://localhost:6379"),
                    daily_loss_limit=leverage_config.get("daily_loss_limit", 0.05),
                )
                logger.info("LeverageManager created (will initialize on account sync)")

            executor = AsyncExecutor(
                redis=self.redis,
                client=client,
                config=self.config.get("risk", {}),
                leverage_manager=leverage_manager,
            )

        self.tasks.append(asyncio.create_task(executor.run()))
        logger.info(f"Started {mode} executor")

        # 3b. Start SmartExecutor if enabled
        if self.config.get("smart_executor", {}).get("enabled", False):
            if mode == "live":
                from trading.executor.smart_executor import SmartExecutor
                smart_executor = SmartExecutor(
                    redis=self.redis,
                    binance_client=client,
                    config=self.config,
                )
                self.tasks.append(asyncio.create_task(smart_executor.run()))
                logger.info("Started SmartExecutor (live)")
            else:
                # Paper mode: use simplified forwarder for exit signals
                paper_smart_executor = PaperSmartExecutor(
                    redis=self.redis,
                    config=self.config,
                )
                self.tasks.append(asyncio.create_task(paper_smart_executor.run()))
                logger.info("Started PaperSmartExecutor")

        # 4. Start periodic logger (5-minute system state logging)
        periodic_logger_interval = self.config.get("periodic_logger", {}).get(
            "interval_seconds", 300
        )
        periodic_logger = PeriodicLoggerTask(
            redis=self.redis,
            symbols=symbols,
            interval_seconds=periodic_logger_interval,
        )
        self.tasks.append(asyncio.create_task(periodic_logger.run()))
        logger.info(f"Started periodic logger (interval={periodic_logger_interval}s)")

        # 5. Start Telegram notification task
        try:
            telegram = TelegramTask(redis=self.redis)
            self.tasks.append(asyncio.create_task(telegram.run()))
            await telegram.send_start_notification(mode=mode, symbols=symbols)
            logger.info("Started Telegram notification task")
        except ValueError as e:
            logger.warning(f"Telegram notifications disabled: {e}")

        # 6. Set up signal handlers
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

        Includes centralized IndicatorService for CPU optimization:
        - Before: 4 strategies × 3 symbols = 12 separate indicator calculations
        - After: 1 calculation per symbol, shared by all strategies
        - CPU reduction: ~75% for indicator computation

        Args:
            symbols: List of trading symbols.
            strategy_config: Strategy configuration from allocation.json.
            mode: Trading mode ("paper" or "live").
        """
        # Create factory with Redis client for persistent strategies
        factory = StrategyFactory(redis=self.redis._client)

        # Determine if we should use persistence (live mode)
        use_persistence = mode == "live"

        # Create shared IndicatorService for CPU optimization
        # All strategies share the same indicator calculations
        indicator_cache_ttl = self.config.get("indicator_cache_ttl", 60)
        indicator_service = IndicatorService(cache_ttl=indicator_cache_ttl)
        logger.info(f"Created shared IndicatorService (cache_ttl={indicator_cache_ttl}s)")

        # Create shared TradingContextBuilder for centralized context
        position_manager = PositionManager(self.redis._client)
        context_builder = TradingContextBuilder(
            indicator_service=indicator_service,
            position_manager=position_manager,
        )
        logger.info("Created shared TradingContextBuilder")

        # Use strategies defined in allocation.json
        # This allows us to enable/disable strategies via config
        strategy_names = list(strategy_config.keys())
        started = 0

        for name in strategy_names:
            # Skip if disabled or not configured to run
            config = strategy_config.get(name, {})
            # Basic check: if config is empty, maybe skip?
            # But the factory acts as the registry check.

            try:
                # Create entry and exit components
                entry, exit_strat = factory.create_components(
                    strategy_name=name,
                    config=config,
                    persistent=use_persistence,
                )

                # Create composite task with shared indicator service
                task = await create_composite_task(
                    name=name,
                    symbols=symbols,
                    redis=self.redis,
                    entry_strategy=entry,
                    exit_strategy=exit_strat,
                    config=config,
                    market=factory.get_market(name),
                    use_smart_exit=config.get("use_smart_exit", False),
                    indicator_service=indicator_service,
                    context_builder=context_builder,
                    regime_version=config.get("regime_version", "v1"),
                )

                self.tasks.append(asyncio.create_task(task.run()))
                started += 1
                logger.info(f"Started component strategy: {name} (persistent={use_persistence})")

            except Exception as e:
                logger.error(f"Failed to create strategy {name}: {e}")

        logger.info(f"Started {started} component strategy tasks (shared indicator service)")
