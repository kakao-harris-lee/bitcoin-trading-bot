#!/usr/bin/env python3
"""Build 7-day selector monitoring KPI report from Redis streams.

This report focuses on:
- selector alert frequency
- signal-event mix (ENTRY_READY / NEW_CANDIDATE / INVALIDATED / SCORE_JUMP)
- conversion from selector signal to executed BUY trade
"""

from __future__ import annotations

import argparse
import csv
import json
from bisect import bisect_left
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import mean
from typing import Any

import redis


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REPORT_DIR = PROJECT_ROOT / "logs" / "paper_soak"


@dataclass(frozen=True)
class SelectorEvent:
    ts_ms: int
    changed: bool
    selected_count: int
    universe_size: int
    dq_blocked_count: int
    rejection_counts: dict[str, int]
    signal_events: list[dict[str, Any]]


@dataclass(frozen=True)
class TradeEvent:
    ts_ms: int
    symbol: str
    side: str
    strategy: str
    paper: bool


def _to_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _id_to_ms(redis_id: str) -> int:
    try:
        return int(redis_id.split("-", maxsplit=1)[0])
    except (TypeError, ValueError, AttributeError, IndexError):
        return 0


def _parse_json_list(raw: Any) -> list[Any]:
    if raw is None:
        return []
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def _parse_json_dict(raw: Any) -> dict[str, Any]:
    if raw is None:
        return {}
    try:
        parsed = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate 7-day selector monitoring KPI report.")
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument(
        "--lookback-hours",
        type=int,
        default=0,
        help="If >0, overrides --lookback-days with hour-based window.",
    )
    parser.add_argument("--strategy", default="mlp_direction_bnb")
    parser.add_argument("--selector-stream", default="strategy:selector:events")
    parser.add_argument("--trades-stream", default="trades")
    parser.add_argument("--entry-window-minutes", type=int, default=240)
    parser.add_argument("--max-selector-entries", type=int, default=300000)
    parser.add_argument("--max-trade-entries", type=int, default=300000)
    parser.add_argument("--redis-host", default="localhost")
    parser.add_argument("--redis-port", type=int, default=6379)
    parser.add_argument("--redis-db", type=int, default=0)
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--entry-ready-min-conv", type=float, default=0.15)
    parser.add_argument("--new-candidate-min-conv", type=float, default=0.08)
    parser.add_argument("--max-dq-blocked-ratio", type=float, default=0.40)
    parser.add_argument("--max-stale-reject-ratio", type=float, default=0.50)
    parser.add_argument("--min-events-per-day", type=float, default=8.0)
    parser.add_argument("--max-events-per-day", type=float, default=250.0)
    return parser.parse_args()


def collect_selector_events(
    r: redis.Redis,
    *,
    stream: str,
    strategy: str,
    start_ms: int,
    max_entries: int,
) -> list[SelectorEvent]:
    rows: list[SelectorEvent] = []
    entries = r.xrevrange(stream, count=max_entries)
    for redis_id, data in entries:
        ts_ms = _id_to_ms(redis_id)
        if ts_ms <= 0:
            continue
        if ts_ms < start_ms:
            break
        if str(data.get("strategy", "")) != strategy:
            continue
        rejection_counts_raw = _parse_json_dict(data.get("rejection_counts"))
        rejection_counts = {str(k): _to_int(v) for k, v in rejection_counts_raw.items()}
        rows.append(
            SelectorEvent(
                ts_ms=ts_ms,
                changed=str(data.get("changed", "false")).lower() == "true",
                selected_count=_to_int(data.get("selected_count"), 0),
                universe_size=max(1, _to_int(data.get("universe_size"), 0)),
                dq_blocked_count=max(0, _to_int(data.get("dq_blocked_count"), 0)),
                rejection_counts=rejection_counts,
                signal_events=[x for x in _parse_json_list(data.get("signal_events")) if isinstance(x, dict)],
            )
        )
    rows.sort(key=lambda x: x.ts_ms)
    return rows


