#!/usr/bin/env python3
"""Recollect spot OHLCV data for all trading assets.

This script force-refreshes DB tables used by backtest/paper/live workflows
with Binance SPOT candles only.
"""

from __future__ import annotations

import argparse
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = PROJECT_ROOT / "data"

SPOT_KLINES_URL = "https://api.binance.com/api/v3/klines"

INTERVAL_MAP = {
    "minute15": "15m",
    "minute60": "1h",
    "minute240": "4h",
    "day": "1d",
}


@dataclass(frozen=True)
class AssetPlan:
    symbol: str
    db_path: Path
    prefixes: tuple[str, ...]
    timeframes: tuple[str, ...]


ASSET_PLANS: tuple[AssetPlan, ...] = (
    AssetPlan(
        symbol="BTCUSDT",
        db_path=DATA_DIR / "binance_bitcoin.db",
        prefixes=("btc", "binance"),
        timeframes=("minute15", "minute60", "minute240", "day"),
    ),
    AssetPlan(
        symbol="ETHUSDT",
        db_path=DATA_DIR / "binance_ethereum.db",
        prefixes=("ethereum", "binance"),
        timeframes=("minute15", "minute60", "minute240", "day"),
    ),
    AssetPlan(
        symbol="SOLUSDT",
        db_path=DATA_DIR / "binance_solana.db",
        prefixes=("solana",),
        timeframes=("minute15", "minute60", "minute240", "day"),
    ),
    AssetPlan(
        symbol="BNBUSDT",
        db_path=DATA_DIR / "binance_bnb.db",
        prefixes=("bnb",),
        timeframes=("minute60", "minute240", "day"),
    ),
    AssetPlan(
        symbol="XRPUSDT",
        db_path=DATA_DIR / "binance_xrp.db",
        prefixes=("xrp",),
        timeframes=("minute15", "minute60", "minute240", "day"),
    ),
)


def fetch_spot_klines(symbol: str, interval: str, start_ms: int, end_ms: int) -> list[list[Any]]:
    rows: list[list[Any]] = []
    cursor = start_ms
    retries = 0

    while cursor < end_ms:
        try:
            response = requests.get(
                SPOT_KLINES_URL,
                params={
                    "symbol": symbol,
                    "interval": interval,
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


def normalize_rows(raw_rows: list[list[Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for k in raw_rows:
        ts = pd.to_datetime(int(k[0]), unit="ms", utc=True).tz_convert(None).strftime("%Y-%m-%dT%H:%M:%S")
        out.append(
            {
                "timestamp": ts,
                "open": float(k[1]),
                "high": float(k[2]),
                "low": float(k[3]),
                "close": float(k[4]),
                "volume": float(k[5]),
                "quote_volume": float(k[7]),
                "trades": int(k[8]),
                "funding_rate": 0.0,
            }
        )
    return out


def ensure_ohlcv_table(conn: sqlite3.Connection, table_name: str) -> None:
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


def table_columns(conn: sqlite3.Connection, table_name: str) -> list[str]:
    cursor = conn.execute(f"PRAGMA table_info({table_name})")
    return [row[1] for row in cursor.fetchall()]


def replace_table_rows(conn: sqlite3.Connection, table_name: str, rows: list[dict[str, Any]]) -> int:
    cols = table_columns(conn, table_name)
    insert_cols = [c for c in ("timestamp", "open", "high", "low", "close", "volume", "quote_volume", "trades", "funding_rate") if c in cols]
    if not insert_cols:
        return 0

    conn.execute(f"DELETE FROM {table_name}")
    placeholders = ", ".join(["?"] * len(insert_cols))
    col_sql = ", ".join(insert_cols)
    values = [tuple(r[c] for c in insert_cols) for r in rows]
    conn.executemany(
        f"INSERT OR REPLACE INTO {table_name} ({col_sql}) VALUES ({placeholders})",
        values,
    )
    return len(values)


def clear_funding_tables(conn: sqlite3.Connection, prefixes: tuple[str, ...]) -> None:
    for prefix in prefixes:
        table = f"{prefix}_funding_rate"
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        )
        if cursor.fetchone():
            conn.execute(f"DELETE FROM {table}")


def recollect_asset(plan: AssetPlan, start: str, end: str) -> None:
    print(f"\n=== {plan.symbol} ({plan.db_path.name}) ===")
    start_ms = int(pd.Timestamp(start, tz=timezone.utc).timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz=timezone.utc).timestamp() * 1000)

    cache: dict[str, list[dict[str, Any]]] = {}
    conn = sqlite3.connect(str(plan.db_path))
    try:
        for timeframe in plan.timeframes:
            interval = INTERVAL_MAP[timeframe]
            print(f"  fetching {timeframe} ({interval}) ...")
            raw = fetch_spot_klines(plan.symbol, interval, start_ms, end_ms)
            normalized = normalize_rows(raw)
            cache[timeframe] = normalized
            if normalized:
                print(f"    fetched {len(normalized):,} rows ({normalized[0]['timestamp']} -> {normalized[-1]['timestamp']})")
            else:
                print("    fetched 0 rows")

        for prefix in plan.prefixes:
            for timeframe in plan.timeframes:
                table = f"{prefix}_{timeframe}"
                ensure_ohlcv_table(conn, table)
                count = replace_table_rows(conn, table, cache[timeframe])
                print(f"  wrote {table}: {count:,} rows")

        clear_funding_tables(conn, plan.prefixes)
        conn.commit()
    finally:
        conn.close()


def show_summary(plan: AssetPlan) -> None:
    conn = sqlite3.connect(str(plan.db_path))
    try:
        print(f"\n[{plan.db_path.name}]")
        for prefix in plan.prefixes:
            for timeframe in plan.timeframes:
                table = f"{prefix}_{timeframe}"
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name=?",
                    (table,),
                )
                if not cursor.fetchone():
                    continue
                cursor = conn.execute(f"SELECT COUNT(*), MIN(timestamp), MAX(timestamp) FROM {table}")
                count, min_ts, max_ts = cursor.fetchone()
                print(f"  {table:20s} {count:8d} {min_ts} -> {max_ts}")
    finally:
        conn.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Recollect spot OHLCV data for all assets.")
    parser.add_argument("--start", default="2020-01-01", help="Start date (YYYY-MM-DD)")
    parser.add_argument(
        "--end",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        help="End date (YYYY-MM-DD, exclusive at exchange side)",
    )
    args = parser.parse_args()

    print(f"Spot recollect start: {args.start} -> {args.end}")
    for plan in ASSET_PLANS:
        recollect_asset(plan, args.start, args.end)

    print("\n=== Summary ===")
    for plan in ASSET_PLANS:
        show_summary(plan)


if __name__ == "__main__":
    main()
