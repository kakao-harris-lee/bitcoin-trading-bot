import sqlite3

from trading.risk.trade_logger import TradeLogger


def test_log_trade_can_store_per_trade_strategy_name(tmp_path):
    db_path = tmp_path / "trades.db"
    logger = TradeLogger(str(db_path), strategy_name="paper_trading")

    logger.log_trade(
        action="buy",
        price=100.0,
        volume=1.0,
        symbol="BTC",
        strategy_name="llm_direction_btc",
    )
    logger.log_trade(
        action="sell",
        price=110.0,
        volume=1.0,
        profit=10.0,
        profit_pct=10.0,
        symbol="BTC",
        strategy_name="llm_direction_btc",
    )
    logger.log_trade(
        action="buy",
        price=200.0,
        volume=2.0,
        symbol="ETH",
        strategy_name="llm_direction_eth",
    )
    logger.close()

    with sqlite3.connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT s.name, t.symbol, t.action, t.profit
            FROM trades t
            JOIN strategies s ON s.strategy_id = t.strategy_id
            ORDER BY t.trade_id
            """
        ).fetchall()

    assert rows == [
        ("llm_direction_btc", "BTC", "BUY", None),
        ("llm_direction_btc", "BTC", "SELL", 10.0),
        ("llm_direction_eth", "ETH", "BUY", None),
    ]


def test_log_trade_keeps_default_strategy_when_no_override(tmp_path):
    db_path = tmp_path / "trades.db"
    logger = TradeLogger(str(db_path), strategy_name="paper_trading")

    logger.log_trade(action="buy", price=100.0, volume=1.0, symbol="BTC")
    logger.close()

    with sqlite3.connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT s.name
            FROM trades t
            JOIN strategies s ON s.strategy_id = t.strategy_id
            """
        ).fetchone()

    assert row == ("paper_trading",)
