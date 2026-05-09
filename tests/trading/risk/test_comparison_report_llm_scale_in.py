from datetime import date
from pathlib import Path
import sqlite3

import pandas as pd

from trading.risk.comparison_report import ComparisonReportGenerator


class FakeAdapter:
    def __init__(self, actions):
        self.actions = actions
        self.symbol = "BTC"
        self.strategy_name = "llm_direction"
        self.market = "spot"
        self.current_position = None
        self.high_water_mark = None

    def __call__(self, _df, index):
        return self.actions[index]


class WarmableFakeAdapter(FakeAdapter):
    def __init__(self, actions):
        super().__init__(actions)
        self.warm_count = 0

    def _decrement_timers(self):
        pass

    def _update_period_risk_state(self, _row):
        pass

    def _extract_row_values(self, _row):
        return {}

    def _build_context(self, _row, _values):
        self.warm_count += 1


def _frame():
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(
                [
                    "2026-05-07 20:00:00",
                    "2026-05-08 00:00:00",
                    "2026-05-08 04:00:00",
                    "2026-05-08 08:00:00",
                ]
            ),
            "close": [100.0, 110.0, 120.0, 130.0],
        }
    )


def test_replay_backtest_day_keeps_scale_in_buy_records(tmp_path: Path):
    generator = ComparisonReportGenerator(db_path=str(tmp_path / "trades.db"))
    adapter = FakeAdapter(
        [
            {"action": "buy", "fraction": 0.10},
            {"action": "buy", "fraction": 0.12, "scale_in": True},
            {"action": "buy", "fraction": 0.12, "scale_in": True},
            {"action": "sell"},
        ]
    )

    trades = generator._replay_backtest_day(
        _frame(),
        date(2026, 5, 8),
        adapter,
        {"allow_scale_in_entries": True},
    )

    assert [trade.action for trade in trades] == ["buy", "buy", "sell"]
    assert trades[0].quantity == 0.12
    assert trades[1].quantity == 0.12
    assert trades[2].profit_loss is not None
    assert trades[2].profit_loss_pct is not None


def test_replay_backtest_day_suppresses_scale_in_when_disabled(tmp_path: Path):
    generator = ComparisonReportGenerator(db_path=str(tmp_path / "trades.db"))
    adapter = FakeAdapter(
        [
            {"action": "hold"},
            {"action": "buy", "fraction": 0.12},
            {"action": "buy", "fraction": 0.12, "scale_in": True},
            {"action": "sell"},
        ]
    )

    trades = generator._replay_backtest_day(
        _frame(),
        date(2026, 5, 8),
        adapter,
        {"allow_scale_in_entries": False},
    )

    assert [trade.action for trade in trades] == ["buy", "sell"]


def test_replay_backtest_day_ignores_warmup_positions_without_carry(tmp_path: Path):
    generator = ComparisonReportGenerator(db_path=str(tmp_path / "trades.db"))
    adapter = FakeAdapter(
        [
            {"action": "buy", "fraction": 0.10},
            {"action": "sell"},
            {"action": "hold"},
            {"action": "hold"},
        ]
    )

    trades = generator._replay_backtest_day(
        _frame(),
        date(2026, 5, 8),
        adapter,
        {"allow_scale_in_entries": False},
    )

    assert trades == []


def test_replay_backtest_day_warms_adapter_context_without_warmup_trades(
    tmp_path: Path,
):
    generator = ComparisonReportGenerator(db_path=str(tmp_path / "trades.db"))
    adapter = WarmableFakeAdapter(
        [
            {"action": "buy", "fraction": 0.10},
            {"action": "sell"},
            {"action": "hold"},
            {"action": "hold"},
        ]
    )

    trades = generator._replay_backtest_day(
        _frame(),
        date(2026, 5, 8),
        adapter,
        {"allow_scale_in_entries": False},
    )

    assert adapter.warm_count == 1
    assert trades == []


def test_replay_backtest_day_seeds_carried_position_before_target_day(tmp_path: Path):
    generator = ComparisonReportGenerator(db_path=str(tmp_path / "trades.db"))
    adapter = FakeAdapter(
        [
            {"action": "buy", "fraction": 0.10},
            {"action": "sell"},
            {"action": "hold"},
            {"action": "hold"},
        ]
    )

    trades = generator._replay_backtest_day(
        _frame(),
        date(2026, 5, 8),
        adapter,
        {"allow_scale_in_entries": False},
        carry_position={
            "symbol": "BTC",
            "quantity": 0.5,
            "entry_price": 100.0,
            "entry_time": pd.Timestamp("2026-05-07 00:00:00").to_pydatetime(),
        },
    )

    assert [trade.action for trade in trades] == ["sell"]
    assert trades[0].quantity == 0.5
    assert trades[0].profit_loss == 5.0
    assert adapter.current_position is not None


