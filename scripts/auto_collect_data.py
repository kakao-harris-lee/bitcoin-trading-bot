#!/usr/bin/env python3
"""
Auto data collector for bitcoin trading bot.

Collects OHLCV data for BTC, ETH, and SOL from Binance.
Runs periodically via cron to keep database updated with latest candles.

Usage:
    python scripts/auto_collect_data.py           # Collect all assets
    python scripts/auto_collect_data.py --btc     # BTC only
    python scripts/auto_collect_data.py --altcoins # ETH/SOL only
"""

# pylint: disable=broad-exception-caught

import argparse
import sqlite3
import sys
import time
from pathlib import Path
from datetime import datetime, timedelta, timezone
from typing import Any

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import requests


SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"
TIMEFRAMES = {
    "minute15": "15m",
    "minute60": "1h",
    "minute240": "4h",
    "day": "1d",
}
TIMEFRAME_MS = {
    "minute15": 15 * 60 * 1000,
    "minute60": 60 * 60 * 1000,
    "minute240": 4 * 60 * 60 * 1000,
    "day": 24 * 60 * 60 * 1000,
}

ASSETS = {
    "BTC": {
        "symbol": "BTCUSDT",
        "db_name": "binance_bitcoin.db",
        "prefixes": ("btc", "binance"),
        "timeframes": ("minute15", "minute60", "minute240", "day"),
    },
    "ETH": {
        "symbol": "ETHUSDT",
        "db_name": "binance_ethereum.db",
        "prefixes": ("ethereum", "binance"),
        "timeframes": ("minute15", "minute60", "minute240", "day"),
    },
    "SOL": {
        "symbol": "SOLUSDT",
        "db_name": "binance_solana.db",
        "prefixes": ("solana",),
        "timeframes": ("minute15", "minute60", "minute240", "day"),
    },
}


def _table_name(prefix: str, timeframe: str) -> str:
    return f"{prefix}_{timeframe}"


def _ensure_ohlcv_table(conn: sqlite3.Connection, table_name: str) -> None:
    conn.execute(
        f"""
        CREATE TABLE IF NOT EXISTS {table_name} (
            timestamp TEXT PRIMARY KEY,
            open REAL NOT NULL,
            high REAL NOT NULL,
            low REAL NOT NULL,
            close REAL NOT NULL,
            volume REAL NOT NULL,
            quote_volume REAL,
            trades INTEGER,
            funding_rate REAL DEFAULT 0.0
        )
        """
    )


def _table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table_name})")]


def _get_last_timestamp(conn: sqlite3.Connection, table_name: str) -> str | None:
    _ensure_ohlcv_table(conn, table_name)
    cursor = conn.execute(f"SELECT MAX(timestamp) FROM {table_name}")
    row = cursor.fetchone()
    return row[0] if row and row[0] else None


def _timestamp_to_ms(value: str) -> int:
    return int(
        datetime.fromisoformat(value).replace(tzinfo=timezone.utc).timestamp() * 1000
    )


