#!/usr/bin/env python3
"""Summarize 7-day soak validation metrics and optionally notify Telegram."""
from __future__ import annotations

import argparse
import csv
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Summarize rolling soak metrics for final 7-day validation."
    )
    parser.add_argument("--history-csv", default="logs/paper_soak/mlp_daily_metrics.csv")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--output-dir", default="logs/paper_soak")
    parser.add_argument("--send-telegram", action="store_true")
    return parser.parse_args()


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip())


def _parse_iso(value: str) -> datetime | None:
    try:
        return datetime.fromisoformat(value)
    except Exception:
        return None


def _to_float(value: str | None) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _to_int(value: str | None) -> int:
    try:
        return int(float(value or 0))
    except Exception:
        return 0


def _mean(values: list[float]) -> float:
    if not values:
        return 0.0
    return sum(values) / len(values)


def _build_summary(rows: list[dict[str, str]], days: int) -> dict:
    now = datetime.now()
    cutoff = now - timedelta(days=days)
    filtered = []
    for row in rows:
        ts = _parse_iso(row.get("run_ts", ""))
        if ts is None:
            continue
        if ts >= cutoff:
            filtered.append(row)

    by_symbol: dict[str, list[dict[str, str]]] = {}
    for row in filtered:
        symbol = (row.get("symbol", "") or "").upper()
        if not symbol:
            continue
        by_symbol.setdefault(symbol, []).append(row)

    symbols_summary = []
    for symbol, entries in sorted(by_symbol.items()):
        up_alphas = [_to_float(e.get("up_market_alpha_pct")) for e in entries]
        early_rates = [_to_float(e.get("early_exit_rate_pct")) for e in entries]
        alphas = [_to_float(e.get("alpha_pct")) for e in entries]
        decisions = [_to_int(e.get("decision_count")) for e in entries]
        captures = [_to_float(e.get("up_market_capture_ratio")) for e in entries]

        symbols_summary.append(
            {
                "symbol": symbol,
                "records": len(entries),
                "mean_up_market_alpha_pct": round(_mean(up_alphas), 6),
                "mean_alpha_pct": round(_mean(alphas), 6),
                "mean_early_exit_rate_pct": round(_mean(early_rates), 6),
                "mean_up_market_capture_ratio": round(_mean(captures), 6),
                "sum_decision_count": int(sum(decisions)),
            }
        )

    return {
        "generated_at": now.isoformat(timespec="seconds"),
        "window_days": days,
        "record_count": len(filtered),
        "symbols": symbols_summary,
    }


def _write_outputs(summary: dict, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = output_dir / f"validation_7d_summary_{ts}.json"
    md_path = output_dir / f"validation_7d_summary_{ts}.md"

    json_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")

    lines = [
        "# 7-Day Soak Validation Summary",
        "",
        f"- generated_at: `{summary['generated_at']}`",
        f"- window_days: `{summary['window_days']}`",
        f"- record_count: `{summary['record_count']}`",
        "",
        "| Symbol | Records | Mean Up Alpha %p | Mean Alpha %p | Mean Early Exit % | Mean Capture Ratio | Decision Sum |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in summary.get("symbols", []):
        lines.append(
            f"| {row['symbol']} | {row['records']} | "
            f"{row['mean_up_market_alpha_pct']:+.4f} | "
            f"{row['mean_alpha_pct']:+.4f} | "
            f"{row['mean_early_exit_rate_pct']:.2f} | "
            f"{row['mean_up_market_capture_ratio']:+.4f} | "
            f"{row['sum_decision_count']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    return json_path, md_path


def _telegram_text(summary: dict, md_path: Path) -> str:
    lines = [
        "[MLP 7-Day Validation]",
        f"- generated_at: {summary['generated_at']}",
        f"- records: {summary['record_count']}",
    ]
    for row in summary.get("symbols", []):
        lines.append(
            f"- {row['symbol']}: up_alpha={row['mean_up_market_alpha_pct']:+.3f}%p, "
            f"early_exit={row['mean_early_exit_rate_pct']:.2f}%, "
            f"capture={row['mean_up_market_capture_ratio']:+.3f}"
        )
    rel_md = md_path.relative_to(PROJECT_ROOT)
    lines.append(f"- report: {rel_md}")
    return "\n".join(lines)


def _send_telegram(message: str) -> bool:
    _load_env(PROJECT_ROOT / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[WARN] Telegram env not set; skipping send.")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        if 200 <= resp.status_code < 300:
            return True
        print(f"[WARN] Telegram send failed: status={resp.status_code}")
        return False
    except Exception as e:
        print(f"[WARN] Telegram send exception: {type(e).__name__}: {e}")
        return False


def main() -> int:
    args = parse_args()
    history_csv = PROJECT_ROOT / args.history_csv
    if not history_csv.exists():
        print(f"[ERROR] Missing history csv: {history_csv}")
        return 1

    with history_csv.open("r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    summary = _build_summary(rows, days=args.days)
    out_dir = PROJECT_ROOT / args.output_dir
    json_path, md_path = _write_outputs(summary, out_dir)

    print(f"Wrote: {json_path.relative_to(PROJECT_ROOT)}")
    print(f"Wrote: {md_path.relative_to(PROJECT_ROOT)}")

    if args.send_telegram:
        text = _telegram_text(summary, md_path)
        ok = _send_telegram(text)
        print(f"Telegram sent: {ok}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
