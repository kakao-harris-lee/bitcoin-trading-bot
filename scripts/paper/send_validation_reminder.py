#!/usr/bin/env python3
"""Send Telegram reminder for final 7-day validation schedule."""
from __future__ import annotations

import argparse
import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests


PROJECT_ROOT = Path(__file__).resolve().parents[2]
KST = ZoneInfo("Asia/Seoul")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Send Telegram reminder for MLP final validation."
    )
    parser.add_argument("--target-date", default="2026-02-20")
    parser.add_argument("--target-time", default="09:40")
    parser.add_argument("--label", default="REMINDER")
    return parser.parse_args()


def _load_env(path: Path) -> None:
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


def _format_delta(delta_seconds: float) -> str:
    total = int(abs(delta_seconds))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, _ = divmod(rem, 60)
    sign = "-" if delta_seconds < 0 else ""
    return f"{sign}{days}d {hours}h {minutes}m"


def _build_message(target_dt: datetime, label: str) -> str:
    now_kst = datetime.now(KST)
    delta = target_dt - now_kst
    lines = [
        f"[MLP Validation {label}]",
        f"- now(KST): {now_kst.strftime('%Y-%m-%d %H:%M:%S')}",
        f"- target(KST): {target_dt.strftime('%Y-%m-%d %H:%M')}",
        f"- time_left: {_format_delta(delta.total_seconds())}",
        "- action: final 7-day summary + telegram send",
        "- script: scripts/paper/run_final_7d_validation_and_notify.sh",
        "- report: logs/paper_soak/validation_7d_summary_*.md",
        "- checklist: open summary, compare day-1 baseline, check cron failures, decide keep/tune/rollback",
    ]
    return "\n".join(lines)


def _send_telegram(message: str) -> bool:
    _load_env(PROJECT_ROOT / ".env")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        print("[ERROR] Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        resp = requests.post(url, json={"chat_id": chat_id, "text": message}, timeout=10)
        if 200 <= resp.status_code < 300:
            return True
        print(f"[ERROR] Telegram send failed: status={resp.status_code}")
        return False
    except Exception as exc:
        print(f"[ERROR] Telegram send exception: {type(exc).__name__}: {exc}")
        return False


def main() -> int:
    args = parse_args()
    target_dt = datetime.strptime(
        f"{args.target_date} {args.target_time}", "%Y-%m-%d %H:%M"
    ).replace(tzinfo=KST)

    msg = _build_message(target_dt, args.label)
    sent = _send_telegram(msg)
    print(f"Telegram sent: {sent}")
    return 0 if sent else 1


if __name__ == "__main__":
    raise SystemExit(main())
