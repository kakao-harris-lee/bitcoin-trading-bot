#!/usr/bin/env python3
"""Archive and reset paper-trading artifacts for clean log validation."""
from __future__ import annotations

import argparse
import shutil
import subprocess
from datetime import datetime
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Clean paper-trading runtime artifacts (logs/DB/Redis)."
    )
    parser.add_argument(
        "--project-root",
        default=".",
        help="Project root path (default: current directory).",
    )
    parser.add_argument(
        "--skip-redis",
        action="store_true",
        help="Skip Redis cleanup.",
    )
    return parser.parse_args()


def _run(cmd: list[str]) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    out = (proc.stdout or proc.stderr).strip()
    return proc.returncode, out


def _archive_file(path: Path, archive_dir: Path) -> bool:
    if not path.exists():
        return False
    archive_dir.mkdir(parents=True, exist_ok=True)
    shutil.move(str(path), str(archive_dir / path.name))
    return True


def _touch_empty(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")


def _cleanup_redis() -> list[str]:
    messages: list[str] = []

    rc, out = _run(["redis-cli", "ping"])
    if rc != 0 or out.upper() != "PONG":
        messages.append("Redis unavailable: skipped.")
        return messages

    rc, out = _run(["redis-cli", "DEL", "orders", "exit_signals", "strategy:decisions", "account:paper"])
    messages.append(f"DEL orders/exit_signals/strategy:decisions/account:paper -> {out}")

    rc, positions = _run(["redis-cli", "--scan", "--pattern", "positions:*"])
    if rc == 0 and positions:
        keys = [k.strip() for k in positions.splitlines() if k.strip()]
        if keys:
            _run(["redis-cli", "DEL", *keys])
            messages.append(f"DEL positions:* -> {len(keys)} keys")
    else:
        messages.append("DEL positions:* -> 0 keys")

    _run(["redis-cli", "HSET", "risk", "daily_pnl", "0", "mode", "paper", "blocked", "false"])
    rc, out = _run(["redis-cli", "HGETALL", "risk"])
    messages.append(f"risk -> {out}")
    return messages


def main() -> int:
    args = parse_args()
    root = Path(args.project_root).resolve()
    logs_dir = root / "logs"
    data_dir = root / "data"
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    archive_dir = logs_dir / "archive" / f"paper_cleanup_{timestamp}"

    targets = [
        logs_dir / "trades.jsonl",
        logs_dir / "trades.runtime.jsonl",
        data_dir / "paper_trading_results.db",
    ]

    moved: list[str] = []
    for target in targets:
        if _archive_file(target, archive_dir):
            moved.append(str(target.relative_to(root)))

    _touch_empty(logs_dir / "trades.jsonl")
    _touch_empty(logs_dir / "trades.runtime.jsonl")

    redis_messages: list[str] = []
    if not args.skip_redis:
        redis_messages = _cleanup_redis()

    print(f"Archive dir: {archive_dir}")
    if moved:
        print("Archived:")
        for m in moved:
            print(f"  - {m}")
    else:
        print("Archived: none")
    print("Reset files:")
    print("  - logs/trades.jsonl")
    print("  - logs/trades.runtime.jsonl")
    if not args.skip_redis:
        print("Redis cleanup:")
        for msg in redis_messages:
            print(f"  - {msg}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
