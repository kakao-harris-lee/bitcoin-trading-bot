"""
HedgeManager - Delta-neutral hedge execution manager.

Manages Binance short positions to hedge Upbit long positions.
Completely independent from Alpha strategies (v35, va02, SHORT_V1).
"""

import asyncio
from datetime import datetime
from typing import Dict, List, Optional, Any, Protocol
from dataclasses import dataclass, field, asdict
import logging

from trading.risk.premium_controller import PremiumController, HedgeSignal, PremiumStats

logger = logging.getLogger(__name__)


class BinanceAccountProtocol(Protocol):
    """Protocol for Binance account operations."""

    async def open_short(self, qty: float, price: float) -> Dict[str, Any]:
        """Open a short position."""
        ...

    async def close_short(self, qty: float) -> Dict[str, Any]:
        """Close a short position."""
        ...

    async def get_position(self) -> Optional[Dict[str, Any]]:
        """Get current position info."""
        ...

    def get_balance(self) -> tuple[float, float]:
        """Get (cash, position) balance."""
        ...


@dataclass
class HedgePosition:
    """Current hedge position state."""
    qty: float
    entry_price: float
    entry_premium: float
    entry_time: datetime
    accumulated_funding: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "qty": self.qty,
            "entry_price": self.entry_price,
            "entry_premium": self.entry_premium,
            "entry_time": self.entry_time.isoformat(),
            "accumulated_funding": self.accumulated_funding,
        }


@dataclass
class HedgeTrade:
    """Completed hedge trade record."""
    entry_time: datetime
    exit_time: datetime
    qty: float
    entry_price: float
    exit_price: float
    entry_premium: float
    exit_premium: float
    pnl: float
    funding: float
    fees: float

    def to_dict(self) -> Dict[str, Any]:
        return {
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "qty": self.qty,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "entry_premium": self.entry_premium,
            "exit_premium": self.exit_premium,
            "pnl": self.pnl,
            "funding": self.funding,
            "fees": self.fees,
        }


class ExecutionError(Exception):
    """Raised when order execution fails."""
    pass


