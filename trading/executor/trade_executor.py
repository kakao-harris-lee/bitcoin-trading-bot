"""
Trade Executor - Consumes signals and executes trades

Responsibilities:
- Consume signals from all strategy streams
- Apply risk controls (kill switch, daily limits)
- Route to correct exchange adapter
- Execute trades (paper or live)
- Send notifications
"""

import asyncio
import logging
from datetime import datetime
from typing import Dict, Any, Optional, List

from .risk_controls import RiskControls

logger = logging.getLogger(__name__)


class TradeExecutor:
    """Consumes signals from all strategies and executes trades."""

    SIGNAL_STREAMS = [
        "signals:v35",
        "signals:short_v1",
        "signals:sideways_v2",
        "signals:h4",
    ]

    # Strategy to exchange mapping
    STRATEGY_EXCHANGE = {
        "v35": "upbit",
        "sideways_v2": "upbit",
        "h4": "upbit",
        "short_v1": "binance",
    }

    def __init__(
        self,
        redis_client,
        upbit_adapter,
        binance_adapter,
        config,
        notifier=None
    ):
        """
        Args:
            redis_client: RedisClient instance
            upbit_adapter: Upbit exchange adapter
            binance_adapter: Binance exchange adapter
            config: Configuration
            notifier: Optional TelegramNotifier
        """
        self.redis = redis_client
        self.upbit = upbit_adapter
        self.binance = binance_adapter
        self.config = config
        self.notifier = notifier
        self.running = True
        self.logger = logging.getLogger("executor")

        # Risk controls
        self.risk = RiskControls(config)

        # Trading modes
        self.upbit_mode = getattr(config, 'upbit_mode', 'paper')
        self.binance_mode = getattr(config, 'binance_mode', 'paper')

        # Position tracking per strategy
        self._positions: Dict[str, Dict] = {}

    async def run(self):
        """Main loop - consume all signal streams."""
        self.logger.info("Starting trade executor...")

        # Create consumer group
        group_name = "executor"
        for stream in self.SIGNAL_STREAMS:
            await self.redis.create_consumer_group(stream, group_name, start_id="$")

        while self.running:
            try:
                # Consume from all signal streams
                for stream in self.SIGNAL_STREAMS:
                    messages = await self.redis.consume(
                        stream_name=stream,
                        group_name=group_name,
                        consumer_name="main",
                        count=10,
                        block=100,  # Short block to cycle through streams
                    )

                    for msg in messages:
                        await self.process_signal(msg)
                        await self.redis.ack(stream, group_name, msg["id"])

                # Small delay between cycles
                await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Executor error: {e}", exc_info=True)
                await asyncio.sleep(1)

        self.logger.info("Trade executor stopped")

    async def process_signal(self, msg: Dict):
        """Process a single signal message."""
        stream = msg.get("stream", "")
        signal = msg.get("data", {})

        # Extract strategy name from stream
        strategy = stream.split(":")[1] if ":" in stream else "unknown"

        self.logger.info(f"Processing signal from {strategy}: {signal.get('action')} @ {signal.get('price')}")

        # Risk check
        if not self.risk.allow_trade(strategy, signal):
            self.logger.warning(f"Signal blocked by risk controls: {strategy}")
            return

        # Route to exchange
        exchange = self.STRATEGY_EXCHANGE.get(strategy, "upbit")

        try:
            if exchange == "upbit":
                await self._execute_upbit(strategy, signal)
            elif exchange == "binance":
                await self._execute_binance(strategy, signal)

            # Notify
            if self.notifier:
                await self._notify_trade(strategy, signal)

        except Exception as e:
            self.logger.error(f"Execution error for {strategy}: {e}", exc_info=True)

    async def _execute_upbit(self, strategy: str, signal: Dict):
        """Execute trade on Upbit."""
        action = signal.get("action")
        price = signal.get("price", 0)
        size = signal.get("size", 0)

        if self.upbit_mode == "paper":
            self.logger.info(f"[PAPER] Upbit {action}: {size} @ {price}")
            # Update paper position
            self._update_paper_position(strategy, action, price, size)
        else:
            # Live execution
            if action == "buy":
                await self.upbit.buy(size=size, price=price)
            elif action in ["sell", "close"]:
                await self.upbit.sell(size=size, price=price)

    def _has_active_binance_position(self, exclude_strategy: str) -> bool:
        """Check if any other strategy has an active Binance position."""
        binance_strategies = ["short_v1"]
        for strat in binance_strategies:
            if strat == exclude_strategy:
                continue
            pos = self._positions.get(strat, {})
            if pos.get("active"):
                return True
        return False

    async def _execute_binance(self, strategy: str, signal: Dict):
        """Execute trade on Binance."""
        action = signal.get("action")
        price = signal.get("price", 0)
        size = signal.get("size", 0)

        # Guard: Prevent conflicting positions
        # Only check for entry actions (short), not exits (close/cover)
        if action in ["short", "buy"]:
            if self._has_active_binance_position(exclude_strategy=strategy):
                conflicting = [s for s in ["short_v1"]
                              if s != strategy and self._positions.get(s, {}).get("active")]
                self.logger.warning(
                    f"[GUARD] {strategy} entry blocked: {conflicting} has active Binance position"
                )
                return

        if self.binance_mode == "paper":
            self.logger.info(f"[PAPER] Binance {action}: {size} @ {price}")
            self._update_paper_position(strategy, action, price, size)
        else:
            # Live execution (short strategy)
            if action == "short":
                await self.binance.open_short(size=size, price=price)
            elif action in ["close", "cover"]:
                await self.binance.close_short(size=size, price=price)

    def _update_paper_position(self, strategy: str, action: str, price: float, size: float):
        """Update paper trading position."""
        if action in ["buy", "short"]:
            self._positions[strategy] = {
                "active": True,
                "entry_price": price,
                "size": size,
                "entry_time": datetime.now(),
            }
        elif action in ["sell", "close", "cover"]:
            pos = self._positions.get(strategy, {})
            if pos.get("active"):
                entry = pos.get("entry_price", price)
                pnl_pct = ((price - entry) / entry) * 100
                if action in ["cover"]:  # Short position
                    pnl_pct = -pnl_pct
                self.risk.record_pnl(strategy, pnl_pct)
            self._positions[strategy] = {"active": False}

    async def _notify_trade(self, strategy: str, signal: Dict):
        """Send trade notification."""
        if not self.notifier:
            return

        action = signal.get("action", "?")
        price = signal.get("price", 0)
        reason = signal.get("reason", "")

        message = f"[{strategy.upper()}] {action.upper()} @ {price:,.0f}\n{reason}"
        await self.notifier.send_message(message)

    def stop(self):
        """Stop the executor gracefully."""
        self.running = False
