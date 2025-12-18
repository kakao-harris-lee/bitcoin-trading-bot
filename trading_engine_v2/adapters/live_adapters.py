"""Live trading account adapters.

These wrappers expose a PaperTradingAccount-like interface (buy/sell/open_short/close_short)
but execute real orders via exchange trader classes.

Safety: construction of the underlying trader classes is expected to be gated by the caller.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple


@dataclass
class UpbitLiveAccount:
    """Adapter over UpbitTrader with a PaperTradingAccount-like API."""

    trader: Any
    initial_capital: float

    def get_balance(self) -> Tuple[float, float]:
        return self.trader.get_balance()

    def get_total_value(self, current_price: float) -> float:
        krw, btc = self.get_balance()
        return float(krw) + float(btc) * float(current_price)

    def buy(self, amount: float, price: float) -> Dict[str, Any]:  # price ignored (market)
        result = self.trader.buy_market_order(float(amount))
        return result or {"success": False, "error": "BUY_FAILED"}

    def sell(self, btc_qty: float, price: float) -> Dict[str, Any]:  # price ignored (market)
        result = self.trader.sell_market_order(float(btc_qty))
        return result or {"success": False, "error": "SELL_FAILED"}

    def get_statistics(self) -> Dict[str, Any]:
        total_value = self.trader.get_total_value()
        return_pct = ((total_value - self.initial_capital) / self.initial_capital) * 100 if self.initial_capital > 0 else 0.0
        return {
            "total_trades": None,
            "total_pnl": None,
            "total_fees": None,
            "net_pnl": None,
            "win_rate": None,
            "initial_capital": self.initial_capital,
            "current_cash": self.get_balance()[0],
            "return_pct": return_pct,
        }


@dataclass
class BinanceLiveAccount:
    """Adapter over BinanceFuturesTrader with a PaperTradingAccount-like API."""

    trader: Any
    initial_capital: float

    def get_balance(self) -> Tuple[float, float]:
        info = self.trader.get_account_info() or {}
        available = float(info.get("available_balance", 0.0))
        return (available, 0.0)

    def get_total_value(self, current_price: float) -> float:
        info = self.trader.get_account_info() or {}
        return float(info.get("total_balance", 0.0))

    def open_short(self, usdt_amount: float, price: float, leverage: int = 1) -> Dict[str, Any]:  # price ignored
        result = self.trader.open_short(float(usdt_amount), leverage=int(leverage))
        return result or {"success": False, "error": "OPEN_SHORT_FAILED"}

    def close_short(self, price: float) -> Dict[str, Any]:  # price ignored
        result = self.trader.close_short()
        return result or {"success": False, "error": "CLOSE_SHORT_FAILED"}

    def get_position(self) -> Optional[Dict[str, Any]]:
        pos = self.trader.get_position()
        if not pos:
            return None
        # Normalize to PaperTradingAccount-like keys used by notifications.
        return {
            "size": abs(float(pos.get("position_amt", 0.0))),
            "entry_price": float(pos.get("entry_price", 0.0)),
            "leverage": int(pos.get("leverage", 1)),
            "is_short": str(pos.get("side", "")).upper() == "SHORT",
        }

    def get_statistics(self) -> Dict[str, Any]:
        total_balance = self.get_total_value(current_price=0.0)
        return_pct = ((total_balance - self.initial_capital) / self.initial_capital) * 100 if self.initial_capital > 0 else 0.0
        return {
            "total_trades": None,
            "total_pnl": None,
            "total_fees": None,
            "net_pnl": None,
            "win_rate": None,
            "initial_capital": self.initial_capital,
            "current_cash": self.get_balance()[0],
            "return_pct": return_pct,
        }