class HedgeManager:
    """
    Manages delta-neutral hedge positions independently from Alpha strategies.

    Responsibilities:
    - Maintains separate capital pool (Binance USDT margin)
    - Opens/closes shorts to match Upbit long exposure
    - Enforces 1:1 delta-neutral ratio
    - Logs hedge P&L separately from Alpha P&L
    """

    DEFAULT_CONFIG = {
        "capital_usdt": 5000,           # Separate hedge capital pool
        "max_capital_usage_pct": 0.8,   # Max 80% of capital per position
        "fee_pct": 0.04,                # Binance taker fee
        "slippage_pct": 0.02,           # Base expected slippage
        "slippage_elevated_pct": 0.04,  # Slippage during elevated volatility
        "slippage_high_pct": 0.08,      # Slippage during high volatility
        "max_retries": 3,               # Retry count for failed orders
    }

    def __init__(
        self,
        binance_account: Any,  # BinanceAccountProtocol
        premium_controller: PremiumController,
        config: Optional[Dict[str, Any]] = None,
        telegram_notifier: Optional[Any] = None,
        execution_mode: str = "paper",
    ):
        """
        Initialize HedgeManager.

        Args:
            binance_account: Dedicated Binance account for hedging
            premium_controller: Premium signal generator
            config: Optional configuration overrides
            telegram_notifier: Optional telegram notifier for alerts
            execution_mode: "paper" or "live"
        """
        self.account = binance_account
        self.controller = premium_controller
        self.config = {**self.DEFAULT_CONFIG, **(config or {})}
        self.telegram = telegram_notifier
        self.execution_mode = execution_mode

        # Capital tracking
        self.capital = float(self.config["capital_usdt"])
        self.initial_capital = self.capital

        # Position state
        self.hedge_position: Optional[HedgePosition] = None
        self.trades: List[HedgeTrade] = []

        # Execution tracking
        self._last_signal: Optional[HedgeSignal] = None
        self._consecutive_errors: int = 0

    @property
    def is_hedged(self) -> bool:
        """Check if currently hedged."""
        return self.hedge_position is not None

    def _get_dynamic_slippage(self) -> float:
        """
        Get dynamic slippage based on current volatility state.

        Returns higher slippage during high volatility periods for more
        accurate actual profit calculations.

        Returns:
            Slippage percentage (0.02, 0.04, or 0.08)
        """
        try:
            stats = self.controller.get_stats()
            volatility_state = getattr(stats, 'volatility_state', None) or stats.get('volatility_state', 'normal')

            if volatility_state == "high":
                return self.config["slippage_high_pct"]
            elif volatility_state == "elevated":
                return self.config["slippage_elevated_pct"]
            else:
                return self.config["slippage_pct"]
        except Exception:
            return self.config["slippage_pct"]

    async def evaluate(
        self,
        upbit_btc_balance: float,
        binance_price: float,
        premium_info: Dict[str, float],
    ) -> Optional[HedgeSignal]:
        """
        Evaluate premium conditions and execute hedge if needed.

        Args:
            upbit_btc_balance: Current Upbit BTC balance (from AlphaManager)
            binance_price: Current Binance BTC price
            premium_info: Premium calculation data

        Returns:
            HedgeSignal indicating action taken
        """
        # Generate signal from controller
        signal = self.controller.generate_signal(
            premium_info=premium_info,
            upbit_btc_qty=upbit_btc_balance,
        )

        self._last_signal = signal

        try:
            if signal.action == "open" and not self.hedge_position:
                await self._open_hedge(signal, binance_price)
            elif signal.action == "close" and self.hedge_position:
                await self._close_hedge(signal, binance_price)

            self._consecutive_errors = 0

        except Exception as e:
            self._consecutive_errors += 1
            logger.error(f"Hedge execution error: {e}")
            if self._consecutive_errors >= 3:
                await self._notify(f"🚨 Hedge execution failed {self._consecutive_errors}x: {e}")

        return signal

    async def _open_hedge(self, signal: HedgeSignal, price: float) -> None:
        """Open Binance short matching Upbit long."""
        qty = signal.target_btc_qty

        # Check capital limits
        margin_required = qty * price
        max_margin = self.capital * self.config["max_capital_usage_pct"]

        if margin_required > max_margin:
            # Cap at available capital
            qty = max_margin / price
            margin_required = qty * price
            logger.warning(f"Hedge qty capped to {qty:.6f} BTC due to capital limits")

        if qty <= 0:
            logger.warning("Hedge qty is zero, skipping open")
            return

        # Calculate fees with dynamic slippage
        slippage = self._get_dynamic_slippage()
        fee_pct = (self.config["fee_pct"] + slippage) / 100
        fee = margin_required * fee_pct

        try:
            # Execute short order based on execution mode
            if self.execution_mode == "live":
                # LIVE MODE: Place actual order on exchange
                if hasattr(self.account, 'open_short'):
                    result = self.account.open_short(qty, price)
                    if not result or not result.get("success"):
                        raise ExecutionError(f"Live short order failed: {result}")
                else:
                    raise ExecutionError("Live account missing open_short method")
            else:
                # PAPER MODE: Simulate trade
                result = self._sync_open_short(qty, price)

            if not result.get("success", True):
                raise ExecutionError(f"Short order failed: {result.get('error', 'unknown')}")

            # Record position
            filled_qty = result.get("filled_qty", qty)
            avg_price = result.get("avg_price", price)

            self.hedge_position = HedgePosition(
                qty=filled_qty,
                entry_price=avg_price,
                entry_premium=signal.premium_stats.current,
                entry_time=datetime.now(),
            )

            # Update controller state
            self.controller.set_position_state(True, self.hedge_position.entry_time)

            # Deduct margin + fees from capital
            self.capital -= fee

            logger.info(f"Hedge opened: {filled_qty:.6f} BTC @ ${avg_price:,.2f} (premium: {signal.premium_stats.current:+.2f}%)")
            await self._notify(f"🔒 Hedge opened: {filled_qty:.4f} BTC @ ${avg_price:,.2f}\nPremium: {signal.premium_stats.current:+.2f}%")

        except Exception as e:
            logger.error(f"Failed to open hedge: {e}")
            await self._notify(f"❌ Hedge open failed: {e}")
            raise

    async def _close_hedge(self, signal: HedgeSignal, price: float) -> None:
        """Close hedge with retry on failure."""
        if not self.hedge_position:
            return

        pos = self.hedge_position
        qty = pos.qty
        max_retries = self.config["max_retries"]

        for attempt in range(max_retries):
            try:
                # Execute close order based on execution mode
                if self.execution_mode == "live":
                    # LIVE MODE: Place actual order on exchange
                    if hasattr(self.account, 'close_short'):
                        result = self.account.close_short(qty)
                        if not result or not result.get("success"):
                            raise ExecutionError(f"Live close order failed: {result}")
                    else:
                        raise ExecutionError("Live account missing close_short method")
                else:
                    # PAPER MODE: Simulate trade
                    result = self._sync_close_short(qty, price)

                if result.get("success", True):
                    # Calculate P&L
                    exit_price = result.get("avg_price", price)
                    pnl = (pos.entry_price - exit_price) * qty  # Short P&L

                    # Calculate fees with dynamic slippage
                    slippage = self._get_dynamic_slippage()
                    fee_pct = (self.config["fee_pct"] + slippage) / 100
                    exit_fee = qty * exit_price * fee_pct

                    # Record trade
                    trade = HedgeTrade(
                        entry_time=pos.entry_time,
                        exit_time=datetime.now(),
                        qty=qty,
                        entry_price=pos.entry_price,
                        exit_price=exit_price,
                        entry_premium=pos.entry_premium,
                        exit_premium=signal.premium_stats.current,
                        pnl=pnl,
                        funding=pos.accumulated_funding,
                        fees=exit_fee,
                    )
                    self.trades.append(trade)

                    # Update capital
                    self.capital += pnl + pos.accumulated_funding - exit_fee

                    # Clear position
                    self.hedge_position = None
                    self.controller.set_position_state(False)

                    net_pnl = pnl + pos.accumulated_funding - exit_fee
                    logger.info(f"Hedge closed: {qty:.6f} BTC @ ${exit_price:,.2f}, PnL: ${net_pnl:+,.2f}")
                    await self._notify(f"🔓 Hedge closed: PnL ${net_pnl:+,.2f}\nReason: {signal.reason}")
                    return

            except Exception as e:
                if attempt < max_retries - 1:
                    wait_time = 2 ** attempt
                    logger.warning(f"Close attempt {attempt + 1} failed, retrying in {wait_time}s: {e}")
                    await asyncio.sleep(wait_time)
                    continue

                # Final failure
                await self._notify(
                    f"🚨 CRITICAL: Hedge close failed after {max_retries} attempts!\n"
                    f"Position: {qty:.4f} BTC still open\n"
                    f"Error: {e}\n"
                    f"Manual intervention required!"
                )
                raise

    def _sync_open_short(self, qty: float, price: float) -> Dict[str, Any]:
        """Synchronous open short for paper trading."""
        # For paper trading account
        if hasattr(self.account, 'open_position'):
            self.account.open_position(qty, price, leverage=1)
        return {"success": True, "filled_qty": qty, "avg_price": price}

    def _sync_close_short(self, qty: float, price: float) -> Dict[str, Any]:
        """Synchronous close short for paper trading."""
        if hasattr(self.account, 'close_position'):
            result = self.account.close_position(price)
            return {"success": True, "avg_price": price, **result}
        return {"success": True, "avg_price": price}

    def apply_funding(self, binance_price: float, rate: float) -> float:
        """
        Apply funding rate to hedge position.

        Args:
            binance_price: Current Binance price
            rate: Funding rate (positive = shorts receive)

        Returns:
            Funding amount applied
        """
        if not self.hedge_position:
            return 0.0

        # Funding = position_value * rate
        funding = self.hedge_position.qty * binance_price * rate
        self.hedge_position.accumulated_funding += funding

        # Update controller with current funding rate
        self.controller.set_funding_rate(rate)

        return funding

    async def sync_position(self) -> None:
        """
        Sync local state with exchange (called on startup).

        Reconciles local hedge_position with actual exchange position.
        """
        try:
            if hasattr(self.account, 'get_position'):
                if asyncio.iscoroutinefunction(self.account.get_position):
                    exchange_pos = await self.account.get_position()
                else:
                    exchange_pos = self.account.get_position()
            else:
                exchange_pos = None

            if exchange_pos and exchange_pos.get("size", 0) > 0:
                if not self.hedge_position:
                    # Exchange has position, local doesn't - recover
                    self.hedge_position = HedgePosition(
                        qty=exchange_pos["size"],
                        entry_price=exchange_pos.get("entry_price", 0),
                        entry_premium=0,  # Unknown
                        entry_time=datetime.now(),
                    )
                    self.controller.set_position_state(True, self.hedge_position.entry_time)
                    await self._notify(f"⚠️ Recovered orphan hedge: {exchange_pos['size']:.4f} BTC")

            elif self.hedge_position and (not exchange_pos or exchange_pos.get("size", 0) == 0):
                # Local has position, exchange doesn't - clear local
                self.hedge_position = None
                self.controller.set_position_state(False)
                await self._notify("⚠️ Cleared stale local hedge position")

        except Exception as e:
            logger.error(f"Position sync failed: {e}")
            await self._notify(f"⚠️ Hedge position sync failed: {e}")

    async def adjust_position(self, target_qty: float, current_price: float) -> Optional[Dict[str, Any]]:
        """
        Adjust existing hedge position to match target quantity.

        Used by DeltaRebalancer to maintain delta neutrality when Alpha
        positions change.

        Args:
            target_qty: Desired short BTC quantity (should match Upbit long)
            current_price: Current Binance BTC price

        Returns:
            Dict with direction, qty_adjusted, new_short_qty, fees_paid, success
            None if no adjustment needed
        """
        if not self.hedge_position:
            return None

        current_qty = self.hedge_position.qty
        diff = target_qty - current_qty

        if abs(diff) < 0.0001:  # Negligible difference
            return None

        if diff > 0:
            # Need to increase short (Alpha bought more)
            return await self._increase_short(diff, current_price)
        else:
            # Need to decrease short (Alpha sold some)
            return await self._decrease_short(abs(diff), current_price)

    async def _increase_short(self, qty: float, price: float) -> Dict[str, Any]:
        """Increase short position for rebalancing."""
        # Check margin availability
        margin_required = qty * price
        max_margin = self.capital * self.config["max_capital_usage_pct"]

        if margin_required > max_margin:
            qty = max_margin / price  # Partial fill
            margin_required = qty * price
            logger.warning(f"Rebalance qty capped to {qty:.6f} BTC due to capital limits")

        if qty <= 0:
            return {"direction": "increase", "qty_adjusted": 0, "new_short_qty": self.hedge_position.qty,
                    "fees_paid": 0, "success": False}

        # Calculate fees with dynamic slippage
        slippage = self._get_dynamic_slippage()
        fee_pct = (self.config["fee_pct"] + slippage) / 100
        fee = margin_required * fee_pct

        try:
            # Execute order based on mode
            if self.execution_mode == "live":
                if hasattr(self.account, 'open_short'):
                    result = self.account.open_short(qty, price)
                    if not result or not result.get("success"):
                        raise ExecutionError(f"Live increase short failed: {result}")
                else:
                    raise ExecutionError("Live account missing open_short method")
            else:
                result = self._sync_open_short(qty, price)

            if result.get("success", True):
                filled_qty = result.get("filled_qty", qty)
                self.hedge_position.qty += filled_qty
                self.capital -= fee

                logger.info(f"Rebalance increase: +{filled_qty:.6f} BTC @ ${price:,.2f}, fee: ${fee:.2f}")
                await self._notify(f"🔄 Hedge rebalance: +{filled_qty:.4f} BTC @ ${price:,.2f}")

                return {
                    "direction": "increase",
                    "qty_adjusted": filled_qty,
                    "new_short_qty": self.hedge_position.qty,
                    "fees_paid": fee,
                    "success": True,
                }

        except Exception as e:
            logger.error(f"Rebalance increase failed: {e}")
            await self._notify(f"❌ Rebalance failed: {e}")

        return {"direction": "increase", "qty_adjusted": 0, "new_short_qty": self.hedge_position.qty,
                "fees_paid": 0, "success": False}

    async def _decrease_short(self, qty: float, price: float) -> Dict[str, Any]:
        """Decrease short position for rebalancing."""
        # Can't decrease more than current position
        qty = min(qty, self.hedge_position.qty)

        if qty <= 0:
            return {"direction": "decrease", "qty_adjusted": 0, "new_short_qty": self.hedge_position.qty,
                    "fees_paid": 0, "success": False}

        # Calculate fees with dynamic slippage
        slippage = self._get_dynamic_slippage()
        fee_pct = (self.config["fee_pct"] + slippage) / 100
        fee = qty * price * fee_pct

        try:
            # Execute order based on mode
            if self.execution_mode == "live":
                if hasattr(self.account, 'close_short'):
                    result = self.account.close_short(qty)
                    if not result or not result.get("success"):
                        raise ExecutionError(f"Live decrease short failed: {result}")
                else:
                    raise ExecutionError("Live account missing close_short method")
            else:
                result = self._sync_close_short(qty, price)

            if result.get("success", True):
                old_qty = self.hedge_position.qty
                self.hedge_position.qty -= qty
                self.capital -= fee

                # If fully closed, clear position
                if self.hedge_position.qty < 0.0001:
                    self.hedge_position = None
                    self.controller.set_position_state(False)
                    new_qty = 0.0
                else:
                    new_qty = self.hedge_position.qty

                logger.info(f"Rebalance decrease: -{qty:.6f} BTC @ ${price:,.2f}, fee: ${fee:.2f}")
                await self._notify(f"🔄 Hedge rebalance: -{qty:.4f} BTC @ ${price:,.2f}")

                return {
                    "direction": "decrease",
                    "qty_adjusted": qty,
                    "new_short_qty": new_qty,
                    "fees_paid": fee,
                    "success": True,
                }

        except Exception as e:
            logger.error(f"Rebalance decrease failed: {e}")
            await self._notify(f"❌ Rebalance failed: {e}")

        return {"direction": "decrease", "qty_adjusted": 0,
                "new_short_qty": self.hedge_position.qty if self.hedge_position else 0,
                "fees_paid": 0, "success": False}

    async def _notify(self, message: str) -> None:
        """Send telegram notification if available."""
        if self.telegram:
            try:
                if asyncio.iscoroutinefunction(self.telegram.send_message):
                    await self.telegram.send_message(message)
                else:
                    self.telegram.send_message(message)
            except Exception as e:
                logger.warning(f"Telegram notification failed: {e}")

    def get_statistics(self) -> Dict[str, Any]:
        """Get hedge trading statistics."""
        if not self.trades:
            return {
                "total_trades": 0,
                "total_pnl": 0,
                "total_funding": 0,
                "total_fees": 0,
                "net_pnl": 0,
                "win_rate": 0,
                "return_pct": 0,
            }

        total_pnl = sum(t.pnl for t in self.trades)
        total_funding = sum(t.funding for t in self.trades)
        total_fees = sum(t.fees for t in self.trades)
        net_pnl = total_pnl + total_funding - total_fees

        winning = [t for t in self.trades if t.pnl + t.funding - t.fees > 0]
        win_rate = len(winning) / len(self.trades) * 100

        return {
            "total_trades": len(self.trades),
            "total_pnl": round(total_pnl, 2),
            "total_funding": round(total_funding, 2),
            "total_fees": round(total_fees, 2),
            "net_pnl": round(net_pnl, 2),
            "win_rate": round(win_rate, 1),
            "return_pct": round((net_pnl / self.initial_capital) * 100, 2),
        }

    def get_delta_exposure(self, upbit_btc: float) -> Dict[str, Any]:
        """
        Calculate current delta exposure.

        Args:
            upbit_btc: Current Upbit BTC balance

        Returns:
            Delta exposure info
        """
        hedge_btc = self.hedge_position.qty if self.hedge_position else 0.0
        net_btc = upbit_btc - hedge_btc

        return {
            "long_btc": round(upbit_btc, 8),
            "short_btc": round(hedge_btc, 8),
            "net_btc": round(net_btc, 8),
            "is_neutral": abs(net_btc) < 0.001,
            "hedge_ratio": round(hedge_btc / upbit_btc, 3) if upbit_btc > 0 else 0,
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize manager state for logging."""
        return {
            "capital": round(self.capital, 2),
            "initial_capital": self.initial_capital,
            "is_hedged": self.is_hedged,
            "position": self.hedge_position.to_dict() if self.hedge_position else None,
            "statistics": self.get_statistics(),
            "last_signal": self._last_signal.to_dict() if self._last_signal else None,
        }
