#!/usr/bin/env python3
"""A/B comparison report for paper-trading exit performance.

Default behavior compares:
- A: previous N days
- B: most recent N days
from a single trades runtime log.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


@dataclass(frozen=True)
class ExitRow:
    ts: datetime
    symbol: str
    strategy: str
    reason: str
    pnl: float
    pnl_pct: float
    hold_sec: float


@dataclass(frozen=True)
class Window:
    start: datetime
    end: datetime


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Paper trading exit A/B report")
    parser.add_argument(
        "--a-log",
        default="logs/trades.runtime.jsonl",
        help="Baseline log path (JSONL)",
    )
    parser.add_argument(
        "--b-log",
        default=None,
        help="Candidate log path (JSONL). Defaults to --a-log",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=3,
        help="Window length in days for automatic split mode (default: 3)",
    )
    parser.add_argument("--a-start", default=None, help="A window start (ISO datetime)")
    parser.add_argument("--a-end", default=None, help="A window end (ISO datetime)")
    parser.add_argument("--b-start", default=None, help="B window start (ISO datetime)")
    parser.add_argument("--b-end", default=None, help="B window end (ISO datetime)")
    parser.add_argument(
        "--out",
        default=None,
        help="Optional markdown output path",
    )
    return parser.parse_args()


def parse_dt(raw: str | None) -> datetime | None:
    if raw is None:
        return None
    value = raw.strip()
    if not value:
        return None
    return datetime.fromisoformat(value)


def load_exits(path: Path) -> list[ExitRow]:
    if not path.exists():
        raise FileNotFoundError(f"log file not found: {path}")

    rows: list[ExitRow] = []
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue

            if rec.get("event") != "EXIT":
                continue

            ts_raw = rec.get("ts")
            if not ts_raw:
                continue
            try:
                ts = datetime.fromisoformat(ts_raw)
            except ValueError:
                continue

            rows.append(
                ExitRow(
                    ts=ts,
                    symbol=str(rec.get("symbol", "")),
                    strategy=str(rec.get("strategy", "")),
                    reason=str(rec.get("reason", "")),
                    pnl=float(rec.get("pnl", 0.0) or 0.0),
                    pnl_pct=float(rec.get("pnl_pct", 0.0) or 0.0),
                    hold_sec=float(rec.get("hold_sec", 0.0) or 0.0),
                )
            )
    return sorted(rows, key=lambda r: r.ts)


def infer_windows(rows: list[ExitRow], days: int) -> tuple[Window, Window]:
    if not rows:
        now = datetime.utcnow()
        zero = Window(start=now - timedelta(days=days), end=now)
        return zero, zero

    b_end = rows[-1].ts
    b_start = b_end - timedelta(days=days)
    a_end = b_start
    a_start = a_end - timedelta(days=days)
    return Window(start=a_start, end=a_end), Window(start=b_start, end=b_end)


def window_filter(rows: list[ExitRow], window: Window) -> list[ExitRow]:
    return [r for r in rows if window.start <= r.ts <= window.end]


def classify_reason(reason: str) -> str:
    lowered = reason.lower()
    if "regime_protect" in lowered:
        return "regime_protect"
    if "stop loss intrabar" in lowered:
        return "stop_loss_intrabar"
    if "mlpdirection exit: stop loss" in lowered or lowered.startswith("stop loss"):
        return "stop_loss"
    if "bear_regime_exit" in lowered:
        return "bear_regime_exit"
    if "trailing stop" in lowered:
        return "trailing_stop"
    return "other"


def summarize(rows: list[ExitRow]) -> dict:
    total = len(rows)
    pnl = sum(r.pnl for r in rows)
    wins = sum(1 for r in rows if r.pnl > 0)
    win_rate = (wins / total * 100.0) if total else 0.0
    avg_pnl_pct = (sum(r.pnl_pct for r in rows) / total) if total else 0.0
    avg_hold_sec = (sum(r.hold_sec for r in rows) / total) if total else 0.0

    by_reason: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    by_strategy: dict[str, dict[str, float]] = defaultdict(lambda: {"count": 0, "pnl": 0.0})
    for row in rows:
        reason_key = classify_reason(row.reason)
        by_reason[reason_key]["count"] += 1
        by_reason[reason_key]["pnl"] += row.pnl

        by_strategy[row.strategy]["count"] += 1
        by_strategy[row.strategy]["pnl"] += row.pnl

    risky_count = int(
        by_reason["regime_protect"]["count"]
        + by_reason["stop_loss_intrabar"]["count"]
        + by_reason["stop_loss"]["count"]
    )
    risky_pnl = float(
        by_reason["regime_protect"]["pnl"]
        + by_reason["stop_loss_intrabar"]["pnl"]
        + by_reason["stop_loss"]["pnl"]
    )

    return {
        "rows": rows,
        "count": total,
        "pnl": pnl,
        "wins": wins,
        "win_rate": win_rate,
        "avg_pnl_pct": avg_pnl_pct,
        "avg_hold_sec": avg_hold_sec,
        "by_reason": by_reason,
        "by_strategy": by_strategy,
        "risky_count": risky_count,
        "risky_pnl": risky_pnl,
    }


def fmt_summary(label: str, summary: dict, window: Window) -> list[str]:
    lines: list[str] = []
    lines.append(f"## {label}")
    lines.append(f"- Window: {window.start.isoformat()} -> {window.end.isoformat()}")
    lines.append(f"- Exits: {summary['count']}")
    lines.append(f"- Net PnL: {summary['pnl']:+.2f}")
    lines.append(f"- Win rate: {summary['win_rate']:.2f}%")
    lines.append(f"- Avg PnL%: {summary['avg_pnl_pct']:+.3f}%")
    lines.append(f"- Avg hold: {summary['avg_hold_sec']:.1f}s")
    lines.append(
        f"- Risk exits (regime_protect+intrabar): {summary['risky_count']} / "
        f"{summary['count']} , PnL {summary['risky_pnl']:+.2f}"
    )
    lines.append("- By reason:")
    for reason, data in sorted(summary["by_reason"].items(), key=lambda kv: kv[1]["pnl"]):
        lines.append(f"  - {reason}: n={int(data['count'])}, pnl={data['pnl']:+.2f}")
    lines.append("- By strategy:")
    for strategy, data in sorted(summary["by_strategy"].items(), key=lambda kv: kv[1]["pnl"]):
        lines.append(f"  - {strategy}: n={int(data['count'])}, pnl={data['pnl']:+.2f}")
    return lines


def compare_section(a: dict, b: dict) -> list[str]:
    lines: list[str] = []
    lines.append("## Delta (B - A)")
    lines.append(f"- Exits: {b['count'] - a['count']:+d}")
    lines.append(f"- Net PnL: {b['pnl'] - a['pnl']:+.2f}")
    lines.append(f"- Win rate: {b['win_rate'] - a['win_rate']:+.2f}pp")
    lines.append(f"- Avg PnL%: {b['avg_pnl_pct'] - a['avg_pnl_pct']:+.3f}pp")
    lines.append(f"- Avg hold: {b['avg_hold_sec'] - a['avg_hold_sec']:+.1f}s")
    lines.append(f"- Risk exits count: {b['risky_count'] - a['risky_count']:+d}")
    lines.append(f"- Risk exits PnL: {b['risky_pnl'] - a['risky_pnl']:+.2f}")
    return lines


def main() -> int:
    args = parse_args()
    a_log = Path(args.a_log)
    b_log = Path(args.b_log) if args.b_log else a_log

    a_rows_all = load_exits(a_log)
    b_rows_all = load_exits(b_log)

    a_start = parse_dt(args.a_start)
    a_end = parse_dt(args.a_end)
    b_start = parse_dt(args.b_start)
    b_end = parse_dt(args.b_end)

    if None in (a_start, a_end, b_start, b_end):
        base_rows = b_rows_all if b_rows_all else a_rows_all
        inferred_a, inferred_b = infer_windows(base_rows, max(args.days, 1))
        a_window = Window(start=a_start or inferred_a.start, end=a_end or inferred_a.end)
        b_window = Window(start=b_start or inferred_b.start, end=b_end or inferred_b.end)
    else:
        a_window = Window(start=a_start, end=a_end)
        b_window = Window(start=b_start, end=b_end)

    a_rows = window_filter(a_rows_all, a_window)
    b_rows = window_filter(b_rows_all, b_window)

    a_summary = summarize(a_rows)
    b_summary = summarize(b_rows)

    lines: list[str] = []
    lines.append("# Paper Exit A/B Report")
    lines.append(f"- A log: {a_log}")
    lines.append(f"- B log: {b_log}")
    lines.extend(fmt_summary("A (Baseline)", a_summary, a_window))
    lines.extend(fmt_summary("B (Candidate)", b_summary, b_window))
    lines.extend(compare_section(a_summary, b_summary))

    report = "\n".join(lines)
    print(report)

    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(report + "\n", encoding="utf-8")
        print(f"\nSaved report: {out_path}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