def collect_trades(
    r: redis.Redis,
    *,
    stream: str,
    strategy: str,
    start_ms: int,
    max_entries: int,
) -> list[TradeEvent]:
    rows: list[TradeEvent] = []
    entries = r.xrevrange(stream, count=max_entries)
    for redis_id, data in entries:
        ts_ms = _to_int(data.get("timestamp"), _id_to_ms(redis_id))
        if ts_ms <= 0:
            continue
        if ts_ms < start_ms:
            break
        if str(data.get("strategy", "")) != strategy:
            continue
        rows.append(
            TradeEvent(
                ts_ms=ts_ms,
                symbol=str(data.get("symbol", "")).upper(),
                side=str(data.get("side", "")).lower(),
                strategy=str(data.get("strategy", "")),
                paper=str(data.get("paper", "true")).lower() == "true",
            )
        )
    rows.sort(key=lambda x: x.ts_ms)
    return rows


def _find_trade_within_window(trade_times: list[int], start_ms: int, end_ms: int) -> int | None:
    idx = bisect_left(trade_times, start_ms)
    if idx >= len(trade_times):
        return None
    matched = trade_times[idx]
    return matched if matched <= end_ms else None


def _fmt_pct(value: float) -> str:
    return f"{value * 100.0:.2f}%"


def _criterion_status(ok: bool) -> str:
    return "PASS" if ok else "FAIL"