def _fetch_klines(symbol: str, timeframe: str, start_ms: int, end_ms: int) -> list[list[Any]]:
    rows: list[list[Any]] = []
    cursor = start_ms
    retries = 0
    while cursor < end_ms:
        try:
            response = requests.get(
                SPOT_KLINES_URL,
                params={
                    "symbol": symbol,
                    "interval": TIMEFRAMES[timeframe],
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
                timeout=30,
            )
            if response.status_code == 429:
                retry_after = float(response.headers.get("Retry-After", "1"))
                time.sleep(max(1.0, retry_after))
                continue
            response.raise_for_status()
            chunk = response.json()
        except (requests.RequestException, ValueError):
            retries += 1
            if retries > 5:
                raise
            time.sleep(min(30, retries * 2))
            continue

        retries = 0
        if not chunk:
            break
        rows.extend(chunk)
        next_cursor = int(chunk[-1][0]) + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(chunk) < 1000:
            break
        time.sleep(0.03)
    return rows


def _normalize_klines(raw_rows: list[list[Any]]) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for row in raw_rows:
        ts = datetime.fromtimestamp(row[0] / 1000, tz=timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%S"
        )
        normalized.append(
            {
                "timestamp": ts,
                "open": float(row[1]),
                "high": float(row[2]),
                "low": float(row[3]),
                "close": float(row[4]),
                "volume": float(row[5]),
                "quote_volume": float(row[7]),
                "trades": int(row[8]),
                "funding_rate": 0.0,
            }
        )
    return normalized


def _insert_rows(conn: sqlite3.Connection, table_name: str, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    _ensure_ohlcv_table(conn, table_name)
    columns = _table_columns(conn, table_name)
    insert_cols = [
        col
        for col in (
            "timestamp",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "quote_volume",
            "trades",
            "funding_rate",
        )
        if col in columns
    ]
    placeholders = ", ".join(["?"] * len(insert_cols))
    col_sql = ", ".join(insert_cols)
    values = [tuple(row[col] for col in insert_cols) for row in rows]
    conn.executemany(
        f"INSERT OR REPLACE INTO {table_name} ({col_sql}) VALUES ({placeholders})",
        values,
    )
    return len(values)


def collect_btc():
    """Collect BTC data using existing collector."""
    collect_asset("BTC")


def collect_altcoins():
    """Collect ETH and SOL data."""
    collect_asset("ETH")
    collect_asset("SOL")


def collect_asset(asset: str) -> None:
    config = ASSETS[asset]
    db_path = PROJECT_ROOT / "data" / config["db_name"]
    end_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    print(f"[{asset}] Collecting data...")

    conn = sqlite3.connect(str(db_path))
    try:
        for timeframe in config["timeframes"]:
            table_names = [
                _table_name(prefix, timeframe) for prefix in config["prefixes"]
            ]
            last_values = [
                _get_last_timestamp(conn, table_name) for table_name in table_names
            ]
            existing = [value for value in last_values if value]
            if existing:
                start_ms = min(_timestamp_to_ms(value) for value in existing)
                start_ms += TIMEFRAME_MS[timeframe]
                print(f"  {timeframe}: resuming from {min(existing)}")
            else:
                start_ms = int(
                    (datetime.now(timezone.utc) - timedelta(days=30)).timestamp()
                    * 1000
                )
                print(f"  {timeframe}: no existing rows, using 30d bootstrap")

            raw = _fetch_klines(config["symbol"], timeframe, start_ms, end_ms)
            rows = _normalize_klines(raw)
            inserted = 0
            for table_name in table_names:
                inserted = max(inserted, _insert_rows(conn, table_name, rows))
            conn.commit()
            if rows:
                print(
                    f"  {timeframe}: {inserted} rows "
                    f"({rows[0]['timestamp']} -> {rows[-1]['timestamp']})"
                )
            else:
                print(f"  {timeframe}: no new rows")
            time.sleep(0.1)
    except Exception as exc:
        conn.rollback()
        print(f"  ERROR: {exc}")
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description="Auto data collector for trading bot")
    parser.add_argument("--btc", action="store_true", help="Collect BTC only")
    parser.add_argument("--eth", action="store_true", help="Collect ETH only")
    parser.add_argument("--sol", action="store_true", help="Collect SOL only")
    parser.add_argument("--altcoins", action="store_true", help="Collect ETH/SOL only")
    args = parser.parse_args()

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Auto data collection started")

    if args.btc:
        collect_btc()
    elif args.eth:
        collect_asset("ETH")
    elif args.sol:
        collect_asset("SOL")
    elif args.altcoins:
        collect_altcoins()
    else:
        # Collect all
        collect_btc()
        collect_altcoins()

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Auto data collection completed")


if __name__ == "__main__":
    main()
