"""
MultiAssetAlphaManager - Coordinates alpha strategies across multiple assets.

Manages per-asset strategy evaluation and execution with concurrent processing.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Callable

from core.types import AssetConfig, current_timestamp
from trading.execution.portfolio_manager import PortfolioManager
from trading.core.multi_asset_data_cache import MultiAssetDataCache
from trading.core.asset_health import AssetHealthTracker
from trading.indicators import technical as ta

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
            "indicators": self.indicators,
            "timestamp": self.timestamp,
        }


@dataclass
class AssetState:
    """Trading state for a single asset."""
    symbol: str
    active: bool = False
    quantity: float = 0.0
    entry_price: float = 0.0
    current_price: float = 0.0
    strategy: Optional[str] = None
    regime: str = "UNKNOWN"
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

        # Per-asset state
        self._states: Dict[str, AssetState] = {}
        self._strategies: Dict[str, Any] = {}  # symbol -> strategy instance
        self._regime_routers: Dict[str, Any] = {}  # symbol -> regime router
        self._accounts: Dict[str, Any] = {}  # symbol -> account/executor

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
        """Initialize per-asset state."""
        for symbol in self._portfolio.get_symbols():
            self._states[symbol] = AssetState(symbol=symbol)

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
                "version": 1,
                "saved_at": datetime.now().isoformat(),
                "execution_mode": self._execution_mode,
                "states": {},
            }

            for symbol, state in self._states.items():
                state_data["states"][symbol] = {
                    "active": state.active,
                    "quantity": state.quantity,
                    "entry_price": state.entry_price,
                    "current_price": state.current_price,
                    "strategy": state.strategy,
                    "regime": state.regime,
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
            if version != 1:
                logger.warning(f"Unknown state version {version}, ignoring")
                return

            saved_at = state_data.get("saved_at", "unknown")
            saved_mode = state_data.get("execution_mode", "unknown")

            logger.info(f"Loading state from {saved_at} (mode: {saved_mode})")

            # Restore states
            states = state_data.get("states", {})
            restored_count = 0

            for symbol, saved_state in states.items():
                if symbol in self._states:
                    state = self._states[symbol]
                    state.active = saved_state.get("active", False)
                    state.quantity = saved_state.get("quantity", 0.0)
                    state.entry_price = saved_state.get("entry_price", 0.0)
                    state.current_price = saved_state.get("current_price", 0.0)
                    state.strategy = saved_state.get("strategy")
                    state.regime = saved_state.get("regime", "UNKNOWN")

                    if state.active:
                        restored_count += 1
                        logger.info(
                            f"Restored {symbol}: {state.quantity:.6f} @ "
                            f"{state.entry_price:,.0f} ({state.strategy})"
                        )

            logger.info(f"State loaded: {restored_count} active positions restored")

        except json.JSONDecodeError as e:
            logger.error(f"Invalid state file format: {e}")
        except Exception as e:
            logger.error(f"Failed to load state: {e}")

    def set_strategy(self, symbol: str, strategy: Any) -> None:
        """Set strategy instance for an asset."""
        self._strategies[symbol] = strategy
        logger.info(f"Strategy set for {symbol}: {type(strategy).__name__}")

    def set_regime_router(self, symbol: str, router: Any) -> None:
        """Set regime router for an asset."""
        self._regime_routers[symbol] = router

    def set_account(self, symbol: str, account: Any) -> None:
        """Set account/executor for an asset."""
        self._accounts[symbol] = account

    def set_block_entries(self, block: bool) -> None:
        """Set whether new entries are blocked."""
        self._block_new_entries = block

    async def evaluate_all(
        self,
        prices: Dict[str, float],
    ) -> List[MultiAssetSignal]:
        """
        Evaluate all healthy assets concurrently.

        Unhealthy assets are skipped until they recover after
        the disable timeout period.

        Args:
            prices: Dict of symbol -> current price

        Returns:
            List of signals from all assets
        """
        # Update portfolio prices
        self._portfolio.update_prices(prices)

        # Only evaluate healthy assets
        healthy_symbols = self._health_tracker.get_healthy_symbols()
        skipped = set(self._states.keys()) - set(healthy_symbols)
        if skipped:
            logger.debug(f"Skipping unhealthy assets: {skipped}")

        # Evaluate healthy assets in parallel
        tasks = []
        task_symbols = []
        for symbol in healthy_symbols:
            # Check if this is a recovery attempt
            if self._health_tracker.check_recovery(symbol):
                logger.info(f"[{symbol}] Attempting recovery evaluation")

            tasks.append(self._evaluate_asset(symbol, prices.get(symbol, 0)))
            task_symbols.append(symbol)

        results = await asyncio.gather(*tasks, return_exceptions=True)

        # Collect valid signals and track health
        signals = []
        for symbol, result in zip(task_symbols, results):
            if isinstance(result, Exception):
                logger.error(f"[{symbol}] Evaluation error: {result}")
                self._health_tracker.record_failure(symbol, result)
            elif result is not None:
                self._health_tracker.record_success(symbol)
                signals.append(result)
                self._signal_history.append(result.to_dict())
            else:
                # None result means no signal, but still healthy
                self._health_tracker.record_success(symbol)

        return signals

    async def _evaluate_asset(
        self,
        symbol: str,
        current_price: float,
    ) -> Optional[MultiAssetSignal]:
        """
        Evaluate a single asset.

        Args:
            symbol: Asset symbol
            current_price: Current price

        Returns:
            Signal if action needed, None otherwise
        """
        state = self._states.get(symbol)
        if not state:
            return None

        state.current_price = current_price
        state.last_evaluation = current_timestamp()

        # Get strategy and router
        strategy = self._strategies.get(symbol)
        router = self._regime_routers.get(symbol)

        if not strategy:
            logger.debug(f"No strategy configured for {symbol}")
            return None

        try:
            # Get regime
            regime = "BULL"  # Default
            mfi_val, adx_val = None, None
            upbit_strategy = None
            if router:
                df_day = self._get_daily_df(symbol)
                if df_day is not None and len(df_day) > 0:
                    decision = router.recommend(df_day)
                    regime = decision.regime
                    upbit_strategy = decision.upbit_strategy
                    # Calculate MFI/ADX for logging
                    try:
                        mfi_series = ta.mfi(
                            df_day["high"], df_day["low"],
                            df_day["close"], df_day["volume"], period=14
                        )
                        adx_series, _, _ = ta.adx(
                            df_day["high"], df_day["low"], df_day["close"], period=14
                        )
                        mfi_val = mfi_series.iloc[-1] if mfi_series is not None else None
                        adx_val = adx_series.iloc[-1] if adx_series is not None else None
                    except Exception:
                        pass  # Keep None if calculation fails

            # Log only when regime changes
            prev_regime = state.regime
            if regime != prev_regime:
                mfi_str = f"{mfi_val:.1f}" if mfi_val is not None else "N/A"
                adx_str = f"{adx_val:.1f}" if adx_val is not None else "N/A"
                logger.info(
                    f"[{symbol}] Regime: {prev_regime} -> {regime} | "
                    f"MFI: {mfi_str} | ADX: {adx_str} | "
                    f"Strategy: {upbit_strategy or 'none'}"
                )
            state.regime = regime

            # Check if strategy is allowed in regime (unless bypassed)
            bypass_regime = self._config.get("bypass_regime_gating", False)
            if not bypass_regime:
                asset_config = self._portfolio.get_asset_config(symbol)
                if asset_config:
                    allowed_strategy = asset_config.strategies.get(regime)
                    if not allowed_strategy:
                        # No strategy for this regime - check for exit
                        if state.active:
                            return MultiAssetSignal(
                                symbol=symbol,
                                strategy=state.strategy or "none",
                                action="sell",
                                reason=f"REGIME_EXIT_{regime}",
                                regime=regime,
                            )
                        return None

            # Get data for strategy
            df = self._get_daily_df(symbol)
            if df is None or len(df) == 0:
                logger.warning(f"No data available for {symbol}")
                return None

            # Run strategy evaluation in thread pool (strategies are sync)
            signal = await asyncio.to_thread(
                self._run_strategy_sync, symbol, strategy, df, current_price, regime
            )

            if signal:
                state.last_signal = signal

            return signal

        except Exception as e:
            logger.error(f"Error evaluating {symbol}: {e}")
            return None

    def _run_strategy_sync(
        self,
        symbol: str,
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
                f"[{symbol}] Signal: {action.upper()} | "
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
                indicators={
                    "score": score,
                    "tier": tier,
                },
            )

        except Exception as e:
            logger.error(f"Strategy execution error for {symbol}: {e}")
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
        state = self._states.get(symbol)
        account = self._accounts.get(symbol)

        if not state:
            return None

        if signal.action == "buy" and not state.active:
            return await self._execute_buy(symbol, signal, price, account)
        elif signal.action == "sell" and state.active:
            return await self._execute_sell(symbol, signal, price, account)

        return None

    async def _execute_buy(
        self,
        symbol: str,
        signal: MultiAssetSignal,
        price: float,
        account: Optional[Any],
    ) -> Optional[Dict]:
        """Execute buy for an asset."""
        if self._block_new_entries:
            logger.info(f"[{symbol}] Entry blocked by risk guard")
            return None

        state = self._states[symbol]
        available_capital = self._portfolio.get_available_capital(symbol)
        buy_amount = available_capital * min(signal.fraction, 0.9)

        min_order = 10000  # 10,000 KRW minimum
        if buy_amount < min_order:
            logger.info(f"[{symbol}] Buy amount too small: {buy_amount:,.0f}")
            return None

        try:
            if self._execution_mode == "live" and account:
                result = account.buy(buy_amount, price)
                if not result or not result.get("success"):
                    logger.error(f"[{symbol}] Buy failed: {result}")
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

            # Update portfolio
            self._portfolio.update_position(
                symbol, qty, actual_price, actual_price, signal.strategy
            )
            self._portfolio.adjust_cash(-buy_amount)

            trade = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "type": "buy",
                "price": actual_price,
                "quantity": qty,
                "amount_krw": buy_amount,
                "reason": signal.reason,
                "strategy": signal.strategy,
            }

            msg = f"🟢 [{symbol}] BUY {qty:.6f} @ {actual_price:,.0f}"
            logger.info(msg)
            self._notify(msg)

            # Persist state after successful trade
            self._save_state()

            return trade

        except Exception as e:
            logger.error(f"[{symbol}] Buy execution failed: {e}")
            return None

    async def _execute_sell(
        self,
        symbol: str,
        signal: MultiAssetSignal,
        price: float,
        account: Optional[Any],
    ) -> Optional[Dict]:
        """Execute sell for an asset."""
        state = self._states[symbol]

        if state.quantity <= 0:
            return None

        try:
            if self._execution_mode == "live" and account:
                result = account.sell(state.quantity, price)
                if not result or not result.get("success"):
                    logger.error(f"[{symbol}] Sell failed: {result}")
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

            # Update portfolio
            self._portfolio.update_position(symbol, 0, 0, actual_price, None)
            self._portfolio.adjust_cash(proceeds)

            trade = {
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                "type": "sell",
                "price": actual_price,
                "quantity": sold_qty,
                "proceeds_krw": proceeds,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "reason": signal.reason,
                "strategy": signal.strategy,
            }

            msg = f"🔴 [{symbol}] SELL @ {actual_price:,.0f} | PnL: {pnl:+,.0f} ({pnl_pct:+.2f}%)"
            logger.info(msg)
            self._notify(msg)

            # Persist state after successful trade
            self._save_state()

            return trade

        except Exception as e:
            logger.error(f"[{symbol}] Sell execution failed: {e}")
            return None

    def _notify(self, message: str) -> None:
        """Send telegram notification."""
        if self._telegram:
            try:
                self._telegram.send_message(message)
            except Exception as e:
                logger.warning(f"Telegram notification failed: {e}")

    def get_state(self, symbol: str) -> Optional[AssetState]:
        """Get state for a specific asset."""
        return self._states.get(symbol)

    def get_all_states(self) -> Dict[str, AssetState]:
        """Get all asset states."""
        return self._states.copy()

    def get_total_exposure(self) -> float:
        """Get total exposure across all assets (in asset units * price)."""
        return sum(
            s.quantity * s.current_price
            for s in self._states.values()
            if s.active
        )

    def get_exposure_by_symbol(self, symbol: str) -> float:
        """Get exposure for a specific symbol."""
        state = self._states.get(symbol)
        if state and state.active:
            return state.quantity
        return 0.0

    def get_long_exposure_krw(self, symbol: str = "BTC") -> float:
        """
        Get long exposure value in KRW for hedge sizing.

        Args:
            symbol: Asset symbol (default BTC)

        Returns:
            Position value in KRW (quantity * current_price)
        """
        state = self._states.get(symbol)
        if state and state.active and state.quantity > 0:
            return state.quantity * state.current_price
        return 0.0

    def get_total_long_exposure_krw(self) -> float:
        """
        Get total long exposure across all assets in KRW.

        Returns:
            Total position value in KRW
        """
        return sum(
            self.get_long_exposure_krw(symbol)
            for symbol in self._states.keys()
        )

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
        return {
            "assets": {
                symbol: {
                    "active": state.active,
                    "quantity": state.quantity,
                    "entry_price": state.entry_price,
                    "current_price": state.current_price,
                    "regime": state.regime,
                    "strategy": state.strategy,
                }
                for symbol, state in self._states.items()
            },
            "statistics": self.get_statistics(),
            "portfolio": self._portfolio.get_stats(),
            "health": self._health_tracker.get_summary(),
        }
