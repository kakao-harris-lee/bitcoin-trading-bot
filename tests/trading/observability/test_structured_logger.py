from __future__ import annotations

import importlib
import json
from pathlib import Path

import trading.observability.structured_logger as structured_logger


def _reload_module():
    return importlib.reload(structured_logger)


def test_structured_logger_disabled_under_pytest_by_default(monkeypatch):
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_case")
    monkeypatch.delenv("ENABLE_TEST_STRUCTURED_LOGS", raising=False)
    mod = _reload_module()

    assert mod._is_structured_logging_enabled() is False


def test_structured_logger_can_write_with_test_override(monkeypatch, tmp_path: Path):
    log_path = tmp_path / "trades.jsonl"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_case")
    monkeypatch.setenv("ENABLE_TEST_STRUCTURED_LOGS", "1")
    monkeypatch.setenv("TRADE_LOG_PATH", str(log_path))
    mod = _reload_module()

    mod.trade_logger.entry(
        symbol="BTC",
        price=100000.0,
        qty=0.01,
        strategy="llm_direction_btc",
        mode="paper",
    )

    assert log_path.exists()
    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "ENTRY"
    assert payload["strategy"] == "llm_direction_btc"


def test_structured_logger_filters_non_actionable_decisions_by_default(
    monkeypatch,
    tmp_path: Path,
):
    log_path = tmp_path / "trades.jsonl"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_case")
    monkeypatch.setenv("ENABLE_TEST_STRUCTURED_LOGS", "1")
    monkeypatch.setenv("TRADE_LOG_PATH", str(log_path))
    monkeypatch.delenv("TRADE_LOG_DECISIONS", raising=False)
    mod = _reload_module()

    mod.trade_logger.decision(
        symbol="BTC",
        strategy="llm_direction_btc",
        decision="HOLD",
        price=100000.0,
        reason="no edge",
    )
    mod.trade_logger.decision(
        symbol="BTC",
        strategy="llm_direction_btc",
        decision="BUY",
        price=100500.0,
        reason="edge",
    )

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "DECISION"
    assert payload["decision"] == "BUY"


def test_structured_logger_keeps_all_decisions_when_overridden(monkeypatch, tmp_path: Path):
    log_path = tmp_path / "trades.jsonl"
    monkeypatch.setenv("PYTEST_CURRENT_TEST", "test_case")
    monkeypatch.setenv("ENABLE_TEST_STRUCTURED_LOGS", "1")
    monkeypatch.setenv("TRADE_LOG_PATH", str(log_path))
    monkeypatch.setenv("TRADE_LOG_DECISIONS", "ALL")
    mod = _reload_module()

    mod.trade_logger.decision(
        symbol="ETH",
        strategy="llm_direction_eth",
        decision="WAIT",
        price=2000.0,
        reason="filters",
    )

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "DECISION"
    assert payload["decision"] == "WAIT"
