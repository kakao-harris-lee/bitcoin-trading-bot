"""
AlphaManager - Directional Alpha strategy manager for Upbit.

Manages v35, va02, sideways_v2 strategies with regime-based gating.
Completely separate from Hedge strategies.
"""

import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Protocol
from dataclasses import dataclass, field

from core.data_loader import DataLoader
from trading.strategy.regime_router import RegimeRouter, RegimeDecision

logger = logging.getLogger(__name__)


class UpbitAccountProtocol(Protocol):
    """Protocol for Upbit account operations."""

    def buy(self, amount: float, price: float) -> Dict[str, Any]:
        """Execute buy order."""
        ...

    def sell(self, btc_amount: float, price: float) -> Dict[str, Any]:
        """Execute sell order."""
        ...

    def get_balance(self) -> tuple[float, float]:
        """Get (cash_krw, btc_balance)."""
        ...

    def get_total_value(self, price: float) -> float:
        """Get total portfolio value in KRW."""
        ...


@dataclass
class StrategyPosition:
    """Position state for a single strategy."""
    name: str
    active: bool = False
    btc: float = 0.0
    entry_price: float = 0.0
    cash: float = 0.0
    ratio: float = 0.5
    regimes: List[str] = field(default_factory=list)
    enabled: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "active": self.active,
            "btc": self.btc,
            "entry_price": self.entry_price,
            "cash": self.cash,
            "ratio": self.ratio,
            "regimes": self.regimes,
            "enabled": self.enabled,
        }


@dataclass
class AlphaSignal:
    """Signal from Alpha strategy."""
    strategy: str
    action: str  # "buy", "sell", "hold"
    fraction: float = 0.5
    reason: str = ""
    indicators: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "strategy": self.strategy,
            "action": self.action,
            "fraction": self.fraction,
            "reason": self.reason,
            "indicators": self.indicators,
        }


