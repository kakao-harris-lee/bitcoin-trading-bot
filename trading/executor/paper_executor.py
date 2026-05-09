# trading/executor/paper_executor.py
"""Paper trading executor for spot-only simulation."""

# pylint: disable=logging-fstring-interpolation,broad-exception-caught

from __future__ import annotations

import asyncio
import logging
import os
import time
import uuid
from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

from trading.observability.structured_logger import trade_logger
from trading.risk.trade_logger import TradeLogger
from trading.utils.precision import PriceUtils, get_symbol_info

if TYPE_CHECKING:
    from trading.risk.leverage_manager import LeverageManager
    from trading.streams.redis_streams import RedisStreams

logger = logging.getLogger(__name__)

VALID_SIDES = {"buy", "sell"}
VALID_MARKETS = {"spot"}
VALID_SYMBOLS = {"BTC", "ETH", "SOL", "BNB"}

DEFAULT_PAPER_BALANCE = 10000
POSITION_EPSILON = 1e-9


class PaperExecutor:
    """Simulates spot order execution without real API calls."""

    def __init__(
        self,
        redis: RedisStreams,
        config: dict,
        leverage_manager: Optional[LeverageManager] = None,
    ):
        self.redis = redis
        self.config = config
        self.leverage_manager = leverage_manager
        self.initial_balance = float(config.get("initial_balance", DEFAULT_PAPER_BALANCE))
        self.spot_balance = self.initial_balance
        # Keep a legacy alias to avoid breaking callers/tests that still read `balance`.
        self.balance = self.spot_balance
        self.fee_rate = float(config.get("fee_rate", 0.001))
        self.slippage = float(config.get("slippage", 0.0004))
        self.max_daily_loss = float(config.get("max_daily_loss", 500))
        self.last_prices: dict[str, float] = {}
        self._running = False

        self.spot_positions: dict[str, float] = {}

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

        self.trade_logger = TradeLogger(
            db_path=trade_log_db_path,
            strategy_name="paper_trading",
        )
        logger.info("TradeLogger initialized for paper trading persistence")

        self._price_tracker_task: Optional[asyncio.Task] = None

    @staticmethod
    def _supports_redis_method(redis_client: Any, method_name: str) -> bool:
        """Return True if Redis client explicitly supports a method."""
        if callable(getattr(type(redis_client), method_name, None)):
            return True
        return method_name in getattr(redis_client, "__dict__", {})

    async def _persist_account_state(self, data: dict[str, Any]) -> None:
        """Persist account state with stream-mirror support and legacy fallback."""
        if self._supports_redis_method(self.redis, "set_account"):
            maybe_coro = self.redis.set_account("account:paper", data)
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
            return
        maybe_coro = self.redis.hset("account:paper", data)
        if asyncio.iscoroutine(maybe_coro):
            await maybe_coro

    async def _persist_risk_state(self, data: dict[str, Any]) -> None:
        """Persist risk state with stream-mirror support and legacy fallback."""
        if self._supports_redis_method(self.redis, "set_risk"):
            maybe_coro = self.redis.set_risk(data)
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
            return
        maybe_coro = self.redis.hset("risk", data)
        if asyncio.iscoroutine(maybe_coro):
            await maybe_coro

    async def run(self) -> None:
        """Main loop: consume and simulate spot orders."""
        self._running = True
        group = "executor"
        consumer = "paper-executor"

        await self.redis.create_consumer_group("orders", group)

        await self._load_balance_from_redis()
        await self._get_current_daily_pnl()
        await self._sync_balance_to_redis()
        logger.info("PaperExecutor started with spot balance: %.2f", self.spot_balance)

        if self.leverage_manager:
            await self.leverage_manager.initialize(initial_equity=self.spot_balance)
            logger.info(
                "LeverageManager initialized: equity=$%s, tier=%s (%sx)",
                f"{self.spot_balance:,.2f}",
                self.leverage_manager.current_tier.name,
                self.leverage_manager.current_tier.leverage,
            )

        self._price_tracker_task = asyncio.create_task(self._price_tracker())

        while self._running:
            try:
                messages = await self.redis.consume(
                    "orders", group, consumer, count=1, block_ms=1000
                )
                for msg in messages:
                    logger.info(
                        "PaperExecutor consume order: stream_id=%s order_id=%s symbol=%s side=%s strategy=%s",
                        msg.get("_id"),
                        msg.get("id"),
                        msg.get("symbol"),
                        msg.get("side"),
                        msg.get("strategy"),
                    )
                    await self._process_order(msg)
                    await self.redis.ack("orders", group, msg["_id"])
            except Exception as exc:
                logger.error("PaperExecutor error: %s", exc)
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
        except Exception as exc:
            logger.debug("Consumer group creation: %s", exc)

        while self._running:
            try:
                messages = await self.redis.consume(
                    "market:prices", group, consumer, count=100, block_ms=500
                )
                for msg in messages:
                    symbol = msg.get("symbol")
                    price = msg.get("price")
                    if symbol and price:
                        self.last_prices[str(symbol)] = float(price)
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
            if not account:
                logger.info("No persisted balance found, using initial: %s", self.initial_balance)
                self.spot_balance = self.initial_balance
                self.balance = self.spot_balance
                return

            raw_balance = (
                account.get("spot_balance")
                or account.get("balance")
            )
            if raw_balance is not None:
                saved_balance = float(raw_balance)
                if saved_balance > 0:
                    self.spot_balance = saved_balance
                    self.balance = self.spot_balance
                    logger.info("Loaded persisted paper spot balance from Redis: %.2f", self.spot_balance)
                    return

            self.spot_balance = self.initial_balance
            self.balance = self.spot_balance
        except Exception as exc:
            logger.warning("Failed to load balance from Redis, using initial: %s", exc)
            self.spot_balance = self.initial_balance
            self.balance = self.spot_balance

    async def _sync_balance_to_redis(self) -> None:
        """Sync paper trading spot balance to Redis for dashboard display."""
        try:
            self.balance = self.spot_balance
            await self._persist_account_state(
                {
                    "spot_balance": str(self.spot_balance),
                    "total_equity": str(self.spot_balance),
                    "last_sync": str(int(time.time())),
                }
            )
            logger.debug("Synced paper spot balance to Redis: %.2f", self.spot_balance)
        except Exception as exc:
            logger.error("Failed to sync balance to Redis: %s", exc)

    async def _process_order(self, order: dict[str, Any]) -> dict[str, Any] | None:
        """Simulate spot order execution."""
        required_fields = ["id", "symbol", "side", "quantity", "market", "strategy"]
        for field in required_fields:
            if field not in order:
                logger.error("Order missing required field: %s", field)
                return None

        side = str(order["side"]).lower()
        if side not in VALID_SIDES:
            logger.error("Invalid order side: %s", order["side"])
            return None

        market = str(order["market"]).lower()
        if market not in VALID_MARKETS:
            logger.warning("Rejected non-spot paper order: %s", order)
            await self._publish_rejection(order, "unsupported_market")
            return None

        symbol = str(order["symbol"]).upper()
        if symbol not in self.valid_symbols:
            logger.error("Invalid symbol: %s", symbol)
            return None
        order["symbol"] = symbol
        order["market"] = "spot"
        order["side"] = side

        try:
            quantity = float(order["quantity"])
            if quantity <= 0:
                logger.error("Invalid quantity: %s", quantity)
                return None
        except (ValueError, TypeError) as exc:
            logger.error("Invalid quantity format: %s: %s", order.get("quantity"), exc)
            return None

        if not await self._pass_risk_gates():
            logger.warning("Paper order %s blocked by risk gates", order["id"])
            await self._publish_rejection(order, "risk_blocked")
            return None

        return await self._simulate_spot_fill(order)

    async def _simulate_spot_fill(self, order: dict[str, Any]) -> dict[str, Any] | None:
        """Simulate spot order fill."""
        symbol = order["symbol"]
        side = order["side"]
        quantity = float(order["quantity"])

        price = self.last_prices.get(symbol)
        if price is None:
            logger.warning(
                "No price available for %s while processing order_id=%s; cached_prices=%s",
                symbol,
                order.get("id"),
                sorted(self.last_prices.keys()),
            )
            return None

        fill_price = self._apply_slippage(price, side)
        order_value = fill_price * quantity
        fees = order_value * self.fee_rate

        redis_position = await self.redis.get_position(symbol, "spot")
        redis_qty = self._to_float(redis_position.get("quantity") if redis_position else 0.0)
        current_qty = self.spot_positions.get(symbol, 0.0)
        if current_qty <= POSITION_EPSILON and redis_qty > POSITION_EPSILON:
            current_qty = redis_qty
            self.spot_positions[symbol] = current_qty

        is_exit = side == "sell" and (current_qty > POSITION_EPSILON or redis_qty > POSITION_EPSILON)

        if side == "buy":
            total_cost = order_value + fees
            if total_cost > self.spot_balance:
                logger.warning("Insufficient spot balance: %s < %s", self.spot_balance, total_cost)
                await self._publish_rejection(order, f"insufficient_spot_balance:{self.spot_balance:.2f}")
                return None

            self.spot_balance -= total_cost
            self.balance = self.spot_balance

            existing_qty = current_qty
            new_qty = existing_qty + quantity
            existing_entry = self._to_float(redis_position.get("entry_price") if redis_position else 0.0)
            if existing_qty > POSITION_EPSILON and existing_entry > 0:
                avg_entry_price = ((existing_entry * existing_qty) + (fill_price * quantity)) / new_qty
                entry_time = str(
                    self._to_int(redis_position.get("entry_time"), int(time.time() * 1000))
                )
            else:
                avg_entry_price = fill_price
                entry_time = str(int(time.time() * 1000))

            self.spot_positions[symbol] = new_qty
            await self.redis.set_position(
                symbol,
                "spot",
                {
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
                },
            )
            logger.info("Spot buy: %s %s @ %s, new position: %s", symbol, quantity, fill_price, new_qty)
        else:
            current_qty = self.spot_positions.get(symbol, current_qty)
            if current_qty + POSITION_EPSILON < quantity:
                logger.warning("Insufficient spot position: %s < %s", current_qty, quantity)
                await self._publish_rejection(order, f"insufficient_spot_position:{current_qty}")
                return None

            self.spot_balance += order_value - fees
            self.balance = self.spot_balance
            remaining_qty = max(current_qty - quantity, 0.0)
            if remaining_qty <= POSITION_EPSILON:
                self.spot_positions.pop(symbol, None)
                remaining_qty = 0.0
            else:
                self.spot_positions[symbol] = remaining_qty
            logger.info("Spot sell: %s %s @ %s, remaining: %s", symbol, quantity, fill_price, self.spot_positions.get(symbol, 0))

        await self._sync_balance_to_redis()

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

        profit_data = None
        entry_price = 0.0
        entry_time = 0
        position = redis_position or await self.redis.get_position(symbol, "spot")
        if is_exit:
            if position:
                entry_price = self._to_float(position.get("entry_price"))
                entry_time = self._to_int(position.get("entry_time"))
            profit_data = await self._calculate_exit_pnl(order, fill)
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
                },
            )

        await self._publish_trade(order, fill, profit_data)
        await self._log_trade_to_db_async(order, fill, profit_data)

        logger.info("Spot paper fill: %s, balance: %.2f", fill, self.spot_balance)

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
                leverage=1,
                mode="paper",
            )

        return fill

    async def _log_trade_to_db_async(self, order: dict, fill: dict, profit_data: dict | None) -> None:
        """Log trade to SQLite database for persistence."""
        try:
            self._log_trade_to_db_sync(order, fill, profit_data)
            logger.info(
                "PaperExecutor logged trade to DB: order_id=%s symbol=%s side=%s fill_order_id=%s",
                order.get("id"),
                order.get("symbol"),
                order.get("side"),
                fill.get("order_id"),
            )
        except Exception as exc:
            logger.error("Failed to log trade to database: %s", exc)

    def _log_trade_to_db_sync(self, order: dict, fill: dict, profit_data: dict | None) -> None:
        """Synchronous database logging."""
        self.trade_logger.log_trade(
            action=order["side"],
            price=fill["filled_price"],
            volume=fill["filled_qty"],
            profit=profit_data.get("profit") if profit_data else None,
            profit_pct=profit_data.get("profit_pct") if profit_data else None,
            exchange="binance",
            symbol=order["symbol"],
            market="spot",
            paper=True,
            strategy_name=order.get("strategy"),
        )

    def _apply_slippage(self, price: float, side: str) -> float:
        """Apply slippage to price."""
        if side == "buy":
            return price * (1 + self.slippage)
        return price * (1 - self.slippage)

    @staticmethod
    def _to_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_int(value: Any, default: int = 0) -> int:
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _current_paper_day() -> str:
        return date.today().isoformat()

    async def _get_current_daily_pnl(self, risk: dict[str, Any] | None = None) -> float:
        """Return same-day realized PnL, resetting stale or legacy cumulative state."""
        state = dict(risk or await self.redis.get_risk() or {})
        current_day = self._current_paper_day()
        stored_day = str(state.get("daily_pnl_date", "")).strip()

        if stored_day != current_day:
            logger.info(
                "PaperExecutor: resetting daily_pnl for new day (stored=%s current=%s previous=%s)",
                stored_day or "missing",
                current_day,
                state.get("daily_pnl", "0"),
            )
            await self._persist_risk_state(
                {"daily_pnl": "0", "daily_pnl_date": current_day}
            )
            return 0.0

        try:
            return float(state.get("daily_pnl", 0))
        except (TypeError, ValueError):
            await self._persist_risk_state(
                {"daily_pnl": "0", "daily_pnl_date": current_day}
            )
            return 0.0

    @staticmethod
    def _position_payload(position: dict[str, Any] | None) -> dict[str, Any]:
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
            self.spot_positions.pop(symbol, None)
            await self.redis.clear_position(symbol, market)
            return

        if self._is_spot_dust_position(symbol, remaining_qty):
            self.spot_positions.pop(symbol, None)
            await self.redis.clear_position(symbol, market)
            return

        payload = self._position_payload(position)
        if fallback_updates:
            payload = {**fallback_updates, **payload}
        payload["quantity"] = str(remaining_qty)
        self.spot_positions[symbol] = remaining_qty
        await self.redis.set_position(symbol, market, payload)

    def _is_spot_dust_position(self, symbol: str, quantity: float) -> bool:
        """Return True when remaining spot quantity is not practically tradable."""
        try:
            symbol_info = get_symbol_info(symbol)
            if not PriceUtils.meets_min_qty(quantity, symbol_info):
                return True

            ref_price = self.last_prices.get(symbol)
            if ref_price and not PriceUtils.meets_min_notional(ref_price, quantity, symbol_info):
                return True
        except Exception:
            return False
        return False

    async def _pass_risk_gates(self) -> bool:
        """Check paper risk conditions."""
        risk = await self.redis.get_risk()

        kill_switch = risk.get("kill_switch", "false")
        if kill_switch is True or str(kill_switch).lower() == "true":
            return False

        blocked = risk.get("blocked", "false")
        if blocked is True or str(blocked).lower() == "true":
            return False

        daily_pnl = await self._get_current_daily_pnl(risk)
        if daily_pnl < -self.max_daily_loss:
            return False
        return True

    async def _update_position(self, order: dict[str, Any], fill: dict[str, Any]) -> None:
        """Persist a spot position after an entry fill."""
        market = str(order.get("market", "spot")).lower()
        if market != "spot":
            raise ValueError("PaperExecutor supports only spot positions.")

        await self.redis.set_position(
            order["symbol"],
            "spot",
            {
                "quantity": str(fill["filled_qty"]),
                "entry_price": str(fill["filled_price"]),
                "strategy": order["strategy"],
                "entry_time": str(int(time.time() * 1000)),
                "side": order["side"],
                "leverage": "1",
            },
        )

    async def _is_exit_order(self, order: dict[str, Any]) -> bool:
        """Check if order is a position-closing spot sell."""
        position = await self.redis.get_position(order["symbol"], "spot")
        if not position:
            return False
        pos_side = position.get("side", "buy")
        order_side = str(order["side"]).lower()
        return pos_side == "buy" and order_side == "sell"

    async def _calculate_exit_pnl(self, order: dict[str, Any], fill: dict[str, Any]) -> dict[str, float] | None:
        """Calculate realized PnL when exiting a spot position."""
        del order
        position = await self.redis.get_position(fill["symbol"], "spot")
        if not position:
            return None

        entry_price = self._to_float(position.get("entry_price", 0))
        exit_price = float(fill["filled_price"])
        quantity = float(fill["filled_qty"])
        if entry_price <= 0 or quantity <= 0:
            return None

        pnl = (exit_price - entry_price) * quantity
        pnl_pct = ((exit_price - entry_price) / entry_price) * 100

        risk = await self.redis.get_risk()
        daily_pnl = await self._get_current_daily_pnl(risk) + pnl
        await self._persist_risk_state(
            {"daily_pnl": str(daily_pnl), "daily_pnl_date": self._current_paper_day()}
        )

        logger.info("Spot P&L: %s %+0.2f USDT (%+0.2f%%)", fill["symbol"], pnl, pnl_pct)

        payload = {
            "type": "pnl_realized",
            "symbol": fill["symbol"],
            "pnl": str(pnl),
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
        except Exception as exc:
            logger.debug("Failed to publish P&L alert: %s", exc)

        if self.leverage_manager:
            await self.leverage_manager.update_equity(pnl)

        return {"profit": pnl, "profit_pct": pnl_pct}

    async def _publish_trade(
        self,
        order: dict[str, Any],
        fill: dict[str, Any],
        profit_data: dict[str, Any] | None = None,
    ) -> None:
        """Publish trade to trades stream."""
        trade = {
            "order_id": str(fill["order_id"]),
            "symbol": order["symbol"],
            "side": order["side"],
            "market": "spot",
            "quantity": str(fill["filled_qty"]),
            "price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "timestamp": str(int(time.time() * 1000)),
            "paper": "true",
            "reason": order.get("reason", ""),
        }
        if profit_data:
            trade["profit"] = str(profit_data["profit"])
            trade["profit_pct"] = str(profit_data["profit_pct"])
        stream_id = await self.redis.publish("trades", trade)
        logger.info(
            "PaperExecutor published trade: stream_id=%s fill_order_id=%s symbol=%s side=%s strategy=%s",
            stream_id,
            fill.get("order_id"),
            order.get("symbol"),
            order.get("side"),
            order.get("strategy"),
        )

    async def _publish_rejection(self, order: dict[str, Any], reason: str) -> None:
        """Publish order rejection to alerts stream."""
        await self.redis.publish(
            "alerts",
            {
                "type": "order_rejected",
                "order_id": order.get("id", "unknown"),
                "symbol": order.get("symbol", "unknown"),
                "reason": reason,
                "timestamp": str(int(time.time() * 1000)),
                "paper": "true",
            },
        )
