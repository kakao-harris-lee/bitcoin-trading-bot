# trading/notification/telegram_task.py
"""Async Telegram task for stream-based notifications and commands."""
from __future__ import annotations

# pylint: disable=logging-fstring-interpolation,broad-exception-caught,protected-access

import asyncio
import json
import logging
import os
import socket
import time
from datetime import datetime
from pathlib import Path

import aiohttp
import pyotp
import pytz
from dotenv import load_dotenv

from trading.core.runtime_defaults import load_allocation_symbols
from trading.streams import RedisStreams

logger = logging.getLogger(__name__)


class _TransientTelegramError(Exception):
    """Retryable Telegram transport error."""


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
    SELECTOR_NORMAL_COOLDOWN = 900  # 15m for normal selector changes
    SELECTOR_ANOMALY_COOLDOWN = 180  # 3m for selector anomalies
    SELECTOR_NEW_CANDIDATE_COOLDOWN = 1800  # 30m for repeated NEW_CANDIDATE updates
    SELECTOR_DQ_ALERT_COOLDOWN = 900  # 15m for persistent dq/liquidity degradation
    SELECTOR_MIN_CHURN = 4
    SELECTOR_MIN_CHURN_RATIO = 0.25
    SELECTOR_DQ_WARN_RATIO = 0.30
    SELECTOR_DQ_CRIT_RATIO = 0.60
    SELECTOR_LOW_SELECTED_RATIO = 0.40
    SYSTEM_ALERT_LEVELS = {
        "INFO": 10,
        "WARNING": 20,
        "ERROR": 30,
        "CRITICAL": 40,
        "NONE": 100,
    }

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
        self.symbols = tuple(load_allocation_symbols(default=("BTC", "ETH", "SOL", "BNB")))
        self._running = False
        self._last_update_id = 0

        # Rate limiting state
        self._last_message_time = 0
        self._last_alert_times: dict[str, float] = {}  # alert_key -> timestamp
        self._selector_last_sent: dict[str, float] = {}
        self._selector_last_snapshot: dict[str, dict[str, object]] = {}

        # Selector notification policy
        self._selector_normal_cooldown = self._env_int(
            "TELEGRAM_SELECTOR_NORMAL_COOLDOWN_SEC",
            self.SELECTOR_NORMAL_COOLDOWN,
            minimum=0,
        )
        self._selector_anomaly_cooldown = self._env_int(
            "TELEGRAM_SELECTOR_ANOMALY_COOLDOWN_SEC",
            self.SELECTOR_ANOMALY_COOLDOWN,
            minimum=0,
        )
        self._selector_new_candidate_cooldown = self._env_int(
            "TELEGRAM_SELECTOR_NEW_CANDIDATE_COOLDOWN_SEC",
            self.SELECTOR_NEW_CANDIDATE_COOLDOWN,
            minimum=0,
        )
        self._selector_dq_alert_cooldown = self._env_int(
            "TELEGRAM_SELECTOR_DQ_ALERT_COOLDOWN_SEC",
            self.SELECTOR_DQ_ALERT_COOLDOWN,
            minimum=0,
        )
        self._selector_min_churn = self._env_int(
            "TELEGRAM_SELECTOR_MIN_CHURN",
            self.SELECTOR_MIN_CHURN,
            minimum=1,
        )
        self._selector_min_churn_ratio = self._env_float(
            "TELEGRAM_SELECTOR_MIN_CHURN_RATIO",
            self.SELECTOR_MIN_CHURN_RATIO,
            minimum=0.0,
            maximum=1.0,
        )
        self._selector_dq_warn_ratio = self._env_float(
            "TELEGRAM_SELECTOR_DQ_WARN_RATIO",
            self.SELECTOR_DQ_WARN_RATIO,
            minimum=0.0,
            maximum=1.0,
        )
        self._selector_dq_crit_ratio = self._env_float(
            "TELEGRAM_SELECTOR_DQ_CRIT_RATIO",
            self.SELECTOR_DQ_CRIT_RATIO,
            minimum=0.0,
            maximum=1.0,
        )
        self._selector_low_selected_ratio = self._env_float(
            "TELEGRAM_SELECTOR_LOW_SELECTED_RATIO",
            self.SELECTOR_LOW_SELECTED_RATIO,
            minimum=0.0,
            maximum=1.0,
        )
        self._notify_selector_events = self._env_bool(
            "TELEGRAM_NOTIFY_SELECTOR_EVENTS",
            False,
        )
        self._notify_order_rejected = self._env_bool(
            "TELEGRAM_NOTIFY_ORDER_REJECTED",
            True,
        )
        self._notify_unknown_executor_alerts = self._env_bool(
            "TELEGRAM_NOTIFY_UNKNOWN_EXECUTOR_ALERTS",
            False,
        )
        self._notify_startup = self._env_bool(
            "TELEGRAM_NOTIFY_STARTUP",
            True,
        )
        self._system_alert_min_level = self._env_choice(
            "TELEGRAM_SYSTEM_ALERT_MIN_LEVEL",
            "CRITICAL",
            set(self.SYSTEM_ALERT_LEVELS.keys()),
        )
        self._http_request_retries = self._env_int(
            "TELEGRAM_HTTP_REQUEST_RETRIES",
            3,
            minimum=1,
        )
        self._http_retry_backoff_sec = self._env_float(
            "TELEGRAM_HTTP_RETRY_BACKOFF_SEC",
            1.0,
            minimum=0.0,
            maximum=30.0,
        )
        self._http_timeout_sec = self._env_float(
            "TELEGRAM_HTTP_TIMEOUT_SEC",
            10.0,
            minimum=1.0,
            maximum=120.0,
        )
        self._force_ipv4 = self._env_bool(
            "TELEGRAM_FORCE_IPV4",
            True,
        )

    async def run(self) -> None:
        """Main loop: consume streams and poll for commands."""
        self._running = True
        logger.info("TelegramTask started")

        # Create consumer groups
        await self.redis.create_consumer_group("trades", self.CONSUMER_GROUP, "$")
        await self.redis.create_consumer_group("alerts", self.CONSUMER_GROUP, "$")
        tasks = [
            self._consume_trades(),
            self._consume_alerts(),
            self._poll_commands(),
        ]
        if self._notify_selector_events:
            await self.redis.create_consumer_group("strategy:selector:events", self.CONSUMER_GROUP, "$")
            tasks.append(self._consume_selector_events())

        await asyncio.gather(*tasks)

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

    async def _consume_selector_events(self) -> None:
        """Consume symbol selector update events."""
        while self._running:
            try:
                messages = await self.redis.consume(
                    "strategy:selector:events",
                    self.CONSUMER_GROUP,
                    self.CONSUMER_NAME,
                    count=10,
                    block_ms=1000,
                )

                for msg in messages:
                    await self._handle_selector_event(msg)
                    await self.redis.ack("strategy:selector:events", self.CONSUMER_GROUP, msg["_id"])

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error consuming selector events: {e}")
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

        for attempt in range(1, self._http_request_retries + 1):
            try:
                async with aiohttp.ClientSession(**self._build_session_kwargs()) as session:
                    async with session.get(
                        url,
                        params=params,
                        timeout=aiohttp.ClientTimeout(total=timeout + self._http_timeout_sec),
                    ) as resp:
                        if resp.status != 200:
                            body = await resp.text()
                            if self._should_retry_status(resp.status) and attempt < self._http_request_retries:
                                await self._sleep_before_retry(
                                    attempt,
                                    f"getUpdates status={resp.status}",
                                )
                                continue
                            logger.warning(
                                "Telegram getUpdates returned status=%s body=%r",
                                resp.status,
                                self._trim_response_body(body),
                            )
                            return []

                        data = await resp.json()
                        return data.get("result", []) if data.get("ok") else []
            except asyncio.TimeoutError:
                if attempt >= self._http_request_retries:
                    return []
                await self._sleep_before_retry(attempt, "getUpdates timeout")
            except (aiohttp.ClientError, OSError) as exc:
                if attempt >= self._http_request_retries:
                    logger.warning(
                        "Telegram getUpdates failed after %s attempts: %s %r",
                        attempt,
                        exc.__class__.__name__,
                        exc,
                    )
                    return []
                await self._sleep_before_retry(
                    attempt,
                    f"getUpdates {exc.__class__.__name__}",
                )

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
                if symbol in self.symbols and symbol not in prices and price_raw:
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
                if symbol in self.symbols and symbol not in signals_by_symbol:
                    decision = (data.get("decision") or "WAIT").upper()
                    regime = data.get("regime", "UNKNOWN")
                    route = self._classify_execution_route(
                        data.get("strategy"),
                        data.get("reason"),
                    )
                    reason = self._summarize_reason(data.get("reason", ""), max_len=80)
                    signals_by_symbol[symbol] = (
                        f"{decision} | {regime} | {self._format_route_label(route)}"
                        f"\n    {reason or '-'}"
                    )
                if len(signals_by_symbol) == len(self.symbols):
                    break
        except Exception:
            return {}
        return signals_by_symbol

    async def _get_positions_text(self) -> str:
        text = ""
        for symbol in self.symbols:
            pos = await self.redis.get_position(symbol, "spot")
            if pos and pos.get("quantity"):
                qty = float(pos.get("quantity", 0))
                entry = float(pos.get("entry_price", 0))
                strategy = pos.get("strategy", "unknown")
                text += f"\n  {symbol} spot: {qty:.4f} @ ${entry:,.2f} ({strategy})"
        return text or "\n  None"

    def _format_prices_text(self, prices: dict[str, float]) -> str:
        text = ""
        for symbol in self.symbols:
            if symbol in prices:
                text += f"\n  {symbol}: ${prices[symbol]:,.2f}"
        return text or "\n  No recent price data"

    def _format_signals_text(self, signals_by_symbol: dict[str, str]) -> str:
        text = ""
        for symbol in self.symbols:
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
        pnl = trade.get("profit", trade.get("pnl"))
        pnl_pct = trade.get("profit_pct", trade.get("pnl_pct"))
        reason = self._summarize_reason(trade.get("reason", ""))
        route = self._classify_execution_route(strategy, reason)
        action = "ENTRY" if side.lower() == "buy" else "EXIT"
        strategy_label = self._format_strategy_label(strategy, symbol)
        lines = [
            f"*{strategy_label} {action}*",
            f"*Symbol:* {symbol} ({market.upper()})",
            f"*Route:* {self._format_route_label(route)}",
            f"*Fill:* {quantity:.4f} @ {self._format_price(price)}",
            f"*Notional:* ${quantity * price:,.2f}",
        ]
        if pnl is not None:
            pnl_val = float(pnl)
            pnl_text = f"*P&L:* ${pnl_val:+,.2f}"
            if pnl_pct is not None:
                pnl_text += f" ({float(pnl_pct):+.2f}%)"
            lines.append(pnl_text)
        if reason:
            lines.append(f"*Reason:* {reason}")
        message = "\n".join(lines)
        await self._send_message(message)

    async def _handle_selector_event(self, event: dict) -> None:
        """Handle symbol selector event notifications."""
        if not self._notify_selector_events:
            return
        strategy = event.get("strategy", "?")
        changed = event.get("changed", "false") == "true"
        selected = [str(x) for x in self._parse_json_array(event.get("selected_symbols", "[]"))]
        top_scores = self._parse_json_array(event.get("top_scores", "[]"))
        signal_events = self._parse_json_array(event.get("signal_events", "[]"))
        rejection_counts = self._parse_json_object(event.get("rejection_counts", "{}"))
        selected_count = self._to_int(event.get("selected_count"), len(selected))
        dq_blocked_count = self._to_int(event.get("dq_blocked_count"), 0)
        universe_size = max(1, self._to_int(event.get("universe_size"), selected_count))
        dq_ratio = dq_blocked_count / universe_size

        prev_snapshot = self._selector_last_snapshot.get(strategy, {})
        prev_selected = set(prev_snapshot.get("selected", [])) if isinstance(
            prev_snapshot.get("selected"), list
        ) else set()
        prev_selected_count = self._to_int(prev_snapshot.get("selected_count"), 0)
        prev_dq_ratio = self._to_float(prev_snapshot.get("dq_ratio"), 0.0)
        prev_dq_blocked = self._to_int(prev_snapshot.get("dq_blocked_count"), 0)
        prev_signal_signature = prev_snapshot.get("signal_signature", ())
        is_first_snapshot = strategy not in self._selector_last_snapshot

        selected_set = set(selected)
        entered = sorted(selected_set - prev_selected)
        exited = sorted(prev_selected - selected_set)
        churn = len(entered) + len(exited)
        churn_threshold = max(
            self._selector_min_churn,
            int(max(selected_count, prev_selected_count, 1) * self._selector_min_churn_ratio),
        )
        significant_churn = changed and churn >= churn_threshold

        dq_warn = dq_ratio >= self._selector_dq_warn_ratio
        dq_jump = abs(dq_blocked_count - prev_dq_blocked) >= max(
            8,
            int(universe_size * 0.10),
        )
        dq_crossed_warn = prev_dq_ratio < self._selector_dq_warn_ratio <= dq_ratio
        dq_crossed_crit = prev_dq_ratio < self._selector_dq_crit_ratio <= dq_ratio
        dq_recovered = prev_dq_ratio >= self._selector_dq_warn_ratio and dq_ratio < self._selector_dq_warn_ratio
        selected_drop = (
            prev_selected_count > 0
            and selected_count < prev_selected_count
            and selected_count <= max(2, int(prev_selected_count * self._selector_low_selected_ratio))
        )
        parsed_signal_events: list[dict] = [
            item for item in signal_events[:8] if isinstance(item, dict) and item.get("type") and item.get("symbol")
        ]
        signal_signature = tuple(
            (str(item.get("type", "")), str(item.get("symbol", "")))
            for item in parsed_signal_events
        )
        has_new_signal_event = bool(signal_signature) and signal_signature != prev_signal_signature
        has_entry_ready = any(str(item.get("type")) == "ENTRY_READY" for item in parsed_signal_events)
        has_new_candidate = any(str(item.get("type")) == "NEW_CANDIDATE" for item in parsed_signal_events)

        anomaly = dq_warn or dq_jump or selected_drop
        reason = ""
        anomaly_mode = False

        if is_first_snapshot and changed:
            reason = "bootstrap"
        elif dq_crossed_crit:
            reason = "dq_critical"
            anomaly_mode = True
        elif dq_crossed_warn or dq_jump or selected_drop:
            reason = "dq_or_liquidity_alert"
            anomaly_mode = True
        elif dq_recovered:
            reason = "dq_recovered"
            anomaly_mode = True
        elif has_new_signal_event and has_entry_ready:
            reason = "entry_ready"
        elif has_new_signal_event and has_new_candidate and changed:
            reason = "new_candidate"
        elif significant_churn:
            reason = "significant_rotation"

        self._selector_last_snapshot[strategy] = {
            "selected": selected,
            "selected_count": selected_count,
            "dq_blocked_count": dq_blocked_count,
            "dq_ratio": dq_ratio,
            "signal_signature": signal_signature,
        }
        if not reason:
            logger.debug(
                "Selector event suppressed: strategy=%s changed=%s churn=%s threshold=%s dq=%s/%s",
                strategy,
                changed,
                churn,
                churn_threshold,
                dq_blocked_count,
                universe_size,
            )
            return

        now = time.time()
        last_sent = self._selector_last_sent.get(strategy, 0.0)
        cooldown = self._selector_anomaly_cooldown if (anomaly_mode or anomaly) else self._selector_normal_cooldown
        if reason == "new_candidate":
            cooldown = max(cooldown, self._selector_new_candidate_cooldown)
        elif reason == "dq_or_liquidity_alert":
            cooldown = max(cooldown, self._selector_dq_alert_cooldown)
        force_send = reason in {"dq_critical", "dq_recovered"}
        if not force_send and (now - last_sent) < cooldown:
            logger.debug(
                "Selector notification cooldown: strategy=%s reason=%s cooldown=%ss",
                strategy,
                reason,
                cooldown,
            )
            return
        self._selector_last_sent[strategy] = now

        top_rejections = sorted(
            rejection_counts.items(),
            key=lambda item: int(item[1]) if str(item[1]).isdigit() else 0,
            reverse=True,
        )[:3]

        score_text = ", ".join(
            f"{item.get('symbol', '?')}:{float(item.get('score', 0)):.3f}"
            for item in top_scores[:3]
            if isinstance(item, dict)
        )
        reject_text = ", ".join(f"{k}:{v}" for k, v in top_rejections)
        entered_text = ", ".join(entered[:6])
        exited_text = ", ".join(exited[:6])
        signal_text = ", ".join(
            f"{item.get('type')}:{item.get('symbol')}({float(item.get('score', 0.0)):.3f})"
            for item in parsed_signal_events[:4]
        )
        selected_preview = ", ".join(selected[:12]) if selected else "-"
        if len(selected) > 12:
            selected_preview += f" (+{len(selected) - 12})"
        kind = "Selector Alert" if (anomaly_mode or anomaly) else "Selector Update"

        message = f"""📊 *{kind}*

*Strategy:* {strategy}
*Reason:* {reason}
*Changed:* {changed} | *Churn:* {churn} (th={churn_threshold})
*DQ Blocked:* {dq_blocked_count}/{universe_size} ({dq_ratio*100:.1f}%)
*Selected({selected_count}):* {selected_preview}
*Entered:* {entered_text or '-'}
*Exited:* {exited_text or '-'}
*Signal Events:* {signal_text or '-'}
*Top Scores:* {score_text or '-'}
*Reject Top3:* {reject_text or '-'}
"""
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
                if not self._notify_order_rejected:
                    return
                symbol = alert.get("symbol", "?")
                reason = alert.get("reason", "Unknown reason")
                message = f"""⚠️ *Order Rejected*

*Symbol:* {symbol}
*Reason:* {reason}

_Time: {datetime.now(self.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC_
"""
            else:
                if not self._notify_unknown_executor_alerts:
                    return
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
            if not self._should_notify_system_level(level):
                return

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

    def _should_notify_system_level(self, level: str) -> bool:
        normalized = str(level or "INFO").upper()
        current_rank = self.SYSTEM_ALERT_LEVELS.get(normalized, self.SYSTEM_ALERT_LEVELS["INFO"])
        min_rank = self.SYSTEM_ALERT_LEVELS.get(
            self._system_alert_min_level,
            self.SYSTEM_ALERT_LEVELS["CRITICAL"],
        )
        return current_rank >= min_rank

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

        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": self.chat_id,
            "text": message,
            "parse_mode": "Markdown",
        }

        for attempt in range(1, self._http_request_retries + 1):
            try:
                async with aiohttp.ClientSession(**self._build_session_kwargs()) as session:
                    sent = await self._post_message_with_fallback(session, url, payload)
                    if sent:
                        if not bypass_rate_limit:
                            self._last_message_time = time.time()
                        return True
            except asyncio.TimeoutError as exc:
                if attempt >= self._http_request_retries:
                    logger.error(
                        "Failed to send Telegram message after %s attempts: %s %r",
                        attempt,
                        exc.__class__.__name__,
                        exc,
                    )
                    return False
                await self._sleep_before_retry(attempt, "sendMessage timeout")
            except (_TransientTelegramError, aiohttp.ClientError, OSError) as exc:
                if attempt >= self._http_request_retries:
                    logger.error(
                        "Failed to send Telegram message after %s attempts: %s %r",
                        attempt,
                        exc.__class__.__name__,
                        exc,
                    )
                    return False
                await self._sleep_before_retry(
                    attempt,
                    f"sendMessage {exc.__class__.__name__}",
                )

        return False

    def _build_session_kwargs(self) -> dict[str, object]:
        if not self._force_ipv4:
            return {}
        return {
            "connector": aiohttp.TCPConnector(family=socket.AF_INET),
        }

    async def _post_message_with_fallback(
        self,
        session: aiohttp.ClientSession,
        url: str,
        payload: dict[str, str],
    ) -> bool:
        response = await self._post_json(session, url, payload)
        if response["success"]:
            return True

        status = response["status"]
        body = response["body"]
        if status == 400 and "parse_mode" in payload:
            fallback_payload = dict(payload)
            fallback_payload.pop("parse_mode", None)
            fallback_response = await self._post_json(session, url, fallback_payload)
            if fallback_response["success"]:
                logger.warning("Telegram Markdown parse failed; resent message without parse_mode")
                return True
            status = fallback_response["status"]
            body = fallback_response["body"]

        if self._should_retry_status(status):
            retry_after = self._extract_retry_after_seconds(body)
            if retry_after is not None:
                await asyncio.sleep(retry_after)
            raise _TransientTelegramError(
                f"status={status} body={self._trim_response_body(body)!r}"
            )

        logger.warning(
            "Telegram sendMessage returned status=%s body=%r",
            status,
            self._trim_response_body(body),
        )
        return False

    async def _post_json(
        self,
        session: aiohttp.ClientSession,
        url: str,
        payload: dict[str, str],
    ) -> dict[str, object]:
        async with session.post(
            url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=self._http_timeout_sec),
        ) as resp:
            body = await resp.text()
            return {
                "success": 200 <= resp.status < 300,
                "status": resp.status,
                "body": body,
            }

    async def _sleep_before_retry(self, attempt: int, reason: str) -> None:
        delay = self._http_retry_backoff_sec * attempt
        if delay > 0:
            logger.warning(
                "Telegram request retry in %.1fs (%s, attempt=%s/%s)",
                delay,
                reason,
                attempt,
                self._http_request_retries,
            )
            await asyncio.sleep(delay)

    @staticmethod
    def _should_retry_status(status: int) -> bool:
        return status == 429 or status >= 500

    @staticmethod
    def _trim_response_body(body: str, limit: int = 240) -> str:
        text = str(body or "").strip()
        if len(text) <= limit:
            return text
        return f"{text[: limit - 3]}..."

    @staticmethod
    def _extract_retry_after_seconds(body: str) -> int | None:
        try:
            data = json.loads(body)
        except (TypeError, json.JSONDecodeError):
            return None

        parameters = data.get("parameters")
        if not isinstance(parameters, dict):
            return None

        retry_after = parameters.get("retry_after")
        try:
            retry_after_int = int(retry_after)
        except (TypeError, ValueError):
            return None
        return max(retry_after_int, 0)

    @staticmethod
    def _parse_json_array(payload: str) -> list:
        try:
            data = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return []
        return data if isinstance(data, list) else []

    @staticmethod
    def _parse_json_object(payload: str) -> dict:
        try:
            data = json.loads(payload)
        except (TypeError, json.JSONDecodeError):
            return {}
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _env_int(name: str, default: int, minimum: int = 0) -> int:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            value = int(raw)
        except ValueError:
            return default
        return max(minimum, value)

    @staticmethod
    def _env_float(
        name: str,
        default: float,
        minimum: float = 0.0,
        maximum: float = 1.0,
    ) -> float:
        raw = os.getenv(name)
        if raw is None:
            return default
        try:
            value = float(raw)
        except ValueError:
            return default
        return max(minimum, min(maximum, value))

    @staticmethod
    def _env_bool(name: str, default: bool) -> bool:
        raw = os.getenv(name)
        if raw is None:
            return default
        value = raw.strip().lower()
        if value in {"1", "true", "yes", "on"}:
            return True
        if value in {"0", "false", "no", "off"}:
            return False
        return default

    @staticmethod
    def _env_choice(name: str, default: str, allowed: set[str]) -> str:
        raw = os.getenv(name)
        if raw is None:
            return default
        value = raw.strip().upper()
        if value in allowed:
            return value
        return default

    @staticmethod
    def _to_int(value, default: int = 0) -> int:
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _to_float(value, default: float = 0.0) -> float:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _format_price(price: float) -> str:
        if price >= 1000:
            return f"${price:,.2f}"
        if price >= 1:
            return f"${price:,.4f}"
        if price > 0:
            return f"${price:,.6f}"
        return "$0.0000"

    @staticmethod
    def _summarize_reason(reason: str, max_len: int = 140) -> str:
        text = " ".join(str(reason or "").split())
        if len(text) <= max_len:
            return text
        return f"{text[: max_len - 3]}..."

    @staticmethod
    def _classify_execution_route(strategy: str | None, reason: str | None) -> str:
        strategy_text = str(strategy or "").lower()
        reason_text = str(reason or "").lower()
        if "fallback" in strategy_text or "fallback" in reason_text:
            return "fallback"
        if "provider error" in reason_text:
            return "fallback"
        if strategy_text.startswith("llm_direction"):
            return "llm"
        return "other"

    @staticmethod
    def _format_route_label(route: str) -> str:
        if route == "fallback":
            return "Fallback"
        if route == "llm":
            return "Primary LLM"
        return "Other"

    @staticmethod
    def _format_strategy_label(strategy: str | None, symbol: str | None = None) -> str:
        strategy_text = str(strategy or "").strip()
        symbol_text = str(symbol or "").strip().upper()
        if strategy_text.startswith("llm_direction_"):
            return f"{(symbol_text or strategy_text.removeprefix('llm_direction_').upper())} LLM"
        return strategy_text or "Strategy"

    async def send_start_notification(self, mode: str, symbols: list[str]) -> None:
        """Send bot start notification.

        Args:
            mode: Trading mode (paper/live)
            symbols: List of enabled symbols
        """
        if not self._notify_startup:
            return
        mode_emoji = "" if mode == "paper" else ""
        symbols_text = ", ".join(symbols)

        message = f"""{mode_emoji} *Trading Bot Started*

*Mode:* {mode.upper()}
*Symbols:* {symbols_text}
*Time:* {datetime.now(self.utc).strftime('%Y-%m-%d %H:%M:%S')} UTC

_Use /info for status, /help for commands_
"""
        await self._send_message(message)