class AlphaManager:
    """
    Manages directional Alpha strategies (v35, va02, sideways_v2).

    Responsibilities:
    - Uses RegimeRouter for strategy selection (MFI/ADX based)
    - Manages Upbit spot positions only
    - No awareness of premium or hedge logic
    - Tracks per-strategy positions and P&L
    """

    def __init__(
        self,
        upbit_account: Any,
        regime_router: RegimeRouter,
        allocation_config: Dict[str, Any],
        strategies: Optional[Dict[str, Any]] = None,
        execution_mode: str = "paper",
        risk_config: Optional[Any] = None,
        telegram_notifier: Optional[Any] = None,
        delta_rebalancer: Optional[Any] = None,
    ):
        """
        Initialize AlphaManager.

        Args:
            upbit_account: Upbit account instance
            regime_router: RegimeRouter for market classification
            allocation_config: Strategy allocation from config
            strategies: Dict of strategy instances
            execution_mode: "paper" or "live"
            risk_config: Risk configuration
            telegram_notifier: Optional telegram notifier
            delta_rebalancer: Optional DeltaRebalancer for hedge notifications
        """
        self.account = upbit_account
        self.router = regime_router
        self.allocation = allocation_config
        self.strategies = strategies or {}
        self.execution_mode = execution_mode
        self.risk_config = risk_config
        self.telegram = telegram_notifier
        self.delta_rebalancer = delta_rebalancer

        # Per-strategy position tracking
        self.positions: Dict[str, StrategyPosition] = {}
        self._init_positions()

        # Trading state
        self._last_decision: Optional[RegimeDecision] = None
        self._block_new_entries: bool = False
        self._signal_history: List[Dict] = []
        self._trade_history: List[Dict] = []

    def _init_positions(self) -> None:
        """Initialize positions from allocation config."""
        upbit_config = self.allocation.get("upbit", {})

        for name in ["v35", "va02", "sideways_v2", "h4_conservative"]:
            config = upbit_config.get(name, {})
            if config.get("enabled", False):
                self.positions[name] = StrategyPosition(
                    name=name,
                    ratio=config.get("ratio", 0.5),
                    regimes=config.get("regimes", ["BULL"]),
                    enabled=True,
                )

        # Allocate initial capital
        self._allocate_capital()

    def _allocate_capital(self) -> None:
        """Allocate capital among enabled strategies."""
        cash, _ = self.account.get_balance()
        total_ratio = sum(p.ratio for p in self.positions.values())

        if total_ratio > 0:
            for pos in self.positions.values():
                pos.cash = cash * (pos.ratio / total_ratio)

    def set_strategies(self, strategies: Dict[str, Any]) -> None:
        """Set strategy instances."""
        self.strategies = strategies

    def set_block_entries(self, block: bool) -> None:
        """Set whether new entries are blocked (e.g., daily loss guard)."""
        self._block_new_entries = block

    def get_current_regime(self) -> str:
        """Get current regime from last decision."""
        return self._last_decision.regime if self._last_decision else "UNKNOWN"

    def get_market_state(self) -> str:
        """Get current market state from last decision."""
        return self._last_decision.market_state if self._last_decision else "UNKNOWN"

    def get_total_btc_exposure(self) -> float:
        """
        Get total BTC held across all Alpha strategies.
        Used by HedgeManager to calculate hedge size.
        """
        _, btc_balance = self.account.get_balance()
        return btc_balance

    def is_strategy_allowed_in_regime(self, strategy_name: str, regime: str) -> bool:
        """Check if strategy is allowed in current regime."""
        pos = self.positions.get(strategy_name)
        if not pos or not pos.enabled:
            return False
        return regime in pos.regimes

    def evaluate(self, current_price: float, df_day=None) -> List[AlphaSignal]:
        """
        Evaluate all enabled strategies based on regime.

        Args:
            current_price: Current Upbit BTC price
            df_day: Optional daily DataFrame (loaded if not provided)

        Returns:
            List of signals from strategies
        """
        # Get regime decision
        if df_day is None:
            df_day = self.router.get_recent_daily_df()

        decision = self.router.recommend(df_day)
        self._last_decision = decision
        regime = decision.regime

        signals = []

        for name, pos in self.positions.items():
            if not pos.enabled:
                continue

            # Check regime gating
            if not self.is_strategy_allowed_in_regime(name, regime):
                if not pos.active:
                    continue  # Skip if not in position

            # Generate signal
            signal = self._evaluate_strategy(name, pos, current_price)
            if signal:
                signals.append(signal)
                self._signal_history.append({
                    "timestamp": datetime.now().isoformat(),
                    "strategy": name,
                    "signal": signal.to_dict(),
                    "regime": regime,
                })

        return signals

    def _evaluate_strategy(
        self,
        name: str,
        pos: StrategyPosition,
        current_price: float,
    ) -> Optional[AlphaSignal]:
        """Evaluate a single strategy and return signal."""
        strategy = self.strategies.get(name)
        if not strategy:
            return None

        try:
            # Load data
            with DataLoader() as loader:
                df = loader.load_timeframe('day', start_date='2024-01-01')
            df = df.tail(500).reset_index(drop=True)

            # Add indicators and generate signal
            if hasattr(strategy, 'add_indicators'):
                df = strategy.add_indicators(df)

            if hasattr(strategy, 'generate_signal'):
                raw_signal = strategy.generate_signal(df, len(df) - 1)
            else:
                raw_signal = None

            if not raw_signal:
                raw_signal = {"action": "hold", "reason": f"{name.upper()}_NO_SIGNAL"}

            # Extract indicators for logging
            indicators = self._extract_indicators(df)
            if "score" in raw_signal:
                indicators["score"] = raw_signal.get("score", 0)
                indicators["tier"] = raw_signal.get("tier", "C")

            return AlphaSignal(
                strategy=name,
                action=raw_signal.get("action", "hold"),
                fraction=raw_signal.get("fraction", 0.5),
                reason=raw_signal.get("reason", ""),
                indicators=indicators,
            )

        except Exception as e:
            logger.error(f"Strategy {name} evaluation failed: {e}")
            return None

    def _extract_indicators(self, df, columns=None) -> Dict[str, Any]:
        """Extract indicator values from DataFrame."""
        if columns is None:
            columns = ["rsi", "mfi", "adx", "close"]

        indicators = {}
        for col in columns:
            if col in df.columns:
                val = df[col].iloc[-1]
                indicators[col] = round(float(val), 2) if not isinstance(val, str) else val

        return indicators

    def execute(self, signals: List[AlphaSignal], price: float) -> None:
        """Execute alpha signals on Upbit."""
        for signal in signals:
            pos = self.positions.get(signal.strategy)
            if not pos:
                continue

            if signal.action == "buy" and not pos.active:
                self._execute_buy(pos, signal, price)
            elif signal.action == "sell" and pos.active:
                self._execute_sell(pos, signal, price)

    def _execute_buy(
        self,
        pos: StrategyPosition,
        signal: AlphaSignal,
        price: float,
    ) -> None:
        """Execute buy for a strategy."""
        if self._block_new_entries:
            logger.info(f"[{pos.name}] Entry blocked by risk guard")
            return

        cash = pos.cash
        frac = min(signal.fraction, 0.9)  # Cap at 90%
        buy_amount = cash * frac

        min_order = 10000  # 10,000 KRW minimum
        if self.risk_config and hasattr(self.risk_config, 'min_upbit_order_krw'):
            min_order = float(self.risk_config.min_upbit_order_krw)

        if buy_amount < min_order:
            logger.info(f"[{pos.name}] Buy amount too small: {buy_amount:,.0f} < {min_order:,.0f}")
            return

        try:
            if self.execution_mode == "live":
                result = self.account.buy(buy_amount, price)
                if not result or not result.get("success"):
                    logger.error(f"[{pos.name}] Buy failed: {result}")
                    return
                btc_amount = float(result.get("executed_volume", 0))
                actual_price = float(result.get("executed_price", price))
                # Refresh balance
                actual_cash, _ = self.account.get_balance()
                pos.cash = actual_cash * pos.ratio
            else:
                # Paper mode
                fee_rate = 0.0005
                btc_amount = (buy_amount * (1 - fee_rate)) / price
                actual_price = price
                pos.cash = cash - buy_amount

            # Update position
            pos.active = True
            pos.btc = btc_amount
            pos.entry_price = actual_price

            # Notify DeltaRebalancer of position change
            if self.delta_rebalancer:
                self.delta_rebalancer.on_alpha_trade(btc_amount, "buy")

            # Record trade
            trade = {
                "timestamp": datetime.now().isoformat(),
                "strategy": pos.name,
                "type": "buy",
                "price": actual_price,
                "btc": btc_amount,
                "amount_krw": buy_amount,
                "reason": signal.reason,
            }
            self._trade_history.append(trade)

            msg = f"🟢 [{pos.name}] BUY {btc_amount:.6f} BTC @ {actual_price:,.0f}원"
            logger.info(msg)
            self._notify(msg)

        except Exception as e:
            logger.error(f"[{pos.name}] Buy execution failed: {e}")

    def _execute_sell(
        self,
        pos: StrategyPosition,
        signal: AlphaSignal,
        price: float,
    ) -> None:
        """Execute sell for a strategy."""
        if pos.btc <= 0:
            return

        try:
            if self.execution_mode == "live":
                result = self.account.sell(pos.btc, price)
                if not result or not result.get("success"):
                    logger.error(f"[{pos.name}] Sell failed: {result}")
                    return
                actual_price = float(result.get("executed_price", price))
                proceeds = float(result.get("executed_value", pos.btc * price))
                # Refresh balance
                actual_cash, _ = self.account.get_balance()
                pos.cash = actual_cash * pos.ratio
            else:
                # Paper mode
                fee_rate = 0.0005
                proceeds = pos.btc * price * (1 - fee_rate)
                actual_price = price
                pos.cash += proceeds

            # Calculate P&L
            pnl = (actual_price - pos.entry_price) * pos.btc
            pnl_pct = ((actual_price / pos.entry_price) - 1) * 100

            # Capture btc before clearing for rebalancer notification
            sold_btc = pos.btc

            # Record trade
            trade = {
                "timestamp": datetime.now().isoformat(),
                "strategy": pos.name,
                "type": "sell",
                "price": actual_price,
                "btc": sold_btc,
                "proceeds_krw": proceeds,
                "pnl": pnl,
                "pnl_pct": pnl_pct,
                "reason": signal.reason,
            }
            self._trade_history.append(trade)

            # Clear position
            pos.active = False
            pos.btc = 0.0
            pos.entry_price = 0.0

            # Notify DeltaRebalancer of position change
            if self.delta_rebalancer:
                self.delta_rebalancer.on_alpha_trade(sold_btc, "sell")

            msg = f"🔴 [{pos.name}] SELL @ {actual_price:,.0f}원 | PnL: {pnl:+,.0f}원 ({pnl_pct:+.2f}%)"
            logger.info(msg)
            self._notify(msg)

        except Exception as e:
            logger.error(f"[{pos.name}] Sell execution failed: {e}")

    def _notify(self, message: str) -> None:
        """Send notification if telegram available."""
        if self.telegram:
            try:
                self.telegram.send_message(message)
            except Exception as e:
                logger.warning(f"Telegram notification failed: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get trading statistics."""
        total_pnl = sum(t.get("pnl", 0) for t in self._trade_history if "pnl" in t)
        total_trades = len([t for t in self._trade_history if t.get("type") == "sell"])
        winning = [t for t in self._trade_history if t.get("pnl", 0) > 0]

        return {
            "total_trades": total_trades,
            "total_pnl_krw": round(total_pnl, 0),
            "win_rate": round(len(winning) / total_trades * 100, 1) if total_trades > 0 else 0,
            "positions": {name: pos.to_dict() for name, pos in self.positions.items()},
        }

    def get_signals_history(self, limit: int = 50) -> List[Dict]:
        """Get recent signal history."""
        return self._signal_history[-limit:]

    def get_trades_history(self, limit: int = 50) -> List[Dict]:
        """Get recent trade history."""
        return self._trade_history[-limit:]

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manager state for logging."""
        return {
            "regime": self.get_current_regime(),
            "market_state": self.get_market_state(),
            "positions": {name: pos.to_dict() for name, pos in self.positions.items()},
            "total_btc": self.get_total_btc_exposure(),
            "statistics": self.get_statistics(),
        }
