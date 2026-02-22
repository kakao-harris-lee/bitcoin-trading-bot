#!/usr/bin/env python3
"""Collect Binance spot OHLCV for allocation universe symbols.

Primary use:
- Build unified multi-coin dataset for bull-follow training/backtest.
"""

from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "universe_backtest_4h"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "reports"

BINANCE_KLINES_URL = "https://api.binance.com/api/v3/klines"

INTERVAL_MAP = {
    "minute15": "15m",
    "minute60": "1h",
    "minute240": "4h",
    "day": "1d",
}


@dataclass(frozen=True)
class CollectResult:
    symbol: str
    rows: int
    first_ts: str
    last_ts: str
    output_file: str
    status: str
    error: str = ""


def _load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _to_repo_path(path: Path) -> str:
    resolved = path.resolve()
    try:
        return str(resolved.relative_to(PROJECT_ROOT))
    except ValueError:
        return str(resolved)


def _dedupe_keep_order(values: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for v in values:
        key = v.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append(key)
    return out


def resolve_symbols(
    config: dict[str, Any],
    strategy_id: str,
    explicit_symbols: list[str] | None,
    include_reference: bool,
    exclude_symbols: list[str] | None,
) -> list[str]:
    if explicit_symbols:
        symbols = [s.strip().upper() for s in explicit_symbols if s.strip()]
        return _dedupe_keep_order(symbols)

    strategy_symbols = (
        config.get("strategies", {}).get(strategy_id, {}).get("symbols", [])
    )
    root_symbols = config.get("symbols", [])

    symbols = (
        [str(s).upper() for s in strategy_symbols]
        if strategy_symbols
        else [str(s).upper() for s in root_symbols]
    )

    if include_reference:
        symbols = ["BTC", "ETH"] + symbols

    resolved = _dedupe_keep_order(symbols)
    excluded = {s.upper() for s in (exclude_symbols or [])}
    if excluded:
        resolved = [s for s in resolved if s not in excluded]
    return resolved


def _date_to_ms(date_str: str) -> int:
    return int(pd.Timestamp(date_str, tz="UTC").timestamp() * 1000)


def fetch_symbol_klines(
    symbol: str,
    interval: str,
    start_ms: int,
    end_ms: int,
    request_sleep: float = 0.03,
    max_retries: int = 5,
) -> list[list[Any]]:
    rows: list[list[Any]] = []
    cursor = start_ms
    retries = 0

    while cursor < end_ms:
        try:
            resp = requests.get(
                BINANCE_KLINES_URL,
                params={
                    "symbol": f"{symbol}USDT",
                    "interval": interval,
                    "startTime": cursor,
                    "endTime": end_ms,
                    "limit": 1000,
                },
                timeout=30,
            )

            if resp.status_code == 429:
                retry_after = float(resp.headers.get("Retry-After", "1"))
                time.sleep(max(1.0, retry_after))
                continue

            resp.raise_for_status()
            chunk = resp.json()
        except (requests.RequestException, ValueError):
            retries += 1
            if retries > max_retries:
                raise
            time.sleep(min(20.0, retries * 1.5))
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

        time.sleep(request_sleep)

    return rows


def klines_to_frame(raw_rows: list[list[Any]]) -> pd.DataFrame:
    if not raw_rows:
        return pd.DataFrame(
            columns=["timestamp", "open", "high", "low", "close", "volume"]
        )

    frame = pd.DataFrame(
        raw_rows,
        columns=[
            "open_time",
            "open",
            "high",
            "low",
            "close",
            "volume",
            "close_time",
            "quote_volume",
            "trades",
            "taker_buy_base",
            "taker_buy_quote",
            "ignore",
        ],
    )

    frame["timestamp"] = pd.to_datetime(
        frame["open_time"], unit="ms", utc=True
    ).dt.tz_convert(None)
    for col in ["open", "high", "low", "close", "volume"]:
        frame[col] = frame[col].astype(float)

    out = frame[["timestamp", "open", "high", "low", "close", "volume"]].copy()
    out = (
        out.drop_duplicates(subset=["timestamp"])
        .sort_values("timestamp")
        .reset_index(drop=True)
    )
    return out


def write_symbol_csv(frame: pd.DataFrame, output_file: Path) -> None:
    output_file.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(output_file, index=False)


def collect_universe(
    symbols: list[str],
    timeframe: str,
    start_date: str,
    end_date: str,
    output_dir: Path,
    overwrite: bool,
    request_sleep: float,
) -> list[CollectResult]:
    start_ms = _date_to_ms(start_date)
    end_ms = _date_to_ms(end_date)
    interval = INTERVAL_MAP[timeframe]

    results: list[CollectResult] = []

    for i, symbol in enumerate(symbols, start=1):
        output_file = output_dir / f"{symbol.lower()}_{timeframe}.csv"
        if output_file.exists() and not overwrite:
            try:
                frame_existing = pd.read_csv(output_file)
                rows = int(len(frame_existing))
                first_ts = str(frame_existing["timestamp"].iloc[0]) if rows > 0 else ""
                last_ts = str(frame_existing["timestamp"].iloc[-1]) if rows > 0 else ""
            except Exception:
                rows = 0
                first_ts = ""
                last_ts = ""
            print(f"[{i}/{len(symbols)}] {symbol}: skip existing ({rows} rows)")
            results.append(
                CollectResult(
                    symbol=symbol,
                    rows=rows,
                    first_ts=first_ts,
                    last_ts=last_ts,
                    output_file=_to_repo_path(output_file),
                    status="skipped",
                )
            )
            continue

        print(f"[{i}/{len(symbols)}] {symbol}: collecting {timeframe} ...")
        try:
            raw = fetch_symbol_klines(
                symbol=symbol,
                interval=interval,
                start_ms=start_ms,
                end_ms=end_ms,
                request_sleep=request_sleep,
            )
            frame = klines_to_frame(raw)
            write_symbol_csv(frame, output_file)

            row_count = int(len(frame))
            first_ts = str(frame["timestamp"].iloc[0]) if row_count > 0 else ""
            last_ts = str(frame["timestamp"].iloc[-1]) if row_count > 0 else ""
            print(f"  -> rows={row_count} range=({first_ts} .. {last_ts})")
            results.append(
                CollectResult(
                    symbol=symbol,
                    rows=row_count,
                    first_ts=first_ts,
                    last_ts=last_ts,
                    output_file=_to_repo_path(output_file),
                    status="ok",
                )
            )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            print(f"  -> failed: {exc}")
            results.append(
                CollectResult(
                    symbol=symbol,
                    rows=0,
                    first_ts="",
                    last_ts="",
                    output_file=_to_repo_path(output_file),
                    status="failed",
                    error=str(exc),
                )
            )

    return results


def write_reports(
    results: list[CollectResult],
    report_dir: Path,
    timeframe: str,
    strategy_id: str,
    start_date: str,
    end_date: str,
) -> tuple[Path, Path]:
    report_dir.mkdir(parents=True, exist_ok=True)
    run_tag = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    csv_path = report_dir / f"universe_collect_{timeframe}_{run_tag}.csv"
    md_path = report_dir / f"universe_collect_{timeframe}_{run_tag}.md"

    df = pd.DataFrame([r.__dict__ for r in results])
    df.to_csv(csv_path, index=False)

    ok_count = int((df["status"] == "ok").sum()) if not df.empty else 0
    skip_count = int((df["status"] == "skipped").sum()) if not df.empty else 0
    fail_count = int((df["status"] == "failed").sum()) if not df.empty else 0

    lines = [
        "# Universe Spot Collection Report",
        "",
        f"- strategy_id: `{strategy_id}`",
        f"- timeframe: `{timeframe}`",
        f"- date_range: `{start_date}` -> `{end_date}`",
        f"- total_symbols: `{len(results)}`",
        f"- ok/skipped/failed: `{ok_count}/{skip_count}/{fail_count}`",
        f"- csv: `{_to_repo_path(csv_path)}`",
        "",
        "| Symbol | Status | Rows | First Timestamp | Last Timestamp | File |",
        "|---|---|---:|---|---|---|",
    ]

    for r in results:
        lines.append(
            f"| {r.symbol} | {r.status} | {r.rows} | {r.first_ts} | {r.last_ts} | {r.output_file} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return csv_path, md_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Collect Binance spot OHLCV for universe symbols"
    )
    parser.add_argument(
        "--config", default=str(DEFAULT_CONFIG_PATH), help="Allocation JSON path"
    )
    parser.add_argument(
        "--strategy-id",
        default="mlp_direction_bnb",
        help="Strategy id to source symbols",
    )
    parser.add_argument(
        "--symbols", nargs="+", default=None, help="Explicit symbol list override"
    )
    parser.add_argument(
        "--exclude-symbols",
        nargs="+",
        default=["BTC", "ETH", "BNB"],
        help="Exclude majors to keep base MLP universe unchanged",
    )
    parser.add_argument(
        "--include-reference", action="store_true", help="Always include BTC/ETH"
    )
    parser.add_argument(
        "--timeframe", choices=tuple(INTERVAL_MAP.keys()), default="minute240"
    )
    parser.add_argument("--start-date", default="2020-01-01")
    parser.add_argument(
        "--end-date",
        default=datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    )
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--request-sleep", type=float, default=0.03)
    parser.add_argument(
        "--no-overwrite", action="store_true", help="Skip files that already exist"
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config_path = Path(args.config)
    output_dir = Path(args.output_dir).resolve()
    report_dir = Path(args.report_dir).resolve()

    config = _load_json(config_path)
    symbols = resolve_symbols(
        config=config,
        strategy_id=args.strategy_id,
        explicit_symbols=args.symbols,
        include_reference=args.include_reference,
        exclude_symbols=args.exclude_symbols,
    )
    if not symbols:
        print("No symbols resolved. Nothing to collect.")
        return 1

    print(
        f"Collecting {len(symbols)} symbols from {args.start_date} to {args.end_date}"
    )
    results = collect_universe(
        symbols=symbols,
        timeframe=args.timeframe,
        start_date=args.start_date,
        end_date=args.end_date,
        output_dir=output_dir,
        overwrite=not args.no_overwrite,
        request_sleep=args.request_sleep,
    )

    csv_path, md_path = write_reports(
        results=results,
        report_dir=report_dir,
        timeframe=args.timeframe,
        strategy_id=args.strategy_id,
        start_date=args.start_date,
        end_date=args.end_date,
    )

    print(f"Report CSV: {_to_repo_path(csv_path)}")
    print(f"Report MD: {_to_repo_path(md_path)}")

    failed = sum(1 for r in results if r.status == "failed")
    return 1 if failed > 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
