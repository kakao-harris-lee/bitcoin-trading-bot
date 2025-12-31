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
    # Dual execution modes: trend (directional) and premium (kimchi hedge)
    trend_mode: str = "paper"      # Trend/directional trading mode
    premium_mode: str = "paper"    # Kimchi premium hedge mode
    paper_upbit_capital: float = 10_000_000
    paper_binance_capital: float = 10_000
    telegram_enabled: bool = True
    telegram_commands_enabled: bool = False
    kill_switch_file: str = "analysis/KILL_SWITCH"
    price_change_threshold: float = 0.001  # 0.1%
    regime_update_interval: int = 300  # 5 minutes
    log_dir: Optional[Path] = None

    @property
    def execution_mode(self) -> str:
        """Legacy compatibility: returns trend_mode."""
        return self.trend_mode

    @classmethod
    def from_args(cls, args: Any) -> "AsyncEngineConfig":
        """Create config from argparse args."""
        # Support both new (--trend/--premium) and legacy (--mode) args
        trend = getattr(args, "trend", None) or getattr(args, "mode", "paper")
        premium = getattr(args, "premium", None) or "paper"
        return cls(
            trend_mode=trend,
            premium_mode=premium,
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
        self.trend_mode = config.trend_mode
        self.premium_mode = config.premium_mode
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
        self._telegram_cmd = None
        if config.telegram_enabled:
            try:
                from .notification.telegram_notifier import TelegramNotifier
                self._telegram = TelegramNotifier()
            except Exception as e:
                logger.warning(f"Telegram init failed: {e}")

        # Telegram commands
        if self._telegram and config.telegram_commands_enabled:
            try:
                from .notification.telegram_commands import TelegramCommandHandler
                self._telegram_cmd = TelegramCommandHandler(self._telegram)
                self._telegram_cmd.register_command("kill_on", self._handle_kill_on)
                self._telegram_cmd.register_command("kill_off", self._handle_kill_off)
                self._telegram_cmd.register_command("kill_status", self._handle_kill_status)
                self._telegram_cmd.register_command("dashboard", self._handle_dashboard)
                self._telegram_cmd.start_polling()
            except Exception as e:
                logger.warning(f"Telegram command handler init failed: {e}")

        # Statistics
        self._iteration_count = 0
        self._signal_count = 0

    @property
    def execution_mode(self) -> str:
        """Legacy compatibility: returns trend_mode."""
        return self.trend_mode

    def _mode_display(self) -> str:
        """Format mode display string."""
        return f"Trend={self.trend_mode.upper()}, Premium={self.premium_mode.upper()}"

    async def start(self) -> None:
        """Initialize and start all components."""
        if self._running:
            logger.warning("Engine already running")
            return

        logger.info("=" * 70)
        logger.info(f"  AsyncTradingEngine [{self._mode_display()}]")
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
            self._periodic_status_loop(),
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

                # Print cycle status (like old engine)
                self._print_cycle_status()

                # Periodic Telegram status report (every 6 iterations)
                self._send_status_notification()

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

    async def _periodic_status_loop(self) -> None:
        """Log status every 5 minutes like the old engine."""
        interval = 300  # 5 minutes

        while self._running:
            try:
                await asyncio.sleep(interval)

                if not self._running:
                    break

                # Print status
                self._print_cycle_status()

                # Write status files
                await self._write_status()

                print(f"\n⏱️  다음 실행까지 5분 대기...\n")

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic status loop error: {e}")

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
                f"🚀 AsyncTradingEngine Started\n"
                f"{'=' * 30}\n\n"
                f"Modes:\n"
                f"  • Trend:   {self.trend_mode.upper()}\n"
                f"  • Premium: {self.premium_mode.upper()}\n\n"
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

    def _get_altcoin_premiums(self, fx_rate: float) -> Dict[str, Dict[str, float]]:
        """Get current premiums for multiple assets."""
        import requests

        assets = {
            "BTC": {"upbit": "KRW-BTC", "binance": "BTCUSDT"},
            "ETH": {"upbit": "KRW-ETH", "binance": "ETHUSDT"},
            "XRP": {"upbit": "KRW-XRP", "binance": "XRPUSDT"},
            "SOL": {"upbit": "KRW-SOL", "binance": "SOLUSDT"},
        }
        result = {}

        try:
            # Fetch Upbit prices
            upbit_tickers = ",".join([v["upbit"] for v in assets.values()])
            upbit_resp = requests.get(
                f"https://api.upbit.com/v1/ticker?markets={upbit_tickers}",
                timeout=5
            )
            upbit_prices = {t["market"]: t["trade_price"] for t in upbit_resp.json()}

            # Fetch Binance prices
            binance_resp = requests.get(
                "https://api.binance.com/api/v3/ticker/price",
                timeout=5
            )
            binance_prices = {t["symbol"]: float(t["price"]) for t in binance_resp.json()}

            # Calculate premiums
            for asset, symbols in assets.items():
                upbit_krw = upbit_prices.get(symbols["upbit"], 0)
                binance_usd = binance_prices.get(symbols["binance"], 0)
                if upbit_krw and binance_usd and fx_rate:
                    upbit_usd = upbit_krw / fx_rate
                    premium = ((upbit_usd - binance_usd) / binance_usd) * 100
                    result[asset] = {
                        "upbit_krw": upbit_krw,
                        "binance_usd": binance_usd,
                        "premium": premium,
                    }
        except Exception as e:
            logger.warning(f"Failed to fetch altcoin premiums: {e}")

        return result

    def _send_status_notification(self) -> None:
        """Send periodic status notification (every 6 iterations = ~30min)."""
        if not self._telegram:
            return

        # Send every 6 iterations (iteration 6, 12, 18, ...)
        if self._iteration_count == 0 or self._iteration_count % 6 != 0:
            return

        try:
            now = datetime.now()
            prices = self.price_hub.get_prices()
            upbit_price = prices.get("upbit", 0)
            binance_price = prices.get("binance", 0)
            fx_rate = self.fx_cache.rate or 1300

            # Header with mode info
            trend_mode = "🔴 LIVE" if self.trend_mode == "live" else "⚪ Paper"
            premium_mode = "🔴 LIVE" if self.premium_mode == "live" else "⚪ Paper"

            msg = "📊 Dual Trading 상태 보고\n"
            msg += "=" * 30 + "\n\n"
            msg += f"🕐 {now.strftime('%Y-%m-%d %H:%M')}\n"
            msg += f"📍 Trend: {trend_mode} | Premium: {premium_mode}\n\n"

            # Market regime
            regime = self._regime_cache or "UNKNOWN"
            regime_emoji = {
                "BULL": "🐂", "BULL_STRONG": "🐂🐂", "BULL_MODERATE": "🐂",
                "BEAR": "🐻", "BEAR_STRONG": "🐻🐻", "BEAR_MODERATE": "🐻",
                "SIDEWAYS": "↔️", "SIDEWAYS_NEUTRAL": "↔️", "SIDEWAYS_BULL": "↔️🐂", "SIDEWAYS_BEAR": "↔️🐻",
            }.get(regime, "❓")
            msg += f"🌐 시장: {regime_emoji} {regime}\n\n"

            # Multi-asset Kimchi Premium
            altcoin_premiums = self._get_altcoin_premiums(fx_rate)
            msg += "🥬 김치 프리미엄\n"
            for asset in ["BTC", "ETH", "XRP", "SOL"]:
                if asset in altcoin_premiums:
                    p = altcoin_premiums[asset]
                    icon = "📈" if p["premium"] > 1.5 else "📉" if p["premium"] < 0 else "➡️"
                    msg += f"   {asset}: {p['premium']:+.2f}% {icon}\n"
            msg += "\n"

            # BTC Premium trend (from tracker)
            premium_stats = self.premium_tracker.get_stats()
            vol_icon = {"normal": "🟢", "elevated": "🟡", "high": "🔴"}.get(premium_stats.volatility_state, "⚪")
            msg += f"   BTC 24h: {premium_stats.mean_24h:+.2f}% ±{premium_stats.std_24h:.2f}% {vol_icon}\n"
            msg += f"   범위: {premium_stats.min_24h:+.2f}% ~ {premium_stats.max_24h:+.2f}%\n\n"

            # Strategy decisions
            upbit_stats = self.upbit_runner.get_stats()
            binance_stats = self.binance_runner.get_stats()
            upbit_strategies = upbit_stats.get("strategies_loaded", [])
            upbit_pos = upbit_stats.get("position", {})
            binance_pos = binance_stats.get("position", {})

            # Get account (live or paper)
            if self.trend_mode == "live" and self.executor._live_adapters:
                upbit_adapter = self.executor._live_adapters.get("upbit")
                if upbit_adapter:
                    try:
                        krw, btc = upbit_adapter.get_balance()
                        upbit_total = krw + (btc * upbit_price)
                        msg += f"📈 [Upbit] LIVE\n"
                        msg += f"   잔고: {krw:,.0f}원 + {btc:.6f} BTC\n"
                        msg += f"   총 가치: {upbit_total:,.0f}원\n"
                    except Exception as e:
                        msg += f"📈 [Upbit] LIVE (조회 실패)\n"
            else:
                upbit_account = self.executor._paper_accounts.get("upbit")
                if upbit_account:
                    cash, btc = upbit_account.get_balance()
                    total = upbit_account.get_total_value(upbit_price)
                    stats = upbit_account.get_statistics()
                    msg += f"📈 [Upbit] Paper\n"
                    msg += f"   잔고: {cash:,.0f}원 + {btc:.6f} BTC\n"
                    msg += f"   총 가치: {total:,.0f}원 ({stats.get('return_pct', 0):+.2f}%)\n"

            # Upbit position & strategy info
            active_strategy = upbit_pos.get("strategy") or (upbit_strategies[0] if upbit_strategies else "none")
            msg += f"   전략: {active_strategy} | 포지션: {'🟢' if upbit_pos.get('active') else '⚪'}\n"
            if upbit_pos.get("active"):
                entry = upbit_pos.get("entry_price", 0)
                pnl = ((upbit_price - entry) / entry * 100) if entry else 0
                msg += f"   진입가: {entry:,.0f}원 ({pnl:+.2f}%)\n"
            msg += f"   신호: {upbit_stats.get('signal_count', 0)}건\n\n"

            # Binance status
            if self.premium_mode == "live" and self.executor._live_adapters:
                binance_adapter = self.executor._live_adapters.get("binance")
                if binance_adapter:
                    try:
                        info = binance_adapter.get_account_info() if hasattr(binance_adapter, 'get_account_info') else {}
                        balance = info.get("total_balance", 0) if info else 0
                        msg += f"📉 [Binance] LIVE\n"
                        msg += f"   잔고: ${balance:,.2f}\n"
                    except Exception as e:
                        msg += f"📉 [Binance] LIVE (조회 실패)\n"
            else:
                binance_account = self.executor._paper_accounts.get("binance")
                if binance_account:
                    cash, _ = binance_account.get_balance()
                    stats = binance_account.get_statistics()
                    msg += f"📉 [Binance] Paper\n"
                    msg += f"   잔고: ${cash:,.2f} ({stats.get('return_pct', 0):+.2f}%)\n"

            # Binance position
            msg += f"   포지션: {'🔻 숏' if binance_pos.get('active') else '⚪ 없음'}\n"
            if binance_pos.get("active"):
                entry = binance_pos.get("entry_price", 0)
                pnl = ((entry - binance_price) / entry * 100) if entry else 0  # Short: profit when price drops
                msg += f"   진입가: ${entry:,.2f} ({pnl:+.2f}%)\n"
            msg += f"   신호: {binance_stats.get('signal_count', 0)}건\n\n"

            # Current prices with premium
            btc_premium = altcoin_premiums.get("BTC", {}).get("premium", 0)
            msg += f"💹 BTC 현재가\n"
            msg += f"   Upbit: ₩{upbit_price:,.0f}\n"
            msg += f"   Binance: ${binance_price:,.2f}\n"
            msg += f"   김프: {btc_premium:+.2f}% | 환율: {fx_rate:,.0f}"

            self._telegram.send_message(msg)
            logger.info("Status notification sent")
        except Exception as e:
            logger.error(f"Status notification failed: {e}")
            import traceback
            traceback.print_exc()

    def _print_cycle_status(self) -> None:
        """Print cycle status like the old engine."""
        try:
            now = datetime.now()
            prices = self.price_hub.get_prices()
            premium = self.price_hub.get_premium()
            premium_stats = self.premium_tracker.get_stats()

            upbit_price = prices.get("upbit", 0)
            binance_price = prices.get("binance", 0)

            # Mode labels
            trend_label = "LIVE" if self.trend_mode == "live" else "PAPER"
            premium_label = "LIVE" if self.premium_mode == "live" else "PAPER"
            mode_label = f"Trend:{trend_label} Premium:{premium_label}"

            # Header
            print(f"\n{'='*70}")
            print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] {mode_label} (#{self._iteration_count})")
            print(f"{'='*70}")

            # Prices
            print(f"Upbit: {upbit_price:,.0f}원 | Binance: ${binance_price:,.2f}")

            # Premium
            if premium_stats:
                trend_icon = {"rising": "↗️", "falling": "↘️", "stable": "➡️"}.get(
                    premium_stats.trend, "➡️"
                )
                vol_icon = "🔴" if premium_stats.volatility_state == "high" else "🟢"
                print(
                    f"[Premium] Premium: {premium_stats.current:+.2f}% "
                    f"(24h: {premium_stats.mean_24h:+.2f}% "
                    f"±{premium_stats.std_24h:.2f}%) {vol_icon} {trend_icon}"
                )

            # Router
            regime = self._regime_cache or "UNKNOWN"
            print(f"[Router] state={regime}")

            # Strategy execution info
            upbit_stats = self.upbit_runner.get_stats()
            binance_stats = self.binance_runner.get_stats()
            strategies = upbit_stats.get("strategies_loaded", [])
            print(f"  [Strategies] Upbit: {strategies}")

            # Positions status
            print(f"\n{'─'*70}")
            print("  현재 상태")
            print(f"{'─'*70}")

            # Upbit
            upbit_pos = upbit_stats.get("position", {})
            upbit_account = self.executor._paper_accounts.get("upbit")
            if upbit_account:
                cash, btc = upbit_account.get_balance()
                total = upbit_account.get_total_value(upbit_price)
                stats = upbit_account.get_statistics()

                print(f"\n[Upbit]")
                print(f"  포지션: {'🟢 있음' if upbit_pos.get('active') else '⚪ 없음'}")
                print(f"  현금: {cash:,.0f}원")
                print(f"  BTC: {btc:.8f} BTC")
                print(f"  총 가치: {total:,.0f}원")
                print(f"  수익률: {stats.get('return_pct', 0):+.2f}%")

            # Binance
            binance_pos = binance_stats.get("position", {})
            binance_account = self.executor._paper_accounts.get("binance")
            if binance_account:
                cash, _ = binance_account.get_balance()
                stats = binance_account.get_statistics()

                print(f"\n[Binance]")
                print(f"  포지션: {'🔻 숏' if binance_pos.get('active') else '⚪ 없음'}")
                print(f"  현금: ${cash:,.2f}")
                print(f"  수익률: {stats.get('return_pct', 0):+.2f}%")

            # Premium info
            if premium:
                print(f"\n[Kimchi Premium]")
                print(f"  프리미엄: {premium.premium_pct:+.2f}%")
                print(f"  Upbit: ${premium.upbit_usd:,.2f} | Binance: ${premium.binance_usd:,.2f}")
                print(f"  환율: {premium.usd_krw_rate:,.0f} KRW/USD")

            # Totals
            if upbit_account and binance_account:
                fx_rate = premium.usd_krw_rate if premium else 1450
                upbit_total = upbit_account.get_total_value(upbit_price)
                binance_cash, _ = binance_account.get_balance()
                total_krw = upbit_total + (binance_cash * fx_rate)

                initial_total = (
                    upbit_account.initial_capital +
                    (binance_account.initial_capital * fx_rate)
                )
                total_return = ((total_krw - initial_total) / initial_total) * 100 if initial_total > 0 else 0

                print(f"\n[합계]")
                print(f"  총 자산: {total_krw:,.0f}원")
                print(f"  총 수익률: {total_return:+.2f}%")

            print(f"{'─'*70}\n")

        except Exception as e:
            logger.error(f"Failed to print cycle status: {e}")

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
            await asyncio.to_thread(self._write_json_sync, status_file, status)

            # Also write v2_engine_combined.json for dashboard compatibility
            await self._write_combined_log(prices, premium)

        except Exception as e:
            logger.error(f"Failed to write status: {e}")

    def _write_json_sync(self, file_path: Path, data: Dict) -> None:
        """Sync helper for writing JSON file."""
        with open(file_path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    async def _write_combined_log(self, prices: Dict, premium) -> None:
        """Write v2_engine_combined.json for dashboard compatibility."""
        try:
            upbit_price = prices.get("upbit", 0)
            binance_price = prices.get("binance", 0)
            premium_stats = self.premium_tracker.get_stats()

            # Get paper accounts for hedge ratio calculation
            upbit_account = self.executor._paper_accounts.get("upbit")
            binance_account = self.executor._paper_accounts.get("binance")

            # Calculate exposures
            long_exposure = 0.0
            short_exposure = 0.0
            if upbit_account:
                _, btc = upbit_account.get_balance()
                long_exposure = btc * upbit_price if btc > 0 else 0

            if binance_account:
                pos = binance_account.get_position()
                if pos and pos.get("size", 0) > 0:
                    fx_rate = premium.usd_krw_rate if premium else 1450
                    short_exposure = pos["size"] * binance_price * fx_rate

            # Calculate hedge ratio
            total_exposure = long_exposure + short_exposure
            hedge_ratio = short_exposure / total_exposure if total_exposure > 0 else 0

            # Determine target based on regime
            regime = self._regime_cache or "SIDEWAYS_NEUTRAL"
            if "BULL" in regime:
                target_min, target_max, target = 0.3, 0.5, 0.4
            elif "BEAR" in regime:
                target_min, target_max, target = 0.5, 0.7, 0.6
            else:
                target_min, target_max, target = 0.4, 0.6, 0.5

            combined = {
                "generated_at": datetime.now().isoformat(),
                "mode": self.execution_mode,
                "regime": regime.split("_")[0] if "_" in regime else regime,
                "market_state": regime,
                "kimchi_premium": {
                    "premium_pct": premium.premium_pct if premium else 0,
                    "upbit_usd": premium.upbit_usd if premium else 0,
                    "binance_usd": premium.binance_usd if premium else 0,
                    "usd_krw_rate": premium.usd_krw_rate if premium else 1450,
                },
                "premium_stats": {
                    "current": premium_stats.current,
                    "mean_24h": premium_stats.mean_24h,
                    "std_24h": premium_stats.std_24h,
                    "min_24h": premium_stats.min_24h,
                    "max_24h": premium_stats.max_24h,
                    "volatility_state": premium_stats.volatility_state,
                    "trend": premium_stats.trend,
                    "readings_count": premium_stats.readings_count,
                },
                "hedge_ratio": {
                    "hedge_ratio": hedge_ratio,
                    "long_exposure_krw": long_exposure,
                    "short_exposure_krw": short_exposure,
                    "regime": regime.split("_")[0] if "_" in regime else regime,
                    "target_min": target_min,
                    "target_max": target_max,
                    "target": target,
                    "adjusted_target": target,
                    "adjustment_reason": "normal",
                },
                "prices": {
                    "upbit_krw": upbit_price,
                    "binance_usd": binance_price,
                },
            }

            combined_file = self.log_dir / "v2_engine_combined.json"
            await asyncio.to_thread(self._write_json_sync, combined_file, combined)

        except Exception as e:
            logger.error(f"Failed to write combined log: {e}")

    def _handle_kill_on(self, args: str) -> None:
        """Handler wrapper for /kill_on command."""
        self._cmd_kill_switch(True)

    def _handle_kill_off(self, args: str) -> None:
        """Handler wrapper for /kill_off command."""
        self._cmd_kill_switch(False)

    def _handle_kill_status(self, args: str) -> None:
        """Handler wrapper for /kill_status command."""
        self._cmd_kill_status()

    def _handle_dashboard(self, args: str) -> None:
        """Handler wrapper for /dashboard command."""
        self._cmd_dashboard()

    def _cmd_kill_switch(self, activate: bool) -> None:
        """Toggle kill switch via Telegram command."""
        try:
            from .risk.risk_controls import set_kill_switch
            set_kill_switch(self.risk_config.kill_switch_file, activate)
            status = "🔴 활성화" if activate else "🟢 비활성화"
            msg = f"Kill Switch {status}"
            print(f"⚠️ {msg}")
            if self._telegram:
                self._telegram.send_message(msg)
        except Exception as e:
            logger.error(f"Kill switch command failed: {e}")

    def _cmd_kill_status(self) -> None:
        """Get kill switch status via Telegram command."""
        try:
            from .risk.risk_controls import kill_switch_active
            active = kill_switch_active(self.risk_config.kill_switch_file)
            status = "🔴 활성화" if active else "🟢 비활성화"
            msg = f"Kill Switch 상태: {status}"
            if self._telegram:
                self._telegram.send_message(msg)
        except Exception as e:
            logger.error(f"Kill status command failed: {e}")

    def _cmd_dashboard(self) -> None:
        """Send dashboard URL and current TOTP code via Telegram."""
        try:
            import pyotp
            from dotenv import load_dotenv

            env_path = Path(__file__).parent.parent / ".env"
            load_dotenv(env_path, override=True)
            totp_secret = os.environ.get("DASHBOARD_TOTP_SECRET")
            if not totp_secret:
                msg = "⚠️ DASHBOARD_TOTP_SECRET not configured in .env"
                if self._telegram:
                    self._telegram.send_message(msg)
                return

            totp = pyotp.TOTP(totp_secret, interval=30)
            current_code = totp.now()

            msg = f"""🖥️ *Dashboard Access*

🔗 URL: `/btc-dashboard`
🔐 TOTP Code: `{current_code}`
⏱️ Valid for: ~30 seconds

_코드 만료 시 다시 /dashboard 명령어를 사용하세요._"""

            print(f"📱 Dashboard TOTP: {current_code}")
            if self._telegram:
                self._telegram.send_message(msg)
        except ImportError:
            msg = "⚠️ pyotp not installed. Run: pip install pyotp"
            print(msg)
            if self._telegram:
                self._telegram.send_message(msg)
        except Exception as e:
            msg = f"Dashboard command failed: {e}"
            logger.error(msg)
            if self._telegram:
                self._telegram.send_message(f"⚠️ {msg}")

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
