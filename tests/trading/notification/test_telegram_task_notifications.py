from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from trading.notification.telegram_task import TelegramTask


def _build_task(monkeypatch: pytest.MonkeyPatch, **env: str) -> TelegramTask:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    redis = AsyncMock()
    task = TelegramTask(redis=redis)
    task._send_message = AsyncMock(return_value=True)  # type: ignore[method-assign]
    return task


def _build_real_task(monkeypatch: pytest.MonkeyPatch, **env: str) -> TelegramTask:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    redis = AsyncMock()
    return TelegramTask(redis=redis)


class _FakeResponse:
    def __init__(self, status: int, body: str = "", json_data: dict | None = None):
        self.status = status
        self._body = body
        self._json_data = json_data or {}

    async def __aenter__(self) -> _FakeResponse:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    async def text(self) -> str:
        return self._body

    async def json(self) -> dict:
        return self._json_data


class _FakeSession:
    def __init__(self, effects: list[object]):
        self._effects = effects

    async def __aenter__(self) -> _FakeSession:
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        return False

    def post(self, *args, **kwargs):
        effect = self._effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return effect

    def get(self, *args, **kwargs):
        effect = self._effects.pop(0)
        if isinstance(effect, BaseException):
            raise effect
        return effect


class _SessionFactory:
    def __init__(self, effects: list[object]):
        self.effects = effects
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeSession(self.effects)


@pytest.mark.asyncio
async def test_selector_notifications_are_disabled_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _build_task(monkeypatch)

    await task._handle_selector_event(
        {
            "strategy": "mlp_direction_bnb",
            "changed": "true",
            "selected_symbols": "[\"NEAR\"]",
            "selected_count": "1",
            "dq_blocked_count": "0",
            "universe_size": "64",
            "top_scores": "[]",
            "signal_events": "[{\"type\":\"ENTRY_READY\",\"symbol\":\"NEAR\",\"score\":0.44}]",
            "rejection_counts": "{}",
        }
    )

    assert task._send_message.await_count == 0


@pytest.mark.asyncio
async def test_generic_error_alert_is_suppressed_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _build_task(monkeypatch)

    await task._handle_alert(
        {
            "level": "ERROR",
            "component": "feed",
            "message": "Connection closed by server.",
        }
    )

    assert task._send_message.await_count == 0


@pytest.mark.asyncio
async def test_order_rejected_alert_still_sends(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _build_task(monkeypatch)

    await task._handle_alert(
        {
            "type": "order_rejected",
            "symbol": "BTC",
            "reason": "insufficient balance",
        }
    )

    assert task._send_message.await_count == 1
    message = task._send_message.await_args.args[0]
    assert "Order Rejected" in message
    assert "BTC" in message


@pytest.mark.asyncio
async def test_trade_notification_uses_profit_fields_and_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _build_task(monkeypatch)

    await task._handle_trade(
        {
            "symbol": "NEAR",
            "side": "sell",
            "market": "spot",
            "quantity": "136.1123",
            "price": "1.41",
            "strategy": "mlp_direction_bnb",
            "profit": "12.26",
            "profit_pct": "6.41",
            "reason": "HybridLong[mlp] MLPDirection exit: Trailing stop 2.95% (HWM=5.26%)",
        }
    )

    assert task._send_message.await_count == 1
    message = task._send_message.await_args.args[0]
    assert "*Trade EXIT*" in message
    assert "*P&L:* $+12.26 (+6.41%)" in message
    assert "Trailing stop" in message


@pytest.mark.asyncio
async def test_send_message_retries_timeout_and_uses_ipv4(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _build_real_task(monkeypatch, TELEGRAM_HTTP_RETRY_BACKOFF_SEC="0")
    session_factory = _SessionFactory(
        [
            asyncio.TimeoutError(),
            _FakeResponse(status=200, body='{"ok":true}'),
        ]
    )
    monkeypatch.setattr("trading.notification.telegram_task.aiohttp.ClientSession", session_factory)

    sent = await task._send_message("connectivity check")

    assert sent is True
    assert task._last_message_time > 0
    assert len(session_factory.calls) == 2
    assert "connector" in session_factory.calls[0]


@pytest.mark.asyncio
async def test_send_message_failure_does_not_consume_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _build_real_task(monkeypatch, TELEGRAM_HTTP_RETRY_BACKOFF_SEC="0")
    failing_factory = _SessionFactory(
        [
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
            asyncio.TimeoutError(),
        ]
    )
    monkeypatch.setattr("trading.notification.telegram_task.aiohttp.ClientSession", failing_factory)

    first = await task._send_message("first attempt")

    success_factory = _SessionFactory([_FakeResponse(status=200, body='{"ok":true}')])
    monkeypatch.setattr("trading.notification.telegram_task.aiohttp.ClientSession", success_factory)
    second = await task._send_message("second attempt")

    assert first is False
    assert second is True
