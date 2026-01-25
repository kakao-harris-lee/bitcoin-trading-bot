"""Combined exit strategy: exit at day close."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from .models import Position, Signal, TradingContext
from .registry import exit_strategy

logger = logging.getLogger(__name__)


@dataclass
class CombinedExitParams:
    """Parameters for combined exit strategy."""

    exit_at_day_close: bool = True
    max_hold_hours: float | None = 24.0
    take_profit_pct: float | None = 5.0
    stop_loss_pct: float | None = 2.0
    market: Literal["futures"] = "futures"


@exit_strategy(params_class=CombinedExitParams)
class CombinedExitStrategy:
    """Exit positions at the first bar of the next day."""

    def __init__(self, params: CombinedExitParams | None = None):
        self.params = params or CombinedExitParams()
        self._entry_day: dict[str, object] = {}
        self._entry_info: dict[str, dict[str, float]] = {}
        self._stats: dict[str, int] = {}

    def on_position_opened(self, position: Position) -> None:
        ts = position.timestamp
        day = datetime.utcfromtimestamp(ts / 1000).date()
        self._entry_day[position.symbol] = day
        self._entry_info[position.symbol] = {
            "timestamp": position.timestamp,
            "price": position.entry_price,
        }

    def on_position_closed(self, symbol: str) -> None:
        self._entry_day.pop(symbol, None)
        self._entry_info.pop(symbol, None)

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        if not self.params.exit_at_day_close:
            return None

        symbol = position.symbol
        entry_day = self._entry_day.get(symbol)
        if entry_day is None:
            return None

        current_day = datetime.utcfromtimestamp(ctx.market.timestamp / 1000).date()
        if current_day == entry_day:
            return None

        entry_info = self._entry_info.get(symbol)
        if entry_info:
            delta_hours = (ctx.market.timestamp - entry_info["timestamp"]) / 1000 / 3600
            if delta_hours >= float(self.params.max_hold_hours or 0):
                reason = "combo_exit max_hold"
                return self._build_exit(symbol, ctx.market, position, reason)

            close = ctx.market.close
            entry_price = float(entry_info["price"])
            pnl_pct = ((close - entry_price) / entry_price) * 100
            if self.params.take_profit_pct and pnl_pct >= self.params.take_profit_pct:
                reason = "combo_exit take_profit"
                return self._build_exit(symbol, ctx.market, position, reason)
            if self.params.stop_loss_pct and pnl_pct <= -self.params.stop_loss_pct:
                reason = "combo_exit stop_loss"
                return self._build_exit(symbol, ctx.market, position, reason)

        reason = "combo_exit day_close"
        return self._build_exit(symbol, ctx.market, position, reason)

    def _build_exit(
        self,
        symbol: str,
        market_data: object,
        position: Position,
        reason: str,
    ) -> Signal:
        self._stats[reason] = self._stats.get(reason, 0) + 1
        return Signal(
            symbol=symbol,
            side="sell",
            market=self.params.market,
            quantity=position.quantity,
            reason=reason,
        )

    def get_stats(self) -> dict[str, int]:
        """Return exit reason counts (for backtests/diagnostics)."""
        return dict(self._stats)
