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
    signal_events: list[dict] | None = None,
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
        "signal_events": json.dumps(signal_events or []),
        "rejection_counts": json.dumps(rejection_counts or {}),
    }


def _build_task(
    monkeypatch: pytest.MonkeyPatch,
    *,
    normal_cooldown: int = 0,
    anomaly_cooldown: int = 0,
    new_candidate_cooldown: int = 0,
    dq_alert_cooldown: int = 0,
) -> TelegramTask:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "123")
    monkeypatch.setenv("TELEGRAM_NOTIFY_SELECTOR_EVENTS", "true")
    monkeypatch.setenv("TELEGRAM_SELECTOR_NORMAL_COOLDOWN_SEC", str(normal_cooldown))
    monkeypatch.setenv("TELEGRAM_SELECTOR_ANOMALY_COOLDOWN_SEC", str(anomaly_cooldown))
    monkeypatch.setenv("TELEGRAM_SELECTOR_NEW_CANDIDATE_COOLDOWN_SEC", str(new_candidate_cooldown))
    monkeypatch.setenv("TELEGRAM_SELECTOR_DQ_ALERT_COOLDOWN_SEC", str(dq_alert_cooldown))
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


@pytest.mark.asyncio
async def test_selector_low_selected_count_without_drop_is_suppressed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _build_task(monkeypatch)

    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=False,
            selected=["LINK"],
            dq_blocked_count=0,
            universe_size=64,
        )
    )

    # selected_count remains 1 -> no drop event, should stay suppressed.
    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=True,
            selected=["LTC"],
            dq_blocked_count=0,
            universe_size=64,
        )
    )
    assert task._send_message.await_count == 0


@pytest.mark.asyncio
async def test_selector_entry_ready_notifies_on_new_signal_signature(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _build_task(monkeypatch)

    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=False,
            selected=["SNX", "ADA", "AVAX", "DOT"],
            signal_events=[{"type": "ENTRY_READY", "symbol": "SNX", "score": 0.44}],
        )
    )
    assert task._send_message.await_count == 1

    # Same signature should be suppressed.
    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=False,
            selected=["SNX", "ADA", "AVAX", "DOT"],
            signal_events=[{"type": "ENTRY_READY", "symbol": "SNX", "score": 0.46}],
        )
    )
    assert task._send_message.await_count == 1


@pytest.mark.asyncio
async def test_selector_new_candidate_reason_cooldown_suppresses_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _build_task(monkeypatch, new_candidate_cooldown=600)
    clock = iter([1_000.0, 1_100.0])
    monkeypatch.setattr("trading.notification.telegram_task.time.time", lambda: next(clock))

    # Seed snapshot without triggering dq/liquidity alert.
    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=False,
            selected=["ADA", "AVAX", "DOT", "LINK"],
            dq_blocked_count=0,
            universe_size=64,
        )
    )

    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=True,
            selected=["ADA", "AVAX", "DOT", "LTC"],
            dq_blocked_count=0,
            universe_size=64,
            signal_events=[{"type": "NEW_CANDIDATE", "symbol": "LTC", "score": 0.011}],
        )
    )
    assert task._send_message.await_count == 1

    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=True,
            selected=["ADA", "AVAX", "DOT", "SUI"],
            dq_blocked_count=0,
            universe_size=64,
            signal_events=[{"type": "NEW_CANDIDATE", "symbol": "SUI", "score": 0.059}],
        )
    )
    assert task._send_message.await_count == 1


@pytest.mark.asyncio
async def test_selector_dq_alert_reason_cooldown_suppresses_repeats(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _build_task(monkeypatch, dq_alert_cooldown=600)
    clock = iter([2_000.0, 2_060.0])
    monkeypatch.setattr("trading.notification.telegram_task.time.time", lambda: next(clock))

    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=False,
            selected=["ADA", "AVAX", "DOT", "XLM"],
            dq_blocked_count=0,
            universe_size=64,
        )
    )

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

    await task._handle_selector_event(
        _selector_event(
            strategy="mlp_direction_bnb",
            changed=False,
            selected=["ADA", "AVAX", "DOT", "XLM"],
            dq_blocked_count=35,
            universe_size=64,
        )
    )
    assert task._send_message.await_count == 1
