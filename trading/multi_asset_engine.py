"""
MultiAssetTradingEngine - Event-driven trading engine for multiple assets.

Orchestrates all multi-asset components:
- MultiAssetPriceHub: Per-symbol price tracking
- MultiAssetDataCache: Per-symbol OHLCV data
- MultiAssetAlphaManager: Per-symbol strategy evaluation
- PortfolioManager: Capital allocation
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any

from .core.multi_asset_price_hub import MultiAssetPriceHub, PriceEvent
from .core.multi_asset_data_cache import MultiAssetDataCache
from .core.fx_cache import FXRateCache
from .core.health_monitor import HealthMonitor
from .data.simple_feed_handler import SimpleFeedHandler
from .execution.portfolio_manager import PortfolioManager
from .execution.multi_asset_alpha_manager import MultiAssetAlphaManager
from .execution.paper_account import PaperTradingAccount
from .risk.risk_controls import kill_switch_active, RiskConfig
from .strategy.regime_router import RegimeRouter

logger = logging.getLogger(__name__)


@dataclass
class MultiAssetEngineConfig:
    """Configuration for MultiAssetTradingEngine."""
    execution_mode: str = "paper"
    total_capital_krw: float = 10_000_000
    telegram_enabled: bool = True
    kill_switch_file: str = "analysis/KILL_SWITCH"
    price_change_threshold: float = 0.001
    regime_update_interval: int = 300
    log_dir: Optional[Path] = None


class MultiAssetTradingEngine:
    """
    Multi-asset trading engine.

    Coordinates all multi-asset components for concurrent evaluation
    and execution across multiple cryptocurrencies.
    """

    def __init__(
        self,
        config: MultiAssetEngineConfig,
        allocation_config: Dict[str, Any],
    ):
        """
        Args:
            config: Engine configuration
            allocation_config: Asset allocation config (from allocation.json)
        """
        self.config = config
        self.allocation_config = allocation_config
        self.execution_mode = config.execution_mode
        self._running = False
        self._started_at: Optional[datetime] = None

        # Log directory
        self.log_dir = config.log_dir or Path(__file__).parent.parent / "logs"
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Risk config
        self.risk_config = RiskConfig(kill_switch_file=config.kill_switch_file)

        # Extract enabled symbols
        self._symbols = self._get_enabled_symbols()

        logger.info(f"Enabled symbols: {self._symbols}")

        # Telegram (initialize before components that may use it)
        self._telegram = None
        if config.telegram_enabled:
            try:
                from .notification.telegram_notifier import TelegramNotifier
                self._telegram = TelegramNotifier()
            except Exception as e:
                logger.warning(f"Telegram init failed: {e}")

        # Initialize components
        self._init_components()

        # Load and wire strategies, accounts, and routers
        self._setup_strategies_and_accounts()

        # Regime cache per symbol
        self._regime_cache: Dict[str, str] = {sym: "SIDEWAYS_NEUTRAL" for sym in self._symbols}

        # Statistics
        self._iteration_count = 0
        self._signal_count = 0

    def _get_enabled_symbols(self) -> List[str]:
        """Get list of enabled symbols from config."""
        assets = self.allocation_config.get("assets", {})
        return [sym for sym, cfg in assets.items() if cfg.get("enabled", False)]

    def _init_components(self) -> None:
        """Initialize all multi-asset components."""
        # Price Hub
        self.price_hub = MultiAssetPriceHub.from_config(self.allocation_config)

        # Data Cache
        self.data_cache = MultiAssetDataCache.from_config(self.allocation_config)

        # FX Rate Cache
        self.fx_cache = FXRateCache(
            on_rate_change=self.price_hub.update_fx_rate,
        )

        # Feed Handler
        self.feed_handler = SimpleFeedHandler.from_config(self.allocation_config)

        # Portfolio Manager
        self.portfolio = PortfolioManager.from_config(
            self.allocation_config,
            total_capital_krw=self.config.total_capital_krw,
        )

        # Alpha Manager
        self.alpha_manager = MultiAssetAlphaManager.from_config(
            self.allocation_config,
            portfolio=self.portfolio,
            data_cache=self.data_cache,
            telegram_notifier=self._telegram,
            execution_mode=self.execution_mode,
        )

        # Health Monitor (pass self for stats)
        self.health_monitor = HealthMonitor(
            engine=self,
            on_alert=self._on_health_alert if self.config.telegram_enabled else None,
        )

    def _setup_strategies_and_accounts(self) -> None:
        """Load strategies, create accounts, and wire up all components."""
        import json as json_module

        for symbol in self._symbols:
            asset_cfg = self.allocation_config["assets"].get(symbol, {})

            # 1. Create paper account for this symbol (Upbit spot long)
            upbit_account = PaperTradingAccount(
                initial_capital=self.config.total_capital_krw * asset_cfg.get("alpha_ratio", 0.3),
                exchange="upbit"
            )
            self.alpha_manager.set_account(symbol, upbit_account)

            # 2. Create regime router for this symbol
            router = RegimeRouter()
            self.alpha_manager.set_regime_router(symbol, router)

            # 3. Load strategy based on config
            strategy = self._load_strategy_for_asset(symbol, asset_cfg)
            if strategy:
                self.alpha_manager.set_strategy(symbol, strategy)
                logger.info(f"[{symbol}] Strategy loaded: {type(strategy).__name__}")
            else:
                logger.warning(f"[{symbol}] No strategy loaded")

    def _load_strategy_for_asset(self, symbol: str, asset_cfg: Dict) -> Optional[Any]:
        """Load the appropriate strategy for an asset based on config."""
        strategies_cfg = asset_cfg.get("strategies", {})
        strategy_configs = asset_cfg.get("strategy_configs", {})
        params_override = asset_cfg.get("params_override", {})

        # For now, load the BULL strategy as the main strategy
        # The regime router will determine when to use it
        bull_strategy = strategies_cfg.get("BULL")

        if not bull_strategy:
            return None

        # Check for asset-specific V35 config (e.g., v35_sol, v35_eth)
        if bull_strategy.startswith("v35"):
            config_file = strategy_configs.get(bull_strategy)
            return self._load_v35_strategy(params_override, config_file, symbol)
        elif bull_strategy == "sideways_v2":
            return self._load_sideways_v2_strategy(params_override)

        return None

    def _load_v35_strategy(self, params_override: Dict, config_file: Optional[str] = None, symbol: str = "BTC") -> Optional[Any]:
        """Load V35 Long Strategy with asset-specific config."""
        try:
            import json as json_module
            from .strategy.v35_long import V35LongStrategy

            # Use asset-specific config if provided, else default to v35_long.json
            if config_file:
                config_path = Path(__file__).parent.parent / config_file
            else:
                config_path = Path(__file__).parent.parent / "config" / "strategies" / "v35_long.json"

            if config_path.exists():
                with open(config_path) as f:
                    config = json_module.load(f)
                # Apply overrides
                config.update(params_override)
                logger.info(f"[{symbol}] Loaded V35 config from: {config_path.name}")
                return V35LongStrategy(config=config)
            else:
                logger.warning(f"[{symbol}] Config not found: {config_path}")
        except Exception as e:
            logger.warning(f"[{symbol}] Failed to load V35: {e}")
        return None

    def _load_sideways_v2_strategy(self, params_override: Dict) -> Optional[Any]:
        """Load SideWays V2 Strategy."""
        try:
            from .strategy.sideways_v2 import SideWaysV2Strategy
            return SideWaysV2Strategy()
        except Exception as e:
            logger.warning(f"Failed to load SideWays_v2: {e}")
        return None

    async def start(self) -> None:
        """Start all components and main loop."""
        if self._running:
            logger.warning("Engine already running")
            return

        logger.info("=" * 70)
        logger.info(f"  MultiAssetTradingEngine [{self.execution_mode.upper()}]")
        logger.info(f"  Assets: {self._symbols}")
        logger.info("=" * 70)

        # 1. Start data cache
        logger.info("Loading initial data...")
        await self.data_cache.start()

        # 2. Start FX rate cache
        logger.info("Starting FX rate cache...")
        await self.fx_cache.start()

        # 3. Start feed handler
        logger.info("Connecting WebSockets...")
        await self.feed_handler.start()

        # 4. Start health monitor
        await self.health_monitor.start()

        # 5. Send startup notification
        self._send_startup_notification()

        # 6. Start main loops
        self._running = True
        self._started_at = datetime.now()

        logger.info("MultiAssetTradingEngine started")

        await asyncio.gather(
            self._main_loop(),
            self._price_feed_loop(),
            self._regime_update_loop(),
            self._periodic_status_loop(),
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        logger.info("Stopping MultiAssetTradingEngine...")
        self._running = False

        await self.health_monitor.stop()
        await self.feed_handler.stop()
        await self.fx_cache.stop()
        await self.data_cache.stop()

        logger.info("MultiAssetTradingEngine stopped")

    async def _price_feed_loop(self) -> None:
        """Update prices from feed handler to price hub."""
        while self._running:
            try:
                for symbol in self._symbols:
                    asset_cfg = self.allocation_config["assets"].get(symbol, {})
                    upbit_sym = asset_cfg.get("upbit_symbol", f"KRW-{symbol}")
                    binance_sym = asset_cfg.get("binance_symbol", f"{symbol}USDT")

                    # Get prices from feed handler
                    upbit_msg = self.feed_handler.get_last_price("upbit", upbit_sym)
                    binance_msg = self.feed_handler.get_last_price("binance", binance_sym)

                    if upbit_msg:
                        await self.price_hub.update_price(
                            symbol, "upbit", upbit_msg.price
                        )
                        # Update data cache
                        self.data_cache.update_from_tick(
                            symbol,
                            upbit_msg.price,
                            upbit_msg.ohlcv.volume if upbit_msg.ohlcv else 0,
                        )

                    if binance_msg:
                        await self.price_hub.update_price(
                            symbol, "binance", binance_msg.price
                        )

            except Exception as e:
                logger.error(f"Price feed loop error: {e}")

            await asyncio.sleep(0.1)

    async def _main_loop(self) -> None:
        """Main event loop - reacts to price changes."""
        price_queue = self.price_hub.subscribe_all()

        while self._running:
            try:
                # Wait for price event
                event = await asyncio.wait_for(price_queue.get(), timeout=60)

                # Check kill switch
                if await self._is_killed():
                    logger.warning("Kill switch active, skipping evaluation")
                    continue

                # Evaluate and execute for the symbol that changed
                await self._evaluate_and_execute(event.symbol)
                self._iteration_count += 1

            except asyncio.TimeoutError:
                logger.debug("No significant price change in 60s")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Main loop error: {e}")
                await asyncio.sleep(1)

    async def _evaluate_and_execute(self, triggered_symbol: str) -> None:
        """Evaluate strategies and execute signals."""
        # Get current prices
        prices = {}
        for symbol in self._symbols:
            upbit_price = self.price_hub.get_price(symbol, "upbit")
            if upbit_price:
                prices[symbol] = upbit_price

        if not prices:
            return

        # Evaluate all assets
        signals = await self.alpha_manager.evaluate_all(prices)

        # Execute signals
        if signals:
            trades = await self.alpha_manager.execute_signals(signals, prices)
            self._signal_count += len(trades)

            for trade in trades:
                logger.info(f"Trade: {trade['symbol']} {trade['type']} @ {trade['price']:,.0f}")

        # Write status
        await self._write_status()

    async def _regime_update_loop(self) -> None:
        """Update regime for each symbol periodically."""
        while self._running:
            try:
                for symbol in self._symbols:
                    df = self.data_cache.get_df(symbol, "day", periods=180)
                    if df is not None and len(df) > 0:
                        regime = await asyncio.to_thread(
                            self._calculate_regime, df
                        )
                        self._regime_cache[symbol] = regime
                        logger.info(f"[{symbol}] Regime: {regime}")

            except Exception as e:
                logger.error(f"Regime update failed: {e}")

            await asyncio.sleep(self.config.regime_update_interval)

    async def _periodic_status_loop(self) -> None:
        """Log status periodically."""
        while self._running:
            try:
                await asyncio.sleep(300)  # 5 minutes
                if not self._running:
                    break

                self._print_status()
                await self._write_status()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Periodic status error: {e}")

    def _calculate_regime(self, df) -> str:
        """Calculate market regime from daily data."""
        try:
            from .strategy.regime_router import RegimeRouter
            router = RegimeRouter()
            return router.classify_market_state(df)
        except Exception as e:
            logger.error(f"Regime calculation failed: {e}")
            return "SIDEWAYS_NEUTRAL"

    async def _is_killed(self) -> bool:
        """Check kill switch."""
        return await asyncio.to_thread(
            kill_switch_active,
            self.risk_config.kill_switch_file
        )

    def _on_health_alert(self, message: str, data: Dict) -> None:
        """Handle health alerts."""
        if self._telegram:
            try:
                self._telegram.send_message(f"⚠️ {message}")
            except Exception as e:
                logger.error(f"Health alert failed: {e}")

    def _send_startup_notification(self) -> None:
        """Send startup notification."""
        if not self._telegram:
            return

        try:
            msg = (
                f"🚀 MultiAssetTradingEngine [{self.execution_mode.upper()}]\n"
                f"{'=' * 30}\n\n"
                f"Assets: {', '.join(self._symbols)}\n"
                f"Capital: {self.config.total_capital_krw:,.0f} KRW\n"
                f"FX Rate: {self.fx_cache.rate:.0f} KRW/USD"
            )
            self._telegram.send_message(msg)
        except Exception as e:
            logger.error(f"Startup notification failed: {e}")

    def _print_status(self) -> None:
        """Print current status."""
        try:
            now = datetime.now()
            print(f"\n{'='*70}")
            print(f"[{now.strftime('%Y-%m-%d %H:%M:%S')}] Multi-Asset Status (#{self._iteration_count})")
            print(f"{'='*70}")

            for symbol in self._symbols:
                state = self.alpha_manager.get_state(symbol)
                regime = self._regime_cache.get(symbol, "UNKNOWN")

                upbit_price = self.price_hub.get_price(symbol, "upbit") or 0
                binance_price = self.price_hub.get_price(symbol, "binance") or 0

                print(f"\n[{symbol}]")
                print(f"  Regime: {regime}")
                print(f"  Upbit: {upbit_price:,.0f} | Binance: ${binance_price:,.2f}")
                if state:
                    pos_str = "🟢 Active" if state.active else "⚪ None"
                    print(f"  Position: {pos_str}")
                    if state.active:
                        print(f"  Qty: {state.quantity:.6f} @ {state.entry_price:,.0f}")

            # Portfolio summary
            portfolio_state = self.portfolio.get_portfolio_state()
            print(f"\n{'─'*70}")
            print(f"Portfolio: {portfolio_state.total_value_krw:,.0f} KRW | "
                  f"Exposure: {portfolio_state.exposure_pct:.1f}%")
            print(f"{'─'*70}\n")

        except Exception as e:
            logger.error(f"Print status failed: {e}")

    async def _write_status(self) -> None:
        """Write status to JSON files."""
        try:
            status = {
                "timestamp": datetime.now().isoformat(),
                "mode": self.execution_mode,
                "engine": "multi-asset",
                "iteration_count": self._iteration_count,
                "signal_count": self._signal_count,
                "assets": {},
            }

            # Get current FX rate for premium recording
            fx_rate = self.fx_cache.rate or 1450.0

            for symbol in self._symbols:
                premium = self.price_hub.get_premium(symbol)
                state = self.alpha_manager.get_state(symbol)

                # Record premium history for this symbol
                if premium and symbol in self.premium_trackers:
                    self.premium_trackers[symbol].record({
                        "premium_pct": premium.premium_pct,
                        "upbit_usd": premium.upbit_usd,
                        "binance_usd": premium.binance_usd,
                        "usd_krw_rate": fx_rate,
                    })

                status["assets"][symbol] = {
                    "regime": self._regime_cache.get(symbol),
                    "upbit_price": self.price_hub.get_price(symbol, "upbit"),
                    "binance_price": self.price_hub.get_price(symbol, "binance"),
                    "premium_pct": premium.premium_pct if premium else None,
                    "position_active": state.active if state else False,
                    "position_qty": state.quantity if state else 0,
                }

            status["portfolio"] = self.portfolio.get_stats()
            status["hedge"] = self.hedge_manager.get_stats()
            status["delta"] = self.delta_rebalancer.get_stats()

            status_file = self.log_dir / "multi_asset_engine_status.json"
            await asyncio.to_thread(self._write_json, status_file, status)

        except Exception as e:
            logger.error(f"Write status failed: {e}")

    def _write_json(self, path: Path, data: Dict) -> None:
        """Write JSON file."""
        with open(path, "w") as f:
            json.dump(data, f, indent=2, ensure_ascii=False, default=str)

    def get_stats(self) -> Dict[str, Any]:
        """Get engine statistics."""
        return {
            "running": self._running,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "execution_mode": self.execution_mode,
            "symbols": self._symbols,
            "hedgeable": self._hedgeable,
            "iteration_count": self._iteration_count,
            "signal_count": self._signal_count,
            "regimes": self._regime_cache,
            "price_hub": self.price_hub.get_stats(),
            "portfolio": self.portfolio.get_stats(),
            "alpha": self.alpha_manager.get_statistics(),
            "hedge": self.hedge_manager.get_stats(),
            "delta": self.delta_rebalancer.get_stats(),
        }


async def main():
    """Test entry point."""
    import json as json_module
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    # Load config
    config_path = Path(__file__).parent.parent / "config" / "strategies" / "allocation.json"
    with open(config_path) as f:
        allocation_config = json_module.load(f)

    engine_config = MultiAssetEngineConfig(
        execution_mode="paper",
        telegram_enabled=False,
    )

    engine = MultiAssetTradingEngine(engine_config, allocation_config)

    try:
        await engine.start()
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        await engine.stop()


if __name__ == "__main__":
    asyncio.run(main())
