"""Spot-only async executor for processing order stream."""

# pylint: disable=logging-fstring-interpolation,broad-exception-caught

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Optional, TYPE_CHECKING

from trading.observability.structured_logger import trade_logger

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.executor.binance_client import BinanceClient
    from trading.risk.leverage_manager import LeverageManager

logger = logging.getLogger(__name__)

APPROX_PRICES = {"BTC": 90000, "ETH": 3000, "SOL": 130, "BNB": 600}


class AsyncExecutor:
    """Consumes orders stream and executes spot orders via Binance API."""

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
        self.max_daily_loss = config.get("max_daily_loss", 500)
        self.position_pct = config.get("position_pct", 0.02)
        self.min_balance = config.get("min_balance", 100)
        self._running = False
        self._balance_cache = {"spot": 0.0, "last_update": 0.0}

    @staticmethod
    def _supports_redis_method(redis_client: Any, method_name: str) -> bool:
        if callable(getattr(type(redis_client), method_name, None)):
            return True
        return method_name in getattr(redis_client, "__dict__", {})

    async def _persist_account_state(self, data: dict[str, Any]) -> None:
        if self._supports_redis_method(self.redis, "set_account"):
            maybe_coro = self.redis.set_account("account:live", data)
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
            return
        await self.redis.hset("account:live", data)

    async def _persist_risk_state(self, data: dict[str, Any]) -> None:
        if self._supports_redis_method(self.redis, "set_risk"):
            maybe_coro = self.redis.set_risk(data)
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
            return
        await self.redis.hset("risk", data)

    async def _patch_position_state(
        self,
        symbol: str,
        market: str,
        updates: dict[str, Any],
    ) -> None:
        if self._supports_redis_method(self.redis, "patch_position"):
            maybe_coro = self.redis.patch_position(symbol, market, updates)
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
            return

        raw_client = getattr(self.redis, "redis", None)
        raw_hset = getattr(raw_client, "hset", None) if raw_client is not None else None
        if callable(raw_hset):
            maybe_coro = raw_hset(f"positions:{symbol}:{market}", mapping=updates)
            if asyncio.iscoroutine(maybe_coro):
                await maybe_coro
            return

        await self.redis.hset(f"positions:{symbol}:{market}", updates)

    async def run(self) -> None:
        self._running = True
        group = "executor"
        consumer = "executor-main"

        await self.redis.create_consumer_group("orders", group)
        await self._sync_account()
        logger.info("AsyncExecutor started (spot-only)")

        asyncio.create_task(self._balance_refresh_loop())

        while self._running:
            try:
                messages = await self.redis.consume("orders", group, consumer, count=1, block_ms=1000)
                for msg in messages:
                    await self._process_order(msg)
                    await self.redis.ack("orders", group, msg["_id"])
            except Exception as exc:
                logger.error("Executor error: %s", exc)
                await asyncio.sleep(1)

    def stop(self) -> None:
        self._running = False

    @staticmethod
    def _normalize_stop_loss_pct(raw_value: Any, default: float = 0.10) -> float:
        try:
            value = float(raw_value)
        except (TypeError, ValueError):
            return default
        if value <= 0:
            return 0.0
        if value > 1.0:
            return min(value, 100.0) / 100.0
        return value

    async def _sync_account(self) -> None:
        logger.info("Syncing spot account with Binance...")
        try:
            balance = await self.client.get_balance()
            spot_balance = getattr(balance, "spot_usdt", 0.0)
            self._balance_cache = {"spot": spot_balance, "last_update": time.time()}
            logger.info("Spot Balance: $%.2f", spot_balance)

            positions = await self.client.get_all_positions()
            synced = 0
            for pos in positions:
                symbol = pos["symbol"]
                market = pos.get("market", "spot")
                redis_pos = await self.redis.get_position(symbol, market)
                if redis_pos:
                    continue
                await self.redis.set_position(
                    symbol,
                    market,
                    {
                        "quantity": str(pos["quantity"]),
                        "entry_price": str(pos.get("entry_price", 0)),
                        "strategy": "external",
                        "entry_time": str(int(time.time() * 1000)),
                        "side": pos.get("side", "buy"),
                        "leverage": "1",
                    },
                )
                synced += 1

            if synced > 0:
                logger.info("Synced %d external spot positions from Binance", synced)

            await self._persist_account_state(
                {
                    "spot_balance": str(spot_balance),
                    "total_equity": str(spot_balance),
                    "last_sync": str(int(time.time())),
                }
            )

            if self.leverage_manager:
                await self.leverage_manager.initialize(initial_equity=spot_balance)
        except Exception as exc:
            logger.error("Account sync failed: %s", exc)

    async def _balance_refresh_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(60)
                balance = await self.client.get_balance()
                spot_balance = getattr(balance, "spot_usdt", 0.0)
                self._balance_cache = {"spot": spot_balance, "last_update": time.time()}
                await self._persist_account_state(
                    {
                        "spot_balance": str(spot_balance),
                        "total_equity": str(spot_balance),
                        "last_sync": str(int(time.time())),
                    }
                )
            except Exception as exc:
                logger.warning("Balance refresh failed: %s", exc)

    async def _process_order(self, order: dict[str, Any]) -> dict | None:
        market = str(order.get("market", "spot") or "spot").lower()
        if market != "spot":
            logger.warning("Rejected non-spot order: %s", order)
            await self._publish_rejection(order, "unsupported_market")
            return None

        if not await self._pass_risk_gates("spot"):
            logger.warning("Order %s blocked by risk gates", order.get("id", "unknown"))
            await self._publish_rejection(order, "risk_blocked")
            return None

        required_balance = self._estimate_order_value(order)
        available = self._balance_cache.get("spot", 0.0)
        if available < required_balance:
            logger.warning("Insufficient balance: %.2f < %.2f", available, required_balance)
            await self._publish_rejection(order, f"insufficient_balance:{available:.2f}")
            return None

        try:
            return await self._execute_spot_order(order)
        except Exception as exc:
            logger.error("Order %s failed: %s", order.get("id", "unknown"), exc)
            await self._publish_rejection(order, str(exc))
            return None

    async def _execute_spot_order(self, order: dict[str, Any]) -> dict | None:
        is_exit = await self._is_exit_order(order)
        if is_exit:
            await self._cancel_server_stop_loss(order["symbol"], "spot")

        fill = await self.client.market_order(
            symbol=order["symbol"],
            side=order["side"],
            quantity=float(order["quantity"]),
            market="spot",
            position_side=None,
        )

        profit_data = None
        entry_price = 0.0
        entry_time = 0
        if is_exit:
            position = await self.redis.get_position(order["symbol"], "spot")
            entry_price = float(position.get("entry_price", 0)) if position else 0
            entry_time = int(position.get("entry_time", 0)) if position else 0
            profit_data = await self._record_exit_pnl(order, fill)
            await self.redis.clear_position(order["symbol"], "spot")
        else:
            await self._update_spot_position(order, fill)
            await self._place_server_stop_loss(order["symbol"], "spot", fill, order)

        await self._publish_trade(order, fill, profit_data)

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
                leverage=1,
                mode="live",
            )

        logger.info("Spot order %s filled: %s", order.get("id", "unknown"), fill)
        return fill

    def _estimate_order_value(self, order: dict[str, Any]) -> float:
        quantity = float(order.get("quantity", 0))
        symbol = order.get("symbol", "BTC")
        price = APPROX_PRICES.get(symbol, 100)
        return quantity * price * 1.01

    async def _is_exit_order(self, order: dict[str, Any]) -> bool:
        position = await self.redis.get_position(order["symbol"], "spot")
        if not position:
            return False
        pos_side = position.get("side", "buy")
        side = order["side"]
        return (side == "buy" and pos_side == "sell") or (side == "sell" and pos_side == "buy")

    async def _record_exit_pnl(self, order: dict[str, Any], fill: dict[str, Any]) -> dict[str, float] | None:
        symbol = order["symbol"]
        position = await self.redis.get_position(symbol, "spot")
        if not position:
            return None

        entry_price = float(position.get("entry_price", 0))
        exit_price = float(fill["filled_price"])
        quantity = float(fill["filled_qty"])
        side = position.get("side", "buy")
        if entry_price <= 0 or quantity <= 0:
            return None

        if side == "buy":
            pnl = (exit_price - entry_price) * quantity
            pnl_pct = ((exit_price - entry_price) / entry_price) * 100
        else:
            pnl = (entry_price - exit_price) * quantity
            pnl_pct = ((entry_price - exit_price) / entry_price) * 100

        risk = await self.redis.get_risk()
        daily_pnl = float(risk.get("daily_pnl", 0)) + pnl
        await self._persist_risk_state({"daily_pnl": str(daily_pnl)})

        if self.leverage_manager:
            await self.leverage_manager.update_equity(pnl)

        await self.redis.publish(
            "alerts",
            {
                "type": "pnl_realized",
                "symbol": symbol,
                "pnl": str(pnl),
                "daily_pnl": str(daily_pnl),
                "timestamp": str(int(time.time() * 1000)),
            },
        )
        return {"profit": pnl, "profit_pct": pnl_pct}

    async def _pass_risk_gates(self, market: str = "spot") -> bool:
        risk = await self.redis.get_risk()
        if risk.get("kill_switch") == "true":
            logger.warning("Kill switch is ON")
            return False
        if risk.get("blocked") == "true":
            logger.warning("Trading is blocked")
            return False
        daily_pnl = float(risk.get("daily_pnl", 0))
        if daily_pnl < -self.max_daily_loss:
            logger.warning("Daily loss limit exceeded: %s", daily_pnl)
            return False
        balance = self._balance_cache.get(market, 0)
        if balance < self.min_balance:
            logger.warning("%s balance too low: %s", market.capitalize(), balance)
            return False
        return True

    async def _update_spot_position(self, order: dict[str, Any], fill: dict[str, Any]) -> None:
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
        logger.info("Spot position opened: %s %s @ %s", order["symbol"], order["side"].upper(), fill["filled_price"])

    async def _publish_trade(self, order: dict[str, Any], fill: dict[str, Any], profit_data: dict[str, float] | None = None) -> None:
        trade = {
            "order_id": str(fill["order_id"]),
            "symbol": order["symbol"],
            "side": order["side"],
            "market": "spot",
            "quantity": str(fill["filled_qty"]),
            "price": str(fill["filled_price"]),
            "strategy": order["strategy"],
            "timestamp": str(int(time.time() * 1000)),
            "reason": order.get("reason", ""),
        }
        if profit_data:
            trade["profit"] = str(profit_data["profit"])
            trade["profit_pct"] = str(profit_data["profit_pct"])
        await self.redis.publish("trades", trade)

    async def _publish_rejection(self, order: dict[str, Any], reason: str) -> None:
        await self.redis.publish(
            "alerts",
            {
                "type": "order_rejected",
                "order_id": order.get("id", "unknown"),
                "symbol": order.get("symbol", "unknown"),
                "reason": reason,
                "timestamp": str(int(time.time() * 1000)),
            },
        )

    async def _place_server_stop_loss(self, symbol: str, market: str, fill: dict[str, Any], order: dict[str, Any]) -> None:
        stop_loss_pct = self._normalize_stop_loss_pct(order.get("stop_loss_pct", 0.10))
        if stop_loss_pct <= 0:
            return

        entry_price = float(fill["filled_price"])
        quantity = float(fill["filled_qty"])
        side = order["side"]
        if side == "buy":
            stop_price = round(entry_price * (1 - stop_loss_pct), 2)
            stop_side = "sell"
        else:
            stop_price = round(entry_price * (1 + stop_loss_pct), 2)
            stop_side = "buy"

        limit_price = round(stop_price * 0.99, 2) if stop_side == "sell" else round(stop_price * 1.01, 2)
        result = await self.client.stop_loss_limit_order(
            symbol=symbol,
            side=stop_side,
            quantity=quantity,
            stop_price=stop_price,
            limit_price=limit_price,
            market=market,
            position_side=None,
        )
        if not result:
            return

        order_id = str(result.get("orderId", ""))
        await self._patch_position_state(symbol, market, {"stop_order_id": order_id, "stop_price": str(stop_price)})
        logger.info(
            "Server stop-loss placed: %s %s stop=%s (%.1f%%) orderId=%s",
            symbol,
            market,
            stop_price,
            stop_loss_pct * 100,
            order_id,
        )

    async def _cancel_server_stop_loss(self, symbol: str, market: str) -> None:
        try:
            pos = await self.redis.get_position(symbol, market)
            stop_order_id = pos.get("stop_order_id") if pos else None
            if not stop_order_id:
                return
            await self.client.cancel_open_orders(symbol=symbol, market=market)
            logger.info("Cancelled server stop-loss for %s %s: orderId=%s", symbol, market, stop_order_id)
        except Exception as exc:
            logger.warning("Failed to cancel stop-loss for %s %s: %s", symbol, market, exc)
