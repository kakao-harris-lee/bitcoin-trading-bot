#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
LOG_DIR = PROJECT_ROOT / "logs" / "paper_soak"
TRADE_LOG = PROJECT_ROOT / "logs" / "trades.runtime.jsonl"
SELECTOR_SCRIPT = PROJECT_ROOT / "scripts" / "paper" / "selector_signal_monitor_7d.py"
TS_FMT = "%Y-%m-%dT%H:%M:%S"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate bullish-phase follow-up report.")
    parser.add_argument("--strategy", default="mlp_direction_bnb")
    parser.add_argument("--trade-log", default=str(TRADE_LOG))
    parser.add_argument("--report-dir", default=str(LOG_DIR))
    parser.add_argument("--restart-ts", default="2026-03-09T13:41:21")
    parser.add_argument("--end-ts", default="")
    parser.add_argument("--selector-entry-window-minutes", type=int, default=240)
    parser.add_argument("--output", default="")
    return parser.parse_args()


def _run_selector_monitor(hours: int, args: argparse.Namespace) -> tuple[dict, Path]:
    proc = subprocess.run(
        [
            sys.executable,
            str(SELECTOR_SCRIPT),
            "--lookback-hours",
            str(hours),
            "--strategy",
            args.strategy,
            "--report-dir",
            args.report_dir,
            "--entry-window-minutes",
            str(args.selector_entry_window_minutes),
        ],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    summary_path: Path | None = None
    for line in proc.stdout.splitlines():
        if line.startswith("summary_json="):
            summary_path = Path(line.split("=", 1)[1].strip())
            break
    if summary_path is None:
        raise RuntimeError(f"Failed to parse selector summary path from output: {proc.stdout}")
    return json.loads(summary_path.read_text()), summary_path


def _load_trade_rows(path: Path) -> list[dict]:
    rows: list[dict] = []
    for line in path.read_text().splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        row["_dt"] = datetime.strptime(row["ts"], TS_FMT)
        rows.append(row)
    return rows


def _window_trade_metrics(rows: list[dict], start: datetime, end: datetime) -> dict:
    in_window = [row for row in rows if start <= row["_dt"] <= end]
    entries = [row for row in in_window if row.get("event") == "ENTRY"]
    exits = [row for row in in_window if row.get("event") == "EXIT"]

    bnb_entries = [row for row in entries if row.get("strategy") == "mlp_direction_bnb"]
    bnb_exits = [row for row in exits if row.get("strategy") == "mlp_direction_bnb"]
    btc_short = [
        row
        for row in exits
        if row.get("strategy") == "mlp_direction_btc" and float(row.get("hold_sec") or 0) < 60
    ]
    eth_exits = [row for row in exits if row.get("strategy") == "mlp_direction_eth"]
    eth_regime = [row for row in eth_exits if "regime_protect" in (row.get("reason") or "")]

    return {
        "start": start.isoformat(timespec="seconds"),
        "end": end.isoformat(timespec="seconds"),
        "entries": len(entries),
        "exits": len(exits),
        "bnb_entry_count": len(bnb_entries),
        "bnb_exit_count": len(bnb_exits),
        "bnb_entry_mix": dict(Counter(row["symbol"] for row in bnb_entries)),
        "bnb_exit_mix": dict(Counter(row["symbol"] for row in bnb_exits)),
        "btc_short_exit_lt60_count": len(btc_short),
        "btc_short_exits": [
            {
                "ts": row["ts"],
                "symbol": row["symbol"],
                "hold_sec": row.get("hold_sec"),
                "reason": row.get("reason"),
            }
            for row in btc_short
        ],
        "eth_exit_count": len(eth_exits),
        "eth_regime_protect_count": len(eth_regime),
        "eth_regime_protect_ratio": (len(eth_regime) / len(eth_exits)) if eth_exits else 0.0,
    }


def _selector_lines(label: str, payload: dict, summary_path: Path) -> list[str]:
    conv = payload.get("conversion") or {}
    entry = conv.get("ENTRY_READY") or {}
    cand = conv.get("NEW_CANDIDATE") or {}
    return [
        f"### {label}",
        f"- source: `{summary_path.name}`",
        f"- ENTRY_READY conversion: {int(entry.get('converted', 0))} / {int(entry.get('total', 0))} = {float(entry.get('conversion_ratio', 0.0)) * 100:.2f}%",
        f"- NEW_CANDIDATE conversion: {int(cand.get('converted', 0))} / {int(cand.get('total', 0))} = {float(cand.get('conversion_ratio', 0.0)) * 100:.2f}%",
        f"- buy_trades: {int(payload.get('buy_trades', 0))}",
        f"- avg_dq_blocked_ratio: {float(payload.get('avg_dq_blocked_ratio', 0.0)) * 100:.2f}%",
        f"- stale_reject_ratio: {float(payload.get('stale_reject_ratio', 0.0)) * 100:.2f}%",
        "",
    ]


def _trade_lines(label: str, metrics: dict) -> list[str]:
    lines = [
        f"### {label}",
        f"- window: `{metrics['start']}` -> `{metrics['end']}`",
        f"- BNB sleeve entries: {metrics['bnb_entry_count']}",
        f"- BNB sleeve exits: {metrics['bnb_exit_count']}",
        f"- BNB sleeve entry mix: {metrics['bnb_entry_mix'] or '{}'}",
        f"- BNB sleeve exit mix: {metrics['bnb_exit_mix'] or '{}'}",
        f"- BTC hold < 60s exits: {metrics['btc_short_exit_lt60_count']}",
        f"- ETH exits: {metrics['eth_exit_count']}",
        f"- ETH regime_protect exits: {metrics['eth_regime_protect_count']} ({metrics['eth_regime_protect_ratio'] * 100:.2f}%)",
    ]
    if metrics["btc_short_exits"]:
        lines.append("- BTC short exits:")
        for row in metrics["btc_short_exits"]:
            lines.append(
                f"  - {row['ts']} {row['symbol']} hold={row['hold_sec']} reason={row['reason']}"
            )
    lines.append("")
    return lines


def main() -> int:
    args = _parse_args()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)
    end_ts = datetime.strptime(args.end_ts, TS_FMT) if args.end_ts else datetime.now()
    restart_ts = datetime.strptime(args.restart_ts, TS_FMT)
    start_24h = end_ts - timedelta(hours=24)

    selector24, selector24_path = _run_selector_monitor(24, args)
    selector72, selector72_path = _run_selector_monitor(72, args)
    trades = _load_trade_rows(Path(args.trade_log))
    trade_24h = _window_trade_metrics(trades, start_24h, end_ts)
    trade_restart = _window_trade_metrics(trades, restart_ts, end_ts)

    output_path = Path(args.output) if args.output else report_dir / f"bullish_phase_followup_{end_ts.strftime('%Y%m%d_%H%M%S')}.md"
    lines = [
        "# Bullish-Phase Follow-up Check",
        "",
        f"Generated: {end_ts.isoformat(timespec='seconds')}",
        f"Strategy: `{args.strategy}`",
        f"Restart anchor: `{restart_ts.isoformat(timespec='seconds')}`",
        "",
        "## Selector / DQ",
        "",
    ]
    lines.extend(_selector_lines("24h", selector24, selector24_path))
    lines.extend(_selector_lines("72h", selector72, selector72_path))
    lines.extend([
        "## Trade / Exit Metrics",
        "",
    ])
    lines.extend(_trade_lines("24h", trade_24h))
    lines.extend(_trade_lines("Since Restart", trade_restart))

    output_path.write_text("\n".join(lines) + "\n")
    print(f"report_md={output_path}")
    print(f"selector_24h={selector24_path}")
    print(f"selector_72h={selector72_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