def main() -> int:
    args = parse_args()
    now = datetime.now()
    if args.lookback_hours > 0:
        lookback_seconds = float(args.lookback_hours) * 3600.0
        lookback_label = f"{args.lookback_hours}h"
    else:
        lookback_days = max(1, int(args.lookback_days))
        lookback_seconds = float(lookback_days) * 86400.0
        lookback_label = f"{lookback_days}d"

    start = now - timedelta(seconds=lookback_seconds)
    start_ms = int(start.timestamp() * 1000)
    window_ms = int(args.entry_window_minutes * 60 * 1000)
    report_dir = Path(args.report_dir).resolve()
    report_dir.mkdir(parents=True, exist_ok=True)

    r = redis.Redis(
        host=args.redis_host,
        port=args.redis_port,
        db=args.redis_db,
        decode_responses=True,
    )
    r.ping()

    selector_events = collect_selector_events(
        r,
        stream=args.selector_stream,
        strategy=args.strategy,
        start_ms=start_ms,
        max_entries=args.max_selector_entries,
    )
    trades = collect_trades(
        r,
        stream=args.trades_stream,
        strategy=args.strategy,
        start_ms=start_ms,
        max_entries=args.max_trade_entries,
    )

    buy_trades = [t for t in trades if t.paper and t.side == "buy" and t.symbol]
    buy_times_by_symbol: dict[str, list[int]] = defaultdict(list)
    for trade in buy_trades:
        buy_times_by_symbol[trade.symbol].append(trade.ts_ms)

    signal_rows: list[dict[str, Any]] = []
    type_counter: Counter[str] = Counter()
    rejection_counter: Counter[str] = Counter()
    dq_ratios: list[float] = []
    changed_count = 0

    for event in selector_events:
        if event.changed:
            changed_count += 1
        dq_ratios.append(event.dq_blocked_count / max(1, event.universe_size))
        rejection_counter.update(event.rejection_counts)

        for sig in event.signal_events:
            sig_type = str(sig.get("type", "")).upper()
            symbol = str(sig.get("symbol", "")).upper()
            score = _to_float(sig.get("score"), 0.0)
            if not sig_type or not symbol:
                continue
            type_counter[sig_type] += 1
            signal_rows.append(
                {
                    "ts_ms": event.ts_ms,
                    "timestamp": datetime.fromtimestamp(event.ts_ms / 1000.0).isoformat(timespec="seconds"),
                    "type": sig_type,
                    "symbol": symbol,
                    "score": round(score, 6),
                }
            )

    conversion_stats: dict[str, dict[str, Any]] = {}
    for sig_type in ("ENTRY_READY", "NEW_CANDIDATE"):
        subset = [row for row in signal_rows if row["type"] == sig_type]
        converted = 0
        delays_min: list[float] = []
        for row in subset:
            trade_times = buy_times_by_symbol.get(str(row["symbol"]), [])
            matched = _find_trade_within_window(trade_times, int(row["ts_ms"]), int(row["ts_ms"]) + window_ms)
            if matched is None:
                continue
            converted += 1
            delays_min.append((matched - int(row["ts_ms"])) / 60000.0)
        total = len(subset)
        conversion_stats[sig_type] = {
            "total": total,
            "converted": converted,
            "conversion_ratio": (converted / total) if total > 0 else 0.0,
            "avg_delay_min": mean(delays_min) if delays_min else 0.0,
        }

    total_selector_events = len(selector_events)
    changed_ratio = (changed_count / total_selector_events) if total_selector_events > 0 else 0.0
    days = max(lookback_seconds / 86400.0, 1e-9)
    events_per_day = total_selector_events / days
    if total_selector_events > 1:
        span_ms = selector_events[-1].ts_ms - selector_events[0].ts_ms
        covered_days = max(span_ms / 86_400_000.0, 1e-9)
    else:
        covered_days = 0.0
    events_per_day_covered = (total_selector_events / covered_days) if covered_days > 0 else 0.0
    coverage_ratio = min(1.0, covered_days / float(days)) if days > 0 else 0.0
    avg_dq_ratio = mean(dq_ratios) if dq_ratios else 0.0

    total_rejections = sum(rejection_counter.values())
    stale_rejections = int(rejection_counter.get("stale_price", 0))
    stale_reject_ratio = (stale_rejections / total_rejections) if total_rejections > 0 else 0.0

    daily: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "selector_events": 0,
            "changed_events": 0,
            "entry_ready": 0,
            "new_candidate": 0,
            "score_jump": 0,
            "invalidated": 0,
            "buys": 0,
            "dq_avg_ratio": [],
        }
    )

    for event in selector_events:
        day_key = datetime.fromtimestamp(event.ts_ms / 1000.0).strftime("%Y-%m-%d")
        day = daily[day_key]
        day["selector_events"] += 1
        day["changed_events"] += int(event.changed)
        day["dq_avg_ratio"].append(event.dq_blocked_count / max(1, event.universe_size))
        for sig in event.signal_events:
            sig_type = str(sig.get("type", "")).upper()
            if sig_type == "ENTRY_READY":
                day["entry_ready"] += 1
            elif sig_type == "NEW_CANDIDATE":
                day["new_candidate"] += 1
            elif sig_type == "SCORE_JUMP":
                day["score_jump"] += 1
            elif sig_type == "INVALIDATED":
                day["invalidated"] += 1

    for trade in buy_trades:
        day_key = datetime.fromtimestamp(trade.ts_ms / 1000.0).strftime("%Y-%m-%d")
        daily[day_key]["buys"] += 1

    daily_rows: list[dict[str, Any]] = []
    for day_key in sorted(daily.keys()):
        row = dict(daily[day_key])
        dq_vals = row.pop("dq_avg_ratio", [])
        row["dq_avg_ratio"] = mean(dq_vals) if dq_vals else 0.0
        row["date"] = day_key
        daily_rows.append(row)

    criteria = [
        {
            "name": "entry_ready_conversion",
            "value": conversion_stats["ENTRY_READY"]["conversion_ratio"],
            "threshold": args.entry_ready_min_conv,
            "condition": ">=",
            "ok": conversion_stats["ENTRY_READY"]["conversion_ratio"] >= args.entry_ready_min_conv,
        },
        {
            "name": "new_candidate_conversion",
            "value": conversion_stats["NEW_CANDIDATE"]["conversion_ratio"],
            "threshold": args.new_candidate_min_conv,
            "condition": ">=",
            "ok": conversion_stats["NEW_CANDIDATE"]["conversion_ratio"] >= args.new_candidate_min_conv,
        },
        {
            "name": "avg_dq_blocked_ratio",
            "value": avg_dq_ratio,
            "threshold": args.max_dq_blocked_ratio,
            "condition": "<=",
            "ok": avg_dq_ratio <= args.max_dq_blocked_ratio,
        },
        {
            "name": "stale_reject_ratio",
            "value": stale_reject_ratio,
            "threshold": args.max_stale_reject_ratio,
            "condition": "<=",
            "ok": stale_reject_ratio <= args.max_stale_reject_ratio,
        },
        {
            "name": "selector_events_per_day",
            "value": events_per_day_covered,
            "threshold": [args.min_events_per_day, args.max_events_per_day],
            "condition": "between",
            "ok": args.min_events_per_day <= events_per_day_covered <= args.max_events_per_day,
        },
        {
            "name": "lookback_coverage",
            "value": coverage_ratio,
            "threshold": 0.70,
            "condition": ">=",
            "ok": coverage_ratio >= 0.70,
        },
    ]

    run_tag = datetime.now().strftime("%Y%m%d_%H%M%S")
    base = report_dir / f"selector_monitor_7d_{run_tag}"
    daily_csv = Path(f"{base}_daily.csv")
    signals_csv = Path(f"{base}_signals.csv")
    summary_json = Path(f"{base}_summary.json")
    summary_md = Path(f"{base}_summary.md")

    with daily_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "date",
                "selector_events",
                "changed_events",
                "entry_ready",
                "new_candidate",
                "score_jump",
                "invalidated",
                "buys",
                "dq_avg_ratio",
            ],
        )
        writer.writeheader()
        for row in daily_rows:
            writer.writerow(row)

    with signals_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=["timestamp", "type", "symbol", "score", "converted_within_window", "conversion_delay_min"],
        )
        writer.writeheader()
        for row in signal_rows:
            trade_times = buy_times_by_symbol.get(str(row["symbol"]), [])
            matched = _find_trade_within_window(trade_times, int(row["ts_ms"]), int(row["ts_ms"]) + window_ms)
            writer.writerow(
                {
                    "timestamp": row["timestamp"],
                    "type": row["type"],
                    "symbol": row["symbol"],
                    "score": row["score"],
                    "converted_within_window": bool(matched is not None),
                    "conversion_delay_min": (
                        round((matched - int(row["ts_ms"])) / 60000.0, 3) if matched is not None else ""
                    ),
                }
            )

    summary_payload = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "lookback_days": args.lookback_days,
        "lookback_hours": args.lookback_hours,
        "lookback_label": lookback_label,
        "strategy": args.strategy,
        "entry_window_minutes": args.entry_window_minutes,
        "selector_events": total_selector_events,
        "changed_events": changed_count,
        "changed_ratio": changed_ratio,
        "events_per_day": events_per_day,
        "events_per_day_covered": events_per_day_covered,
        "covered_days": covered_days,
        "coverage_ratio": coverage_ratio,
        "buy_trades": len(buy_trades),
        "signal_type_counts": dict(type_counter),
        "conversion": conversion_stats,
        "avg_dq_blocked_ratio": avg_dq_ratio,
        "rejections_total": total_rejections,
        "stale_rejections": stale_rejections,
        "stale_reject_ratio": stale_reject_ratio,
        "criteria": criteria,
        "daily_csv": str(daily_csv),
        "signals_csv": str(signals_csv),
    }
    summary_json.write_text(json.dumps(summary_payload, indent=2), encoding="utf-8")

    lines: list[str] = []
    lines.append("# Selector 7D Monitoring Report")
    lines.append("")
    lines.append(f"- generated_at: `{summary_payload['generated_at']}`")
    lines.append(f"- strategy: `{args.strategy}`")
    lines.append(
        f"- window: `{lookback_label}` (entry_conversion_window `{args.entry_window_minutes}m`)"
    )
    lines.append("")
    lines.append("## KPI Snapshot")
    lines.append("")
    lines.append("| Metric | Value |")
    lines.append("|---|---:|")
    lines.append(f"| selector_events | {total_selector_events} |")
    lines.append(f"| changed_events | {changed_count} ({_fmt_pct(changed_ratio)}) |")
    lines.append(f"| events_per_day (requested {days:.2f}d) | {events_per_day:.2f} |")
    lines.append(f"| events_per_day (covered window) | {events_per_day_covered:.2f} |")
    lines.append(f"| covered_days | {covered_days:.2f} ({_fmt_pct(coverage_ratio)}) |")
    lines.append(f"| buy_trades | {len(buy_trades)} |")
    lines.append(
        f"| ENTRY_READY conversion | {conversion_stats['ENTRY_READY']['converted']}/{conversion_stats['ENTRY_READY']['total']} ({_fmt_pct(conversion_stats['ENTRY_READY']['conversion_ratio'])}) |"
    )
    lines.append(
        f"| NEW_CANDIDATE conversion | {conversion_stats['NEW_CANDIDATE']['converted']}/{conversion_stats['NEW_CANDIDATE']['total']} ({_fmt_pct(conversion_stats['NEW_CANDIDATE']['conversion_ratio'])}) |"
    )
    lines.append(
        f"| avg conversion delay (ENTRY_READY) | {conversion_stats['ENTRY_READY']['avg_delay_min']:.2f} min |"
    )
    lines.append(f"| avg dq_blocked_ratio | {_fmt_pct(avg_dq_ratio)} |")
    lines.append(f"| stale_reject_ratio | {_fmt_pct(stale_reject_ratio)} |")
    lines.append("")
    lines.append("## Criteria")
    lines.append("")
    lines.append("| Criterion | Value | Threshold | Status |")
    lines.append("|---|---:|---:|---|")
    for criterion in criteria:
        if criterion["condition"] == "between":
            threshold_text = f"{criterion['threshold'][0]:.2f}~{criterion['threshold'][1]:.2f}"
            value_text = f"{criterion['value']:.2f}"
        elif "ratio" in str(criterion["name"]) or "conversion" in str(criterion["name"]):
            threshold_text = _fmt_pct(float(criterion["threshold"]))
            value_text = _fmt_pct(float(criterion["value"]))
        else:
            threshold_text = f"{float(criterion['threshold']):.2f}"
            value_text = f"{float(criterion['value']):.2f}"
        lines.append(
            f"| {criterion['name']} | {value_text} | {criterion['condition']} {threshold_text} | {_criterion_status(bool(criterion['ok']))} |"
        )
    lines.append("")
    lines.append("## Signal Type Counts")
    lines.append("")
    lines.append("| Type | Count |")
    lines.append("|---|---:|")
    for sig_type, count in sorted(type_counter.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"| {sig_type} | {count} |")
    lines.append("")
    lines.append("## Daily Breakdown")
    lines.append("")
    lines.append("| Date | selector_events | changed | entry_ready | new_candidate | score_jump | invalidated | buys | dq_avg_ratio |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in daily_rows:
        lines.append(
            f"| {row['date']} | {row['selector_events']} | {row['changed_events']} | {row['entry_ready']} | "
            f"{row['new_candidate']} | {row['score_jump']} | {row['invalidated']} | {row['buys']} | {_fmt_pct(float(row['dq_avg_ratio']))} |"
        )
    lines.append("")
    lines.append("## Artifacts")
    lines.append("")
    lines.append(f"- summary_json: `{summary_json}`")
    lines.append(f"- daily_csv: `{daily_csv}`")
    lines.append(f"- signals_csv: `{signals_csv}`")
    summary_md.write_text("\n".join(lines), encoding="utf-8")

    print(f"summary_md={summary_md}")
    print(f"summary_json={summary_json}")
    print(f"daily_csv={daily_csv}")
    print(f"signals_csv={signals_csv}")
    print(
        "entry_ready_conversion="
        f"{conversion_stats['ENTRY_READY']['converted']}/{conversion_stats['ENTRY_READY']['total']} "
        f"({_fmt_pct(conversion_stats['ENTRY_READY']['conversion_ratio'])})"
    )
    print(
        "new_candidate_conversion="
        f"{conversion_stats['NEW_CANDIDATE']['converted']}/{conversion_stats['NEW_CANDIDATE']['total']} "
        f"({_fmt_pct(conversion_stats['NEW_CANDIDATE']['conversion_ratio'])})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
