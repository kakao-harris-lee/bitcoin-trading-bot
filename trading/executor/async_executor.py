# trading/executor/async_executor.py
"""Async executor for processing order stream."""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.executor.binance_client import BinanceClient
    from trading.risk.leverage_manager import LeverageManager

logger = logging.getLogger(__name__)


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
        self._balance_cache = {"futures": 0.0, "last_update": 0}

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
            # Get balance
            balance = await self.client.get_balance()
            self._balance_cache = {
                "futures": balance.futures_usdt,
                "last_update": time.time(),
            }
            logger.info(f"Futures Balance: ${balance.futures_usdt:.2f}")

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
            await self.redis.hset("account", {
                "futures_balance": str(balance.futures_usdt),
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
        """Periodically refresh balance cache."""
        while self._running:
            try:
                await asyncio.sleep(60)  # Refresh every minute
                balance = await self.client.get_balance()
                self._balance_cache = {
                    "futures": balance.futures_usdt,
                    "last_update": time.time(),
                }
                # Update Redis
                await self.redis.hset("account", {
                    "futures_balance": str(balance.futures_usdt),
                    "last_sync": str(int(time.time())),
                })
            except Exception as e:
                logger.warning(f"Balance refresh failed: {e}")

    async def _process_order(self, order: dict[str, Any]) -> dict | None:
        """Process single order."""
        # Check risk gates
        if not await self._pass_risk_gates():
            logger.warning(f"Order {order['id']} blocked by risk gates")
            await self._publish_rejection(order, "risk_blocked")
            return None

        # Check balance before order
        market = order.get("market", "futures")
        required_balance = self._estimate_order_value(order)
        available = self._balance_cache.get(market, 0)

        if available < required_balance:
            logger.warning(f"Insufficient balance: {available:.2f} < {required_balance:.2f}")
            await self._publish_rejection(order, f"insufficient_balance:{available:.2f}")
            return None

        try:
            # Check if this is an exit (closing an existing position)
            is_exit = await self._is_exit_order(order)

            # Check leverage allowance for futures entry orders
            allowed_leverage = None
            if market == "futures" and not is_exit and self.leverage_manager:
                allowed_leverage = await self.leverage_manager.get_allowed_leverage()
                if allowed_leverage == 0:
                    logger.warning(
                        f"Order {order['id']} blocked: leverage halted "
                        f"(drawdown={self.leverage_manager.get_drawdown_pct():.1f}%)"
                    )
                    await self._publish_rejection(order, "leverage_halted")
                    return None

                # Set leverage on Binance before order
                symbol = order["symbol"]
                await self.client.set_leverage(symbol, allowed_leverage)
                logger.info(f"Set leverage for {symbol}: {allowed_leverage}x")

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
                # Calculate realized P&L (must be done before clearing position)
                profit_data = await self._record_exit_pnl(order, fill)
                await self.redis.clear_position(order["symbol"], order["market"])
            else:
                await self._update_position(order, fill)

            # Publish trade notification (with profit data for exits)
            await self._publish_trade(order, fill, profit_data)

            logger.info(f"Order {order['id']} filled: {fill}")
            return fill

        except Exception as e:
            logger.error(f"Order {order['id']} failed: {e}")
            await self._publish_rejection(order, str(e))
            return None

    def _estimate_order_value(self, order: dict) -> float:
        """Estimate USDT value of order."""
        quantity = float(order.get("quantity", 0))
        # Use approximate price (we don't have real-time price here)
        # This is a rough estimate for balance check
        symbol = order.get("symbol", "BTC")
        approx_prices = {"BTC": 90000, "ETH": 3000, "SOL": 130}
        price = approx_prices.get(symbol, 100)
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

        # Calculate P&L
        if side == "buy":  # Long position
            pnl = (exit_price - entry_price) * quantity
            pnl_pct = ((exit_price - entry_price) / entry_price * 100) if entry_price > 0 else 0
        else:  # Short position
            pnl = (entry_price - exit_price) * quantity
            pnl_pct = ((entry_price - exit_price) / entry_price * 100) if entry_price > 0 else 0

        # Update daily P&L
        risk = await self.redis.get_risk()
        daily_pnl = float(risk.get("daily_pnl", 0)) + pnl
        await self.redis.hset("risk", {"daily_pnl": str(daily_pnl)})

        logger.info(f"Recorded P&L: {symbol} {pnl:+.2f} USDT ({pnl_pct:+.2f}%) (daily total: {daily_pnl:+.2f})")

        # Update LeverageManager equity
        if self.leverage_manager:
            await self.leverage_manager.update_equity(pnl)
            logger.info(
                f"LeverageManager updated: equity=${self.leverage_manager.current_equity:,.2f}, "
                f"drawdown={self.leverage_manager.get_drawdown_pct():.1f}%, "
                f"tier={self.leverage_manager.current_tier.name} ({self.leverage_manager.current_tier.leverage}x)"
            )

        # Publish P&L alert
        await self.redis.publish("alerts", {
            "type": "pnl_realized",
            "symbol": symbol,
            "pnl": str(pnl),
            "daily_pnl": str(daily_pnl),
            "timestamp": str(int(time.time() * 1000)),
        })

        return {"profit": pnl, "profit_pct": pnl_pct}

    async def _pass_risk_gates(self) -> bool:
        """Check all risk conditions."""
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

        # Minimum balance check
        futures = self._balance_cache.get("futures", 0)
        if futures < self.min_balance:
            logger.warning(f"Futures balance too low: {futures}")
            return False

        return True

    async def _update_position(self, order: dict, fill: dict) -> None:
        """Update position in Redis."""
        await self.redis.set_position(order["symbol"], order["market"], {
            "quantity": str(fill["filled_qty"]),
            "entry_price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "entry_time": str(int(time.time() * 1000)),
            "side": order["side"],
        })

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
