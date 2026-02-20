from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from trading.notification.telegram_task import TelegramTask


def _selector_event(
    *,
    strategy: str,
    changed: bool,
    selected: list[str],
    selected_count: int | None = None,
    dq_blocked_count: int = 0,
    universe_size: int = 64,
    top_scores: list[dict] | None = None,
    rejection_counts: dict | None = None,
) -> dict:
    return {
        "strategy": strategy,
        "changed": "true" if changed else "false",
        "selected_symbols": json.dumps(selected),
        "selected_count": str(selected_count if selected_count is not None else len(selected)),
        "dq_blocked_count": str(dq_blocked_count),
        "universe_size": str(universe_size),
        "top_scores": json.dumps(top_scores or []),
        "rejection_counts": json.dumps(rejection_counts or {}),
    }


def _build_task(monkeypatch: pytest.MonkeyPatch) -> TelegramTask:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_SELECTOR_NORMAL_COOLDOWN_SEC", "0")
    monkeypatch.setenv("TELEGRAM_SELECTOR_ANOMALY_COOLDOWN_SEC", "0")
    redis = AsyncMock()
    task = TelegramTask(redis=redis)
    task._send_message = AsyncMock(return_value=True)  # type: ignore[method-assign]
    return task


@pytest.mark.asyncio
async def test_selector_minor_rotation_is_suppressed(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _build_task(monkeypatch)

    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=True,
            selected=["ADA", "AVAX", "DOT", "XLM"],
        )
    )
    assert task._send_message.await_count == 1

    # Churn=2 (< min churn threshold=4) should not notify.
    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=True,
            selected=["ADA", "AVAX", "DOT", "TRX"],
        )
    )
    assert task._send_message.await_count == 1


@pytest.mark.asyncio
async def test_selector_significant_rotation_notifies(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _build_task(monkeypatch)

    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=True,
            selected=["ADA", "AVAX", "DOT", "XLM", "TRX", "UNI", "NEAR", "ARB"],
        )
    )
    assert task._send_message.await_count == 1

    # Churn=8 should notify.
    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=True,
            selected=["FIL", "FLOW", "RUNE", "SEI", "TIA", "WLD", "MEME", "GRT"],
        )
    )
    assert task._send_message.await_count == 2


@pytest.mark.asyncio
async def test_selector_dq_alert_notifies_even_without_rotation(monkeypatch: pytest.MonkeyPatch) -> None:
    task = _build_task(monkeypatch)

    # Healthy baseline (no selector change).
    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=False,
            selected=["ADA", "AVAX", "DOT", "XLM"],
            dq_blocked_count=0,
            universe_size=64,
        )
    )
    assert task._send_message.await_count == 0

    # DQ blocked ratio 25/64 ~= 39% crosses warning threshold and should notify.
    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=False,
            selected=["ADA", "AVAX", "DOT", "XLM"],
            dq_blocked_count=25,
            universe_size=64,
        )
    )
    assert task._send_message.await_count == 1
