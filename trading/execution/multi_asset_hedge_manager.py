"""
MultiAssetHedgeManager - Per-asset hedge position management.

Manages Binance short positions for multiple assets to hedge
their respective long positions on Upbit.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Any

logger = logging.getLogger(__name__)


@dataclass
class AssetHedgePosition:
    """Hedge position for a single asset."""
    symbol: str
    qty: float
    entry_price: float
    entry_premium: float
    entry_time: datetime
    accumulated_funding: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "qty": self.qty,
            "entry_price": self.entry_price,
            "entry_premium": self.entry_premium,
            "entry_time": self.entry_time.isoformat(),
            "accumulated_funding": self.accumulated_funding,
        }


@dataclass
class AssetHedgeTrade:
    """Completed hedge trade for a single asset."""
    symbol: str
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
            "symbol": self.symbol,
            "entry_time": self.entry_time.isoformat(),
            "exit_time": self.exit_time.isoformat(),
            "qty": self.qty,
            "entry_price": self.entry_price,
            "exit_price": self.exit_price,
            "pnl": self.pnl,
            "funding": self.funding,
            "fees": self.fees,
        }


class MultiAssetHedgeManager:
    """
    Manages hedge positions across multiple assets.

    Features:
    - Per-asset position tracking
    - Per-asset capital allocation
    - Dynamic slippage based on volatility
    - Integration with premium controllers per asset
    """

    DEFAULT_CONFIG = {
        "total_capital_usdt": 5000,
        "max_capital_usage_pct": 0.8,
        "fee_pct": 0.04,
        "slippage_pct": 0.02,
        "slippage_elevated_pct": 0.04,
        "slippage_high_pct": 0.08,
        "max_retries": 3,
    }

    def __init__(
        self,
        hedgeable_symbols: List[str],
        binance_accounts: Dict[str, Any],
        config: Optional[Dict[str, Any]] = None,
        telegram_notifier: Optional[Any] = None,
        execution_mode: str = "paper",
    ):
        """
        Args:
            hedgeable_symbols: List of symbols that can be hedged
            binance_accounts: Dict of symbol -> Binance account
            config: Configuration with hedge settings
            telegram_notifier: Optional telegram notifier
            execution_mode: "paper" or "live"
        """
        self._symbols = hedgeable_symbols
        self._accounts = binance_accounts
        self._config = {**self.DEFAULT_CONFIG, **(config or {})}
        self._telegram = telegram_notifier
        self._execution_mode = execution_mode

        # Per-asset capital allocation (proportional)
        self._total_capital = float(self._config.get("total_capital_usdt", 5000))
        self._capital_per_asset: Dict[str, float] = {}
        self._allocate_capital()

        # Per-asset positions
        self._positions: Dict[str, AssetHedgePosition] = {}

        # Trade history
        self._trades: Dict[str, List[AssetHedgeTrade]] = {
            sym: [] for sym in hedgeable_symbols
        }

        logger.info(f"MultiAssetHedgeManager initialized for {hedgeable_symbols}")

    @classmethod
    def from_config(
        cls,
        config: Dict[str, Any],
        binance_accounts: Dict[str, Any],
        **kwargs,
    ) -> "MultiAssetHedgeManager":
        """Create from allocation config."""
        assets = config.get("assets", {})
        hedgeable = [
            symbol for symbol, cfg in assets.items()
            if cfg.get("enabled") and cfg.get("hedge_enabled")
        ]

        hedge_config = config.get("hedge", {})

        return cls(
            hedgeable_symbols=hedgeable,
            binance_accounts=binance_accounts,
            config=hedge_config,
            **kwargs,
        )

    def _allocate_capital(self) -> None:
        """Allocate capital equally among hedgeable assets."""
        if not self._symbols:
            return

        per_asset = self._total_capital / len(self._symbols)
        for symbol in self._symbols:
            self._capital_per_asset[symbol] = per_asset

    def get_position_qty(self, symbol: str) -> float:
        """Get hedge position quantity for a symbol."""
        pos = self._positions.get(symbol)
        return pos.qty if pos else 0.0

    def get_position(self, symbol: str) -> Optional[AssetHedgePosition]:
        """Get hedge position for a symbol."""
        return self._positions.get(symbol)

    def is_hedged(self, symbol: str) -> bool:
        """Check if symbol is currently hedged."""
        return symbol in self._positions and self._positions[symbol].qty > 0

    async def open_hedge(
        self,
        symbol: str,
        qty: float,
        price: float,
        premium: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Open hedge position for an asset.

        Args:
            symbol: Asset symbol
            qty: Quantity to hedge
            price: Current price
            premium: Current premium percentage

        Returns:
            Result dict with success status
        """
        if symbol not in self._symbols:
            return {"success": False, "error": f"Symbol {symbol} not hedgeable"}

        # Check capital limits
        capital = self._capital_per_asset.get(symbol, 0)
        margin_required = qty * price
        max_margin = capital * self._config["max_capital_usage_pct"]

        if margin_required > max_margin:
            qty = max_margin / price
            margin_required = qty * price
            logger.warning(f"[{symbol}] Hedge qty capped to {qty:.6f}")

        if qty <= 0:
            return {"success": False, "error": "Quantity too small"}

        # Calculate fees
        fee_pct = (self._config["fee_pct"] + self._config["slippage_pct"]) / 100
        fee = margin_required * fee_pct

        try:
            account = self._accounts.get(symbol)

            if self._execution_mode == "live" and account:
                if hasattr(account, 'open_short'):
                    result = account.open_short(qty, price)
                    if not result or not result.get("success"):
                        return {"success": False, "error": str(result)}
                    filled_qty = result.get("filled_qty", qty)
                    avg_price = result.get("avg_price", price)
                else:
                    return {"success": False, "error": "Account missing open_short"}
            else:
                # Paper mode
                filled_qty = qty
                avg_price = price

            # Record position
            self._positions[symbol] = AssetHedgePosition(
                symbol=symbol,
                qty=filled_qty,
                entry_price=avg_price,
                entry_premium=premium,
                entry_time=datetime.now(),
            )

            # Deduct fee
            self._capital_per_asset[symbol] -= fee

            logger.info(f"[{symbol}] Hedge opened: {filled_qty:.6f} @ ${avg_price:,.2f}")
            await self._notify(f"🔒 [{symbol}] Hedge opened: {filled_qty:.4f} @ ${avg_price:,.2f}")

            return {
                "success": True,
                "filled_qty": filled_qty,
                "avg_price": avg_price,
                "fee": fee,
            }

        except Exception as e:
            logger.error(f"[{symbol}] Open hedge failed: {e}")
            return {"success": False, "error": str(e)}

    async def close_hedge(
        self,
        symbol: str,
        price: float,
        premium: float = 0.0,
    ) -> Dict[str, Any]:
        """
        Close hedge position for an asset.

        Args:
            symbol: Asset symbol
            price: Current price
            premium: Current premium percentage

        Returns:
            Result dict with P&L info
        """
        pos = self._positions.get(symbol)
        if not pos:
            return {"success": False, "error": "No position to close"}

        qty = pos.qty
        fee_pct = (self._config["fee_pct"] + self._config["slippage_pct"]) / 100
        fee = qty * price * fee_pct

        try:
            account = self._accounts.get(symbol)

            if self._execution_mode == "live" and account:
                if hasattr(account, 'close_short'):
                    result = account.close_short(qty)
                    if not result or not result.get("success"):
                        return {"success": False, "error": str(result)}
                    avg_price = result.get("avg_price", price)
                else:
                    return {"success": False, "error": "Account missing close_short"}
            else:
                avg_price = price

            # Calculate P&L
            pnl = (pos.entry_price - avg_price) * qty

            # Record trade
            trade = AssetHedgeTrade(
                symbol=symbol,
                entry_time=pos.entry_time,
                exit_time=datetime.now(),
                qty=qty,
                entry_price=pos.entry_price,
                exit_price=avg_price,
                entry_premium=pos.entry_premium,
                exit_premium=premium,
                pnl=pnl,
                funding=pos.accumulated_funding,
                fees=fee,
            )
            self._trades[symbol].append(trade)

            # Update capital
            net_pnl = pnl + pos.accumulated_funding - fee
            self._capital_per_asset[symbol] += net_pnl

            # Clear position
            del self._positions[symbol]

            logger.info(f"[{symbol}] Hedge closed: PnL ${net_pnl:+,.2f}")
            await self._notify(f"🔓 [{symbol}] Hedge closed: PnL ${net_pnl:+,.2f}")

            return {
                "success": True,
                "avg_price": avg_price,
                "pnl": pnl,
                "funding": pos.accumulated_funding,
                "fee": fee,
                "net_pnl": net_pnl,
            }

        except Exception as e:
            logger.error(f"[{symbol}] Close hedge failed: {e}")
            return {"success": False, "error": str(e)}

    async def adjust_position(
        self,
        symbol: str,
        target_qty: float,
        price: float,
    ) -> Dict[str, Any]:
        """
        Adjust hedge position to target quantity.

        Args:
            symbol: Asset symbol
            target_qty: Target short quantity
            price: Current price

        Returns:
            Result dict with adjustment info
        """
        current_qty = self.get_position_qty(symbol)
        diff = target_qty - current_qty

        if abs(diff) < 0.0001:
            return {"success": True, "qty_adjusted": 0}

        if diff > 0:
            return await self._increase_position(symbol, diff, price)
        else:
            return await self._decrease_position(symbol, abs(diff), price)

    async def _increase_position(
        self,
        symbol: str,
        qty: float,
        price: float,
    ) -> Dict[str, Any]:
        """Increase hedge position."""
        pos = self._positions.get(symbol)
        if not pos:
            # Open new position
            return await self.open_hedge(symbol, qty, price)

        # Check capital
        capital = self._capital_per_asset.get(symbol, 0)
        margin_required = qty * price
        max_margin = capital * self._config["max_capital_usage_pct"]

        if margin_required > max_margin:
            qty = max_margin / price

        if qty <= 0:
            return {"success": False, "qty_adjusted": 0, "error": "Insufficient capital"}

        fee_pct = (self._config["fee_pct"] + self._config["slippage_pct"]) / 100
        fee = qty * price * fee_pct

        try:
            account = self._accounts.get(symbol)

            if self._execution_mode == "live" and account:
                if hasattr(account, 'open_short'):
                    result = account.open_short(qty, price)
                    if not result or not result.get("success"):
                        return {"success": False, "error": str(result)}
                    filled_qty = result.get("filled_qty", qty)
                else:
                    return {"success": False, "error": "Account missing open_short"}
            else:
                filled_qty = qty

            # Update position
            pos.qty += filled_qty
            self._capital_per_asset[symbol] -= fee

            logger.info(f"[{symbol}] Hedge increased: +{filled_qty:.6f}")

            return {
                "success": True,
                "direction": "increase",
                "qty_adjusted": filled_qty,
                "new_short_qty": pos.qty,
                "fees_paid": fee,
            }

        except Exception as e:
            logger.error(f"[{symbol}] Increase failed: {e}")
            return {"success": False, "error": str(e)}

    async def _decrease_position(
        self,
        symbol: str,
        qty: float,
        price: float,
    ) -> Dict[str, Any]:
        """Decrease hedge position."""
        pos = self._positions.get(symbol)
        if not pos:
            return {"success": False, "error": "No position to decrease"}

        qty = min(qty, pos.qty)
        if qty <= 0:
            return {"success": True, "qty_adjusted": 0}

        fee_pct = (self._config["fee_pct"] + self._config["slippage_pct"]) / 100
        fee = qty * price * fee_pct

        try:
            account = self._accounts.get(symbol)

            if self._execution_mode == "live" and account:
                if hasattr(account, 'close_short'):
                    result = account.close_short(qty)
                    if not result or not result.get("success"):
                        return {"success": False, "error": str(result)}
                else:
                    return {"success": False, "error": "Account missing close_short"}

            # Update position
            pos.qty -= qty
            self._capital_per_asset[symbol] -= fee

            # If fully closed, remove position
            if pos.qty < 0.0001:
                del self._positions[symbol]
                new_qty = 0.0
            else:
                new_qty = pos.qty

            logger.info(f"[{symbol}] Hedge decreased: -{qty:.6f}")

            return {
                "success": True,
                "direction": "decrease",
                "qty_adjusted": qty,
                "new_short_qty": new_qty,
                "fees_paid": fee,
            }

        except Exception as e:
            logger.error(f"[{symbol}] Decrease failed: {e}")
            return {"success": False, "error": str(e)}

    def apply_funding(
        self,
        symbol: str,
        price: float,
        rate: float,
    ) -> float:
        """Apply funding rate to position."""
        pos = self._positions.get(symbol)
        if not pos:
            return 0.0

        funding = pos.qty * price * rate
        pos.accumulated_funding += funding
        return funding

    async def _notify(self, message: str) -> None:
        """Send telegram notification."""
        if self._telegram:
            try:
                if asyncio.iscoroutinefunction(self._telegram.send_message):
                    await self._telegram.send_message(message)
                else:
                    self._telegram.send_message(message)
            except Exception as e:
                logger.warning(f"Telegram failed: {e}")

    def get_all_positions(self) -> Dict[str, AssetHedgePosition]:
        """Get all hedge positions."""
        return self._positions.copy()

    def get_total_exposure_usd(self, prices: Dict[str, float]) -> float:
        """Get total hedge exposure in USD."""
        total = 0.0
        for symbol, pos in self._positions.items():
            price = prices.get(symbol, pos.entry_price)
            total += pos.qty * price
        return total

    def get_statistics(self, symbol: Optional[str] = None) -> Dict[str, Any]:
        """Get hedge statistics."""
        if symbol:
            trades = self._trades.get(symbol, [])
            return self._calc_stats(symbol, trades)

        # All symbols
        return {
            sym: self._calc_stats(sym, trades)
            for sym, trades in self._trades.items()
        }

    def _calc_stats(self, symbol: str, trades: List[AssetHedgeTrade]) -> Dict[str, Any]:
        """Calculate stats for a symbol."""
        if not trades:
            return {
                "total_trades": 0,
                "total_pnl": 0,
                "total_funding": 0,
                "total_fees": 0,
                "net_pnl": 0,
                "win_rate": 0,
            }

        total_pnl = sum(t.pnl for t in trades)
        total_funding = sum(t.funding for t in trades)
        total_fees = sum(t.fees for t in trades)
        net_pnl = total_pnl + total_funding - total_fees

        winning = [t for t in trades if t.pnl + t.funding - t.fees > 0]
        win_rate = len(winning) / len(trades) * 100 if trades else 0

        return {
            "total_trades": len(trades),
            "total_pnl": round(total_pnl, 2),
            "total_funding": round(total_funding, 2),
            "total_fees": round(total_fees, 2),
            "net_pnl": round(net_pnl, 2),
            "win_rate": round(win_rate, 1),
        }

    def get_stats(self) -> Dict[str, Any]:
        """Get overall statistics."""
        return {
            "symbols": self._symbols,
            "total_capital": self._total_capital,
            "capital_per_asset": self._capital_per_asset,
            "positions": {
                sym: pos.to_dict()
                for sym, pos in self._positions.items()
            },
            "statistics": self.get_statistics(),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for logging."""
        return self.get_stats()
