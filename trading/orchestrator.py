"""
Trading Orchestrator - Single entry point for all trading coroutines

Spawns and monitors:
- Feed publishers (Upbit, Binance)
- Regime publisher
- Strategy coroutines (V35, SHORT_V1, SIDEWAYS_V2, H4, PREMIUM)
- Trade executor
- Telegram command handler (kill switch control)
"""

import asyncio
import logging
import signal
from datetime import datetime
from typing import Dict, Any, Optional

from trading.core.redis_client import RedisClient
from trading.core.config import Config
from trading.publishers.feed_publisher import FeedPublisher
from trading.publishers.regime_publisher import RegimePublisher
from trading.strategies import (
    V35Strategy,
    ShortV1Strategy,
    SidewaysV2Strategy,
    H4Strategy,
    PremiumStrategy,
)
from trading.executor.trade_executor import TradeExecutor
from trading.adapters import UpbitTrader, BinanceFuturesTrader
from trading.notification import TelegramNotifier
from trading.risk.risk_controls import kill_switch_active
from core.types import Exchange

logger = logging.getLogger(__name__)


class TradingOrchestrator:
    """Spawns and monitors all trading coroutines."""

    def __init__(self, config: Config):
        self.config = config
        self.redis = RedisClient(config.redis)
        self.tasks: Dict[str, asyncio.Task] = {}
        self.running = True
        self.logger = logging.getLogger("orchestrator")

        # Components (initialized in run())
        self.notifier: Optional[TelegramNotifier] = None
        self.upbit_adapter: Optional[UpbitTrader] = None
        self.binance_adapter: Optional[BinanceFuturesTrader] = None
        self.executor: Optional[TradeExecutor] = None
        self._telegram_cmd = None

    async def run(self):
        """Main entry point - spawn all coroutines."""
        self.logger.info("=" * 60)
        self.logger.info("  Trading Orchestrator Starting")
        self.logger.info("=" * 60)

        # Connect Redis
        if not await self.redis.connect():
            self.logger.error("Failed to connect to Redis")
            return

        # Initialize adapters
        self.upbit_adapter = UpbitTrader()
        self.binance_adapter = BinanceFuturesTrader()

        # Initialize notifier if enabled
        if self.config.telegram.enabled:
            try:
                self.notifier = TelegramNotifier()
            except ValueError as e:
                self.logger.warning(f"Telegram notifier disabled: {e}")

        # Create executor (need reference for kill switch commands)
        self.executor = TradeExecutor(
            self.redis,
            self.upbit_adapter,
            self.binance_adapter,
            self.config,
            self.notifier
        )

        # Initialize Telegram command handler for kill switch control
        self._setup_telegram_commands()

        # Define all components
        components = {
            # Publishers
            "feed:upbit": FeedPublisher(Exchange.UPBIT, self.redis, self.config),
            "feed:binance": FeedPublisher(Exchange.BINANCE, self.redis, self.config),
            "regime": RegimePublisher(self.redis, self.config),

            # Strategies
            "strategy:v35": V35Strategy(self.redis, self.config),
            "strategy:short_v1": ShortV1Strategy(self.redis, self.config),
            "strategy:sideways_v2": SidewaysV2Strategy(self.redis, self.config),
            "strategy:h4": H4Strategy(self.redis, self.config),
            "strategy:premium": PremiumStrategy(self.redis, self.config),

            # Executor
            "executor": self.executor,
        }

        # Spawn with auto-restart
        for name, component in components.items():
            self.tasks[name] = asyncio.create_task(
                self._run_with_restart(name, component)
            )
            self.logger.info(f"  Started: {name}")

        self.logger.info("=" * 60)
        self.logger.info("  All components started")
        self.logger.info("=" * 60)

        # Setup signal handlers
        loop = asyncio.get_event_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, self._handle_shutdown)

        # Wait for all tasks
        try:
            await asyncio.gather(*self.tasks.values())
        except asyncio.CancelledError:
            pass
        finally:
            await self._cleanup()

    async def _run_with_restart(self, name: str, component):
        """Run component with auto-restart on failure."""
        restart_count = 0
        max_restarts = 10

        while self.running and restart_count < max_restarts:
            try:
                self.logger.info(f"[{name}] Starting...")
                await component.run()

            except asyncio.CancelledError:
                self.logger.info(f"[{name}] Cancelled")
                break

            except Exception as e:
                restart_count += 1
                self.logger.error(f"[{name}] Crashed: {e}", exc_info=True)

                if self.notifier and self.running:
                    try:
                        await self.notifier.send_message(
                            f"⚠️ {name} crashed: {e}\n"
                            f"Restart {restart_count}/{max_restarts} in 5s..."
                        )
                    except Exception:
                        pass

                if self.running:
                    await asyncio.sleep(5)

        if restart_count >= max_restarts:
            self.logger.error(f"[{name}] Max restarts reached, giving up")

    def _setup_telegram_commands(self):
        """Initialize Telegram command handler for kill switch control."""
        if not self.notifier:
            self.logger.info("Telegram commands disabled (no notifier)")
            return

        try:
            from trading.notification.telegram_commands import TelegramCommandHandler
        except ImportError:
            self.logger.warning("TelegramCommandHandler not available")
            return

        try:
            self._telegram_cmd = TelegramCommandHandler(self.notifier)
            self._telegram_cmd.register_command("kill_on", lambda _: self._cmd_kill_switch(True))
            self._telegram_cmd.register_command("kill_off", lambda _: self._cmd_kill_switch(False))
            self._telegram_cmd.register_command("kill_status", lambda _: self._cmd_kill_status())
            self._telegram_cmd.start_polling()
            self.logger.info("Telegram commands enabled: /kill_on /kill_off /kill_status")
        except Exception as e:
            self.logger.error(f"Failed to setup Telegram commands: {e}")

    def _cmd_kill_switch(self, activate: bool):
        """Handle kill switch command from Telegram."""
        if self.executor:
            self.executor.risk.set_kill_switch(activate)
            status = "ACTIVATED" if activate else "DEACTIVATED"
            msg = f"Kill switch {status}"
            self.logger.warning(msg)
            if self.notifier:
                try:
                    self.notifier.send_message(msg)
                except Exception:
                    pass

    def _cmd_kill_status(self):
        """Handle kill status command from Telegram."""
        if self.executor:
            is_on = self.executor.risk.kill_switch_on
            daily_pnl = self.executor.risk.get_daily_pnl()
            total_pnl = sum(daily_pnl.values())

            msg = (
                f"Kill Switch: {'ON' if is_on else 'OFF'}\n"
                f"Daily P&L: {total_pnl:+.2f}%\n"
                f"By strategy: {daily_pnl}"
            )
            if self.notifier:
                try:
                    self.notifier.send_message(msg)
                except Exception:
                    pass

    def _handle_shutdown(self):
        """Handle shutdown signal."""
        self.logger.info("Shutdown signal received...")
        self.running = False

        # Stop Telegram command polling
        if self._telegram_cmd:
            try:
                self._telegram_cmd.stop_polling()
            except Exception:
                pass

        for task in self.tasks.values():
            task.cancel()

    async def _cleanup(self):
        """Cleanup on shutdown."""
        self.logger.info("Cleaning up...")

        # Stop all components
        for name, task in self.tasks.items():
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Disconnect Redis
        await self.redis.disconnect()

        self.logger.info("Cleanup complete")


async def run_orchestrator(config: Optional[Config] = None):
    """Convenience function to run the orchestrator."""
    if config is None:
        config = Config.from_env()

    orchestrator = TradingOrchestrator(config)
    await orchestrator.run()
