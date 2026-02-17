# trading/notification/telegram_task.py
"""Async Telegram task for stream-based notifications and commands."""
from __future__ import annotations

# pylint: disable=logging-fstring-interpolation,broad-exception-caught,protected-access

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path

import aiohttp
import pyotp
import pytz
from dotenv import load_dotenv

from trading.streams import RedisStreams

logger = logging.getLogger(__name__)


class TelegramTask:
    """Async Telegram notification and command handler.

    Subscribes to:
    - `trades` stream for trade execution notifications
    - `alerts` stream for system alerts

    Handles commands:
    - /kill_on: Enable kill switch
    - /kill_off: Disable kill switch
    - /info: Show current status
    """

    CONSUMER_GROUP = "telegram"
    CONSUMER_NAME = "telegram-1"

    # Rate limiting settings
    MIN_MESSAGE_INTERVAL = 5  # Minimum seconds between messages
    ALERT_COOLDOWN = 60  # Cooldown for same alert type (seconds)

    def __init__(self, redis: RedisStreams):
        """Initialize Telegram task.

        Args:
            redis: RedisStreams instance for pub/sub
        """
        # Load env
        project_root = Path(__file__).parent.parent.parent
        load_dotenv(project_root / ".env")

        self.bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
        self.chat_id = os.getenv("TELEGRAM_CHAT_ID")

        if not self.bot_token or not self.chat_id:
            raise ValueError("TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID must be set")

        self.api_url = f"https://api.telegram.org/bot{self.bot_token}"
        self.redis = redis
        self.utc = pytz.UTC
        self._running = False
        self._last_update_id = 0

        # Rate limiting state
        self._last_message_time = 0
        self._last_alert_times: dict[str, float] = {}  # alert_key -> timestamp

    async def run(self) -> None:
        """Main loop: consume streams and poll for commands."""
        self._running = True
        logger.info("TelegramTask started")

        # Create consumer groups
        await self.redis.create_consumer_group("trades", self.CONSUMER_GROUP, "$")
        await self.redis.create_consumer_group("alerts", self.CONSUMER_GROUP, "$")

        # Run both loops concurrently
        await asyncio.gather(
            self._consume_trades(),
            self._consume_alerts(),
            self._poll_commands(),
        )

    def stop(self) -> None:
        """Stop the task."""
        self._running = False

    async def _consume_trades(self) -> None:
        """Consume trade notifications from trades stream."""
        while self._running:
            try:
                messages = await self.redis.consume(
                    "trades",
                    self.CONSUMER_GROUP,
                    self.CONSUMER_NAME,
                    count=10,
                    block_ms=1000,
                )

                for msg in messages:
                    await self._handle_trade(msg)
                    await self.redis.ack("trades", self.CONSUMER_GROUP, msg["_id"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error consuming trades: {e}")
                await asyncio.sleep(1)

    async def _consume_alerts(self) -> None:
        """Consume system alerts from alerts stream."""
        while self._running:
            try:
                messages = await self.redis.consume(
                    "alerts",
                    self.CONSUMER_GROUP,
                    self.CONSUMER_NAME,
                    count=10,
                    block_ms=1000,
                )

                for msg in messages:
                    await self._handle_alert(msg)
                    await self.redis.ack("alerts", self.CONSUMER_GROUP, msg["_id"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error consuming alerts: {e}")
                await asyncio.sleep(1)

    async def _poll_commands(self) -> None:
        """Poll for Telegram commands."""
        while self._running:
            try:
                updates = await self._get_updates()

                for update in updates:
                    await self._handle_update(update)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error polling commands: {e}")
                await asyncio.sleep(5)

    async def _get_updates(self, timeout: int = 30) -> list[dict]:
        """Get updates from Telegram API.

        Args:
            timeout: Long polling timeout in seconds

        Returns:
            List of update objects
        """
        url = f"{self.api_url}/getUpdates"
        params = {
            "offset": self._last_update_id + 1,
            "timeout": timeout,
            "allowed_updates": ["message"],
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(url, params=params, timeout=aiohttp.ClientTimeout(total=timeout + 5)) as resp:
                    if resp.status != 200:
                        return []
                    data = await resp.json()
                    return data.get("result", []) if data.get("ok") else []
        except asyncio.TimeoutError:
            return []

    async def _handle_update(self, update: dict) -> None:
        """Handle a Telegram update.

        Args:
            update: Telegram update object
        """
        self._last_update_id = update.get("update_id", 0)

        message = update.get("message")
        if not message:
            return

        # Verify chat ID
        chat_id = str(message.get("chat", {}).get("id", ""))
        if chat_id != self.chat_id:
            logger.warning(f"Unauthorized chat_id: {chat_id}")
            return

        text = message.get("text", "").strip()
        if not text.startswith("/"):
            return

        # Parse command
        parts = text.split(maxsplit=1)
        command = parts[0][1:]  # Remove /
        args = parts[1] if len(parts) > 1 else ""

        logger.info(f"Command received: /{command} {args}")

        # Handle commands
        if command == "kill_on":
            await self._cmd_kill_on()
        elif command == "kill_off":
            await self._cmd_kill_off()
        elif command == "info":
            await self._cmd_info()
        elif command == "dashboard":
            await self._cmd_dashboard()
        elif command == "help":
            await self._cmd_help()
        else:
            await self._send_message(f"Unknown command: /{command}\n\nUse /help for available commands.", bypass_rate_limit=True)

    async def _cmd_kill_on(self) -> None:
        """Handle /kill_on command - enable kill switch."""
        risk = await self.redis.get_risk()
        risk["kill_switch"] = "true"
        await self.redis.set_risk(risk)

        await self._send_message("*Kill Switch: ON*\n\nTrading is now DISABLED. Use /kill_off to re-enable.", bypass_rate_limit=True)

    async def _cmd_kill_off(self) -> None:
        """Handle /kill_off command - disable kill switch."""
        risk = await self.redis.get_risk()
        risk["kill_switch"] = "false"
        await self.redis.set_risk(risk)

        await self._send_message("*Kill Switch: OFF*\n\nTrading is now ENABLED.", bypass_rate_limit=True)

    async def _cmd_info(self) -> None:
        """Handle /info command - show market status and latest signals."""
        risk = await self.redis.get_risk()

        daily_pnl = float(risk.get("daily_pnl", 0))
        blocked = risk.get("blocked", "false")
        blocked_text = " (BLOCKED)" if blocked == "true" else ""

        prices = await self._get_latest_prices()
        signals_by_symbol = await self._get_latest_signals()
        positions_text = await self._get_positions_text()
        market_text = self._format_prices_text(prices)
        signal_text = self._format_signals_text(signals_by_symbol)

        message = f"""*System Status*

*Daily P&L:* ${daily_pnl:+,.2f}{blocked_text}

*Market Snapshot:*{market_text}

*Latest Signals:*{signal_text}

*Active Positions:*{positions_text}

_Updated: {datetime.now(self.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC_
"""
        await self._send_message(message, bypass_rate_limit=True)

    async def _get_latest_prices(self) -> dict[str, float]:
        prices: dict[str, float] = {}
        try:
            entries = await self.redis._client.xrevrange("market:prices", count=100)
            for _, data in entries:
                symbol = data.get("symbol")
                price_raw = data.get("price")
                if symbol in ("BTC", "ETH", "SOL") and symbol not in prices and price_raw:
                    prices[symbol] = float(price_raw)
        except Exception:
            return {}
        return prices

    async def _get_latest_signals(self) -> dict[str, str]:
        signals_by_symbol: dict[str, str] = {}
        try:
            entries = await self.redis._client.xrevrange("strategy:decisions", count=200)
            for _, data in entries:
                symbol = data.get("symbol", "")
                if symbol in ("BTC", "ETH", "SOL") and symbol not in signals_by_symbol:
                    decision = (data.get("decision") or "WAIT").upper()
                    regime = data.get("regime", "UNKNOWN")
                    strategy = data.get("strategy", "unknown")
                    signals_by_symbol[symbol] = f"{decision} | {regime} ({strategy})"
                if len(signals_by_symbol) == 3:
                    break
        except Exception:
            return {}
        return signals_by_symbol

    async def _get_positions_text(self) -> str:
        text = ""
        for symbol in ("BTC", "ETH", "SOL"):
            for market in ("spot", "futures"):
                pos = await self.redis.get_position(symbol, market)
                if pos and pos.get("quantity"):
                    qty = float(pos.get("quantity", 0))
                    entry = float(pos.get("entry_price", 0))
                    strategy = pos.get("strategy", "unknown")
                    text += f"\n  {symbol} {market}: {qty:.4f} @ ${entry:,.2f} ({strategy})"
        return text or "\n  None"

    def _format_prices_text(self, prices: dict[str, float]) -> str:
        text = ""
        for symbol in ("BTC", "ETH", "SOL"):
            if symbol in prices:
                text += f"\n  {symbol}: ${prices[symbol]:,.2f}"
        return text or "\n  No recent price data"

    def _format_signals_text(self, signals_by_symbol: dict[str, str]) -> str:
        text = ""
        for symbol in ("BTC", "ETH", "SOL"):
            if symbol in signals_by_symbol:
                text += f"\n  {symbol}: {signals_by_symbol[symbol]}"
        return text or "\n  No recent strategy signals"

    async def _cmd_dashboard(self) -> None:
        """Handle /dashboard command - show TOTP code for dashboard access."""
        totp_secret = os.getenv("DASHBOARD_TOTP_SECRET")
        if not totp_secret:
            await self._send_message("⚠️ DASHBOARD_TOTP_SECRET not configured in .env", bypass_rate_limit=True)
            return

        totp = pyotp.TOTP(totp_secret, interval=30)
        current_code = totp.now()

        domain = os.getenv("DASHBOARD_DOMAIN", "localhost")
        port = os.getenv("DASHBOARD_PORT", "5080")
        scheme = "http" if domain in ("localhost", "127.0.0.1") else "https"

        message = f"""🖥️ *Dashboard Access*

🔗 URL: `{scheme}://{domain}:{port}/btc-dashboard`
🔐 TOTP: `{current_code}`

_Code valid for ~30 seconds_
"""
        await self._send_message(message, bypass_rate_limit=True)

    async def _cmd_help(self) -> None:
        """Handle /help command."""
        message = """*Available Commands*

/info - Show current status
/dashboard - Get dashboard TOTP code
/kill_on - Enable kill switch (stop trading)
/kill_off - Disable kill switch (resume trading)
/help - Show this message
"""
        await self._send_message(message, bypass_rate_limit=True)

    async def _handle_trade(self, trade: dict) -> None:
        """Handle trade notification.

        Args:
            trade: Trade data from trades stream
        """
        symbol = trade.get("symbol", "?")
        side = trade.get("side", "?")
        market = trade.get("market", "?")
        quantity = float(trade.get("quantity", 0))
        price = float(trade.get("price", 0))
        strategy = trade.get("strategy", "?")
        pnl = trade.get("pnl")

        if side.lower() == "buy":
            emoji = ""
            action = "BOUGHT"
        else:
            emoji = ""
            action = "SOLD"

        message = f"""{emoji} *Trade Executed*

*{action}* {quantity:.4f} {symbol}
*Market:* {market.upper()}
*Price:* ${price:,.2f}
*Value:* ${quantity * price:,.2f}
*Strategy:* {strategy}
"""

        if pnl is not None:
            pnl_val = float(pnl)
            pnl_emoji = "" if pnl_val >= 0 else ""
            message += f"\n{pnl_emoji} *P&L:* ${pnl_val:+,.2f}"

        await self._send_message(message)

    async def _handle_alert(self, alert: dict) -> None:
        """Handle system alert.

        Args:
            alert: Alert data from alerts stream

        Handles two formats:
        1. Executor format: {"type": "order_rejected", "symbol": "BTC", "reason": "..."}
        2. Generic format: {"level": "error", "component": "system", "message": "..."}
        """
        alert_type = alert.get("type")

        # Handle executor alert format
        if alert_type:
            # Skip pnl_realized - already shown in trade notification
            if alert_type == "pnl_realized":
                return

            # Rate limit by alert type + symbol
            alert_key = f"{alert_type}:{alert.get('symbol', 'unknown')}"
            if not self._should_send_alert(alert_key):
                logger.debug(f"Alert rate limited: {alert_key}")
                return

            if alert_type == "order_rejected":
                symbol = alert.get("symbol", "?")
                reason = alert.get("reason", "Unknown reason")
                message = f"""⚠️ *Order Rejected*

*Symbol:* {symbol}
*Reason:* {reason}

_Time: {datetime.now(self.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC_
"""
            else:
                # Unknown executor alert type
                message = f"""ℹ️ *Alert: {alert_type}*

{', '.join(f'{k}: {v}' for k, v in alert.items() if k not in ['type', 'timestamp', '_id'])}

_Time: {datetime.now(self.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC_
"""
        else:
            # Handle generic alert format
            level = alert.get("level", "info").upper()
            component = alert.get("component", "system")
            message_text = alert.get("message", "No message")

            # Rate limit by level + component
            alert_key = f"{level}:{component}"
            if not self._should_send_alert(alert_key):
                logger.debug(f"Alert rate limited: {alert_key}")
                return

            if level == "CRITICAL":
                emoji = "🚨"
            elif level == "ERROR":
                emoji = "❌"
            elif level == "WARNING":
                emoji = "⚠️"
            else:
                emoji = "ℹ️"

            message = f"""{emoji} *{level}*

*Component:* {component}
*Message:* {message_text}

_Time: {datetime.now(self.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC_
"""
        await self._send_message(message)

    def _should_send_alert(self, alert_key: str) -> bool:
        """Check if alert should be sent (rate limiting).

        Args:
            alert_key: Unique key for this alert type

        Returns:
            True if alert should be sent
        """
        now = time.time()
        last_time = self._last_alert_times.get(alert_key, 0)

        if now - last_time < self.ALERT_COOLDOWN:
            return False

        self._last_alert_times[alert_key] = now
        return True

    async def _send_message(self, message: str, bypass_rate_limit: bool = False) -> bool:
        """Send message to Telegram with rate limiting.

        Args:
            message: Message text (supports Markdown)
            bypass_rate_limit: Skip rate limiting (for command responses)

        Returns:
            True if sent successfully
        """
        # Global rate limiting (except for command responses)
        if not bypass_rate_limit:
            now = time.time()
            if now - self._last_message_time < self.MIN_MESSAGE_INTERVAL:
                logger.debug("Message rate limited (global)")
                return False
            self._last_message_time = now

        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 400:
                        # Retry without markdown on parse error
                        payload.pop("parse_mode", None)
                        async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as retry_resp:
                            return 200 <= retry_resp.status < 300
                    return 200 <= resp.status < 300
        except Exception as e:
            logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def send_start_notification(self, mode: str, symbols: list[str]) -> None:
        """Send bot start notification.

        Args:
            mode: Trading mode (paper/live)
            symbols: List of enabled symbols
        """
        mode_emoji = "" if mode == "paper" else ""
        symbols_text = ", ".join(symbols)

        message = f"""{mode_emoji} *Trading Bot Started*

*Mode:* {mode.upper()}
*Symbols:* {symbols_text}
*Time:* {datetime.now(self.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC

_Use /info for status, /help for commands_
"""
        await self._send_message(message)
