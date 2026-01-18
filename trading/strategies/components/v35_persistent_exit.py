"""V35 Persistent Exit Strategy - Redis-backed state for trailing stop.

Extends V35TrailingExitStrategy with StateManager integration to persist
high_water_mark across restarts. Solves the problem of state loss.

Key difference from V35TrailingExitStrategy:
- high_water_mark is stored in Redis, not in-memory
- State survives bot restarts
- Requires async initialization via load_state()
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .models import MarketData, Position, Signal
from .state_manager import StateManager
from .v35_trailing_exit import V35ExitParams
from .registry import exit_strategy

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)

# State variable names
STATE_HIGH_WATER_MARK = "high_water_mark"


@exit_strategy(params_class=V35ExitParams)
class V35PersistentExitStrategy:
    """V35 Exit strategy with Redis-persisted trailing stop state.

    Same exit logic as V35TrailingExitStrategy but with state persistence:
    - high_water_mark is stored in Redis and survives restarts
    - State is loaded on position open (or via load_state for existing positions)
    - State is written immediately on every update

    Exit conditions (checked in order):
    1. Stop Loss: P&L <= -stop_loss_pct
    2. Take Profit: P&L >= take_profit_pct
    3. Trailing Stop: Activated when P&L >= trailing_activation,
       triggers when price drops trailing_distance% below high water mark
    4. Regime Change: Exit on bearish regime if in profit

    Implements IExitStrategy protocol (structural subtyping).
    Requires async operations for state management.
    """

    def __init__(
        self,
        redis: Redis,
        params: V35ExitParams | None = None,
        strategy_name: str = "v35_trailing_exit",
    ):
        """Initialize with Redis client and exit parameters.

        Args:
            redis: Async Redis client for state persistence.
            params: Exit parameters. Uses defaults if not provided.
            strategy_name: Name for state keys (default: "v35_trailing_exit").
        """
        self.params = params or V35ExitParams()
        self._state = StateManager(redis, strategy_name)
        self._initialized_symbols: set[str] = set()

    async def load_state(self, symbols: list[str]) -> None:
        """Load existing state for symbols (call on startup).

        This restores high_water_mark for any open positions that
        existed before the bot restarted.

        Args:
            symbols: List of symbols to load state for.
        """
        for symbol in symbols:
            hwm = await self._state.load(symbol, STATE_HIGH_WATER_MARK, default=None)
            if hwm is not None:
                self._initialized_symbols.add(symbol)
                logger.info(
                    f"{symbol}: Restored high_water_mark={hwm:.2f} from Redis"
                )

    async def check_exit(
        self,
        position: Position,
        market_data: MarketData,
    ) -> Signal | None:
        """Evaluate exit conditions for position.

        Args:
            position: Current open position.
            market_data: Current market state.

        Returns:
            Signal to close position, or None to hold.
        """
        symbol = position.symbol
        entry_price = position.entry_price
        quantity = position.quantity
        current_price = market_data.close

        if entry_price <= 0 or quantity <= 0:
            return None

        p = self.params

        # Calculate P&L percentage
        pnl_pct = ((current_price - entry_price) / entry_price) * 100

        # Update high water mark (persisted to Redis)
        await self._update_high_water_mark(symbol, current_price)
        hwm = self._state.get_cached(symbol, STATE_HIGH_WATER_MARK, current_price)
        hwm_pnl = ((hwm - entry_price) / entry_price) * 100

        # Exit condition 1: Stop loss
        if pnl_pct <= -p.stop_loss_pct:
            reason = f"V35 exit: Stop loss {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            await self._clear_state(symbol)
            return self._create_exit_signal(position, reason)

        # Exit condition 2: Take profit
        if pnl_pct >= p.take_profit_pct:
            reason = f"V35 exit: Take profit {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            await self._clear_state(symbol)
            return self._create_exit_signal(position, reason)

        # Exit condition 3: Trailing stop
        if p.trailing_enabled and hwm_pnl >= p.trailing_activation:
            trailing_stop_price = hwm * (1 - p.trailing_distance / 100)
            if current_price <= trailing_stop_price:
                locked_pnl = ((trailing_stop_price - entry_price) / entry_price) * 100
                reason = f"V35 exit: Trailing stop {locked_pnl:.2f}% (HWM={hwm_pnl:.2f}%)"
                logger.info(f"{symbol}: {reason}")
                await self._clear_state(symbol)
                return self._create_exit_signal(position, reason, trailing_stop_price)

        # Exit condition 4: Regime change to bearish (only if in profit)
        regime = self._classify_regime(market_data.mfi, market_data.adx)
        if regime in ("BEAR_STRONG", "BEAR_MODERATE") and pnl_pct > 0:
            reason = f"V35 exit: Regime change to {regime}, locking {pnl_pct:.2f}%"
            logger.info(f"{symbol}: {reason}")
            await self._clear_state(symbol)
            return self._create_exit_signal(position, reason)

        return None

    async def on_position_opened(self, position: Position) -> None:
        """Initialize state when position is opened.

        Sets initial high water mark to entry price and persists to Redis.

        Args:
            position: The newly opened position.
        """
        symbol = position.symbol
        await self._state.set(symbol, STATE_HIGH_WATER_MARK, position.entry_price)
        self._initialized_symbols.add(symbol)
        logger.info(
            f"{symbol}: Position opened, HWM initialized to {position.entry_price:.2f} (persisted)"
        )

    async def on_position_closed(self, symbol: str) -> None:
        """Clean up state when position is closed.

        Removes high water mark from Redis.

        Args:
            symbol: The symbol whose position was closed.
        """
        await self._clear_state(symbol)
        logger.info(f"{symbol}: Position closed, state cleared from Redis")

    async def _update_high_water_mark(self, symbol: str, current_price: float) -> None:
        """Update high water mark if current price is higher.

        Persists to Redis immediately on update.

        Args:
            symbol: Trading symbol.
            current_price: Current market price.
        """
        old_hwm = self._state.get_cached(symbol, STATE_HIGH_WATER_MARK, current_price)

        if current_price > old_hwm:
            await self._state.set(symbol, STATE_HIGH_WATER_MARK, current_price)
            logger.debug(
                f"{symbol}: HWM updated {old_hwm:.2f} -> {current_price:.2f} (persisted)"
            )
        elif symbol not in self._initialized_symbols:
            # First time seeing this symbol, initialize
            await self._state.set(symbol, STATE_HIGH_WATER_MARK, current_price)
            self._initialized_symbols.add(symbol)

    async def _clear_state(self, symbol: str) -> None:
        """Clear state for symbol from Redis.

        Args:
            symbol: Trading symbol.
        """
        await self._state.delete(symbol, STATE_HIGH_WATER_MARK)
        self._initialized_symbols.discard(symbol)

    def _classify_regime(self, mfi: float, adx: float) -> str:
        """Classify market regime for exit decision.

        Args:
            mfi: Money Flow Index value.
            adx: Average Directional Index value.

        Returns:
            Regime classification string.
        """
        p = self.params

        if mfi >= p.mfi_bull:
            return "BULL"
        elif mfi <= p.mfi_bear:
            if adx >= p.adx_trend:
                return "BEAR_STRONG"
            elif adx >= p.adx_weak:
                return "BEAR_MODERATE"
            else:
                return "SIDEWAYS_BEAR"
        else:
            return "SIDEWAYS_NEUTRAL"

    def _create_exit_signal(
        self,
        position: Position,
        reason: str,
        trigger_price: float | None = None,
    ) -> Signal:
        """Create exit signal for position.

        Args:
            position: Position to close.
            reason: Exit reason for logging.
            trigger_price: Optional trigger price for trailing stop.

        Returns:
            Signal to close the position.
        """
        return Signal(
            symbol=position.symbol,
            side="sell",
            market=position.market,
            quantity=position.quantity,
            reason=reason,
            trigger_price=trigger_price,
        )

    async def get_high_water_mark(self, symbol: str) -> float | None:
        """Get current high water mark for a symbol.

        Args:
            symbol: Trading symbol.

        Returns:
            High water mark value or None if not set.
        """
        return await self._state.get(symbol, STATE_HIGH_WATER_MARK)

    @property
    def state_manager(self) -> StateManager:
        """Access the underlying StateManager."""
        return self._state
