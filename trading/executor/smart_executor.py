# trading/executor/smart_executor.py
"""Smart executor for optimized exit execution."""
from __future__ import annotations
import asyncio
import logging
import time
import uuid
from typing import Any, TYPE_CHECKING
from dataclasses import dataclass, field

from trading.strategies.volatility_tracker import VolatilityTracker

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

    def _calculate_ladder_prices(self, base_price: float) -> list[float]:
        """Calculate limit prices for ladder tiers."""
        prices = []
        for tier_pct in self.ladder_tiers:
            price = base_price * (1 + tier_pct / 100)
            prices.append(round(price, 2))
        return prices

    def _calculate_ladder_quantities(self, total_qty: float) -> list[float]:
        """Calculate quantity for each ladder tier."""
        quantities = []
        for weight in self.ladder_weights:
            qty = total_qty * weight
            quantities.append(round(qty, 8))
        return quantities

    async def run(self) -> None:
        """Main loop: monitor positions, execute smart exits."""
        self._running = True
        group = "smart-executor"
        consumer = f"smart-exec-{uuid.uuid4().hex[:8]}"

        await self.redis.create_consumer_group("exit_signals", group)

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

    def stop(self) -> None:
        """Signal executor to stop."""
        self._running = False

    async def _price_monitor_loop(self) -> None:
        """Monitor prices and update volatility trackers."""
        while self._running:
            try:
                # Read recent prices from market:prices stream
                # Update volatility trackers
                await asyncio.sleep(1)
            except Exception as e:
                logger.error(f"Price monitor error: {e}")

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
        market = signal.get("market", "spot")
        quantity = float(signal.get("quantity", 0))
        trigger_price = float(signal.get("trigger_price", 0))
        strategy = signal.get("strategy", "unknown")

        logger.info(f"Received exit signal: {symbol} {quantity} @ {trigger_price}")

        # Create exit plan
        plan = ExitPlan(
            symbol=symbol,
            market=market,
            total_quantity=quantity,
            trigger_price=trigger_price,
            strategy=strategy,
        )

        # Start ladder execution
        await self._execute_ladder(plan)

        # Track active exit
        self.active_exits[f"{symbol}:{market}"] = plan

    async def _execute_ladder(self, plan: ExitPlan) -> None:
        """Place limit order ladder."""
        prices = self._calculate_ladder_prices(plan.trigger_price)
        quantities = self._calculate_ladder_quantities(plan.total_quantity)

        for price, qty in zip(prices, quantities):
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
                del self.active_exits[key]
                continue

            # Phase transition: sweep if timeout
            if elapsed > self.max_execution_time and remaining > 0:
                await self._sweep_remaining(plan, remaining)
                plan.phase = "complete"
                del self.active_exits[key]

    async def _sweep_remaining(self, plan: ExitPlan, remaining_qty: float) -> None:
        """Cancel unfilled orders and sweep with market order."""
        logger.info(f"Sweeping remaining {remaining_qty} {plan.symbol}")

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
                quantity=remaining_qty,
                market=plan.market,
            )
            logger.info(f"Sweep complete: {result}")
        except Exception as e:
            logger.error(f"Sweep failed: {e}")
