#!/usr/bin/env python3
"""Compare post-patch paper-trading checkpoints against pre-patch baselines."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class TradeEvent:
    ts: datetime
    event: str
    strategy: str
    symbol: str
    reason: str
    pnl: float
    hold_sec: float


@dataclass(frozen=True)
class ClosedTrade:
    exit_ts: datetime
    symbol: str
    strategy: str
    entry_reason: str
    exit_reason: str
    pnl: float
    hold_sec: float


@dataclass(frozen=True)
class Window:
    label: str
    start: datetime
    end: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Post-patch checkpoint report")
    parser.add_argument(
        "--log",
        default="logs/trades.runtime.jsonl",
        help="Trades runtime log path",
    )
    parser.add_argument(
        "--strategy",
        default="mlp_direction_bnb",
        help="Strategy id to analyze",
    )
    parser.add_argument(
        "--patch-ts",
        required=True,
        help="Patch/restart timestamp (ISO datetime)",
    )
    parser.add_argument(
        "--as-of",
        default=None,
        help="Analysis cutoff timestamp (ISO datetime). Defaults to latest log timestamp.",
    )
    parser.add_argument(
        "--fixed-hours",
        type=float,
        default=24.0,
        help="Fixed post window length in hours for checkpoint comparison",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Optional markdown output path",
    )
    return parser.parse_args()


def parse_dt(raw: str) -> datetime:
    return datetime.fromisoformat(raw.strip())


def load_events(path: Path, strategy: str) -> list[TradeEvent]:
    rows: list[TradeEvent] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if str(obj.get("strategy", "")) != strategy:
                continue
            ts_raw = obj.get("ts")
            if not ts_raw:
                continue
            try:
                ts = parse_dt(str(ts_raw))
            except ValueError:
                continue
            rows.append(
                TradeEvent(
                    ts=ts,
                    event=str(obj.get("event", "")),
                    strategy=str(obj.get("strategy", "")),
                    symbol=str(obj.get("symbol", "")).upper(),
                    reason=str(obj.get("reason", "")),
                    pnl=float(obj.get("pnl", 0.0) or 0.0),
                    hold_sec=float(obj.get("hold_sec", 0.0) or 0.0),
                )
            )
    return sorted(rows, key=lambda row: (row.ts, {"DECISION": 0, "SIGNAL": 1, "ENTRY": 2, "EXIT": 3}.get(row.event, 9)))


def classify_entry(reason: str) -> str:
    text = (reason or "").lower()
    if "regime_fallback" in text:
        return "regime_fallback"
    if "hybridlong[mlp]" in text or "mlpdirection" in text:
        return "mlp"
    if "selector" in text:
        return "selector"
    return "other"


def classify_exit(reason: str) -> str:
    text = (reason or "").lower()
    if "below ema_120" in text:
        return "regime_ema120"
    if "peak drawdown" in text:
        return "regime_drawdown"
    if "stop loss intrabar" in text:
        return "stop_loss_intrabar"
    if "mlpdirection exit: stop loss" in text or text.startswith("stop loss"):
        return "stop_loss"
    if "trailing stop" in text:
        return "trailing_stop"
    if "bear_regime_exit" in text:
        return "bear_regime_exit"
    if "deadcross" in text:
        return "ema_deadcross"
    return "other"


def is_risk_exit(exit_category: str) -> bool:
    return exit_category in {
        "regime_ema120",
        "regime_drawdown",
        "stop_loss_intrabar",
        "stop_loss",
        "bear_regime_exit",
        "ema_deadcross",
    }


def build_closed_trades(events: list[TradeEvent]) -> list[ClosedTrade]:
    reason_map: dict[tuple[datetime, str], list[str]] = defaultdict(list)
    for event in events:
        if event.event in {"DECISION", "SIGNAL"} and event.reason:
            reason_map[(event.ts, event.symbol)].append(event.reason)

    open_positions: dict[str, str] = {}
    trades: list[ClosedTrade] = []
    for event in events:
        if event.event == "ENTRY":
            reasons = reason_map.get((event.ts, event.symbol), [])
            entry_reason = next(
                (
                    reason
                    for reason in reasons
                    if "entry" in reason.lower() or "fallback" in reason.lower() or "buy" in reason.lower()
                ),
                reasons[0] if reasons else "",
            )
            open_positions[event.symbol] = entry_reason
            continue

        if event.event != "EXIT":
            continue

        entry_reason = open_positions.pop(event.symbol, "")
        trades.append(
            ClosedTrade(
                exit_ts=event.ts,
                symbol=event.symbol,
                strategy=event.strategy,
                entry_reason=entry_reason,
                exit_reason=event.reason,
                pnl=event.pnl,
                hold_sec=event.hold_sec,
            )
        )
    return trades


def filter_window_events(events: list[TradeEvent], window: Window) -> list[TradeEvent]:
    return [event for event in events if window.start <= event.ts <= window.end]


def summarize(trades: list[ClosedTrade]) -> dict[str, object]:
    total = len(trades)
    net_pnl = sum(trade.pnl for trade in trades)
    fallback_count = sum(1 for trade in trades if classify_entry(trade.entry_reason) == "regime_fallback")
    risk_count = sum(1 for trade in trades if is_risk_exit(classify_exit(trade.exit_reason)))
    trailing_rows = [trade for trade in trades if classify_exit(trade.exit_reason) == "trailing_stop"]
    trailing_pnl = sum(trade.pnl for trade in trailing_rows)
    avg_hold_sec = (sum(trade.hold_sec for trade in trades) / total) if total else 0.0

    by_exit: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0.0, "pnl": 0.0})
    by_symbol: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0.0, "pnl": 0.0})
    for trade in trades:
        exit_key = classify_exit(trade.exit_reason)
        by_exit[exit_key]["count"] += 1
        by_exit[exit_key]["pnl"] += trade.pnl
        by_symbol[trade.symbol]["count"] += 1
        by_symbol[trade.symbol]["pnl"] += trade.pnl

    return {
        "count": total,
        "net_pnl": net_pnl,
        "fallback_entry_count": fallback_count,
        "fallback_entry_share": (fallback_count / total) if total else 0.0,
        "risk_exit_count": risk_count,
        "risk_exit_share": (risk_count / total) if total else 0.0,
        "trailing_stop_count": len(trailing_rows),
        "trailing_stop_realized_pnl": trailing_pnl,
        "avg_hold_sec": avg_hold_sec,
        "by_exit": dict(by_exit),
        "by_symbol": dict(by_symbol),
    }


def summarize_window(events: list[TradeEvent], window: Window) -> dict[str, object]:
    return summarize(build_closed_trades(filter_window_events(events, window)))


def fmt_pct(value: float) -> str:
    return f"{value * 100:.2f}%"


def fmt_hours(seconds: float) -> str:
    return f"{seconds / 3600.0:.2f}h"


def render_section(title: str, window: Window, summary: dict[str, object]) -> list[str]:
    by_exit = summary["by_exit"]
    lines = [
        f"## {title}",
        f"- Window: {window.start.isoformat()} -> {window.end.isoformat()}",
        f"- Closed trades: {summary['count']}",
        f"- Net PnL: {summary['net_pnl']:+.2f}",
        f"- Fallback entry share: {fmt_pct(float(summary['fallback_entry_share']))} ({summary['fallback_entry_count']}/{summary['count']})" if summary["count"] else "- Fallback entry share: -",
        f"- Risk exit share: {fmt_pct(float(summary['risk_exit_share']))} ({summary['risk_exit_count']}/{summary['count']})" if summary["count"] else "- Risk exit share: -",
        f"- Trailing-stop realized PnL: {float(summary['trailing_stop_realized_pnl']):+.2f} ({summary['trailing_stop_count']} exits)",
        f"- Avg hold: {fmt_hours(float(summary['avg_hold_sec']))}",
        "- Exit breakdown:",
    ]
    for key, value in sorted(by_exit.items(), key=lambda item: item[1]["pnl"]):
        lines.append(f"  - {key}: n={int(value['count'])}, pnl={value['pnl']:+.2f}")
    return lines


def render_delta(title: str, base: dict[str, object], current: dict[str, object]) -> list[str]:
    return [
        f"## {title}",
        f"- Closed trades: {int(current['count']) - int(base['count']):+d}",
        f"- Net PnL: {float(current['net_pnl']) - float(base['net_pnl']):+.2f}",
        f"- Fallback entry share: {((float(current['fallback_entry_share']) - float(base['fallback_entry_share'])) * 100):+.2f}pp",
        f"- Risk exit share: {((float(current['risk_exit_share']) - float(base['risk_exit_share'])) * 100):+.2f}pp",
        f"- Trailing-stop realized PnL: {float(current['trailing_stop_realized_pnl']) - float(base['trailing_stop_realized_pnl']):+.2f}",
        f"- Avg hold: {((float(current['avg_hold_sec']) - float(base['avg_hold_sec'])) / 3600.0):+.2f}h",
    ]


def main() -> int:
    args = parse_args()
    log_path = Path(args.log)
    patch_ts = parse_dt(args.patch_ts)
    events = load_events(log_path, args.strategy)
    if not events:
        raise SystemExit(f"no events found for strategy={args.strategy}")

    latest_ts = events[-1].ts
    as_of = parse_dt(args.as_of) if args.as_of else latest_ts
    if as_of > latest_ts:
        as_of = latest_ts
    if as_of <= patch_ts:
        raise SystemExit("as-of timestamp must be after patch timestamp")

    fixed_delta = timedelta(hours=args.fixed_hours)
    post_fixed_end = min(patch_ts + fixed_delta, as_of)
    pre_fixed = Window("pre_fixed", patch_ts - (post_fixed_end - patch_ts), patch_ts)
    post_fixed = Window("post_fixed", patch_ts, post_fixed_end)

    live_delta = as_of - patch_ts
    pre_live = Window("pre_live", patch_ts - live_delta, patch_ts)
    post_live = Window("post_live", patch_ts, as_of)

    windows = [
        ("Pre 24h", pre_fixed),
        ("Post 24h", post_fixed),
        ("Pre Equal Window", pre_live),
        ("Post Since Patch", post_live),
    ]

    summaries = {label: summarize_window(events, window) for label, window in windows}

    lines: list[str] = []
    lines.append(f"# Post-Patch Checkpoints ({args.strategy})")
    lines.append("")
    lines.append(f"- Patch timestamp: `{patch_ts.isoformat()}`")
    lines.append(f"- Analysis cutoff: `{as_of.isoformat()}`")
    lines.append(f"- Fixed checkpoint length: `{(post_fixed.end - post_fixed.start).total_seconds() / 3600.0:.2f}h`")
    lines.append(f"- Since-patch live length: `{live_delta.total_seconds() / 3600.0:.2f}h`")
    lines.append("")

    for label, window in windows:
        lines.extend(render_section(label, window, summaries[label]))
        lines.append("")

    lines.extend(render_delta("Delta 24h (Post - Pre)", summaries["Pre 24h"], summaries["Post 24h"]))
    lines.append("")
    lines.extend(render_delta("Delta Equal Window (Post - Pre)", summaries["Pre Equal Window"], summaries["Post Since Patch"]))
    lines.append("")

    if live_delta < timedelta(hours=72):
        remaining = timedelta(hours=72) - live_delta
        lines.append(
            f"- 72h checkpoint status: incomplete, `{remaining.total_seconds() / 3600.0:.2f}h` remaining from `{as_of.isoformat()}`."
        )

    output = "\n".join(lines).rstrip() + "\n"
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(output, encoding="utf-8")
        print(f"Wrote: {out_path}")
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