def test_load_strategy_config_prefers_allocation(monkeypatch, tmp_path: Path):
    generator = ComparisonReportGenerator(db_path=str(tmp_path / "trades.db"))
    monkeypatch.setattr(
        generator,
        "_load_allocation_strategies",
        lambda: {
            "llm_direction_btc": {
                "enabled": True,
                "symbols": ["BTC"],
                "allow_scale_in_entries": True,
            }
        },
    )

    config = generator._load_strategy_config("llm_direction_btc")

    assert config["symbols"] == ["BTC"]
    assert config["allow_scale_in_entries"] is True


def test_build_component_adapter_forces_fallback_by_default(monkeypatch, tmp_path: Path):
    generator = ComparisonReportGenerator(db_path=str(tmp_path / "trades.db"))

    config = {
        "symbols": ["BTC"],
        "market": "spot",
        "entry": {
            "class": "LLMDecisionEntryStrategy",
            "params": {"market": "spot"},
        },
        "exit": {
            "class": "LLMHybridExitStrategy",
            "params": {"market": "spot"},
        },
    }

    adapter = generator._build_component_adapter("llm_direction_btc", config)

    assert adapter._backtest_force_entry_fallback is True
    assert adapter.strategy_name == "llm_direction"


def test_load_actual_trades_falls_back_to_symbol_rows(tmp_path: Path):
    db_path = tmp_path / "paper.db"
    generator = ComparisonReportGenerator(db_path=str(db_path))

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute("SELECT strategy_id FROM strategies WHERE name = 'paper_trading'")
    strategy_id = cur.fetchone()[0]
    cur.execute(
        """
        INSERT INTO trades
        (strategy_id, symbol, action, price, volume, profit, profit_pct, exchange, market, paper, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            strategy_id,
            "BTC",
            "BUY",
            100.0,
            0.1,
            None,
            None,
            "binance",
            "spot",
            1,
            "2026-05-08 00:00:00",
        ),
    )
    cur.execute(
        """
        INSERT INTO trades
        (strategy_id, symbol, action, price, volume, profit, profit_pct, exchange, market, paper, timestamp)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            strategy_id,
            "ETH",
            "BUY",
            10.0,
            1.0,
            None,
            None,
            "binance",
            "spot",
            1,
            "2026-05-08 00:00:00",
        ),
    )
    con.commit()
    con.close()

    rows = generator._load_actual_trades(
        target_date=date(2026, 5, 8),
        strategy_name="llm_direction_btc",
        strategy_config={"symbols": ["BTC"]},
        exchange="binance",
    )

    assert len(rows) == 1
    assert rows[0]["symbol"] == "BTC"
    assert rows[0]["action"] == "BUY"


def test_reconstruct_position_infers_from_target_exit_when_prior_buys_missing(
    tmp_path: Path,
):
    generator = ComparisonReportGenerator(db_path=str(tmp_path / "trades.db"))

    position = generator._reconstruct_open_position_before_date(
        target_date=date(2026, 5, 8),
        strategy_config={"symbols": ["BTC"]},
        exchange="binance",
        target_day_trades=[
            {
                "action": "SELL",
                "price": 79320.773994,
                "volume": 0.04654,
                "profit": -95.4779,
                "timestamp": pd.Timestamp("2026-05-08 12:01:44").to_pydatetime(),
            }
        ],
    )

    assert position is not None
    assert position["source"] == "target_day_sell_profit"
    assert position["quantity"] == 0.04654
    assert round(position["entry_price"], 2) == 81372.30


def test_comparison_tolerance_scales_with_strategy_timeframe(tmp_path: Path):
    generator = ComparisonReportGenerator(db_path=str(tmp_path / "trades.db"))

    assert (
        generator._resolve_comparison_tolerance_minutes(
            "llm_direction_btc", {"symbols": ["BTC"], "timeframe": "minute240"}
        )
        == 60
    )
    assert (
        generator._resolve_comparison_tolerance_minutes(
            "llm_direction_btc", {"symbols": ["BTC"], "timeframe": "minute15"}
        )
        == 5
    )


def test_comparison_schema_is_initialized(tmp_path: Path):
    db_path = tmp_path / "paper.db"
    ComparisonReportGenerator(db_path=str(db_path))

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='comparison_reports'"
    )
    assert cur.fetchone() is not None
    con.close()
