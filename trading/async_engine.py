"""
AsyncTradingEngine - Event-driven async trading engine.

Full async rewrite for maximum speed:
- WebSocket price feeds (FeedHandler)
- In-memory data cache (no DB per cycle)
- Real-time FX rates (exchangerate-api.com)
- Event-driven on >0.1% price change
- No Redis dependency (in-process queues)

Target: <50ms full iteration vs current 500-1000ms
"""

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, Optional, Any, Callable

from .core.price_hub import PriceHub, PriceMessage, PriceEvent
from .core.data_cache import DataCache
from .core.fx_cache import FXRateCache
from .core.health_monitor import HealthMonitor
from .data.simple_feed_handler import SimpleFeedHandler
from .strategy.strategy_runner import StrategyRunner, Signal
from .execution.async_executor import AsyncExecutor
from .risk.risk_controls import kill_switch_active, RiskConfig
from .risk.premium_tracker import PremiumTracker

logger = logging.getLogger(__name__)


@dataclass
class AsyncEngineConfig:
    """Configuration for AsyncTradingEngine."""
    execution_mode: str = "paper"
    paper_upbit_capital: float = 10_000_000
    paper_binance_capital: float = 10_000
    telegram_enabled: bool = True
    telegram_commands_enabled: bool = False
    kill_switch_file: str = "analysis/KILL_SWITCH"
    price_change_threshold: float = 0.001  # 0.1%
    regime_update_interval: int = 300  # 5 minutes
    log_dir: Optional[Path] = None

    @classmethod
    def from_args(cls, args: Any) -> "AsyncEngineConfig":
        """Create config from argparse args."""
        return cls(
            execution_mode=getattr(args, "mode", "paper"),
            paper_upbit_capital=getattr(args, "paper_upbit_capital", 10_000_000),
            paper_binance_capital=getattr(args, "paper_binance_capital", 10_000),
            telegram_enabled=not getattr(args, "no_telegram", False),
            telegram_commands_enabled=getattr(args, "telegram_commands", False),
        )


