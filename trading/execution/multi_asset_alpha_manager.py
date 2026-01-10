"""
MultiAssetAlphaManager - Coordinates alpha strategies across multiple assets.

Manages per-asset strategy evaluation and execution with concurrent processing.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

from core.types import AssetConfig, current_timestamp
from trading.execution.portfolio_manager import PortfolioManager
from trading.core.multi_asset_data_cache import MultiAssetDataCache
from trading.core.asset_health import AssetHealthTracker

logger = logging.getLogger(__name__)

# Default state file path
DEFAULT_ALPHA_STATE_FILE = Path("logs/alpha_state.json")


@dataclass
class MultiAssetSignal:
    """Signal from multi-asset alpha evaluation."""
    symbol: str
    strategy: str
    action: str  # "buy", "sell", "hold"
    fraction: float = 0.5
    reason: str = ""
    regime: str = ""
    exchange: str = "upbit"  # "upbit" or "binance"
    indicators: Dict[str, Any] = field(default_factory=dict)
    timestamp: int = field(default_factory=current_timestamp)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "strategy": self.strategy,
            "action": self.action,
            "fraction": self.fraction,
            "reason": self.reason,
            "regime": self.regime,
            "exchange": self.exchange,
            "indicators": self.indicators,
            "timestamp": self.timestamp,
        }


@dataclass
class AssetState:
    """Trading state for a single asset on a specific exchange."""
    symbol: str
    exchange: str = "upbit"  # "upbit" or "binance"
    active: bool = False
    quantity: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    strategy: Optional[str] = None
    regime: str = "UNKNOWN"
    leverage: int = 1  # For Binance futures
    direction: str = "long"  # "long" or "short"
    last_signal: Optional[MultiAssetSignal] = None
    last_evaluation: Optional[int] = None


class MultiAssetAlphaManager:
    """
    Manages alpha strategies across multiple assets.

    Features:
    - Concurrent strategy evaluation via asyncio.gather
    - Per-asset regime tracking
    - Integration with PortfolioManager for capital allocation
    """

    def __init__(
        self,
        portfolio: PortfolioManager,
        config: Dict[str, Any],
        data_cache: Optional[MultiAssetDataCache] = None,
        telegram_notifier: Optional[Any] = None,
        execution_mode: str = "paper",
        state_file: Optional[Path] = None,
    ):
        """
        Args:
            portfolio: PortfolioManager for capital allocation
            config: Allocation config with "assets" section
            data_cache: MultiAssetDataCache for OHLCV data
            telegram_notifier: Optional telegram notifier
            execution_mode: "paper" or "live"
            state_file: Path to state persistence file
        """
        self._portfolio = portfolio
        self._config = config
        self._data_cache = data_cache
        self._telegram = telegram_notifier
        self._execution_mode = execution_mode

        # State persistence
        self._state_file = state_file or DEFAULT_ALPHA_STATE_FILE
        self._state_file.parent.mkdir(parents=True, exist_ok=True)

        # Per-asset state - keyed by (symbol, exchange) tuple
        self._states: Dict[tuple, AssetState] = {}
        self._strategies: Dict[tuple, Any] = {}  # (symbol, exchange) -> strategy instance
        self._regime_routers: Dict[str, Any] = {}  # symbol -> regime router (shared)
        self._accounts: Dict[tuple, Any] = {}  # (symbol, exchange) -> account/executor

        # Signal and trade history
        self._signal_history: List[Dict] = []
        self._trade_history: List[Dict] = []

        # Control flags
        self._block_new_entries: bool = False

        self._init_states()
        self._load_state()  # Load persisted state on startup

        # Per-asset health tracking for graceful degradation
        self._health_tracker = AssetHealthTracker(
            symbols=list(self._states.keys()),
            max_failures=5,
            disable_duration_sec=300.0,  # 5 minutes
            on_disable=self._on_asset_disabled,
            on_recovery=self._on_asset_recovered,
        )

        logger.info(f"MultiAssetAlphaManager initialized for {len(self._states)} assets")

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        portfolio: PortfolioManager,
        data_cache: Optional[MultiAssetDataCache] = None,
        **kwargs,
    ) -> "MultiAssetAlphaManager":
        """Create from allocation config."""
        return cls(
            portfolio=portfolio,
            config=config,
            data_cache=data_cache,
            **kwargs,
        )

    def _init_states(self) -> None:
        """Initialize per-asset state for both exchanges."""
        assets_config = self._config.get("assets", {})
        for symbol in self._portfolio.get_symbols():
            asset_cfg = assets_config.get(symbol, {})

            # Initialize Upbit state if enabled
            if asset_cfg.get("upbit_enabled", True):  # Default to True for backward compat
                self._states[(symbol, "upbit")] = AssetState(
                    symbol=symbol, exchange="upbit", direction="long"
                )

            # Initialize Binance state if enabled
            if asset_cfg.get("binance_enabled", False):
                self._states[(symbol, "binance")] = AssetState(
                    symbol=symbol, exchange="binance",
                    leverage=asset_cfg.get("binance_leverage", 1)
                )

    def _on_asset_disabled(self, symbol: str, reason: str) -> None:
        """Callback when an asset is disabled due to failures."""
        self._notify(f"[{symbol}] Asset DISABLED: {reason}")

    def _on_asset_recovered(self, symbol: str) -> None:
        """Callback when an asset recovers after being disabled."""
        self._notify(f"[{symbol}] Asset RECOVERED and re-enabled")

    def _save_state(self) -> None:
        """Persist current state to file."""
        try:
            state_data = {
                "version": 2,  # Version 2 for exchange-aware state
                "saved_at": datetime.now().isoformat(),
                "execution_mode": self._execution_mode,
                "states": {},
            }

            for (symbol, exchange), state in self._states.items():
                key = f"{symbol}_{exchange}"
                state_data["states"][key] = {
                    "symbol": symbol,
                    "exchange": exchange,
                    "active": state.active,
                    "quantity": state.quantity,
                    "entry_price": state.entry_price,
                    "current_price": state.current_price,
                    "strategy": state.strategy,
                    "regime": state.regime,
                    "direction": state.direction,
                    "leverage": state.leverage,
                }

            # Write atomically (write to temp, then rename)
            temp_file = self._state_file.with_suffix(".tmp")
            temp_file.write_text(json.dumps(state_data, indent=2))
            temp_file.rename(self._state_file)

            logger.debug(f"State saved to {self._state_file}")

        except Exception as e:
            logger.error(f"Failed to save state: {e}")

    def _load_state(self) -> None:
        """Load persisted state from file."""
        if not self._state_file.exists():
            logger.info("No persisted state file found, starting fresh")
            return

        try:
            state_data = json.loads(self._state_file.read_text())

            # Version check
            version = state_data.get("version", 0)
            if version not in (1, 2):
                logger.warning(f"Unknown state version {version}, ignoring")
                return

            saved_at = state_data.get("saved_at", "unknown")
            saved_mode = state_data.get("execution_mode", "unknown")

            logger.info(f"Loading state from {saved_at} (mode: {saved_mode})")

            # Restore states
            states = state_data.get("states", {})
            restored_count = 0

            for key, saved_state in states.items():
                # Handle both v1 (symbol only) and v2 (symbol_exchange) keys
                if version == 1:
                    symbol = key
                    exchange = "upbit"  # v1 was upbit-only
                else:
                    symbol = saved_state.get("symbol", key.split("_")[0])
                    exchange = saved_state.get("exchange", "upbit")

                state_key = (symbol, exchange)
                if state_key in self._states:
                    state = self._states[state_key]
                    state.active = saved_state.get("active", False)
                    state.quantity = saved_state.get("quantity", 0.0)
                    state.entry_price = saved_state.get("entry_price", 0.0)
                    state.current_price = saved_state.get("current_price", 0.0)
                    state.strategy = saved_state.get("strategy")
                    state.regime = saved_state.get("regime", "UNKNOWN")
                    state.direction = saved_state.get("direction", "long")
                    state.leverage = saved_state.get("leverage", 1)

                    if state.active:
                        restored_count += 1
                        logger.info(
                            f"Restored {symbol}/{exchange}: {state.quantity:.6f} @ "
                            f"{state.entry_price:,.0f} ({state.strategy}, {state.direction})"
                        )

            logger.info(f"State loaded: {restored_count} active positions restored")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid state file format: {e}")
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

    def set_strategy(self, symbol: str, exchange: str, strategy: Any) -> None:
        """Set strategy instance for an asset on a specific exchange."""
        self._strategies[(symbol, exchange)] = strategy
        logger.info(f"Strategy set for {symbol}/{exchange}: {type(strategy).__name__}")

    def set_regime_router(self, symbol: str, router: Any) -> None:
        """Set regime router for an asset (shared across exchanges)."""
        self._regime_routers[symbol] = router

    def get_strategy_name(self, symbol: str, exchange: str) -> Optional[str]:
        """Get the configured strategy name for an asset/exchange."""
        strategy = self._strategies.get((symbol, exchange))
        return type(strategy).__name__ if strategy else None

    def set_account(self, symbol: str, exchange: str, account: Any) -> None:
        """Set account/executor for an asset on a specific exchange."""
        self._accounts[(symbol, exchange)] = account

    def set_block_entries(self, block: bool) -> None:
        """Set whether new entries are blocked."""
        self._block_new_entries = block

    async def evaluate_all(
        self,
        prices: Dict[str, float],
    ) -> List[MultiAssetSignal]:
        """
        Evaluate all healthy assets concurrently across all exchanges.

        Unhealthy assets are skipped until they recover after
        the disable timeout period.

        Args:
            prices: Dict of symbol -> current price

        Returns:
            List of signals from all assets/exchanges
        """
        # Update portfolio prices
        self._portfolio.update_prices(prices)

        # Only evaluate healthy assets
        healthy_symbols = self._health_tracker.get_healthy_symbols()

        # Evaluate all (symbol, exchange) pairs in parallel
        tasks = []
        task_keys = []
        for (symbol, exchange), state in self._states.items():
            if symbol not in healthy_symbols:
                continue

            # Check if this is a recovery attempt
            if self._health_tracker.check_recovery(symbol):
                logger.info(f"[{symbol}/{exchange}] Attempting recovery evaluation")

            tasks.append(self._evaluate_asset(symbol, exchange, prices.get(symbol, 0)))
            task_keys.append((symbol, exchange))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect valid signals and track health
        signals = []
        for (symbol, exchange), result in zip(task_keys, results):
            if isinstance(result, Exception):
                logger.error(f"[{symbol}/{exchange}] Evaluation error: {result}")
                self._health_tracker.record_failure(symbol, result)
            elif result is not None:
                if isinstance(result, list):
                    for sig in result:
                        signals.append(sig)
                        self._signal_history.append(sig.to_dict())
                else:
                    signals.append(result)
                    self._signal_history.append(result.to_dict())
                self._health_tracker.record_success(symbol)
            else:
                # None result means no signal, but still healthy
                self._health_tracker.record_success(symbol)

        return signals

    async def _evaluate_asset(
        self,
        symbol: str,
        exchange: str,
        current_price: float,
    ) -> Optional[MultiAssetSignal]:
        """
        Evaluate a single asset on a specific exchange.

        Args:
            symbol: Asset symbol
            exchange: Exchange ("upbit" or "binance")
            current_price: Current price

        Returns:
            Signal if action needed, None otherwise
        """
        state = self._states.get((symbol, exchange))
        if not state:
            return None

        state.current_price = current_price
        state.last_evaluation = current_timestamp()

        # Get strategy for this symbol/exchange and router
        strategy = self._strategies.get((symbol, exchange))
        router = self._regime_routers.get(symbol)

        if not strategy:
            logger.debug(f"No strategy configured for {symbol}/{exchange}")
            return None

        try:
            # Get regime context (includes market_state, regime, mfi, adx)
            regime = "BULL"  # Default
            mfi_val, adx_val = None, None
            if router:
                df_day = self._get_daily_df(symbol)
                if df_day is not None and len(df_day) > 0:
                    context = router.recommend(df_day)
                    regime = context.regime
                    mfi_val = context.mfi
                    adx_val = context.adx

            # Log only when regime changes
            prev_regime = state.regime
            if regime != prev_regime:
                mfi_str = f"{mfi_val:.1f}" if mfi_val is not None else "N/A"
                adx_str = f"{adx_val:.1f}" if adx_val is not None else "N/A"
                logger.info(
                    f"[{symbol}/{exchange}] Regime: {prev_regime} -> {regime} | "
                    f"MFI: {mfi_str} | ADX: {adx_str}"
                )
            state.regime = regime

            # Get strategies config for this exchange
            asset_cfg = self._config.get("assets", {}).get(symbol, {})
            strategies_key = "upbit_strategies" if exchange == "upbit" else "binance_strategies"
            strategies_cfg = asset_cfg.get(strategies_key, asset_cfg.get("strategies", {}))

            # Check if strategy is allowed in regime (unless bypassed)
            bypass_regime = self._config.get("bypass_regime_gating", False)
            regime_key = regime.split("_")[0]  # e.g., "BEAR_STRONG" -> "BEAR"
            allowed_strategy = strategies_cfg.get(regime_key) or strategies_cfg.get(regime)

            if not bypass_regime and not allowed_strategy:
                # No strategy for this regime - check for exit
                if state.active:
                    action = "sell" if state.direction == "long" else "close_short"
                    return MultiAssetSignal(
                        symbol=symbol,
                        strategy=state.strategy or "none",
                        action=action,
                        reason=f"REGIME_EXIT_{regime}",
                        regime=regime,
                        exchange=exchange,
                    )
                return None

            # Determine direction for Binance based on regime
            if exchange == "binance":
                if regime_key == "BEAR" and strategies_cfg.get("BEAR"):
                    state.direction = "short"
                else:
                    state.direction = "long"

            # Get data for strategy
            df = self._get_daily_df(symbol)
            if df is None or len(df) == 0:
                logger.warning(f"No data available for {symbol}")
                return None

            # Run strategy evaluation in thread pool (strategies are sync)
            signal = await asyncio.to_thread(
                self._run_strategy_sync, symbol, exchange, strategy, df, current_price, regime
            )

            if signal:
                state.last_signal = signal

            return signal

        except Exception as e:
            logger.error(f"Error evaluating {symbol}/{exchange}: {e}")
            return None

    def _run_strategy_sync(
        self,
        symbol: str,
        exchange: str,
        strategy: Any,
        df: Any,
        current_price: float,
        regime: str,
    ) -> Optional[MultiAssetSignal]:
        """Run strategy evaluation synchronously (for thread pool)."""
        try:
            # Add indicators
            if hasattr(strategy, 'add_indicators'):
                df = strategy.add_indicators(df)

            # Generate signal
            if hasattr(strategy, 'generate_signal'):
                raw_signal = strategy.generate_signal(df, len(df) - 1)
            else:
                raw_signal = {"action": "hold"}

            if not raw_signal:
                raw_signal = {"action": "hold"}

            action = raw_signal.get("action", "hold")
            reason = raw_signal.get("reason", "")
            strategy_name = type(strategy).__name__

            if action == "hold":
                return None

            # Log strategy decision
            metadata = raw_signal.get("metadata", {})
            market_state = metadata.get("market_state", "")
            score = raw_signal.get("score", "")
            tier = raw_signal.get("tier", "")
            logger.info(
                f"[{symbol}/{exchange}] Signal: {action.upper()} | "
                f"Strategy: {strategy_name} | "
                f"Reason: {reason} | "
                f"MarketState: {market_state} | "
                f"Score: {score} | Tier: {tier}"
            )

            return MultiAssetSignal(
                symbol=symbol,
                strategy=strategy_name,
                action=action,
                fraction=raw_signal.get("fraction", 0.5),
                reason=reason,
                regime=regime,
                exchange=exchange,
                indicators={
                    "score": score,
                    "tier": tier,
                },
            )

        except Exception as e:
            logger.error(f"Strategy execution error for {symbol}/{exchange}: {e}")
            return None

    def _get_daily_df(self, symbol: str):
        """Get daily DataFrame for symbol."""
        if self._data_cache:
            return self._data_cache.get_df(symbol, "day", periods=500)
        return None

    async def execute_signals(
        self,
        signals: List[MultiAssetSignal],
        prices: Dict[str, float],
    ) -> List[Dict]:
        """
        Execute signals for all assets.

        Args:
            signals: List of signals to execute
            prices: Current prices

        Returns:
            List of executed trades
        """
        trades = []

        for signal in signals:
            if signal.action == "hold":
                continue

            trade = await self._execute_signal(signal, prices.get(signal.symbol, 0))
            if trade:
                trades.append(trade)
                self._trade_history.append(trade)

        return trades

    async def _execute_signal(
        self,
        signal: MultiAssetSignal,
        price: float,
    ) -> Optional[Dict]:
        """Execute a single signal."""
        symbol = signal.symbol
        exchange = signal.exchange
        state = self._states.get((symbol, exchange))
        account = self._accounts.get((symbol, exchange))

        if not state:
            return None

        # Handle different action types based on exchange/direction
        if signal.action in ("buy", "open_long") and not state.active:
            return await self._execute_buy(symbol, exchange, signal, price, account)
        elif signal.action in ("sell", "close_long") and state.active and state.direction == "long":
            return await self._execute_sell(symbol, exchange, signal, price, account)
        elif signal.action == "open_short" and not state.active:
            return await self._execute_short(symbol, exchange, signal, price, account)
        elif signal.action == "close_short" and state.active and state.direction == "short":
            return await self._execute_close_short(symbol, exchange, signal, price, account)
        elif signal.action == "partial_close" and state.active:
            return await self._execute_partial_close(symbol, exchange, signal, price, account)

        return None

    async def _execute_buy(
        self,
        symbol: str,
        exchange: str,
        signal: MultiAssetSignal,
        price: float,
        account: Optional[Any],
    ) -> Optional[Dict]:
        """Execute buy (long) for an asset."""
        if self._block_new_entries:
            logger.info(f"[{symbol}/{exchange}] Entry blocked by risk guard")
            return None

        state = self._states[(symbol, exchange)]
        available_capital = self._portfolio.get_available_capital(symbol)
        buy_amount = available_capital * min(signal.fraction, 0.9)

        min_order = 10000 if exchange == "upbit" else 10  # KRW or USDT
        if buy_amount < min_order:
            logger.info(f"[{symbol}/{exchange}] Buy amount too small: {buy_amount:,.0f}")
            return None

        try:
            if self._execution_mode == "live" and account:
                result = account.buy(buy_amount, price)
                if not result or not result.get("success"):
                    logger.error(f"[{symbol}/{exchange}] Buy failed: {result}")
                    return None
                qty = float(result.get("executed_volume", 0))
                actual_price = float(result.get("executed_price", price))
            else:
                # Paper mode
                fee_rate = 0.0005
                qty = (buy_amount * (1 - fee_rate)) / price
                actual_price = price

            # Update state
            state.active = True
            state.quantity = qty
            state.entry_price = actual_price
            state.current_price = actual_price
            state.strategy = signal.strategy
            state.direction = "long"

            # Update portfolio (only for upbit)
            if exchange == "upbit":
                self._portfolio.update_position(
                    symbol, qty, actual_price, actual_price, signal.strategy
                )
                self._portfolio.adjust_cash(-buy_amount)

            trade = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "exchange": exchange,
                "type": "buy",
                "direction": "long",
                "price": actual_price,
                "quantity": qty,
                "amount": buy_amount,
                "reason": signal.reason,
                "strategy": signal.strategy,
            }

            currency = "KRW" if exchange == "upbit" else "USDT"
            msg = f"🟢 [{symbol}/{exchange}] BUY {qty:.6f} @ {actual_price:,.0f} {currency}"
            logger.info(msg)
            self._notify(msg)

            # Persist state after successful trade
            self._save_state()

            return trade

        except Exception as e:
            logger.error(f"[{symbol}/{exchange}] Buy execution failed: {e}")
            return None

    async def _execute_sell(
        self,
        symbol: str,
        exchange: str,
        signal: MultiAssetSignal,
        price: float,
        account: Optional[Any],
    ) -> Optional[Dict]:
        """Execute sell (close long) for an asset."""
        state = self._states[(symbol, exchange)]

        if state.quantity <= 0:
            return None

        try:
            if self._execution_mode == "live" and account:
                result = account.sell(state.quantity, price)
                if not result or not result.get("success"):
                    logger.error(f"[{symbol}/{exchange}] Sell failed: {result}")
                    return None
                actual_price = float(result.get("executed_price", price))
                proceeds = float(result.get("executed_value", state.quantity * price))
            else:
                # Paper mode
                fee_rate = 0.0005
                proceeds = state.quantity * price * (1 - fee_rate)
                actual_price = price

            # Calculate P&L
            pnl = (actual_price - state.entry_price) * state.quantity
            pnl_pct = ((actual_price / state.entry_price) - 1) * 100 if state.entry_price > 0 else 0

            sold_qty = state.quantity

            # Clear state
            state.active = False
            state.quantity = 0.0
            state.entry_price = 0.0
            state.strategy = None

            # Update portfolio (only for upbit)
            if exchange == "upbit":
                self._portfolio.update_position(symbol, 0, 0, actual_price, None)
                self._portfolio.adjust_cash(proceeds)

            trade = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "exchange": exchange,
                "type": "sell",
                "direction": "long",
                "price": actual_price,
                "quantity": sold_qty,
                "proceeds": proceeds,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "reason": signal.reason,
                "strategy": signal.strategy,
            }

            currency = "KRW" if exchange == "upbit" else "USDT"
            msg = f"🔴 [{symbol}/{exchange}] SELL @ {actual_price:,.0f} {currency} | PnL: {pnl:+,.0f} ({pnl_pct:+.2f}%)"
            logger.info(msg)
            self._notify(msg)

            # Persist state after successful trade
            self._save_state()

            return trade

        except Exception as e:
            logger.error(f"[{symbol}/{exchange}] Sell execution failed: {e}")
            return None

    async def _execute_short(
        self,
        symbol: str,
        exchange: str,
        signal: MultiAssetSignal,
        price: float,
        account: Optional[Any],
    ) -> Optional[Dict]:
        """Execute open short for Binance futures."""
        if self._block_new_entries:
            logger.info(f"[{symbol}/{exchange}] Entry blocked by risk guard")
            return None

        state = self._states[(symbol, exchange)]

        # Get Binance capital from config
        capital_cfg = self._config.get("capital", {})
        binance_capital = capital_cfg.get("binance_usdt", 5000)
        asset_cfg = self._config.get("assets", {}).get(symbol, {})
        alpha_ratio = asset_cfg.get("alpha_ratio", 0.3)
        leverage = state.leverage or asset_cfg.get("binance_leverage", 3)

        available_capital = binance_capital * alpha_ratio
        position_size = available_capital * min(signal.fraction, 0.9) * leverage

        min_order = 10  # 10 USDT minimum
        if position_size < min_order:
            logger.info(f"[{symbol}/{exchange}] Short size too small: ${position_size:.2f}")
            return None

        try:
            if self._execution_mode == "live" and account:
                result = account.open_short(position_size, price, leverage)
                if not result or not result.get("success"):
                    logger.error(f"[{symbol}/{exchange}] Short failed: {result}")
                    return None
                qty = float(result.get("executed_volume", 0))
                actual_price = float(result.get("executed_price", price))
            else:
                # Paper mode
                fee_rate = 0.0004  # Binance futures fee
                qty = (position_size * (1 - fee_rate)) / price
                actual_price = price

            # Update state
            state.active = True
            state.quantity = qty
            state.entry_price = actual_price
            state.current_price = actual_price
            state.strategy = signal.strategy
            state.direction = "short"
            state.leverage = leverage

            trade = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "exchange": exchange,
                "type": "open_short",
                "direction": "short",
                "price": actual_price,
                "quantity": qty,
                "notional": position_size,
                "leverage": leverage,
                "reason": signal.reason,
                "strategy": signal.strategy,
            }

            msg = f"🔻 [{symbol}/{exchange}] SHORT {qty:.6f} @ ${actual_price:,.2f} ({leverage}x)"
            logger.info(msg)
            self._notify(msg)

            # Persist state after successful trade
            self._save_state()

            return trade

        except Exception as e:
            logger.error(f"[{symbol}/{exchange}] Short execution failed: {e}")
            return None

    async def _execute_close_short(
        self,
        symbol: str,
        exchange: str,
        signal: MultiAssetSignal,
        price: float,
        account: Optional[Any],
    ) -> Optional[Dict]:
        """Execute close short for Binance futures."""
        state = self._states[(symbol, exchange)]

        if state.quantity <= 0:
            return None

        try:
            if self._execution_mode == "live" and account:
                result = account.close_short(state.quantity, price)
                if not result or not result.get("success"):
                    logger.error(f"[{symbol}/{exchange}] Close short failed: {result}")
                    return None
                actual_price = float(result.get("executed_price", price))
            else:
                # Paper mode
                actual_price = price

            # Calculate P&L (short: profit when price goes down)
            pnl = (state.entry_price - actual_price) * state.quantity
            pnl_pct = ((state.entry_price - actual_price) / state.entry_price) * 100 if state.entry_price > 0 else 0

            closed_qty = state.quantity
            leverage = state.leverage

            # Clear state
            state.active = False
            state.quantity = 0.0
            state.entry_price = 0.0
            state.strategy = None
            state.direction = "long"  # Reset to default

            trade = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "exchange": exchange,
                "type": "close_short",
                "direction": "short",
                "price": actual_price,
                "quantity": closed_qty,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "leverage": leverage,
                "reason": signal.reason,
                "strategy": signal.strategy,
            }

            msg = f"🔺 [{symbol}/{exchange}] CLOSE SHORT @ ${actual_price:,.2f} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%)"
            logger.info(msg)
            self._notify(msg)

            # Persist state after successful trade
            self._save_state()

            return trade

        except Exception as e:
            logger.error(f"[{symbol}/{exchange}] Close short execution failed: {e}")
            return None

    async def _execute_partial_close(
        self,
        symbol: str,
        exchange: str,
        signal: MultiAssetSignal,
        price: float,
        account: Optional[Any],
    ) -> Optional[Dict]:
        """Execute partial position close (for two-tier exits).

        Closes a fraction of the position while keeping the rest open.
        Works for both long and short positions.
        """
        state = self._states[(symbol, exchange)]

        if state.quantity <= 0:
            return None

        # Calculate quantity to close
        close_fraction = min(signal.fraction, 1.0)
        close_qty = state.quantity * close_fraction
        remaining_qty = state.quantity - close_qty

        if close_qty <= 0:
            return None

        try:
            if self._execution_mode == "live" and account:
                if state.direction == "short":
                    result = account.close_short(close_qty, price)
                else:
                    result = account.sell(close_qty, price)

                if not result or not result.get("success"):
                    logger.error(f"[{symbol}/{exchange}] Partial close failed: {result}")
                    return None
                actual_price = float(result.get("executed_price", price))
            else:
                # Paper mode
                actual_price = price

            # Calculate P&L for closed portion
            if state.direction == "short":
                pnl = (state.entry_price - actual_price) * close_qty
                pnl_pct = ((state.entry_price - actual_price) / state.entry_price) * 100 if state.entry_price > 0 else 0
            else:
                pnl = (actual_price - state.entry_price) * close_qty
                pnl_pct = ((actual_price / state.entry_price) - 1) * 100 if state.entry_price > 0 else 0

            leverage = state.leverage

            # Update state - keep position active with remaining quantity
            state.quantity = remaining_qty
            # state.active remains True since we still have a position

            trade = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "exchange": exchange,
                "type": "partial_close",
                "direction": state.direction,
                "price": actual_price,
                "quantity": close_qty,
                "remaining_quantity": remaining_qty,
                "fraction": close_fraction,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "leverage": leverage,
                "reason": signal.reason,
                "strategy": signal.strategy,
            }

            direction_emoji = "🔻" if state.direction == "short" else "🔸"
            msg = (
                f"{direction_emoji} [{symbol}/{exchange}] PARTIAL CLOSE ({close_fraction:.0%}) "
                f"@ ${actual_price:,.2f} | PnL: ${pnl:+,.2f} ({pnl_pct:+.2f}%) | "
                f"Remaining: {remaining_qty:.6f}"
            )
            logger.info(msg)
            self._notify(msg)

            # Persist state after successful trade
            self._save_state()

            return trade

        except Exception as e:
            logger.error(f"[{symbol}/{exchange}] Partial close execution failed: {e}")
            return None

    def _notify(self, message: str) -> None:
        """Send telegram notification."""
        if self._telegram:
            try:
                self._telegram.send_message(message)
            except Exception as e:
                logger.warning(f"Telegram notification failed: {e}")

    def get_state(self, symbol: str, exchange: str = "upbit") -> Optional[AssetState]:
        """Get state for a specific asset/exchange."""
        return self._states.get((symbol, exchange))

    def get_all_states(self) -> Dict[tuple, AssetState]:
        """Get all asset states keyed by (symbol, exchange)."""
        return self._states.copy()

    def get_states_by_symbol(self, symbol: str) -> Dict[str, AssetState]:
        """Get all states for a symbol across exchanges."""
        return {
            exchange: state
            for (sym, exchange), state in self._states.items()
            if sym == symbol
        }

    def get_total_exposure(self) -> float:
        """Get total exposure across all assets (in asset units * price)."""
        return sum(
            s.quantity * s.current_price
            for s in self._states.values()
            if s.active
        )

    def get_exposure_by_symbol(self, symbol: str, exchange: str = "upbit") -> float:
        """Get exposure for a specific symbol on an exchange."""
        state = self._states.get((symbol, exchange))
        if state and state.active:
            return state.quantity
        return 0.0

    def get_long_exposure_krw(self, symbol: str = "BTC", exchange: str = "upbit") -> float:
        """
        Get long exposure value in KRW for hedge sizing.

        Args:
            symbol: Asset symbol (default BTC)
            exchange: Exchange name (default upbit)

        Returns:
            Position value in KRW (quantity * current_price)
        """
        state = self._states.get((symbol, exchange))
        if state and state.active and state.direction == "long" and state.quantity > 0:
            return state.quantity * state.current_price
        return 0.0

    def get_total_long_exposure_krw(self) -> float:
        """
        Get total long exposure across all assets in KRW.

        Returns:
            Total position value in KRW
        """
        total = 0.0
        for (symbol, exchange), state in self._states.items():
            if state.active and state.direction == "long" and state.quantity > 0:
                total += state.quantity * state.current_price
        return total

    def get_statistics(self) -> Dict[str, Any]:
        """Get trading statistics."""
        total_pnl = sum(t.get("pnl", 0) for t in self._trade_history if "pnl" in t)
        sell_trades = [t for t in self._trade_history if t.get("type") == "sell"]
        winning = [t for t in sell_trades if t.get("pnl", 0) > 0]

        return {
            "total_trades": len(sell_trades),
            "total_pnl_krw": round(total_pnl, 0),
            "win_rate": round(len(winning) / len(sell_trades) * 100, 1) if sell_trades else 0,
            "states": {s: st.symbol for s, st in self._states.items()},
        }

    def get_signals_history(self, limit: int = 50) -> List[Dict]:
        """Get recent signal history."""
        return self._signal_history[-limit:]

    def get_trades_history(self, limit: int = 50) -> List[Dict]:
        """Get recent trade history."""
        return self._trade_history[-limit:]

    def get_health_status(self) -> Dict[str, Any]:
        """Get health status for all assets."""
        return self._health_tracker.get_all_health()

    def get_health_summary(self) -> Dict[str, Any]:
        """Get health summary statistics."""
        return self._health_tracker.get_summary()

    def reset_asset_health(self, symbol: Optional[str] = None) -> None:
        """Reset health status for asset(s)."""
        self._health_tracker.reset(symbol)

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging."""
        assets = {}
        for (symbol, exchange), state in self._states.items():
            key = f"{symbol}_{exchange}"
            assets[key] = {
                "symbol": symbol,
                "exchange": exchange,
                "active": state.active,
                "quantity": state.quantity,
                "entry_price": state.entry_price,
                "current_price": state.current_price,
                "regime": state.regime,
                "strategy": state.strategy,
                "direction": state.direction,
                "leverage": state.leverage,
            }
        return {
            "assets": assets,
            "statistics": self.get_statistics(),
            "portfolio": self._portfolio.get_stats(),
            "health": self._health_tracker.get_summary(),
        }
