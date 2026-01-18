# trading/executor/paper_executor.py
"""Paper trading executor for simulation."""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from typing import Any, Optional, TYPE_CHECKING

from trading.risk.trade_logger import TradeLogger
from trading.risk.liquidation_guard import LiquidationGuard

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)


class PaperExecutor:
    """Simulates order execution without real API calls."""

    def __init__(
        self,
        redis: RedisStreams,
        config: dict,
    ):
        self.redis = redis
        self.config = config
        self.balance = config.get("initial_balance", 10000)
        self.fee_rate = config.get("fee_rate", 0.001)  # 0.1%
        self.slippage = config.get("slippage", 0.0004)  # 0.04%
        self.max_daily_loss = config.get("max_daily_loss", 500)
        self.last_prices: dict[str, float] = {}
        self._running = False

        # Initialize trade logger for database persistence
        self.trade_logger = TradeLogger(strategy_name="paper_trading")
        logger.info("TradeLogger initialized for paper trading persistence")

        # Add liquidation guard
        self.liquidation_guard = LiquidationGuard()

    async def run(self) -> None:
        """Main loop: consume and simulate orders."""
        self._running = True
        group = "executor"
        consumer = "paper-executor"

        await self.redis.create_consumer_group("orders", group)
        logger.info(f"PaperExecutor started with balance: {self.balance}")

        # Also consume prices to track latest prices
        asyncio.create_task(self._price_tracker())

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
        consumer = "tracker"

        try:
            await self.redis.create_consumer_group("market:prices", group)
        except Exception:
            pass

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

    async def _process_order(self, order: dict[str, Any]) -> dict | None:
        """Simulate order execution."""
        # Check risk gates
        if not await self._pass_risk_gates():
            logger.warning(f"Paper order {order['id']} blocked by risk gates")
            return None

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

        # Calculate order value and fees
        order_value = fill_price * quantity
        fees = order_value * self.fee_rate

        # Check balance for buys
        if side == "buy":
            total_cost = order_value + fees
            if total_cost > self.balance:
                logger.warning(f"Insufficient balance: {self.balance} < {total_cost}")
                return None
            self.balance -= total_cost
        else:
            # For sells, add to balance (minus fees)
            self.balance += order_value - fees

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

        # Check if exit and calculate P&L
        profit_data = None
        is_exit = await self._is_exit_order(order)
        if is_exit:
            profit_data = await self._calculate_exit_pnl(order, fill)
            await self.redis.clear_position(order["symbol"], order["market"])
        else:
            await self._update_position(order, fill)

        # Publish trade to Redis stream
        await self._publish_trade(order, fill, profit_data)

        # Log trade to database for persistence
        self._log_trade_to_db(order, fill, profit_data)

        logger.info(f"Paper fill: {fill}, balance: {self.balance:.2f}")
        return fill

    def _log_trade_to_db(self, order: dict, fill: dict, profit_data: dict | None) -> None:
        """Log trade to SQLite database for persistence."""
        try:
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
        except Exception as e:
            logger.error(f"Failed to log trade to database: {e}")

    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply slippage to price."""
        if side == "buy":
            return price * (1 + self.slippage)
        else:
            return price * (1 - self.slippage)

    async def _pass_risk_gates(self) -> bool:
        """Check risk conditions."""
        risk = await self.redis.get_risk()

        if risk.get("kill_switch") == "true":
            return False
        if risk.get("blocked") == "true":
            return False

        daily_pnl = float(risk.get("daily_pnl", 0))
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
