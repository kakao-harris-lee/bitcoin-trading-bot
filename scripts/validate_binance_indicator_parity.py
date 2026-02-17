#!/usr/bin/env python3
"""Validate local OHLCV/indicator parity against Binance spot candles.

Compares local DB candles to Binance spot klines and reports:
- OHLC max absolute diff
- major indicator max absolute diff (computed with same precompute pipeline)

Usage:
  python scripts/validate_binance_indicator_parity.py \
    --start 2024-01-01 --end 2025-01-01 --interval 4h
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path
import sys
from typing import Iterable

import numpy as np
import pandas as pd
import requests

# Add project root to import path (same pattern used by other scripts).
PROJECT_ROOT = Path(__file__).parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.data_loader import DataLoader
from trading.indicators.precompute import add_all_indicators


SYMBOL_DB_MAP: dict[str, Path] = {
    "BTCUSDT": Path("data/binance_bitcoin.db"),
    "ETHUSDT": Path("data/binance_ethereum.db"),
    "SOLUSDT": Path("data/binance_solana.db"),
    "BNBUSDT": Path("data/binance_bnb.db"),
    "XRPUSDT": Path("data/binance_xrp.db"),
}

INTERVAL_TO_TIMEFRAME = {
    "4h": "minute240",
    "1h": "minute60",
    "1d": "day",
}


@dataclass
class CompareResult:
    symbol: str
    market: str
    rows: int
    ohlc_max_abs_diff: float
    close_max_abs_diff: float
    volume_max_abs_diff: float
    rsi_max_abs_diff: float
    mfi_max_abs_diff: float
    adx_max_abs_diff: float
    bb_upper_max_abs_diff: float
    macd_max_abs_diff: float


def _fetch_klines(
    symbol: str,
    interval: str,
    start: str,
    end: str,
) -> pd.DataFrame:
    base_url = "https://api.binance.com/api/v3/klines"

    start_ms = int(pd.Timestamp(start, tz="UTC").timestamp() * 1000)
    end_ms = int(pd.Timestamp(end, tz="UTC").timestamp() * 1000)

    cursor = start_ms
    rows: list[list] = []
    while cursor < end_ms:
        response = requests.get(
            base_url,
            params={
                "symbol": symbol,
                "interval": interval,
                "startTime": cursor,
                "endTime": end_ms,
                "limit": 1000,
            },
            timeout=20,
        )
        response.raise_for_status()
        chunk = response.json()
        if not chunk:
            break
        rows.extend(chunk)
        next_cursor = int(chunk[-1][0]) + 1
        if next_cursor <= cursor:
            break
        cursor = next_cursor
        if len(chunk) < 1000:
            break

    if not rows:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])

    df = pd.DataFrame(
        rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_asset_volume",
            "num_trades",
            "taker_buy_base_volume",
            "taker_buy_quote_volume",
            "ignore",
        ],
    )
    df["timestamp"] = pd.to_datetime(df["open_time"], unit="ms", utc=True).dt.tz_convert(None)
    for col in ("open", "high", "low", "close", "volume"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df[["timestamp", "open", "high", "low", "close", "volume"]]


def _max_abs_diff(a: Iterable[float], b: Iterable[float]) -> float:
    av = np.asarray(list(a), dtype=float)
    bv = np.asarray(list(b), dtype=float)
    mask = np.isfinite(av) & np.isfinite(bv)
    if int(mask.sum()) <= 0:
        return float("nan")
    return float(np.max(np.abs(av[mask] - bv[mask])))


def _compare_single(symbol: str, db_path: Path, interval: str, start: str, end: str) -> CompareResult:
    timeframe = INTERVAL_TO_TIMEFRAME[interval]
    with DataLoader(db_path=str(db_path)) as loader:
        local = loader.load_timeframe(timeframe, start, end)
    local = local[["timestamp", "open", "high", "low", "close", "volume"]].copy()

    remote = _fetch_klines(symbol=symbol, interval=interval, start=start, end=end)
    merged = local.merge(remote, on="timestamp", suffixes=("_local", "_remote"))
    if merged.empty:
        return CompareResult(
            symbol=symbol,
            market="spot",
            rows=0,
            ohlc_max_abs_diff=float("nan"),
            close_max_abs_diff=float("nan"),
            volume_max_abs_diff=float("nan"),
            rsi_max_abs_diff=float("nan"),
            mfi_max_abs_diff=float("nan"),
            adx_max_abs_diff=float("nan"),
            bb_upper_max_abs_diff=float("nan"),
            macd_max_abs_diff=float("nan"),
        )

    ohlc_max = max(
        _max_abs_diff(merged["open_local"], merged["open_remote"]),
        _max_abs_diff(merged["high_local"], merged["high_remote"]),
        _max_abs_diff(merged["low_local"], merged["low_remote"]),
        _max_abs_diff(merged["close_local"], merged["close_remote"]),
    )

    left = merged[["timestamp", "open_local", "high_local", "low_local", "close_local", "volume_local"]].rename(
        columns=lambda c: c.replace("_local", "")
    )
    right = merged[["timestamp", "open_remote", "high_remote", "low_remote", "close_remote", "volume_remote"]].rename(
        columns=lambda c: c.replace("_remote", "")
    )
    for col in ("open", "high", "low", "close", "volume"):
        left[col] = pd.to_numeric(left[col], errors="coerce").astype(np.float64)
        right[col] = pd.to_numeric(right[col], errors="coerce").astype(np.float64)
    add_all_indicators(left)
    add_all_indicators(right)

    return CompareResult(
        symbol=symbol,
        market="spot",
        rows=len(merged),
        ohlc_max_abs_diff=ohlc_max,
        close_max_abs_diff=_max_abs_diff(merged["close_local"], merged["close_remote"]),
        volume_max_abs_diff=_max_abs_diff(merged["volume_local"], merged["volume_remote"]),
        rsi_max_abs_diff=_max_abs_diff(left["rsi"], right["rsi"]),
        mfi_max_abs_diff=_max_abs_diff(left["mfi"], right["mfi"]),
        adx_max_abs_diff=_max_abs_diff(left["adx"], right["adx"]),
        bb_upper_max_abs_diff=_max_abs_diff(left["bb_upper"], right["bb_upper"]),
        macd_max_abs_diff=_max_abs_diff(left["macd"], right["macd"]),
    )


def _to_markdown(rows: list[CompareResult], start: str, end: str, interval: str) -> str:
    lines = [
        "# Binance Indicator Parity Report",
        "",
        f"- period: {start} ~ {end}",
        f"- interval: {interval}",
        "- market mode: spot",
        "",
        "| symbol | selected_market | rows | ohlc_max | close_max | volume_max | rsi_max | mfi_max | adx_max | bb_upper_max | macd_max |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row.symbol} | {row.market} | {row.rows} | "
            f"{row.ohlc_max_abs_diff:.12g} | {row.close_max_abs_diff:.12g} | {row.volume_max_abs_diff:.12g} | {row.rsi_max_abs_diff:.12g} | "
            f"{row.mfi_max_abs_diff:.12g} | {row.adx_max_abs_diff:.12g} | "
            f"{row.bb_upper_max_abs_diff:.12g} | {row.macd_max_abs_diff:.12g} |"
        )
    return "\n".join(lines) + "\n"


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate local indicators against Binance candles.")
    parser.add_argument("--start", default="2024-01-01")
    parser.add_argument("--end", default="2025-01-01")
    parser.add_argument("--interval", default="4h", choices=sorted(INTERVAL_TO_TIMEFRAME.keys()))
    parser.add_argument("--output", default="")
    args = parser.parse_args()

    results: list[CompareResult] = []
    for symbol, db_path in SYMBOL_DB_MAP.items():
        result = _compare_single(symbol, db_path, args.interval, args.start, args.end)
        results.append(result)

    for row in results:
        print(
            f"{row.symbol:8s} market={row.market:7s} rows={row.rows:5d} "
            f"ohlc_max={row.ohlc_max_abs_diff:.12g} close_max={row.close_max_abs_diff:.12g} "
            f"vol_max={row.volume_max_abs_diff:.12g} "
            f"rsi={row.rsi_max_abs_diff:.12g} mfi={row.mfi_max_abs_diff:.12g} "
            f"adx={row.adx_max_abs_diff:.12g} bb_u={row.bb_upper_max_abs_diff:.12g} macd={row.macd_max_abs_diff:.12g}"
        )

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(_to_markdown(results, args.start, args.end, args.interval), encoding="utf-8")
        print(f"saved report: {output_path}")


if __name__ == "__main__":
    main()
