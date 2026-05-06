# trading/engine.py
"""Lightweight trading engine orchestrator."""

# pylint: disable=logging-fstring-interpolation,broad-exception-caught

from __future__ import annotations
import asyncio
import json
import logging
import os
import signal
from datetime import date
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
from trading.strategies.components.context_builder import (
    TradingContextBuilder,
    PositionManager,
)
from trading.core.runtime_defaults import load_allocation_symbols
from trading.core.llm_provider import (
    collect_llm_provider_health,
    summarize_llm_provider_health,
)

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
    with open(path, encoding="utf-8") as f:
        config = json.load(f)
    return _expand_env_vars(config)


class TradingEngine:
    """Lightweight orchestrator for stream-based trading."""

    def __init__(self, config_path: str = "config/strategies/allocation.json"):
        self.config = load_config(config_path)
        self.redis: RedisStreams | None = None
        self.tasks: list[asyncio.Task] = []
        self._shutdown_event = asyncio.Event()

    def _get_redis_client(self):
        if not self.redis:
            return None
        return getattr(self.redis, "_client", None)

    def _resolve_feed_market(self, strategy_config: dict[str, Any]) -> str:
        """Resolve feed market.

        The system is spot-only. Keep the top-level override for compatibility,
        but coerce everything back to spot to avoid mixed-market drift.
        """
        return "spot"

    def _resolve_feed_warmup_enabled(self) -> bool:
        """Return whether feed-level warmup is enabled."""
        return bool(self.config.get("feed_warmup_enabled", False))

    def _resolve_feed_stream_type(self) -> str:
        """Return Binance feed stream type (`miniTicker` or `bookTicker`)."""
        raw = str(self.config.get("feed_stream_type", "miniTicker")).strip().lower()
        if raw in {"bookticker", "book_ticker"}:
            return "bookTicker"
        return "miniTicker"

    async def start(self, mode: str = "paper") -> None:
        """Start all trading components."""
        if mode == "live" and os.getenv("ENABLE_LIVE_TRADING") != "1":
            raise RuntimeError(
                "Live mode is not armed. Set ENABLE_LIVE_TRADING=1 to proceed."
            )

        logger.info(f"Starting TradingEngine in {mode} mode")
        self._log_llm_provider_health(mode)

        # Connect to Redis
        self.redis = RedisStreams(
            url=self.config.get("redis_url", "redis://localhost:6379")
        )
        await self.redis.connect()

        # Initialize/sync risk state.
        await self._initialize_risk_state(mode)

        symbols = self.config.get("symbols") or load_allocation_symbols()

        strategy_config = self.config.get("strategies", {})
        feed_market = self._resolve_feed_market(strategy_config)
        feed_warmup_enabled = self._resolve_feed_warmup_enabled()
        feed_stream_type = self._resolve_feed_stream_type()
        logger.info(
            "Feed config resolved: market=%s, warmup_enabled=%s, stream_type=%s",
            feed_market,
            feed_warmup_enabled,
            feed_stream_type,
        )

        # 1. Create feed instances and optionally run feed warmup BEFORE starting strategies
        feeds: list[BinanceFeedTask] = []
        for symbol in symbols:
            feed = BinanceFeedTask(
                symbol=symbol,
                redis=self.redis,
                market=feed_market,
                stream_type=feed_stream_type,
                warmup_enabled=feed_warmup_enabled,
            )
            feeds.append(feed)

        if feed_warmup_enabled:
            # Run warmup for all feeds concurrently and wait for completion.
            warmup_tasks = [feed.warmup() for feed in feeds]
            await asyncio.gather(*warmup_tasks, return_exceptions=True)
            logger.info(f"Completed warmup for {len(feeds)} feeds")
        else:
            logger.info("Skipped feed warmup (feed_warmup_enabled=false)")

        # Now start feed run tasks (warmup already done, will skip to WebSocket streaming)
        for feed in feeds:
            self.tasks.append(asyncio.create_task(feed.run()))

        logger.info(f"Started {len(feeds)} feed tasks")

        # 2. Start strategy tasks (AFTER optional feed warmup is complete)
        # Always use component-based strategy architecture
        await self._start_component_strategies(symbols, strategy_config, mode)

        # 3. Start executor
        if mode == "paper":
            paper_config = dict(self.config.get("paper", {"initial_balance": 10000}))
            paper_config.setdefault("symbols", symbols)
            paper_config.setdefault(
                "max_daily_loss",
                self.config.get("risk", {}).get("max_daily_loss", 500),
            )
            paper_config.setdefault(
                "trade_log_db_path",
                str(Path(__file__).parent.parent / "data" / "paper_trading_results.db"),
            )

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
                config=paper_config,
                leverage_manager=leverage_manager,
            )
        else:
            client = BinanceClient(
                api_key=self.config["binance"]["api_key"],
                api_secret=self.config["binance"]["api_secret"],
            )
            await client.connect()

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
        await self._start_telegram_notifications(mode=mode, symbols=symbols)

        # 6. Set up signal handlers
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, self._signal_handler)

        logger.info("TradingEngine started successfully")

        # Wait for shutdown
        await self._shutdown_event.wait()

        # Graceful shutdown
        await self._shutdown()

    async def _initialize_risk_state(self, mode: str) -> None:
        """Initialize risk hash and normalize cross-mode startup behavior."""
        assert self.redis is not None

        current_risk = await self.redis.get_risk()
        current_day = date.today().isoformat()
        if not current_risk:
            await self.redis.set_risk(
                {
                    "kill_switch": "false",
                    "blocked": "false",
                    "daily_pnl": "0",
                    "daily_pnl_date": current_day,
                    "mode": mode,
                }
            )
            return

        previous_mode = current_risk.get("mode")
        updates: dict[str, str] = {"mode": mode}
        stored_day = str(current_risk.get("daily_pnl_date", "")).strip()

        # Avoid carrying paper PnL into live risk gates (and vice versa).
        if previous_mode and previous_mode != mode:
            updates["daily_pnl"] = "0"
            updates["daily_pnl_date"] = current_day
            logger.warning(
                f"Mode changed ({previous_mode} -> {mode}); resetting daily_pnl to 0."
            )
        elif stored_day != current_day:
            updates["daily_pnl"] = "0"
            updates["daily_pnl_date"] = current_day
            logger.info(
                "New trading day detected (%s -> %s); resetting daily_pnl to 0.",
                stored_day or "missing",
                current_day,
            )

        redis_client = self._get_redis_client()
        if redis_client is not None:
            await redis_client.hset("risk", mapping=updates)
        logger.info(
            f"Loaded existing risk state: daily_pnl={current_risk.get('daily_pnl')}"
        )

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

    async def _start_telegram_notifications(
        self, mode: str, symbols: list[str]
    ) -> None:
        """Start Telegram notification background tasks without blocking startup."""
        assert self.redis is not None

        try:
            telegram = TelegramTask(redis=self.redis)
        except ValueError as exc:
            logger.warning(f"Telegram notifications disabled: {exc}")
            return

        self.tasks.append(asyncio.create_task(telegram.run()))
        self.tasks.append(
            asyncio.create_task(
                telegram.send_start_notification(mode=mode, symbols=symbols)
            )
        )
        logger.info("Started Telegram notification task")

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
        redis_client = self._get_redis_client()
        factory = StrategyFactory(redis=redis_client)

        # Determine if we should use persistence (live mode)
        use_persistence = mode == "live"

        # Create shared IndicatorService for CPU optimization
        # All strategies share the same indicator calculations
        indicator_cache_ttl = self.config.get("indicator_cache_ttl", 60)
        indicator_service = IndicatorService(cache_ttl=indicator_cache_ttl)
        logger.info(
            f"Created shared IndicatorService (cache_ttl={indicator_cache_ttl}s)"
        )

        # Create shared TradingContextBuilder for centralized context
        position_manager = PositionManager(redis_client)
        regime_thresholds = self.config.get("defaults", {}).get("regime_thresholds", {})
        context_builder = TradingContextBuilder(
            indicator_service=indicator_service,
            position_manager=position_manager,
            regime_thresholds=regime_thresholds,
        )
        logger.info("Created shared TradingContextBuilder")

        # Use strategies defined in allocation.json
        # This allows us to enable/disable strategies via config
        strategy_names = list(strategy_config.keys())
        started = 0
        regime_defaults = self.config.get("defaults", {}).get("regime_v2", {})
        regime_runtime_overlay_defaults = self.config.get("defaults", {}).get(
            "regime_runtime_overlay", {}
        )
        mtf_enabled_by_symbol = regime_defaults.get("mtf_enabled_by_symbol", {})

        for name in strategy_names:
            # Skip if disabled or not configured to run
            config = strategy_config.get(name, {})

            # Check if strategy is explicitly disabled
            if config.get("enabled") is False:
                logger.info(f"Skipping disabled strategy: {name}")
                continue

            try:
                # Allow per-strategy symbol overrides
                strategy_symbols = config.get("symbols", symbols)
                if not strategy_symbols:
                    logger.warning(f"Skipping strategy {name}: no symbols configured")
                    continue

                # Apply v2 regime defaults unless strategy explicitly sets version
                effective_config = dict(config)
                # Pass global symbols for portfolio risk tracking
                effective_config["_global_symbols"] = symbols
                if "regime_version" not in effective_config and regime_defaults:
                    effective_config["regime_version"] = "v2"
                    for key in (
                        "bbw_block_threshold",
                        "bbw_confirm_threshold",
                        "volume_block_ratio",
                        "volume_boost_ratio",
                        "mtf_enabled",
                    ):
                        if key not in effective_config and key in regime_defaults:
                            effective_config[key] = regime_defaults[key]

                # Optional global per-symbol MTF override.
                # This allows quick on/off by asset without editing each strategy.
                if strategy_symbols and isinstance(mtf_enabled_by_symbol, dict):
                    if len(strategy_symbols) == 1:
                        symbol_key = strategy_symbols[0]
                        if symbol_key in mtf_enabled_by_symbol:
                            effective_config["mtf_enabled"] = bool(
                                mtf_enabled_by_symbol[symbol_key]
                            )

                # Optional runtime regime overlay defaults (safe-off unless enabled).
                if (
                    "regime_runtime_overlay" not in effective_config
                    and regime_runtime_overlay_defaults
                ):
                    effective_config["regime_runtime_overlay"] = (
                        regime_runtime_overlay_defaults
                    )

                # Create entry and exit components
                entry, exit_strat = factory.create_components(
                    strategy_name=name,
                    config=effective_config,
                    persistent=use_persistence,
                )

                # Create composite task with shared indicator service
                task = await create_composite_task(
                    name=name,
                    symbols=strategy_symbols,
                    redis=self.redis,
                    entry_strategy=entry,
                    exit_strategy=exit_strat,
                    config=effective_config,
                    market=factory.get_market(name, effective_config),
                    use_smart_exit=effective_config.get("use_smart_exit", False),
                    emit_events=bool(
                        (self.config.get("observability") or {}).get(
                            "emit_events", False
                        )
                    ),
                    indicator_service=indicator_service,
                    context_builder=context_builder,
                    regime_version=effective_config.get("regime_version", "v2"),
                )

                self.tasks.append(asyncio.create_task(task.run()))
                started += 1
                logger.info(
                    f"Started component strategy: {name} (persistent={use_persistence})"
                )

            except Exception as e:
                logger.error(f"Failed to create strategy {name}: {e}")

        logger.info(
            f"Started {started} component strategy tasks (shared indicator service)"
        )

    def _log_llm_provider_health(self, mode: str) -> None:
        reports = collect_llm_provider_health(self.config)
        if not reports:
            return

        warnings, errors = summarize_llm_provider_health(reports, mode=mode)
        for report in reports:
            logger.info(
                "LLM provider readiness %s: provider=%s model=%s healthy=%s fallback=%s reason=%s",
                report.strategy,
                report.provider,
                report.model or "-",
                "yes" if report.healthy else "no",
                "enabled" if report.fallback_enabled else "disabled",
                report.reason,
            )

        for message in warnings:
            logger.warning("%s", message)
        if errors:
            raise RuntimeError(
                "LLM provider readiness check failed: " + "; ".join(errors)
            )
