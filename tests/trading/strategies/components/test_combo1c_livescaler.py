"""Tests for Combo1-C LiveScaler feature alignment."""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from lstm_trainer.src.live_scaler import LiveScaler
from trading.strategies.components.combo1c_entry import Combo1CEntryParams, Combo1CEntryStrategy


def _create_scaling_db(path: Path, columns: list[str], base_columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.execute(
        """
        CREATE TABLE scaling_params (
            column_name TEXT PRIMARY KEY,
            min_value REAL,
            max_value REAL,
            rolling_window INTEGER,
            updated_at TEXT
        )
        """
    )
    for col in sorted(set(columns + base_columns)):
        if col in base_columns:
            min_val, max_val = 0.0, 100.0
        else:
            min_val, max_val = 0.0, 1.0
        conn.execute(
            """
            INSERT INTO scaling_params
            (column_name, min_value, max_value, rolling_window, updated_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (col, min_val, max_val, None, "2026-01-01T00:00:00"),
        )
    conn.commit()
    conn.close()


def test_live_scaler_nested_chain_values(tmp_path: Path) -> None:
    """LiveScaler reproduces nested scaling chain values."""
    cols = [
        "open_scaled",
        "open_scaled_rolling",
        "open_scaled_rolling_scaled",
        "open_scaled_rolling_scaled_rolling",
    ]
    db_path = tmp_path / "scaling.db"
    _create_scaling_db(db_path, cols, base_columns=["open"])

    scaler = LiveScaler(db_path=str(db_path), rolling_window=3, feature_columns=cols)
    history = [
        {"open": 0.0},
        {"open": 50.0},
        {"open": 100.0},
    ]
    df = scaler.prepare_sequence(history)
    last = df.iloc[-1]

    assert last["open_scaled"] == pytest.approx(1.0)
    assert last["open_scaled_rolling"] == pytest.approx(1.0)
    assert last["open_scaled_rolling_scaled"] == pytest.approx(1.0)
    assert last["open_scaled_rolling_scaled_rolling"] == pytest.approx(1.0)


def test_live_scaler_checkpoint_columns_present(tmp_path: Path) -> None:
    """LiveScaler produces all checkpoint feature columns."""
    try:
        import torch
    except Exception as exc:  # pragma: no cover - environment missing torch
        pytest.skip(f"torch not available: {exc}")

    ckpt_path = Path("lstm_trainer/models/hybrid_lstm.pth")
    if not ckpt_path.exists():
        pytest.skip("checkpoint not available in repo")

    ckpt = torch.load(ckpt_path, map_location="cpu", weights_only=False)
    feature_columns = ckpt.get("feature_columns", [])
    if not feature_columns:
        pytest.skip("checkpoint missing feature_columns")

    db_path = tmp_path / "scaling.db"
    _create_scaling_db(db_path, feature_columns, base_columns=["open", "high", "low", "close"])

    scaler = LiveScaler(
        db_path=str(db_path),
        rolling_window=3,
        feature_columns=feature_columns,
    )
    scaled = scaler.scale_row({"open": 100.0, "high": 110.0, "low": 90.0, "close": 105.0})
    missing = [c for c in feature_columns if c not in scaled]

    assert missing == []


def test_combo1c_scaler_uses_predictor_columns(tmp_path: Path) -> None:
    """Combo1-C scaler picks up predictor feature columns."""
    cols = ["open_scaled", "open_scaled_rolling"]
    db_path = tmp_path / "scaling.db"
    _create_scaling_db(db_path, cols, base_columns=["open"])

    params = Combo1CEntryParams(db_path=str(db_path))
    strategy = Combo1CEntryStrategy(params)
    strategy._predictor = type("Predictor", (), {"scaled_columns": cols})()

    scaler = strategy._get_scaler()
    assert scaler is not None
    assert scaler.feature_columns == cols
