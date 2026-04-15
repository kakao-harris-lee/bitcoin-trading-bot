from __future__ import annotations

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
