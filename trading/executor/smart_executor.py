# trading/executor/smart_executor.py
"""Smart executor for optimized exit execution."""

# pylint: disable=logging-fstring-interpolation,broad-exception-caught,protected-access

from __future__ import annotations
import asyncio
import logging
import time
import json
import uuid
from typing import TYPE_CHECKING
from dataclasses import dataclass, field, asdict

from trading.strategies.volatility_tracker import VolatilityTracker
from trading.utils.precision import PriceUtils
from trading.utils.exchange_info import get_exchange_cache

if TYPE_CHECKING:
    from trading.streams.redis_streams import RedisStreams
    from trading.executor.binance_client import BinanceClient

logger = logging.getLogger(__name__)


@dataclass
class ExitPlan:
    """Tracks an in-progress smart exit."""
    symbol: str
    market: str
    total_quantity: float
    trigger_price: float
    strategy: str
    start_time: float = field(default_factory=time.time)
    ladder_orders: list[dict] = field(default_factory=list)
    filled_quantity: float = 0.0
    phase: str = "ladder"  # ladder, sweep, complete
    reason: str = ""
    entry_price: float = 0.0  # For P&L calculation


class SmartExecutor:
    """Intercepts exit signals and applies smart execution."""

    def __init__(
        self,
        redis: RedisStreams,
        binance_client: BinanceClient,
        config: dict,
    ):
        self.redis = redis
        self.client = binance_client
        self.config = config

        # Extract smart_executor config
        se_config = config.get("smart_executor", {})
        self.enabled = se_config.get("enabled", True)

        # Trailing config
        trailing = se_config.get("trailing", {})
        self.volatility_window = trailing.get("volatility_window", 20)
        self.trail_distances = {
            "low": trailing.get("low_vol_trail", 0.8),
            "medium": trailing.get("med_vol_trail", 1.2),
            "high": trailing.get("high_vol_trail", 1.8),
        }

        # Split execution config
        split = se_config.get("split_execution", {})
        self.ladder_tiers = split.get("ladder_tiers", [0.05, 0.12, 0.20])
        self.ladder_weights = split.get("ladder_weights", [0.40, 0.35, 0.25])
        self.phase1_timeout = split.get("phase1_timeout_sec", 60)
        self.max_execution_time = split.get("max_execution_sec", 90)

        # Volatility trackers per symbol
        self.volatility_trackers: dict[str, VolatilityTracker] = {}

        # Active exit plans
        self.active_exits: dict[str, ExitPlan] = {}

        # High water marks for trailing stops
        self.high_water_marks: dict[str, float] = {}

        self._running = False

    async def update_high_water_mark(self, symbol: str, price: float) -> None:
        """Update high water mark for symbol."""
        current_hwm = self.high_water_marks.get(symbol, 0)
        if price > current_hwm:
            self.high_water_marks[symbol] = price
            await self._save_hwm(symbol, price)

    def calculate_stop_price(self, symbol: str, volatility: str) -> float:
        """Calculate trailing stop price."""
        hwm = self.high_water_marks.get(symbol, 0)
        trail_pct = self.trail_distances.get(volatility, 1.2)
        return hwm * (1 - trail_pct / 100)

    def should_trigger_stop(
        self, symbol: str, current_price: float, volatility: str
    ) -> bool:
        """Check if trailing stop should trigger."""
        if symbol not in self.high_water_marks:
            return False
        stop_price = self.calculate_stop_price(symbol, volatility)
        return current_price <= stop_price

    def analyze_price_action(self, symbol: str) -> str:
        """Analyze recent price action for execution decisions."""
        tracker = self.volatility_trackers.get(symbol)
        if not tracker or len(tracker.prices) < 4:
            return "unknown"

        prices = list(tracker.prices)[-4:]

        # Count direction changes
        changes = []
        for i in range(1, len(prices)):
            changes.append(prices[i] - prices[i - 1])

        # 3+ consecutive drops = trending down
        if all(c < 0 for c in changes):
            return "trending_down"

        # 3+ consecutive rises = trending up
        if all(c > 0 for c in changes):
            return "trending_up"

        # Mixed = choppy/bouncing
        return "bouncing"

    def _calculate_ladder_prices(self, base_price: float, symbol: str, market: str) -> list[float]:
        """Calculate limit prices for ladder tiers with Binance tick_size compliance."""
        cache = get_exchange_cache(market)
        symbol_info = cache.get(symbol)

        prices = []
        for tier_pct in self.ladder_tiers:
            price = base_price * (1 + tier_pct / 100)
            rounded_price = PriceUtils.round_to_tick(price, symbol_info.tick_size)
            prices.append(float(rounded_price))
        return prices

    def _calculate_ladder_quantities(self, total_qty: float, symbol: str, market: str) -> list[float]:
        """Calculate quantity for each ladder tier with Binance LOT_SIZE compliance."""
        cache = get_exchange_cache(market)
        symbol_info = cache.get(symbol)

        quantities = []
        for weight in self.ladder_weights:
            qty = total_qty * weight
            rounded_qty = PriceUtils.round_down_to_step(qty, symbol_info.step_size)
            quantities.append(float(rounded_qty))
        return quantities

    async def run(self) -> None:
        """Main loop: monitor positions, execute smart exits."""
        self._running = True
        group = "smart-executor"
        consumer = f"smart-exec-{uuid.uuid4().hex[:8]}"

        await self.redis.create_consumer_group("exit_signals", group)

        # Restore state
        await self._load_state()

        # Initialize exchange info cache for LOT_SIZE/PRICE_FILTER compliance
        symbols = self.config.get("symbols", ["BTC", "ETH", "SOL"])
        spot_cache = get_exchange_cache("spot")
        futures_cache = get_exchange_cache("futures")
        await spot_cache.refresh(symbols)
        await futures_cache.refresh(symbols)
        logger.info(f"ExchangeInfo loaded for {symbols}")

        logger.info("SmartExecutor started")

        # Start background tasks
        asyncio.create_task(self._price_monitor_loop())
        asyncio.create_task(self._exit_execution_loop())

        while self._running:
            try:
                # Consume exit signals
                messages = await self.redis.consume(
                    "exit_signals", group, consumer, count=10, block_ms=1000
                )

                for msg in messages:
                    await self._handle_exit_signal(msg)
                    await self.redis.ack("exit_signals", group, msg["_id"])

            except Exception as e:
                logger.error(f"SmartExecutor error: {e}")
                await asyncio.sleep(1)

    async def _load_state(self) -> None:
        """Load state from Redis."""
        try:
            # Load active exit plans
            data = await self.redis.hgetall("smart_exit:plans")
            for key, plan_json in data.items():
                try:
                    plan_dict = json.loads(plan_json)
                    self.active_exits[key] = ExitPlan(**plan_dict)
                except Exception as e:
                    logger.error(f"Failed to load exit plan for {key}: {e}")

            # Load high water marks
            data = await self.redis.hgetall("smart_exit:hwm")
            for symbol, hwm in data.items():
                self.high_water_marks[symbol] = float(hwm)

            logger.info(f"Loaded {len(self.active_exits)} active exits and {len(self.high_water_marks)} HWMs")
        except Exception as e:
            logger.error(f"Failed to load smart executor state: {e}")

    async def _save_exit_plan(self, key: str, plan: ExitPlan) -> None:
        """Save exit plan to Redis."""
        try:
            plan_json = json.dumps(asdict(plan))
            await self.redis.hset("smart_exit:plans", {key: plan_json})
        except Exception as e:
            logger.error(f"Failed to save exit plan: {e}")

    async def _remove_exit_plan(self, key: str) -> None:
        """Remove exit plan from Redis."""
        # Note: RedisStreams wrapper might not have hdel, check implementation
        # If not, we might need to add it or use raw client if exposed
        if hasattr(self.redis, "hdel"):
            await self.redis.hdel("smart_exit:plans", key)
        elif self.redis._client:
            await self.redis._client.hdel("smart_exit:plans", key)

    async def _save_hwm(self, symbol: str, price: float) -> None:
        """Save HWM to Redis."""
        try:
            await self.redis.hset("smart_exit:hwm", {symbol: str(price)})
        except Exception as e:
            logger.error(f"Failed to save HWM: {e}")

    async def _remove_hwm(self, symbol: str) -> None:
        """Remove HWM from Redis."""
        if self.redis._client:
            await self.redis._client.hdel("smart_exit:hwm", symbol)

    def stop(self) -> None:
        """Signal executor to stop."""
        self._running = False

    async def _price_monitor_loop(self) -> None:
        """Monitor prices and update volatility trackers."""
        group = "smart-executor-prices"
        consumer = f"price-mon-{uuid.uuid4().hex[:8]}"

        await self.redis.create_consumer_group("market:prices", group)

        while self._running:
            try:
                messages = await self.redis.consume(
                    "market:prices", group, consumer, count=50, block_ms=500
                )

                for msg in messages:
                    symbol = msg.get("symbol")
                    price = msg.get("price")

                    if symbol and price:
                        if symbol not in self.volatility_trackers:
                            self.volatility_trackers[symbol] = VolatilityTracker(
                                window=self.volatility_window
                            )
                        self.volatility_trackers[symbol].add_price(float(price))

                        # Also update high water mark for active positions
                        if symbol in self.high_water_marks:
                            await self.update_high_water_mark(symbol, float(price))

                    await self.redis.ack("market:prices", group, msg["_id"])

            except Exception as e:
                logger.error(f"Price monitor error: {e}")
                await asyncio.sleep(1)

    async def _exit_execution_loop(self) -> None:
        """Monitor active exits and manage ladder phases."""
        while self._running:
            try:
                await self._check_active_exits()
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Exit execution error: {e}")

    async def _handle_exit_signal(self, signal: dict) -> None:
        """Handle incoming exit signal from strategy."""
        symbol = signal.get("symbol")
        market = signal.get("market", "futures")
        quantity = float(signal.get("quantity", 0))
        trigger_price = float(signal.get("trigger_price", 0))
        strategy = signal.get("strategy", "unknown")
        reason = signal.get("reason", "")

        # Skip if exit already in progress for this symbol
        exit_key = f"{symbol}:{market}"
        if exit_key in self.active_exits:
            logger.debug(f"Exit already active for {symbol}, skipping duplicate signal")
            return

        logger.info(f"Received exit signal: {symbol} {quantity} @ {trigger_price}")

        # Get entry price from position for P&L calculation
        entry_price = 0.0
        position = await self.redis.get_position(symbol, market)
        if position:
            entry_price = float(position.get("entry_price", 0))

        # Create exit plan
        plan = ExitPlan(
            symbol=symbol,
            market=market,
            total_quantity=quantity,
            trigger_price=trigger_price,
            strategy=strategy,
            reason=reason,
            entry_price=entry_price,
        )

        # Start ladder execution
        await self._execute_ladder(plan)

        # Track active exit
        key = f"{symbol}:{market}"
        self.active_exits[key] = plan
        await self._save_exit_plan(key, plan)

    async def _execute_ladder(self, plan: ExitPlan) -> None:
        """Place limit order ladder."""
        prices = self._calculate_ladder_prices(plan.trigger_price, plan.symbol, plan.market)
        quantities = self._calculate_ladder_quantities(plan.total_quantity, plan.symbol, plan.market)

        for price, qty in zip(prices, quantities):
            # Skip tiers with zero quantity after rounding
            if qty <= 0:
                logger.warning(f"Skipping ladder tier: qty rounded to 0 @ {price}")
                continue

            try:
                result = await self.client.limit_order(
                    symbol=plan.symbol,
                    side="sell",
                    quantity=qty,
                    price=price,
                    market=plan.market,
                )
                plan.ladder_orders.append(result)
                logger.info(f"Placed ladder order: {qty} @ {price}")
            except Exception as e:
                logger.error(f"Ladder order failed: {e}")

    async def _check_active_exits(self) -> None:
        """Check status of active exit plans."""
        for key, plan in list(self.active_exits.items()):
            if plan.phase == "complete":
                continue

            elapsed = time.time() - plan.start_time

            # Check order fills
            filled = 0.0
            for order in plan.ladder_orders:
                try:
                    status = await self.client.get_order(
                        symbol=plan.symbol,
                        order_id=order["order_id"],
                        market=plan.market,
                    )
                    filled += status.get("filled_qty", 0)
                except Exception:
                    pass

            plan.filled_quantity = filled
            remaining = plan.total_quantity - filled

            # Check if complete
            if remaining <= 0:
                plan.phase = "complete"
                logger.info(f"Exit complete: {plan.symbol} all filled via ladder")
                # Publish trade notification BEFORE clearing position
                await self._publish_trade(plan, plan.total_quantity, plan.trigger_price)
                await self.redis.clear_position(plan.symbol, plan.market)
                del self.active_exits[key]
                await self._remove_exit_plan(key)
                continue

            # Phase 1 timeout: partial sweep for unfilled quantity
            if plan.phase == "ladder" and elapsed > self.phase1_timeout and remaining > 0:
                plan.phase = "sweep"
                logger.info(f"Phase 1 timeout: sweeping {remaining} {plan.symbol}")
                await self._sweep_remaining(plan, remaining)
                plan.phase = "complete"
                # Publish trade notification BEFORE clearing position
                await self._publish_trade(plan, plan.total_quantity, plan.trigger_price)
                await self.redis.clear_position(plan.symbol, plan.market)
                del self.active_exits[key]
                await self._remove_exit_plan(key)
                continue

            # Phase transition: sweep if max timeout
            if elapsed > self.max_execution_time and remaining > 0:
                await self._sweep_remaining(plan, remaining)
                plan.phase = "complete"
                # Publish trade notification BEFORE clearing position
                await self._publish_trade(plan, plan.total_quantity, plan.trigger_price)
                await self.redis.clear_position(plan.symbol, plan.market)
                del self.active_exits[key]
                await self._remove_exit_plan(key)
                continue

            # Save progress
            await self._save_exit_plan(key, plan)

    async def _sweep_remaining(self, plan: ExitPlan, remaining_qty: float) -> None:
        """Cancel unfilled orders and sweep with market order."""
        # Round quantity to step_size for LOT_SIZE compliance
        cache = get_exchange_cache(plan.market)
        symbol_info = cache.get(plan.symbol)
        rounded_qty = float(PriceUtils.round_down_to_step(remaining_qty, symbol_info.step_size))

        logger.info(f"Sweeping remaining {rounded_qty} {plan.symbol} (raw: {remaining_qty})")

        if rounded_qty <= 0:
            logger.warning(f"Sweep cancelled: qty rounded to 0 for {plan.symbol}")
            return

        # Cancel unfilled orders
        for order in plan.ladder_orders:
            try:
                await self.client.cancel_order(
                    symbol=plan.symbol,
                    order_id=order["order_id"],
                    market=plan.market,
                )
            except Exception:
                pass  # Order may already be filled/canceled

        # Market sweep
        try:
            result = await self.client.market_order(
                symbol=plan.symbol,
                side="sell",
                quantity=rounded_qty,
                market=plan.market,
            )
            logger.info(f"Sweep complete: {result}")
        except Exception as e:
            logger.error(f"Sweep failed: {e}")

    async def _publish_trade(self, plan: ExitPlan, filled_qty: float, avg_price: float) -> None:
        """Publish completed exit trade to trades stream for Telegram notification."""
        # Calculate P&L
        pnl = 0.0
        pnl_pct = 0.0
        if plan.entry_price > 0:
            pnl = (avg_price - plan.entry_price) * filled_qty
            pnl_pct = ((avg_price - plan.entry_price) / plan.entry_price * 100)

        trade = {
            "order_id": str(int(time.time() * 1000)),
            "symbol": plan.symbol,
            "side": "sell",
            "market": plan.market,
            "quantity": str(filled_qty),
            "price": str(avg_price),
            "strategy": plan.strategy,
            "timestamp": str(int(time.time() * 1000)),
            "reason": plan.reason,
            "profit": str(pnl),
            "profit_pct": str(pnl_pct),
        }

        await self.redis.publish("trades", trade)
        logger.info(f"Published exit trade: {plan.symbol} SELL {filled_qty} @ {avg_price} (P&L: {pnl:+.2f})")
