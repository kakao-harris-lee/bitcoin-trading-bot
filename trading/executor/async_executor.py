# trading/executor/async_executor.py
"""Async executor for processing order stream."""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Optional, TYPE_CHECKING

from trading.observability.structured_logger import trade_logger
from trading.risk.liquidation_guard import LiquidationGuard

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.executor.binance_client import BinanceClient
    from trading.risk.leverage_manager import LeverageManager

logger = logging.getLogger(__name__)

# Approximate prices for balance estimation (used before order execution)
APPROX_PRICES = {"BTC": 90000, "ETH": 3000, "SOL": 130}


class AsyncExecutor:
    """Consumes orders stream and executes via Binance API."""

    def __init__(
        self,
        redis: RedisStreams,
        client: BinanceClient,
        config: dict,
        leverage_manager: Optional[LeverageManager] = None,
    ):
        self.redis = redis
        self.client = client
        self.config = config
        self.leverage_manager = leverage_manager
        self.max_daily_loss = config.get("max_daily_loss", 500)  # USDT
        self.position_pct = config.get("position_pct", 0.02)  # 2% of balance per trade
        self.min_balance = config.get("min_balance", 100)  # Minimum USDT to trade
        self._running = False
        self._balance_cache = {"spot": 0.0, "futures": 0.0, "last_update": 0}
        self.liquidation_guard = LiquidationGuard()

    async def run(self) -> None:
        """Main loop: consume and execute orders."""
        self._running = True
        group = "executor"
        consumer = "executor-main"

        await self.redis.create_consumer_group("orders", group)

        # Sync account on startup
        await self._sync_account()

        logger.info("AsyncExecutor started")

        # Periodic balance refresh task
        asyncio.create_task(self._balance_refresh_loop())

        while self._running:
            try:
                messages = await self.redis.consume(
                    "orders", group, consumer, count=1, block_ms=1000
                )

                for msg in messages:
                    await self._process_order(msg)
                    await self.redis.ack("orders", group, msg["_id"])

            except Exception as e:
                logger.error(f"Executor error: {e}")
                await asyncio.sleep(1)

    def stop(self) -> None:
        """Signal executor to stop."""
        self._running = False

    async def _sync_account(self) -> None:
        """Sync positions and balance from Binance on startup."""
        logger.info("Syncing account with Binance...")

        try:
            # Get balance (both spot and futures)
            balance = await self.client.get_balance()
            spot_balance = getattr(balance, "spot_usdt", 0.0)
            futures_balance = balance.futures_usdt
            total_equity = spot_balance + futures_balance

            self._balance_cache = {
                "spot": spot_balance,
                "futures": futures_balance,
                "last_update": time.time(),
            }
            logger.info(f"Spot Balance: ${spot_balance:.2f}, Futures Balance: ${futures_balance:.2f}")

            # Get positions and sync to Redis
            positions = await self.client.get_all_positions()
            synced = 0

            for pos in positions:
                symbol = pos["symbol"]
                market = pos["market"]

                # Check if position exists in Redis
                redis_pos = await self.redis.get_position(symbol, market)
                if not redis_pos:
                    # Add to Redis (mark as external/unknown strategy)
                    await self.redis.set_position(symbol, market, {
                        "quantity": str(pos["quantity"]),
                        "entry_price": str(pos.get("entry_price", 0)),
                        "strategy": "external",
                        "entry_time": str(int(time.time() * 1000)),
                        "side": pos["side"],
                    })
                    synced += 1
                    logger.info(f"Synced external position: {symbol} {market}")

            if synced > 0:
                logger.info(f"Synced {synced} external positions from Binance")

            # Store balance in Redis for strategies to access
            await self.redis.hset("account:live", {
                "spot_balance": str(spot_balance),
                "futures_balance": str(futures_balance),
                "total_equity": str(total_equity),
                "last_sync": str(int(time.time())),
            })

            # Initialize LeverageManager with futures equity
            if self.leverage_manager:
                await self.leverage_manager.initialize(initial_equity=balance.futures_usdt)
                logger.info(
                    f"LeverageManager initialized: equity=${total_equity:,.2f}, "
                    f"tier={self.leverage_manager.current_tier.name} "
                    f"({self.leverage_manager.current_tier.leverage}x)"
                )

        except Exception as e:
            logger.error(f"Account sync failed: {e}")

    async def _balance_refresh_loop(self) -> None:
        """Periodically refresh balance cache (spot and futures)."""
        while self._running:
            try:
                await asyncio.sleep(60)  # Refresh every minute
                balance = await self.client.get_balance()
                spot_balance = getattr(balance, "spot_usdt", 0.0)
                futures_balance = balance.futures_usdt

                self._balance_cache = {
                    "spot": spot_balance,
                    "futures": futures_balance,
                    "last_update": time.time(),
                }
                # Update Redis
                await self.redis.hset("account:live", {
                    "spot_balance": str(spot_balance),
                    "futures_balance": str(futures_balance),
                    "total_equity": str(spot_balance + futures_balance),
                    "last_sync": str(int(time.time())),
                })
            except Exception as e:
                logger.warning(f"Balance refresh failed: {e}")

    async def _process_order(self, order: dict[str, Any]) -> dict | None:
        """Process single order - routes to spot or futures execution."""
        market = order.get("market", "futures")

        # Check risk gates (market-specific)
        if not await self._pass_risk_gates(market):
            logger.warning(f"Order {order['id']} blocked by risk gates")
            await self._publish_rejection(order, "risk_blocked")
            return None

        # Check balance before order
        required_balance = self._estimate_order_value(order)
        available = self._balance_cache.get(market, 0)

        if available < required_balance:
            logger.warning(f"Insufficient balance: {available:.2f} < {required_balance:.2f}")
            await self._publish_rejection(order, f"insufficient_balance:{available:.2f}")
            return None

        try:
            # Route to appropriate execution based on market type
            if market == "spot":
                return await self._execute_spot_order(order)
            else:
                return await self._execute_futures_order(order)

        except Exception as e:
            logger.error(f"Order {order['id']} failed: {e}")
            await self._publish_rejection(order, str(e))
            return None

    async def _execute_spot_order(self, order: dict[str, Any]) -> dict | None:
        """Execute spot order - no leverage, no liquidation."""
        # Check if this is an exit (closing an existing position)
        is_exit = await self._is_exit_order(order)

        if is_exit:
            # Cancel server-side stop-loss BEFORE exit
            await self._cancel_server_stop_loss(order["symbol"], "spot")

        # Execute order (spot markets don't need position_side)
        fill = await self.client.market_order(
            symbol=order["symbol"],
            side=order["side"],
            quantity=float(order["quantity"]),
            market="spot",
            position_side=None,
        )

        # Update position
        profit_data = None
        if is_exit:
            # Capture position data BEFORE clearing
            position = await self.redis.get_position(order["symbol"], "spot")
            entry_price = float(position.get("entry_price", 0)) if position else 0
            entry_time = int(position.get("entry_time", 0)) if position else 0

            # Calculate realized P&L (must be done before clearing position)
            profit_data = await self._record_exit_pnl(order, fill)
            await self.redis.clear_position(order["symbol"], "spot")
        else:
            await self._update_spot_position(order, fill)
            # Place server-side stop-loss AFTER entry
            await self._place_server_stop_loss(order["symbol"], "spot", fill, order)

        # Publish trade notification (with profit data for exits)
        await self._publish_trade(order, fill, profit_data)

        # Structured logging for trade analysis
        if is_exit and profit_data:
            hold_time = int(time.time() * 1000 - entry_time) // 1000 if entry_time else 0
            trade_logger.exit(
                symbol=order["symbol"],
                price=fill["filled_price"],
                qty=fill["filled_qty"],
                entry_price=entry_price,
                strategy=order["strategy"],
                pnl=profit_data["profit"],
                pnl_pct=profit_data["profit_pct"],
                hold_time_sec=hold_time,
                exit_reason=order.get("reason", ""),
                mode="live",
            )
        else:
            trade_logger.entry(
                symbol=order["symbol"],
                price=fill["filled_price"],
                qty=fill["filled_qty"],
                strategy=order["strategy"],
                leverage=1,  # Spot always 1x
                mode="live",
            )

        logger.info(f"Spot order {order['id']} filled: {fill}")
        return fill

    async def _execute_futures_order(self, order: dict[str, Any]) -> dict | None:
        """Execute futures order - with leverage and liquidation checks."""
        # Check if this is an exit (closing an existing position)
        is_exit = await self._is_exit_order(order)

        if is_exit:
            # Cancel server-side stop-loss BEFORE exit
            await self._cancel_server_stop_loss(order["symbol"], order["market"])

        # Check leverage allowance for futures entry orders
        effective_leverage = None
        allowed_leverage: int | None = None
        if not is_exit and self.leverage_manager:
            allowed_leverage = await self.leverage_manager.get_allowed_leverage()
            if allowed_leverage == 0:
                logger.warning(
                    f"Order {order['id']} blocked: leverage halted "
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

            # Set leverage on Binance before order
            symbol = order["symbol"]
            await self.client.set_leverage(symbol, effective_leverage)
            logger.info(f"Set leverage for {symbol}: {effective_leverage}x")

        # Determine position_side for futures hedge mode
        position_side = await self._get_position_side(order, is_exit)

        # Execute order
        fill = await self.client.market_order(
            symbol=order["symbol"],
            side=order["side"],
            quantity=float(order["quantity"]),
            market=order["market"],
            position_side=position_side,
        )

        # Update position
        profit_data = None
        if is_exit:
            # Capture position data BEFORE clearing
            position = await self.redis.get_position(order["symbol"], order["market"])
            entry_price = float(position.get("entry_price", 0)) if position else 0
            entry_time = int(position.get("entry_time", 0)) if position else 0

            # Calculate realized P&L (must be done before clearing position)
            profit_data = await self._record_exit_pnl(order, fill)
            await self.redis.clear_position(order["symbol"], order["market"])
        else:
            await self._update_position(order, fill)
            # Place server-side stop-loss AFTER entry
            await self._place_server_stop_loss(order["symbol"], order["market"], fill, order)

        # Publish trade notification (with profit data for exits)
        await self._publish_trade(order, fill, profit_data)

        # Structured logging for trade analysis
        if is_exit and profit_data:
            hold_time = int(time.time() * 1000 - entry_time) // 1000 if entry_time else 0
            trade_logger.exit(
                symbol=order["symbol"],
                price=fill["filled_price"],
                qty=fill["filled_qty"],
                entry_price=entry_price,
                strategy=order["strategy"],
                pnl=profit_data["profit"],
                pnl_pct=profit_data["profit_pct"],
                hold_time_sec=hold_time,
                exit_reason=order.get("reason", ""),
                mode="live",
            )
        else:
            logged_leverage = 1
            try:
                logged_leverage = int(order.get("leverage", 1) or 1)
            except (TypeError, ValueError):
                logged_leverage = 1
            trade_logger.entry(
                symbol=order["symbol"],
                price=fill["filled_price"],
                qty=fill["filled_qty"],
                strategy=order["strategy"],
                leverage=logged_leverage,
                mode="live",
            )

        logger.info(f"Futures order {order['id']} filled: {fill}")
        return fill

    def _estimate_order_value(self, order: dict) -> float:
        """Estimate USDT value of order."""
        quantity = float(order.get("quantity", 0))
        # Use approximate price (we don't have real-time price here)
        # This is a rough estimate for balance check
        symbol = order.get("symbol", "BTC")
        price = APPROX_PRICES.get(symbol, 100)
        return quantity * price * 1.01  # 1% buffer for slippage

    async def _is_exit_order(self, order: dict) -> bool:
        """Check if order is closing an existing position."""
        symbol = order["symbol"]
        market = order["market"]
        side = order["side"]

        position = await self.redis.get_position(symbol, market)
        if not position:
            return False

        pos_side = position.get("side", "buy")

        # Exit: selling a long (buy) position or buying to cover a short (sell) position
        return (side == "buy" and pos_side == "sell") or (side == "sell" and pos_side == "buy")

    async def _get_position_side(self, order: dict, is_exit: bool) -> str:
        """Determine position_side for futures hedge mode.

        In hedge mode, orders must specify which position they affect:
        - LONG: for opening/closing long positions
        - SHORT: for opening/closing short positions

        Args:
            order: Order dict with symbol, side, market.
            is_exit: Whether this order is closing an existing position.

        Returns:
            "LONG" or "SHORT" for futures orders.
        """
        market = order.get("market", "futures")
        side = order["side"]

        if is_exit:
            # For exits, use the existing position's side
            position = await self.redis.get_position(order["symbol"], market)
            if position:
                pos_side = position.get("side", "buy")
                # Position side buy means LONG position, sell means SHORT position
                return "LONG" if pos_side == "buy" else "SHORT"

        # For entries: BUY opens LONG, SELL opens SHORT
        return "LONG" if side == "buy" else "SHORT"

    async def _record_exit_pnl(self, order: dict, fill: dict) -> dict | None:
        """Record realized P&L when exiting a position.

        Returns:
            Dict with profit and profit_pct, or None if no position found.
        """
        symbol = order["symbol"]
        market = order["market"]

        position = await self.redis.get_position(symbol, market)
        if not position:
            return None

        entry_price = float(position.get("entry_price", 0))
        exit_price = fill["filled_price"]
        quantity = fill["filled_qty"]
        side = position.get("side", "buy")
        leverage = int(position.get("leverage", 1))

        if entry_price <= 0 or quantity <= 0:
            return None

        # Calculate P&L based on position direction
        if side == "buy":  # Long position
            pnl = (exit_price - entry_price) * quantity
            price_change_pct = ((exit_price - entry_price) / entry_price) * 100
        else:  # Short position
            pnl = (entry_price - exit_price) * quantity
            price_change_pct = ((entry_price - exit_price) / entry_price) * 100

        # Apply leverage to P&L (same as paper trading)
        pnl_with_leverage = pnl * leverage
        pnl_pct = price_change_pct * leverage

        # Update daily P&L
        risk = await self.redis.get_risk()
        daily_pnl = float(risk.get("daily_pnl", 0)) + pnl_with_leverage
        await self.redis.hset("risk", {"daily_pnl": str(daily_pnl)})

        direction = "Long" if side == "buy" else "Short"
        logger.info(f"Recorded P&L ({direction}): {symbol} {pnl_with_leverage:+.2f} USDT ({pnl_pct:+.2f}%) (daily total: {daily_pnl:+.2f})")

        # Update LeverageManager equity
        if self.leverage_manager:
            await self.leverage_manager.update_equity(pnl_with_leverage)
            logger.info(
                f"LeverageManager updated: equity=${self.leverage_manager.current_equity:,.2f}, "
                f"drawdown={self.leverage_manager.get_drawdown_pct():.1f}%, "
                f"tier={self.leverage_manager.current_tier.name} ({self.leverage_manager.current_tier.leverage}x)"
            )

        # Publish P&L alert
        await self.redis.publish("alerts", {
            "type": "pnl_realized",
            "symbol": symbol,
            "pnl": str(pnl_with_leverage),
            "daily_pnl": str(daily_pnl),
            "timestamp": str(int(time.time() * 1000)),
        })

        return {"profit": pnl_with_leverage, "profit_pct": pnl_pct}

    async def _pass_risk_gates(self, market: str = "futures") -> bool:
        """Check all risk conditions for the specified market.

        Args:
            market: "spot" or "futures". Default "futures" for backwards compatibility.
        """
        risk = await self.redis.get_risk()

        # Kill switch
        if risk.get("kill_switch") == "true":
            logger.warning("Kill switch is ON")
            return False

        # Blocked flag
        if risk.get("blocked") == "true":
            logger.warning("Trading is blocked")
            return False

        # Daily loss limit
        daily_pnl = float(risk.get("daily_pnl", 0))
        if daily_pnl < -self.max_daily_loss:
            logger.warning(f"Daily loss limit exceeded: {daily_pnl}")
            return False

        # Minimum balance check (market-specific)
        balance = self._balance_cache.get(market, 0)
        if balance < self.min_balance:
            logger.warning(f"{market.capitalize()} balance too low: {balance}")
            return False

        return True

    async def _update_position(self, order: dict, fill: dict) -> None:
        """Update futures position in Redis with leverage and liquidation price."""
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

    async def _update_spot_position(self, order: dict, fill: dict) -> None:
        """Update spot position in Redis - no leverage, no liquidation."""
        await self.redis.set_position(order["symbol"], "spot", {
            "quantity": str(fill["filled_qty"]),
            "entry_price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "entry_time": str(int(time.time() * 1000)),
            "side": order["side"],
            "leverage": "1",
            "liquidation_price": "0",
        })

        logger.info(
            f"Spot position opened: {order['symbol']} {order['side'].upper()} "
            f"@ {fill['filled_price']}"
        )

    async def _publish_trade(self, order: dict, fill: dict, profit_data: dict | None = None) -> None:
        """Publish trade to trades stream.

        Args:
            order: Order dict with symbol, side, market, strategy.
            fill: Fill dict with order_id, filled_qty, filled_price.
            profit_data: Optional dict with profit and profit_pct for exit trades.
        """
        trade = {
            "order_id": str(fill["order_id"]),
            "symbol": order["symbol"],
            "side": order["side"],
            "market": order["market"],
            "quantity": str(fill["filled_qty"]),
            "price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "timestamp": str(int(time.time() * 1000)),
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
            "order_id": order["id"],
            "symbol": order["symbol"],
            "reason": reason,
            "timestamp": str(int(time.time() * 1000)),
        })

    async def _place_server_stop_loss(self, symbol: str, market: str, fill: dict, order: dict) -> None:
        """Place server-side stop-loss order after entry fill.

        Args:
            symbol: Trading symbol (e.g., "BTC")
            market: "spot" or "futures"
            fill: Fill dict with filled_price and filled_qty
            order: Order dict with stop_loss_pct (optional)
        """
        # Get stop_loss_pct from order metadata (default to 10%)
        stop_loss_pct = float(order.get("stop_loss_pct", 0.10))
        if stop_loss_pct <= 0:
            logger.debug(f"No stop-loss configured for {symbol} (stop_loss_pct={stop_loss_pct})")
            return

        entry_price = fill["filled_price"]
        quantity = fill["filled_qty"]
        side = order["side"]

        # Calculate stop price based on position direction
        if side == "buy":
            # Long position: stop price below entry
            stop_price = round(entry_price * (1 - stop_loss_pct), 2)
            stop_side = "sell"
            position_side = "LONG"
        else:
            # Short position: stop price above entry
            stop_price = round(entry_price * (1 + stop_loss_pct), 2)
            stop_side = "buy"
            position_side = "SHORT"

        # Set limit price 1% away from stop to ensure fill
        if stop_side == "sell":
            limit_price = round(stop_price * 0.99, 2)
        else:
            limit_price = round(stop_price * 1.01, 2)

        try:
            result = await self.client.stop_loss_limit_order(
                symbol=symbol,
                side=stop_side,
                quantity=quantity,
                stop_price=stop_price,
                limit_price=limit_price,
                market=market,
                position_side=position_side if market == "futures" else None,
            )

            if result:
                order_id = str(result.get("orderId", ""))
                # Store in Redis position hash
                await self.redis.redis.hset(
                    f"positions:{symbol}:{market}",
                    mapping={
                        "stop_order_id": order_id,
                        "stop_price": str(stop_price),
                    },
                )
                logger.info(
                    f"Server stop-loss placed: {symbol} {market} {side} position, "
                    f"stop={stop_price} ({stop_loss_pct*100:.1f}%), orderId={order_id}"
                )
        except Exception as e:
            logger.error(f"Failed to place server stop-loss for {symbol}: {e}")

    async def _cancel_server_stop_loss(self, symbol: str, market: str) -> None:
        """Cancel server-side stop-loss before normal exit.

        Args:
            symbol: Trading symbol (e.g., "BTC")
            market: "spot" or "futures"
        """
        try:
            pos = await self.redis.get_position(symbol, market)
            stop_order_id = pos.get("stop_order_id") if pos else None

            if stop_order_id:
                # Cancel all open orders to be safe
                await self.client.cancel_open_orders(
                    symbol=symbol,
                    market=market,
                )
                logger.info(f"Cancelled server stop-loss for {symbol} {market}: orderId={stop_order_id}")
        except Exception as e:
            logger.warning(f"Failed to cancel stop-loss for {symbol} {market}: {e}")
