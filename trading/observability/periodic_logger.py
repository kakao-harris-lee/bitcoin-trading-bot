# trading/observability/periodic_logger.py
"""Periodic system state logger for observability."""
from __future__ import annotations

# pylint: disable=logging-fstring-interpolation,broad-exception-caught,protected-access

import asyncio
import logging
from datetime import datetime
from typing import Any

from trading.streams import RedisStreams

logger = logging.getLogger(__name__)


class PeriodicLoggerTask:
    """Logs system state (OHLCV, positions, decisions) at regular intervals.

    Provides visibility into:
    - Current prices and OHLCV data for each symbol
    - Active positions and their P&L
    - Recent strategy decisions
    - Risk state (kill switch, daily P&L)

    Usage:
        periodic_logger = PeriodicLoggerTask(
            redis=redis_streams,
            symbols=["BTC", "ETH"],
            interval_seconds=300,  # 5 minutes
        )
        asyncio.create_task(periodic_logger.run())
    """

    STREAM_NAME = "observability:system:state"

    def __init__(
        self,
        redis: RedisStreams,
        symbols: list[str],
        interval_seconds: int = 300,
    ):
        """Initialize the periodic logger.

        Args:
            redis: RedisStreams instance.
            symbols: List of trading symbols to monitor.
            interval_seconds: Logging interval (default: 300 = 5 minutes).
        """
        self.redis = redis
        self.symbols = symbols
        self.interval_seconds = interval_seconds
        self._running = False

    async def run(self) -> None:
        """Main loop: log system state at regular intervals."""
        self._running = True
        logger.info(
            f"PeriodicLoggerTask started (interval={self.interval_seconds}s, "
            f"symbols={self.symbols})"
        )

        while self._running:
            try:
                await self._log_system_state()
            except Exception as e:
                logger.error(f"Error in periodic logger: {e}")

            await asyncio.sleep(self.interval_seconds)

    async def stop(self) -> None:
        """Stop the periodic logger."""
        self._running = False
        logger.info("PeriodicLoggerTask stopped")

    async def _log_system_state(self) -> None:
        """Collect and log current system state."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Collect data
        prices = await self._get_latest_prices()
        positions = await self._get_positions()
        decisions = await self._get_recent_decisions()
        risk = await self.redis.get_risk()

        # Build log output
        lines = [
            "",
            "=" * 70,
            f"  SYSTEM STATE - {timestamp}",
            "=" * 70,
        ]

        # Risk state
        mode = risk.get("mode", "unknown")
        kill_switch = risk.get("kill_switch", "false") == "true"
        blocked = risk.get("blocked", "false") == "true"
        daily_pnl = float(risk.get("daily_pnl", "0"))

        lines.append(f"  Mode: {mode.upper()} | Kill Switch: {'ON' if kill_switch else 'OFF'} | "
                     f"Blocked: {'YES' if blocked else 'NO'} | Daily P&L: ${daily_pnl:,.2f}")
        lines.append("-" * 70)

        # Prices and OHLCV
        lines.append("  MARKET DATA:")
        for symbol in self.symbols:
            price_data = prices.get(symbol, {})
            if price_data:
                price = float(price_data.get("price", 0))
                high = float(price_data.get("high", price))
                low = float(price_data.get("low", price))
                volume = float(price_data.get("volume", 0))
                lines.append(
                    f"    {symbol}: ${price:,.2f} | "
                    f"H: ${high:,.2f} | L: ${low:,.2f} | "
                    f"Vol: {volume:,.0f}"
                )
            else:
                lines.append(f"    {symbol}: No data")

        lines.append("-" * 70)

        # Positions
        lines.append("  POSITIONS:")
        has_positions = False
        for symbol in self.symbols:
            pos = positions.get(symbol, {})
            if pos and pos.get("quantity") and float(pos.get("quantity", 0)) != 0:
                has_positions = True
                qty = float(pos.get("quantity", 0))
                entry_price = float(pos.get("entry_price", 0))
                current_price = float(prices.get(symbol, {}).get("price", entry_price))
                strategy = pos.get("strategy", "unknown")

                # Calculate P&L
                if entry_price > 0:
                    pnl = (current_price - entry_price) * qty
                    pnl_pct = ((current_price / entry_price) - 1) * 100
                else:
                    pnl = 0
                    pnl_pct = 0

                lines.append(
                    f"    {symbol}: {qty:.6f} @ ${entry_price:,.2f} | "
                    f"P&L: ${pnl:,.2f} ({pnl_pct:+.2f}%) | "
                    f"Strategy: {strategy}"
                )

        if not has_positions:
            lines.append("    No active positions")

        lines.append("-" * 70)

        # Recent decisions
        lines.append("  RECENT DECISIONS:")
        if decisions:
            # Group by symbol, show most recent per symbol
            symbol_decisions: dict[str, dict] = {}
            for dec in decisions[:20]:  # Look at recent 20
                sym = dec.get("symbol", "")
                if sym not in symbol_decisions:
                    symbol_decisions[sym] = dec

            for symbol in self.symbols:
                dec = symbol_decisions.get(symbol)
                if dec:
                    decision = dec.get("decision", "UNKNOWN")
                    strategy = dec.get("strategy", "unknown")
                    mfi = dec.get("mfi", "?")
                    adx = dec.get("adx", "?")
                    regime = dec.get("regime", "?")
                    reason = dec.get("reason", "")
                    # Truncate reason if too long
                    if len(reason) > 40:
                        reason = reason[:37] + "..."
                    lines.append(
                        f"    {symbol} [{strategy}]: {decision} | "
                        f"MFI={mfi} ADX={adx} | {regime}"
                    )
                else:
                    lines.append(f"    {symbol}: No recent decisions")
        else:
            lines.append("    No decisions recorded yet")

        lines.append("=" * 70)
        lines.append("")

        # Log to console
        logger.info("\n".join(lines))

        # Also publish to Redis stream for dashboard access
        await self._publish_state_event(timestamp, prices, positions, risk)

    async def _get_latest_prices(self) -> dict[str, dict[str, Any]]:
        """Get latest prices from market:prices stream."""
        prices: dict[str, dict[str, Any]] = {}

        try:
            # Read last 50 entries to find latest for each symbol
            entries = await self.redis._client.xrevrange("market:prices", count=50)

            for _, data in entries:
                symbol = data.get("symbol", "")
                if symbol and symbol not in prices:
                    prices[symbol] = data

        except Exception as e:
            logger.error(f"Error getting latest prices: {e}")

        return prices

    async def _get_positions(self) -> dict[str, dict[str, str]]:
        """Get current positions for all symbols."""
        positions: dict[str, dict[str, str]] = {}

        for symbol in self.symbols:
            try:
                pos = await self.redis.get_position(symbol, "futures")
                if pos:
                    positions[symbol] = pos
            except Exception as e:
                logger.error(f"Error getting position for {symbol}: {e}")

        return positions

    async def _get_recent_decisions(self) -> list[dict[str, str]]:
        """Get recent strategy decisions from stream."""
        try:
            entries = await self.redis._client.xrevrange("strategy:decisions", count=20)
            return [data for _, data in entries]
        except Exception as e:
            logger.error(f"Error getting recent decisions: {e}")
            return []

    async def _publish_state_event(
        self,
        timestamp: str,
        prices: dict[str, dict[str, Any]],
        positions: dict[str, dict[str, str]],
        risk: dict[str, str],
    ) -> None:
        """Publish state summary to Redis stream for dashboard access."""
        try:
            # Build summary for each symbol
            for symbol in self.symbols:
                price_data = prices.get(symbol, {})
                pos_data = positions.get(symbol, {})

                event_data = {
                    "timestamp": timestamp,
                    "symbol": symbol,
                    "price": price_data.get("price", "0"),
                    "high": price_data.get("high", "0"),
                    "low": price_data.get("low", "0"),
                    "volume": price_data.get("volume", "0"),
                    "position_qty": pos_data.get("quantity", "0"),
                    "position_entry": pos_data.get("entry_price", "0"),
                    "position_strategy": pos_data.get("strategy", ""),
                    "mode": risk.get("mode", "unknown"),
                    "kill_switch": risk.get("kill_switch", "false"),
                    "daily_pnl": risk.get("daily_pnl", "0"),
                }

                await self.redis._client.xadd(
                    self.STREAM_NAME,
                    event_data,
                    maxlen=1000,  # Keep ~3 days at 5-min intervals
                )

        except Exception as e:
            logger.error(f"Error publishing state event: {e}")