class AsyncTradingEngine:
    """
    Event-driven async trading engine.

    Architecture:
    - FeedHandler: WebSocket price feeds
    - PriceHub: Central price cache with subscriber notification
    - DataCache: In-memory OHLCV with hybrid updates
    - FXRateCache: Real-time USD/KRW rates
    - StrategyRunner: Async strategy evaluation
    - AsyncExecutor: Order queue processing
    - HealthMonitor: Continuous health checks
    """

    def __init__(self, config: AsyncEngineConfig):
        """
        Args:
            config: Engine configuration
        """
        self.config = config
        self.execution_mode = config.execution_mode
        self._running = False
        self._started_at: Optional[datetime] = None

        # Log directory
        self.log_dir = config.log_dir or Path(__file__).parent.parent / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Risk config
        self.risk_config = RiskConfig(kill_switch_file=config.kill_switch_file)

        # Core components
        self.price_hub = PriceHub(
            price_change_threshold=config.price_change_threshold,
        )
        self.data_cache = DataCache(exchange="upbit")
        self.fx_cache = FXRateCache(
            on_rate_change=self.price_hub.update_fx_rate,
        )
        self.feed_handler = SimpleFeedHandler(
            upbit_symbols=["KRW-BTC"],
            binance_symbols=["btcusdt"],
        )

        # Strategy runners
        self.upbit_runner = StrategyRunner(
            exchange="upbit",
            price_hub=self.price_hub,
            data_cache=self.data_cache,
        )
        self.binance_runner = StrategyRunner(
            exchange="binance",
            price_hub=self.price_hub,
            data_cache=self.data_cache,
        )

        # Executor
        self.executor = AsyncExecutor(
            execution_mode=config.execution_mode,
            on_order_filled=self._on_order_filled,
        )

        # Monitoring
        self.health_monitor = HealthMonitor(
            engine=self,
            on_alert=self._on_health_alert if config.telegram_enabled else None,
        )
        self.premium_tracker = PremiumTracker()

        # Regime tracking
        self._regime_cache: Optional[str] = None
        self._regime_updated_at: Optional[datetime] = None

        # Telegram
        self._telegram = None
        if config.telegram_enabled:
            try:
                from .notification.telegram_notifier import TelegramNotifier
                self._telegram = TelegramNotifier()
            except Exception as e:
                logger.warning(f"Telegram init failed: {e}")

        # Statistics
        self._iteration_count = 0
        self._signal_count = 0

    async def start(self) -> None:
        """Initialize and start all components."""
        if self._running:
            logger.warning("Engine already running")
            return

        logger.info("=" * 70)
        logger.info(f"  AsyncTradingEngine [{self.execution_mode.upper()}]")
        logger.info("=" * 70)

        # 1. Load initial data
        logger.info("Loading initial data...")
        await self.data_cache.start()

        # 2. Start FX rate cache
        logger.info("Starting FX rate cache...")
        await self.fx_cache.start()

        # 3. Start feed handler (WebSockets)
        logger.info("Connecting WebSockets...")
        await self.feed_handler.start()

        # 4. Start executor
        logger.info("Starting executor...")
        await self.executor.start()

        # 5. Start health monitor
        await self.health_monitor.start()

        # 6. Send startup notification
        self._send_startup_notification()

        # 7. Start main loop
        self._running = True
        self._started_at = datetime.now()

        logger.info("AsyncTradingEngine started")

        await asyncio.gather(
            self._main_loop(),
            self._regime_update_loop(),
            self._price_feed_loop(),
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("Stopping AsyncTradingEngine...")
        self._running = False

        await self.health_monitor.stop()
        await self.executor.drain()
        await self.executor.stop()
        await self.feed_handler.stop()
        await self.fx_cache.stop()
        await self.data_cache.stop()

        logger.info("AsyncTradingEngine stopped")

    async def _price_feed_loop(self) -> None:
        """Receive prices from FeedHandler and update PriceHub."""
        while self._running:
            try:
                # Get latest prices from FeedHandler
                upbit_msg = self.feed_handler.get_last_price("upbit", "KRW-BTC")
                binance_msg = self.feed_handler.get_last_price("binance", "BTCUSDT")

                if upbit_msg:
                    price_msg = PriceMessage(
                        exchange="upbit",
                        symbol="KRW-BTC",
                        price=upbit_msg.price,
                        volume=upbit_msg.volume_24h,
                        timestamp=datetime.fromtimestamp(upbit_msg.timestamp / 1000)
                        if upbit_msg.timestamp > 1e12 else datetime.now(),
                    )
                    await self.price_hub.update_price("upbit", price_msg)

                    # Update data cache
                    self.data_cache.update_from_tick(
                        price=upbit_msg.price,
                        volume=upbit_msg.ohlcv.volume if upbit_msg.ohlcv else 0,
                    )

                if binance_msg:
                    price_msg = PriceMessage(
                        exchange="binance",
                        symbol="BTCUSDT",
                        price=binance_msg.price,
                        volume=binance_msg.volume_24h,
                        timestamp=datetime.fromtimestamp(binance_msg.timestamp / 1000)
                        if binance_msg.timestamp > 1e12 else datetime.now(),
                    )
                    await self.price_hub.update_price("binance", price_msg)

                # Track premium
                premium = self.price_hub.get_premium()
                if premium:
                    self.premium_tracker.record({
                        "premium_pct": premium.premium_pct,
                        "upbit_usd": premium.upbit_usd,
                        "binance_usd": premium.binance_usd,
                        "usd_krw_rate": premium.usd_krw_rate,
                    })

            except Exception as e:
                logger.error(f"Price feed loop error: {e}")

            await asyncio.sleep(0.1)  # 100ms

    async def _main_loop(self) -> None:
        """Main event loop - reacts to significant price changes."""
        price_queue = self.price_hub.subscribe()

        while self._running:
            try:
                # Wait for price change event
                event = await asyncio.wait_for(price_queue.get(), timeout=60)

                # Check kill-switch
                if await self._is_killed():
                    logger.warning("Kill-switch active, skipping evaluation")
                    continue

                # Evaluate and execute
                await self._evaluate_and_execute()
                self._iteration_count += 1

                # Write status
                await self._write_status()

            except asyncio.TimeoutError:
                # No price change in 60s - still alive
                logger.debug("No significant price change in 60s")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(1)

    async def _evaluate_and_execute(self) -> None:
        """Run strategies and execute signals."""
        regime = self._regime_cache or "SIDEWAYS_NEUTRAL"

        # Concurrent strategy evaluation
        signals = await asyncio.gather(
            self.upbit_runner.evaluate(regime),
            self.binance_runner.evaluate(regime),
            return_exceptions=True,
        )

        # Submit valid signals
        for signal in signals:
            if signal and not isinstance(signal, Exception):
                await self.executor.submit(signal)
                self._signal_count += 1
                logger.info(f"Signal: {signal.exchange} {signal.action} @ {signal.price}")

    async def _regime_update_loop(self) -> None:
        """Update regime periodically."""
        while self._running:
            try:
                df = self.data_cache.get_df("day", periods=180)
                if not df.empty:
                    regime = await asyncio.to_thread(
                        self._calculate_regime, df
                    )
                    self._regime_cache = regime
                    self._regime_updated_at = datetime.now()
                    logger.info(f"Regime updated: {regime}")

            except Exception as e:
                logger.error(f"Regime update failed: {e}")

            await asyncio.sleep(self.config.regime_update_interval)

    def _calculate_regime(self, df) -> str:
        """Calculate market regime from daily data (sync)."""
        try:
            from .strategy.regime_router import RegimeRouter
            router = RegimeRouter()
            market_state = router.classify_market_state(df)
            return market_state
        except Exception as e:
            logger.error(f"Regime calculation failed: {e}")
            return "SIDEWAYS_NEUTRAL"

    async def _is_killed(self) -> bool:
        """Non-blocking kill-switch check."""
        return await asyncio.to_thread(
            kill_switch_active,
            self.risk_config.kill_switch_file
        )

    def _on_order_filled(self, order) -> None:
        """Callback when order is filled."""
        # Update position in runner
        if order.exchange == "upbit":
            self.upbit_runner.update_position(
                active=order.action == "buy",
                entry_price=order.fill_price or order.price,
                size=order.fill_size or 0,
                strategy=order.strategy,
            )
        else:
            self.binance_runner.update_position(
                active=order.action == "sell",  # Short position
                entry_price=order.fill_price or order.price,
                size=order.fill_size or 0,
                strategy=order.strategy,
            )

        # Notify
        if self._telegram:
            try:
                msg = (
                    f"{'🟢' if order.action == 'buy' else '🔴'} Order Filled\n"
                    f"Exchange: {order.exchange}\n"
                    f"Action: {order.action}\n"
                    f"Price: {order.fill_price:,.0f}\n"
                    f"Strategy: {order.strategy}"
                )
                self._telegram.send_message(msg)
            except Exception as e:
                logger.error(f"Telegram notification failed: {e}")

    def _on_health_alert(self, message: str, data: Dict) -> None:
        """Callback for health alerts."""
        if self._telegram:
            try:
                self._telegram.send_message(f"⚠️ {message}")
            except Exception as e:
                logger.error(f"Health alert notification failed: {e}")

    def _send_startup_notification(self) -> None:
        """Send startup notification."""
        if not self._telegram:
            return

        try:
            msg = (
                f"🚀 AsyncTradingEngine [{self.execution_mode.upper()}] Started\n"
                f"{'=' * 30}\n\n"
                f"Components:\n"
                f"  • PriceHub: Ready\n"
                f"  • DataCache: {len(self.data_cache.get_sizes())} timeframes\n"
                f"  • FXRateCache: {self.fx_cache.rate:.0f} KRW/USD\n"
                f"  • Executor: {self.executor.execution_mode}\n\n"
                f"Settings:\n"
                f"  • Price threshold: {self.config.price_change_threshold:.1%}\n"
                f"  • Regime interval: {self.config.regime_update_interval}s"
            )
            self._telegram.send_message(msg)
        except Exception as e:
            logger.error(f"Startup notification failed: {e}")

    async def _write_status(self) -> None:
        """Write engine status to JSON for dashboard."""
        try:
            prices = self.price_hub.get_prices()
            premium = self.price_hub.get_premium()

            status = {
                "timestamp": datetime.now().isoformat(),
                "mode": self.execution_mode,
                "engine": "async",
                "regime": self._regime_cache,
                "iteration_count": self._iteration_count,
                "signal_count": self._signal_count,
                "prices": {
                    "upbit": prices.get("upbit"),
                    "binance": prices.get("binance"),
                },
                "premium": {
                    "premium_pct": premium.premium_pct if premium else None,
                    "fx_rate": premium.usd_krw_rate if premium else None,
                },
                "upbit": self.upbit_runner.get_stats(),
                "binance": self.binance_runner.get_stats(),
                "executor": self.executor.get_stats(),
                "health": self.health_monitor.get_health(),
            }

            status_file = self.log_dir / "async_engine_status.json"
            with open(status_file, "w") as f:
                json.dump(status, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"Failed to write status: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "running": self._running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "uptime_seconds": (datetime.now() - self._started_at).total_seconds()
            if self._started_at else 0,
            "execution_mode": self.execution_mode,
            "iteration_count": self._iteration_count,
            "signal_count": self._signal_count,
            "regime": self._regime_cache,
            "price_hub": self.price_hub.get_stats(),
            "data_cache": self.data_cache.get_stats(),
            "fx_cache": self.fx_cache.get_stats(),
            "upbit_runner": self.upbit_runner.get_stats(),
            "binance_runner": self.binance_runner.get_stats(),
            "executor": self.executor.get_stats(),
            "health": self.health_monitor.get_stats(),
        }


async def main():
    """Test entry point."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    config = AsyncEngineConfig(
        execution_mode="paper",
        telegram_enabled=False,
    )

    engine = AsyncTradingEngine(config)

    try:
        await engine.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
