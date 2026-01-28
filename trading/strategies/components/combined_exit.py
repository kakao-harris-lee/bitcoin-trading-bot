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
    # Trailing stop parameters
    trailing_enabled: bool = False
    trailing_activation_pct: float = 2.0  # Activate at +2%
    trailing_distance_pct: float = 1.5    # Trail 1.5% below HWM
    market: Literal["futures"] = "futures"


@exit_strategy(params_class=CombinedExitParams)
class CombinedExitStrategy:
    """Exit positions at the first bar of the next day."""

    def __init__(self, params: CombinedExitParams | None = None):
        self.params = params or CombinedExitParams()
        self._entry_day: dict[str, object] = {}
        self._entry_info: dict[str, dict[str, float]] = {}
        self._high_water_mark: dict[str, float] = {}  # Track HWM for trailing stop
        self._stats: dict[str, int] = {}

    def on_position_opened(self, position: Position) -> None:
        ts = position.timestamp
        day = datetime.utcfromtimestamp(ts / 1000).date()
        self._entry_day[position.symbol] = day
        self._entry_info[position.symbol] = {
            "timestamp": position.timestamp,
            "price": position.entry_price,
        }
        # Initialize HWM to entry price
        self._high_water_mark[position.symbol] = position.entry_price

    def on_position_closed(self, symbol: str) -> None:
        self._entry_day.pop(symbol, None)
        self._entry_info.pop(symbol, None)
        self._high_water_mark.pop(symbol, None)

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        symbol = position.symbol
        entry_info = self._entry_info.get(symbol)

        # Ensure we have entry info
        if entry_info is None:
            self.on_position_opened(position)
            entry_info = self._entry_info[symbol]

        close = ctx.market.close
        entry_price = float(entry_info["price"])
        pnl_pct = ((close - entry_price) / entry_price) * 100

        # Update high water mark
        hwm = self._high_water_mark.get(symbol, entry_price)
        if close > hwm:
            hwm = close
            self._high_water_mark[symbol] = hwm
        hwm_pnl_pct = ((hwm - entry_price) / entry_price) * 100

        # 1. Stop loss check (highest priority)
        if self.params.stop_loss_pct and pnl_pct <= -self.params.stop_loss_pct:
            reason = f"combo_exit stop_loss ({pnl_pct:.2f}%)"
            return self._build_exit(symbol, ctx.market, position, reason)

        # 2. Trailing stop check (if enabled and activated)
        if self.params.trailing_enabled:
            if hwm_pnl_pct >= self.params.trailing_activation_pct:
                trailing_stop_price = hwm * (1 - self.params.trailing_distance_pct / 100)
                if close <= trailing_stop_price:
                    locked_pnl = ((trailing_stop_price - entry_price) / entry_price) * 100
                    reason = f"combo_exit trailing_stop ({locked_pnl:.2f}% locked, HWM={hwm_pnl_pct:.2f}%)"
                    return self._build_exit(symbol, ctx.market, position, reason)

        # 3. Take profit check
        if self.params.take_profit_pct and pnl_pct >= self.params.take_profit_pct:
            reason = f"combo_exit take_profit ({pnl_pct:.2f}%)"
            return self._build_exit(symbol, ctx.market, position, reason)

        # 4. Max hold time check
        if self.params.max_hold_hours:
            delta_hours = (ctx.market.timestamp - entry_info["timestamp"]) / 1000 / 3600
            if delta_hours >= self.params.max_hold_hours:
                reason = f"combo_exit max_hold ({delta_hours:.1f}h)"
                return self._build_exit(symbol, ctx.market, position, reason)

        # 5. Day close exit (if enabled)
        if self.params.exit_at_day_close:
            entry_day = self._entry_day.get(symbol)
            if entry_day:
                current_day = datetime.utcfromtimestamp(ctx.market.timestamp / 1000).date()
                if current_day != entry_day:
                    reason = f"combo_exit day_close ({pnl_pct:.2f}%)"
                    return self._build_exit(symbol, ctx.market, position, reason)

        return None

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
