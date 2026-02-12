from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from trading.core.paper_readiness import evaluate_paper_readiness


def _write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload), encoding="utf-8")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_paper_readiness_passes_with_sufficient_exits(tmp_path: Path):
    config_path = tmp_path / "allocation.json"
    trades_path = tmp_path / "trades.jsonl"

    _write_json(
        config_path,
        {
            "strategies": {
                "alpha": {"enabled": True},
                "beta": {"enabled": True},
            }
        },
    )
    _write_jsonl(
        trades_path,
        [
            {"ts": "2026-02-10T10:00:00", "event": "EXIT", "mode": "paper", "strategy": "alpha", "pnl": 10},
            {"ts": "2026-02-10T11:00:00", "event": "EXIT", "mode": "paper", "strategy": "alpha", "pnl": -3},
            {"ts": "2026-02-10T12:00:00", "event": "EXIT", "mode": "paper", "strategy": "beta", "pnl": 7},
            {"ts": "2026-02-10T13:00:00", "event": "EXIT", "mode": "paper", "strategy": "beta", "pnl": 5},
        ],
    )

    report = evaluate_paper_readiness(
        config_path=str(config_path),
        trades_log_path=str(trades_path),
        lookback_days=14,
        min_exits_per_strategy=2,
        min_total_exits=4,
        min_win_rate_pct=40.0,
        min_profit_factor=1.0,
        require_positive_pnl=True,
        now=datetime(2026, 2, 12, 0, 0, 0),
    )

    assert report.ready is True
    assert report.total_exits == 4
    assert report.total_pnl == 19


def test_paper_readiness_fails_when_strategy_has_no_exits(tmp_path: Path):
    config_path = tmp_path / "allocation.json"
    trades_path = tmp_path / "trades.jsonl"

    _write_json(
        config_path,
        {"strategies": {"alpha": {"enabled": True}, "beta": {"enabled": True}}},
    )
    _write_jsonl(
        trades_path,
        [{"ts": "2026-02-10T10:00:00", "event": "EXIT", "mode": "paper", "strategy": "alpha", "pnl": 10}],
    )

    report = evaluate_paper_readiness(
        config_path=str(config_path),
        trades_log_path=str(trades_path),
        min_exits_per_strategy=1,
        min_total_exits=2,
        now=datetime(2026, 2, 12, 0, 0, 0),
    )

    assert report.ready is False
    assert any("beta: not enough paper exits" in e for e in report.errors)
    assert any("Total paper exits too low" in e for e in report.errors)


def test_paper_readiness_ignores_non_paper_non_exit_events(tmp_path: Path):
    config_path = tmp_path / "allocation.json"
    trades_path = tmp_path / "trades.jsonl"

    _write_json(config_path, {"strategies": {"alpha": {"enabled": True}}})
    _write_jsonl(
        trades_path,
        [
            {"ts": "2026-02-10T10:00:00", "event": "ENTRY", "mode": "paper", "strategy": "alpha", "pnl": 1},
            {"ts": "2026-02-10T10:01:00", "event": "EXIT", "mode": "live", "strategy": "alpha", "pnl": 1},
            {"ts": "2026-02-10T10:02:00", "event": "EXIT", "mode": "paper", "strategy": "alpha"},
        ],
    )

    report = evaluate_paper_readiness(
        config_path=str(config_path),
        trades_log_path=str(trades_path),
        min_exits_per_strategy=1,
        min_total_exits=1,
        now=datetime(2026, 2, 12, 0, 0, 0),
    )

    assert report.ready is False
    assert report.total_exits == 0


def test_paper_readiness_warns_for_non_enabled_strategy_exits(tmp_path: Path):
    config_path = tmp_path / "allocation.json"
    trades_path = tmp_path / "trades.jsonl"

    _write_json(config_path, {"strategies": {"alpha": {"enabled": True}}})
    _write_jsonl(
        trades_path,
        [
            {
                "ts": "2026-02-10T10:00:00",
                "event": "EXIT",
                "mode": "paper",
                "strategy": "unknown_strategy",
                "pnl": 5,
            },
            {
                "ts": "2026-02-10T11:00:00",
                "event": "EXIT",
                "mode": "paper",
                "strategy": "alpha",
                "pnl": 3,
            },
        ],
    )

    report = evaluate_paper_readiness(
        config_path=str(config_path),
        trades_log_path=str(trades_path),
        min_exits_per_strategy=1,
        min_total_exits=1,
        now=datetime(2026, 2, 12, 0, 0, 0),
    )

    assert report.total_exits == 1
    assert any("Ignored 1 paper EXIT records" in w for w in report.warnings)
