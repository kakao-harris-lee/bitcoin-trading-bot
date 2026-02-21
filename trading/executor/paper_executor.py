# trading/executor/paper_executor.py
"""Paper trading executor for simulation."""

# pylint: disable=logging-fstring-interpolation,broad-exception-caught

from __future__ import annotations
import asyncio
import logging
import os
import time
import uuid
from typing import Any, Optional, TYPE_CHECKING
from pathlib import Path

from trading.risk.trade_logger import TradeLogger
from trading.risk.liquidation_guard import LiquidationGuard
from trading.observability.structured_logger import trade_logger

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.risk.leverage_manager import LeverageManager

logger = logging.getLogger(__name__)

# Valid order sides and markets for validation
VALID_SIDES = {"buy", "sell"}
VALID_MARKETS = {"futures", "spot"}  # Support both futures and spot
VALID_SYMBOLS = {"BTC", "ETH", "SOL", "BNB"}  # Fallback supported trading symbols

# Default configuration values
DEFAULT_PAPER_BALANCE = 10000  # Default initial balance in USDT
POSITION_EPSILON = 1e-9


class PaperExecutor:
    """Simulates order execution without real API calls."""

    def __init__(
        self,
        redis: RedisStreams,
        config: dict,
        leverage_manager: Optional[LeverageManager] = None,
    ):
        self.redis = redis
        self.config = config
        self.leverage_manager = leverage_manager
        self.initial_balance = config.get("initial_balance", DEFAULT_PAPER_BALANCE)
        self.balance = self.initial_balance  # Futures balance - will be overwritten by Redis value if exists
        self.fee_rate = config.get("fee_rate", 0.0005)  # 0.05% (futures default)
        self.slippage = config.get("slippage", 0.0004)  # 0.04%
        self.max_daily_loss = config.get("max_daily_loss", 500)
        self.last_prices: dict[str, float] = {}
        self._running = False

        # Spot trading balances
        self.spot_balance: float = self.initial_balance  # Separate spot balance
        self.spot_positions: dict[str, float] = {}  # {symbol: quantity}
        self.spot_fee_rate: float = 0.001  # 0.1% (spot fee)

        configured_symbols = config.get("symbols", [])
        self.valid_symbols = (
            {str(sym).upper() for sym in configured_symbols}
            if configured_symbols
            else set(VALID_SYMBOLS)
        )

        default_db_path = Path(__file__).resolve().parents[2] / "data" / "paper_trading_results.db"
        trade_log_db_path = config.get("trade_log_db_path", str(default_db_path))
        if os.getenv("PYTEST_CURRENT_TEST"):
            trade_log_db_path = ":memory:"

        # Initialize trade logger for database persistence
        self.trade_logger = TradeLogger(
            db_path=trade_log_db_path,
            strategy_name="paper_trading",
        )
        logger.info("TradeLogger initialized for paper trading persistence")

        # Add liquidation guard
        self.liquidation_guard = LiquidationGuard()
        # Store reference to background task to prevent garbage collection
        self._price_tracker_task: Optional[asyncio.Task] = None

    async def run(self) -> None:
        """Main loop: consume and simulate orders."""
        self._running = True
        group = "executor"
        consumer = "paper-executor"

        await self.redis.create_consumer_group("orders", group)

        # Load persisted balance from Redis (if exists), otherwise use initial_balance
        await self._load_balance_from_redis()

        # Sync balance to Redis so dashboard shows correct values
        await self._sync_balance_to_redis()
        logger.info(f"PaperExecutor started with balance: {self.balance}")

        # Initialize LeverageManager with paper balance
        if self.leverage_manager:
            await self.leverage_manager.initialize(initial_equity=self.balance)
            logger.info(
                f"LeverageManager initialized: equity=${self.balance:,.2f}, "
                f"tier={self.leverage_manager.current_tier.name} "
                f"({self.leverage_manager.current_tier.leverage}x)"
            )

        # Store task reference to prevent garbage collection
        self._price_tracker_task = asyncio.create_task(self._price_tracker())

        while self._running:
            try:
                messages = await self.redis.consume(
                    "orders", group, consumer, count=1, block_ms=1000
                )

                for msg in messages:
                    await self._process_order(msg)
                    await self.redis.ack("orders", group, msg["_id"])

            except Exception as e:
                logger.error(f"PaperExecutor error: {e}")
                await asyncio.sleep(1)

    async def _price_tracker(self) -> None:
        """Track latest prices from price stream."""
        group = "paper-price-tracker"
        consumer = "paper-price-tracker-consumer"

        try:
            if hasattr(self.redis.__class__, "ensure_ephemeral_consumer_group"):
                stats = await self.redis.ensure_ephemeral_consumer_group(
                    stream="market:prices",
                    group=group,
                    consumer=consumer,
                )
                if stats["reclaimed"] > 0 or stats["pruned_consumers"] > 0:
                    logger.info(
                        "Paper price tracker stream cleanup: reclaimed=%s pruned=%s",
                        stats["reclaimed"],
                        stats["pruned_consumers"],
                    )
            else:
                await self.redis.create_consumer_group("market:prices", group, start_id="$")
        except Exception as e:
            # Group may already exist, which is fine
            logger.debug(f"Consumer group creation: {e}")

        while self._running:
            try:
                messages = await self.redis.consume(
                    "market:prices", group, consumer, count=100, block_ms=500
                )
                for msg in messages:
                    symbol = msg.get("symbol")
                    price = msg.get("price")
                    if symbol and price:
                        self.last_prices[symbol] = float(price)
                    await self.redis.ack("market:prices", group, msg["_id"])
            except Exception:
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal executor to stop."""
        self._running = False

    async def _load_balance_from_redis(self) -> None:
        """Load persisted paper balance from Redis on startup."""
        try:
            account = await self.redis.hgetall("account:paper")
            if account:
                # Load futures balance
                if "futures_balance" in account:
                    saved_balance = float(account["futures_balance"])
                    if saved_balance > 0:
                        self.balance = saved_balance
                        logger.info(f"Loaded persisted futures balance from Redis: {self.balance:.2f}")

                # Load spot balance
                if "spot_balance" in account:
                    saved_spot = float(account["spot_balance"])
                    if saved_spot > 0:
                        self.spot_balance = saved_spot
                        logger.info(f"Loaded persisted spot balance from Redis: {self.spot_balance:.2f}")

                return
            # No valid saved balance, use initial
            logger.info(f"No persisted balance found, using initial: {self.initial_balance}")
            self.balance = self.initial_balance
            self.spot_balance = self.initial_balance
        except Exception as e:
            logger.warning(f"Failed to load balance from Redis, using initial: {e}")
            self.balance = self.initial_balance
            self.spot_balance = self.initial_balance

    async def _sync_balance_to_redis(self) -> None:
        """Sync paper trading balance to Redis for dashboard display."""
        try:
            await self.redis.hset("account:paper", {
                "futures_balance": str(self.balance),
                "spot_balance": str(self.spot_balance),
                "last_sync": str(int(time.time())),
            })
            logger.debug(f"Synced paper balances to Redis - futures: {self.balance:.2f}, spot: {self.spot_balance:.2f}")
        except Exception as e:
            logger.error(f"Failed to sync balance to Redis: {e}")

    async def _process_order(self, order: dict[str, Any]) -> dict | None:
        """Simulate order execution."""
        # Validate required fields
        required_fields = ["id", "symbol", "side", "quantity", "market", "strategy"]
        for field in required_fields:
            if field not in order:
                logger.error(f"Order missing required field: {field}")
                return None

        # Validate side
        side = order["side"]
        if side not in VALID_SIDES:
            logger.error(f"Invalid order side: {side}")
            return None

        # Validate market
        market = order["market"]
        if market not in VALID_MARKETS:
            logger.error(f"Invalid market type: {market}")
            return None

        # Validate symbol
        symbol = order["symbol"]
        if symbol not in self.valid_symbols:
            logger.error(f"Invalid symbol: {symbol}")
            return None

        # Validate quantity
        try:
            quantity = float(order["quantity"])
            if quantity <= 0:
                logger.error(f"Invalid quantity: {quantity}")
                return None
        except (ValueError, TypeError) as e:
            logger.error(f"Invalid quantity format: {order['quantity']}: {e}")
            return None

        # Check risk gates
        if not await self._pass_risk_gates():
            logger.warning(f"Paper order {order['id']} blocked by risk gates")
            await self._publish_rejection(order, "risk_blocked")
            return None

        # Route by market type
        if market == "spot":
            return await self._simulate_spot_fill(order)
        else:
            return await self._simulate_futures_fill(order)

    async def _simulate_futures_fill(self, order: dict[str, Any]) -> dict | None:
        """Simulate futures order fill."""
        symbol = order["symbol"]
        side = order["side"]
        quantity = float(order["quantity"])

        # Check if this is an exit (closing an existing position)
        is_exit = await self._is_exit_order(order)
        exit_position: dict[str, Any] | None = None
        exit_position_qty = 0.0
        if is_exit:
            exit_position = await self.redis.get_position(symbol, order["market"])
            exit_position_qty = self._to_float(
                exit_position.get("quantity") if exit_position else 0.0
            )
            if exit_position_qty > 0 and quantity > exit_position_qty + POSITION_EPSILON:
                logger.warning(
                    "Insufficient futures position for exit: %s < %s",
                    exit_position_qty,
                    quantity,
                )
                await self._publish_rejection(
                    order, f"insufficient_futures_position:{exit_position_qty:.8f}"
                )
                return None

        # Check leverage allowance for futures entry orders
        allowed_leverage = None
        if not is_exit and self.leverage_manager:
            allowed_leverage = await self.leverage_manager.get_allowed_leverage()
            if allowed_leverage == 0:
                logger.warning(
                    f"Paper order {order['id']} blocked: leverage halted "
                    f"(drawdown={self.leverage_manager.get_drawdown_pct():.1f}%)"
                )
                await self._publish_rejection(order, "leverage_halted")
                return None

            # Use minimum of allowed leverage and order leverage
            order_leverage = int(order.get("leverage", 1))
            effective_leverage = min(order_leverage, allowed_leverage)
            if effective_leverage != order_leverage:
                logger.info(
                    f"Leverage adjusted: {order_leverage}x -> {effective_leverage}x "
                    f"(risk tier: {self.leverage_manager.current_tier.name})"
                )
            order["leverage"] = effective_leverage

        # Get current price
        price = self.last_prices.get(symbol)
        if price is None:
            logger.warning(f"No price available for {symbol}")
            return None

        # Apply slippage
        fill_price = self._apply_slippage(price, side)

        # Calculate order value and fees
        order_value = fill_price * quantity
        fees = order_value * self.fee_rate

        # Check balance for buys
        if side == "buy":
            total_cost = order_value + fees
            if total_cost > self.balance:
                logger.warning(f"Insufficient futures balance: {self.balance} < {total_cost}")
                await self._publish_rejection(order, f"insufficient_balance:{self.balance:.2f}")
                return None
            self.balance -= total_cost
        else:
            # For sells, add to balance (minus fees)
            self.balance += order_value - fees

        # Sync updated balance to Redis for dashboard
        await self._sync_balance_to_redis()

        # Create fill result
        fill = {
            "order_id": str(uuid.uuid4().int)[:8],
            "symbol": symbol,
            "side": side,
            "market": order["market"],
            "filled_qty": quantity,
            "filled_price": fill_price,
            "status": "FILLED",
            "fees": fees,
        }

        # Calculate P&L for exits, update position for entries
        profit_data = None
        entry_price = 0.0
        entry_time = 0
        if is_exit:
            # Capture position data BEFORE updating/clearing
            position = exit_position
            entry_price = self._to_float(position.get("entry_price") if position else 0.0)
            entry_time = self._to_int(position.get("entry_time") if position else 0)

            profit_data = await self._calculate_exit_pnl(order, fill)
            await self._update_position_after_exit(
                symbol=order["symbol"],
                market=order["market"],
                position=position,
                filled_qty=quantity,
                position_qty=exit_position_qty,
            )

            # Update LeverageManager equity after P&L realized
            if profit_data and self.leverage_manager:
                pnl = profit_data.get("profit", 0)
                await self.leverage_manager.update_equity(pnl)
                logger.info(
                    f"LeverageManager updated: equity=${self.leverage_manager.current_equity:,.2f}, "
                    f"drawdown={self.leverage_manager.get_drawdown_pct():.1f}%, "
                    f"tier={self.leverage_manager.current_tier.name} ({self.leverage_manager.current_tier.leverage}x)"
                )
        else:
            await self._update_position(order, fill)

        # Publish trade to Redis stream
        await self._publish_trade(order, fill, profit_data)

        # Log trade to database for persistence.
        await self._log_trade_to_db_async(order, fill, profit_data)

        logger.info(f"Paper fill: {fill}, balance: {self.balance:.2f}")

        # Structured logging for trade analysis
        if is_exit:
            if not profit_data:
                logger.warning(
                    "Exit filled without realized P&L data: symbol=%s market=%s strategy=%s",
                    symbol,
                    order.get("market"),
                    order.get("strategy"),
                )
            hold_time = int(time.time() * 1000 - entry_time) // 1000 if entry_time else 0
            trade_logger.exit(
                symbol=symbol,
                price=fill_price,
                qty=quantity,
                entry_price=entry_price if entry_price > 0 else fill_price,
                strategy=order["strategy"],
                pnl=profit_data.get("profit", 0.0) if profit_data else 0.0,
                pnl_pct=profit_data.get("profit_pct", 0.0) if profit_data else 0.0,
                hold_time_sec=hold_time,
                exit_reason=order.get("reason", ""),
                mode="paper",
            )
        else:
            trade_logger.entry(
                symbol=symbol,
                price=fill_price,
                qty=quantity,
                strategy=order["strategy"],
                leverage=int(order.get("leverage", 1)),
                mode="paper",
            )

        return fill

    async def _simulate_spot_fill(self, order: dict[str, Any]) -> dict | None:
        """Simulate spot order fill."""
        symbol = order["symbol"]
        side = order["side"]
        quantity = float(order["quantity"])

        # Get current price
        price = self.last_prices.get(symbol)
        if price is None:
            logger.warning(f"No price available for {symbol}")
            return None

        # Apply slippage
        fill_price = self._apply_slippage(price, side)

        # Calculate order value and fees (spot uses higher fee rate)
        order_value = fill_price * quantity
        fees = order_value * self.spot_fee_rate

        # Check if this is an exit (selling existing spot position)
        redis_position = await self.redis.get_position(symbol, "spot")
        redis_qty = self._to_float(redis_position.get("quantity") if redis_position else 0.0)
        current_qty = self.spot_positions.get(symbol, 0.0)
        if current_qty <= POSITION_EPSILON and redis_qty > POSITION_EPSILON:
            # Recover in-memory state after restart from Redis position.
            current_qty = redis_qty
            self.spot_positions[symbol] = current_qty

        is_exit = side == "sell" and (current_qty > POSITION_EPSILON or redis_qty > POSITION_EPSILON)

        if side == "buy":
            # Spot buy: deduct from spot balance
            total_cost = order_value + fees
            if total_cost > self.spot_balance:
                logger.warning(f"Insufficient spot balance: {self.spot_balance} < {total_cost}")
                await self._publish_rejection(order, f"insufficient_spot_balance:{self.spot_balance:.2f}")
                return None

            self.spot_balance -= total_cost

            # Add to spot positions (weighted entry for add-ons)
            existing_qty = current_qty
            new_qty = existing_qty + quantity
            existing_entry = self._to_float(
                redis_position.get("entry_price") if redis_position else 0.0
            )
            if existing_qty > POSITION_EPSILON and existing_entry > 0:
                avg_entry_price = (
                    (existing_entry * existing_qty) + (fill_price * quantity)
                ) / new_qty
                entry_time = str(self._to_int(redis_position.get("entry_time"), int(time.time() * 1000)))
            else:
                avg_entry_price = fill_price
                entry_time = str(int(time.time() * 1000))

            self.spot_positions[symbol] = new_qty

            # Store entry price in Redis for P&L calculation
            await self.redis.set_position(symbol, "spot", {
                "quantity": str(new_qty),
                "entry_price": str(avg_entry_price),
                "strategy": str(
                    redis_position.get("strategy", order["strategy"])
                    if redis_position
                    else order["strategy"]
                ),
                "entry_time": entry_time,
                "side": "buy",
                "leverage": "1",
                "liquidation_price": "0",
            })

            logger.info(f"Spot buy: {symbol} {quantity} @ {fill_price}, new position: {new_qty}")

        else:  # sell
            # Check if we have enough spot holdings
            current_qty = self.spot_positions.get(symbol, current_qty)
            if current_qty < quantity:
                logger.warning(f"Insufficient spot position: {current_qty} < {quantity}")
                await self._publish_rejection(order, f"insufficient_spot_position:{current_qty}")
                return None

            # Spot sell: add to spot balance (minus fees)
            self.spot_balance += order_value - fees

            # Reduce spot position
            remaining_qty = max(current_qty - quantity, 0.0)
            if remaining_qty <= POSITION_EPSILON:
                del self.spot_positions[symbol]
                remaining_qty = 0.0
            else:
                self.spot_positions[symbol] = remaining_qty

            logger.info(
                f"Spot sell: {symbol} {quantity} @ {fill_price}, remaining: {self.spot_positions.get(symbol, 0)}"
            )

        # Sync updated balance to Redis for dashboard
        await self._sync_balance_to_redis()

        # Create fill result
        fill = {
            "order_id": str(uuid.uuid4().int)[:8],
            "symbol": symbol,
            "side": side,
            "market": "spot",
            "filled_qty": quantity,
            "filled_price": fill_price,
            "status": "FILLED",
            "fees": fees,
        }

        # Calculate P&L for exits
        profit_data = None
        entry_price = 0.0
        entry_time = 0
        if is_exit:
            # Use the pre-fill snapshot to keep partial exits consistent.
            position = redis_position or await self.redis.get_position(symbol, "spot")
            if position:
                entry_price = self._to_float(position.get("entry_price"))
                entry_time = self._to_int(position.get("entry_time"))

                if entry_price > 0:
                    # Calculate spot P&L (no leverage)
                    pnl = (fill_price - entry_price) * quantity
                    pnl_pct = ((fill_price - entry_price) / entry_price) * 100

                    profit_data = {"profit": pnl, "profit_pct": pnl_pct}

                    # Update daily P&L
                    risk = await self.redis.get_risk()
                    daily_pnl = float(risk.get("daily_pnl", 0)) + pnl
                    await self.redis.hset("risk", {"daily_pnl": str(daily_pnl)})

                    logger.info(f"Spot P&L: {symbol} {pnl:+.2f} USDT ({pnl_pct:+.2f}%)")

            # Preserve remaining quantity for partial exits.
            await self._update_position_after_exit(
                symbol=symbol,
                market="spot",
                position=position,
                filled_qty=quantity,
                position_qty=current_qty,
                fallback_updates={
                    "entry_price": str(entry_price if entry_price > 0 else fill_price),
                    "strategy": order["strategy"],
                    "entry_time": str(entry_time if entry_time > 0 else int(time.time() * 1000)),
                    "side": "buy",
                    "leverage": "1",
                    "liquidation_price": "0",
                },
            )

        # Publish trade to Redis stream
        await self._publish_trade(order, fill, profit_data)

        # Log trade to database
        await self._log_trade_to_db_async(order, fill, profit_data)

        logger.info(f"Spot paper fill: {fill}, balance: {self.spot_balance:.2f}")

        # Structured logging
        if is_exit:
            if not profit_data:
                logger.warning(
                    "Spot exit filled without realized P&L data: symbol=%s strategy=%s",
                    symbol,
                    order.get("strategy"),
                )
            hold_time = int(time.time() * 1000 - entry_time) // 1000 if entry_time else 0
            trade_logger.exit(
                symbol=symbol,
                price=fill_price,
                qty=quantity,
                entry_price=entry_price if entry_price > 0 else fill_price,
                strategy=order["strategy"],
                pnl=profit_data.get("profit", 0.0) if profit_data else 0.0,
                pnl_pct=profit_data.get("profit_pct", 0.0) if profit_data else 0.0,
                hold_time_sec=hold_time,
                exit_reason=order.get("reason", ""),
                mode="paper",
            )
        else:
            trade_logger.entry(
                symbol=symbol,
                price=fill_price,
                qty=quantity,
                strategy=order["strategy"],
                leverage=1,  # Spot always 1x
                mode="paper",
            )

        return fill

    async def _log_trade_to_db_async(self, order: dict, fill: dict, profit_data: dict | None) -> None:
        """Log trade to SQLite database for persistence."""
        try:
            # Keep this synchronous to avoid threadpool shutdown hangs in tests.
            self._log_trade_to_db_sync(order, fill, profit_data)
        except Exception as e:
            logger.error(f"Failed to log trade to database: {e}")

    def _log_trade_to_db_sync(self, order: dict, fill: dict, profit_data: dict | None) -> None:
        """Synchronous database logging (called from thread pool)."""
        self.trade_logger.log_trade(
            action=order["side"],
            price=fill["filled_price"],
            volume=fill["filled_qty"],
            profit=profit_data.get("profit") if profit_data else None,
            profit_pct=profit_data.get("profit_pct") if profit_data else None,
            exchange="binance",
            symbol=order["symbol"],
            market=order["market"],
            paper=True
        )

    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply slippage to price."""
        if side == "buy":
            return price * (1 + self.slippage)
        else:
            return price * (1 - self.slippage)

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        """Safely convert a value to float."""
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        """Safely convert a value to int."""
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _position_payload(position: dict[str, Any] | None) -> dict[str, Any]:
        """Return position payload excluding helper metadata keys."""
        if not position:
            return {}
        return {k: v for k, v in position.items() if k not in {"symbol", "market"}}

    async def _update_position_after_exit(
        self,
        symbol: str,
        market: str,
        position: dict[str, Any] | None,
        filled_qty: float,
        position_qty: float | None = None,
        fallback_updates: dict[str, Any] | None = None,
    ) -> None:
        """Update remaining quantity after an exit, or clear position when fully closed."""
        base_qty = position_qty
        if base_qty is None:
            base_qty = self._to_float(position.get("quantity") if position else 0.0)
        remaining_qty = max(base_qty - filled_qty, 0.0)

        if remaining_qty <= POSITION_EPSILON:
            await self.redis.clear_position(symbol, market)
            return

        payload = self._position_payload(position)
        if fallback_updates:
            payload = {**fallback_updates, **payload}
        payload["quantity"] = str(remaining_qty)
        await self.redis.set_position(symbol, market, payload)

    async def _pass_risk_gates(self) -> bool:
        """Check risk conditions."""
        risk = await self.redis.get_risk()

        # Properly handle string/bool values from Redis
        kill_switch = risk.get("kill_switch", "false")
        if kill_switch is True or str(kill_switch).lower() == "true":
            return False

        blocked = risk.get("blocked", "false")
        if blocked is True or str(blocked).lower() == "true":
            return False

        try:
            daily_pnl = float(risk.get("daily_pnl", 0))
        except (ValueError, TypeError):
            daily_pnl = 0.0

        if daily_pnl < -self.max_daily_loss:
            return False

        return True

    async def _update_position(self, order: dict, fill: dict) -> None:
        """Update position in Redis with liquidation price."""
        leverage = int(order.get("leverage", 1))
        position_value = fill["filled_price"] * fill["filled_qty"]

        # Calculate liquidation price for futures positions
        liq_price = 0.0
        if order.get("market") == "futures" and leverage > 1:
            liq_price = self.liquidation_guard.calculate_liquidation_price(
                entry_price=fill["filled_price"],
                leverage=leverage,
                side=order["side"],
                position_value=position_value,
            )

        await self.redis.set_position(order["symbol"], order["market"], {
            "quantity": str(fill["filled_qty"]),
            "entry_price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "entry_time": str(int(time.time() * 1000)),
            "side": order["side"],
            "leverage": str(leverage),
            "liquidation_price": str(liq_price),
        })

        if liq_price > 0:
            logger.info(
                f"Position opened: {order['symbol']} {order['side'].upper()} "
                f"{leverage}x @ {fill['filled_price']}, liq: {liq_price:.2f}"
            )

    async def _is_exit_order(self, order: dict) -> bool:
        """Check if order is an exit (closing position)."""
        symbol = order["symbol"]
        market = order["market"]
        order_side = order["side"]

        position = await self.redis.get_position(symbol, market)
        if not position:
            return False

        pos_side = position.get("side", "buy")

        # Long exit: sell closes buy
        # Short exit: buy closes sell
        return (
            (pos_side == "buy" and order_side == "sell") or
            (pos_side == "sell" and order_side == "buy")
        )

    async def _calculate_exit_pnl(self, order: dict, fill: dict) -> dict | None:
        """Calculate P&L when exiting a position (long or short)."""
        symbol = order["symbol"]
        market = order["market"]

        position = await self.redis.get_position(symbol, market)
        if not position:
            return None

        entry_price = float(position.get("entry_price", 0))
        exit_price = fill["filled_price"]
        quantity = fill["filled_qty"]
        pos_side = position.get("side", "buy")
        leverage = int(position.get("leverage", 1))

        if entry_price <= 0 or quantity <= 0:
            return None

        # Calculate P&L based on position direction
        if pos_side == "buy":  # Long position
            pnl = (exit_price - entry_price) * quantity
            price_change_pct = ((exit_price - entry_price) / entry_price) * 100
        else:  # Short position
            pnl = (entry_price - exit_price) * quantity
            price_change_pct = ((entry_price - exit_price) / entry_price) * 100

        # Apply leverage
        pnl_with_leverage = pnl * leverage
        pnl_pct = price_change_pct * leverage

        # Update daily P&L
        risk = await self.redis.get_risk()
        daily_pnl = float(risk.get("daily_pnl", 0)) + pnl_with_leverage
        await self.redis.hset("risk", {"daily_pnl": str(daily_pnl)})

        direction = "Long" if pos_side == "buy" else "Short"
        logger.info(f"Paper P&L ({direction}): {symbol} {pnl_with_leverage:+.2f} USDT ({pnl_pct:+.2f}%)")

        # Publish P&L alert (same as live trading)
        payload = {
            "type": "pnl_realized",
            "symbol": symbol,
            "pnl": str(pnl_with_leverage),
            "daily_pnl": str(daily_pnl),
            "timestamp": str(int(time.time() * 1000)),
            "paper": "true",
        }
        try:
            maybe_coro = getattr(self.redis, "publish", None)
            if maybe_coro:
                result = maybe_coro("alerts", payload)
                if asyncio.iscoroutine(result):
                    await result
        except Exception as e:
            logger.debug(f"Failed to publish P&L alert: {e}")

        return {"profit": pnl_with_leverage, "profit_pct": pnl_pct}

    async def _publish_trade(self, order: dict, fill: dict, profit_data: dict | None = None) -> None:
        """Publish trade to trades stream."""
        trade = {
            "order_id": str(fill["order_id"]),
            "symbol": order["symbol"],
            "side": order["side"],
            "market": order["market"],
            "quantity": str(fill["filled_qty"]),
            "price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "timestamp": str(int(time.time() * 1000)),
            "paper": "true",
            "reason": order.get("reason", ""),
        }

        # Add profit data for exit trades
        if profit_data:
            trade["profit"] = str(profit_data["profit"])
            trade["profit_pct"] = str(profit_data["profit_pct"])

        await self.redis.publish("trades", trade)

    async def _publish_rejection(self, order: dict, reason: str) -> None:
        """Publish order rejection to alerts stream."""
        await self.redis.publish("alerts", {
            "type": "order_rejected",
            "order_id": order.get("id", "unknown"),
            "symbol": order.get("symbol", "unknown"),
            "reason": reason,
            "timestamp": str(int(time.time() * 1000)),
            "paper": "true",
        })
