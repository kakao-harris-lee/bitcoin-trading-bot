#!/usr/bin/env python3
"""DB0 retention cleanup for trading bot Redis.

Applies conservative cleanup/retention policies:
- Trim oversized streams with explicit maxlen
- Delete old RQ result streams
- Normalize TTL for RQ/QuantLab/state legacy keys
- Optionally remove stale state keys for non-active strategies

Default mode is dry-run. Use --apply to execute changes.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

import redis


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


STREAM_MAXLEN_POLICY = {
    "alerts": _env_int("REDIS_STREAM_MAXLEN_ALERTS", 20000),
    "orders": _env_int("REDIS_STREAM_MAXLEN_ORDERS", 10000),
    "trades": _env_int("REDIS_STREAM_MAXLEN_TRADES", 20000),
    "exit_signals": _env_int("REDIS_STREAM_MAXLEN_EXIT_SIGNALS", 10000),
    "market:prices": _env_int("REDIS_STREAM_MAXLEN_MARKET_PRICES", 50000),
    "strategy:decisions": _env_int("REDIS_STREAM_MAXLEN_STRATEGY_DECISIONS", 10000),
    "strategy:selector:events": _env_int("REDIS_STREAM_MAXLEN_STRATEGY_SELECTOR_EVENTS", 5000),
    "observability:system:state": _env_int("REDIS_STREAM_MAXLEN_OBSERVABILITY_SYSTEM_STATE", 2000),
    "system:universe": _env_int("REDIS_STREAM_MAXLEN_SYSTEM_UNIVERSE", 5000),
    "system:universe_updates": _env_int("REDIS_STREAM_MAXLEN_SYSTEM_UNIVERSE_UPDATES", 2000),
    "market:quotes": _env_int("REDIS_STREAM_MAXLEN_MARKET_QUOTES", 50000),
    "market:ticks": _env_int("REDIS_STREAM_MAXLEN_MARKET_TICKS", 100000),
    "signals:detected": _env_int("REDIS_STREAM_MAXLEN_SIGNALS_DETECTED", 10000),
}
LEGACY_STALE_STREAMS = {
    "system:universe",
    "system:universe_updates",
    "market:quotes",
    "market:ticks",
    "signals:detected",
}


def _load_active_strategies(repo_root: Path) -> set[str]:
    cfg_path = repo_root / "config" / "strategies" / "allocation.json"
    if not cfg_path.exists():
        return set()
    try:
        data = json.loads(cfg_path.read_text(encoding="utf-8"))
    except Exception:
        return set()
    strategies = data.get("strategies", {})
    if not isinstance(strategies, dict):
        return set()
    return {str(name) for name in strategies.keys() if isinstance(name, str)}


def _apply_or_print(apply: bool, action: str, fn, *args, **kwargs) -> Any:
    print(action)
    if not apply:
        return None
    return fn(*args, **kwargs)


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _last_entry_age_sec(r: redis.Redis, stream: str) -> int | None:
    try:
        item = r.xrevrange(stream, count=1)
    except Exception:
        return None
    if not item:
        return None
    msg_id = str(item[0][0])
    try:
        ts_ms = int(msg_id.split("-")[0])
    except Exception:
        return None
    now_ms = int(time.time() * 1000)
    return max(0, (now_ms - ts_ms) // 1000)


def main() -> int:
    parser = argparse.ArgumentParser(description="Redis DB0 retention/cleanup")
    parser.add_argument("--db", type=int, default=0, help="Redis DB index (default: 0)")
    parser.add_argument("--apply", action="store_true", help="Execute cleanup actions")
    parser.add_argument("--rq-results-idle-days", type=int, default=7)
    parser.add_argument("--rq-results-ttl-days", type=int, default=7)
    parser.add_argument("--rq-job-ttl-days", type=int, default=14)
    parser.add_argument("--quantlab-active-ttl-days", type=int, default=3)
    parser.add_argument("--quantlab-finished-ttl-days", type=int, default=14)
    parser.add_argument("--state-ttl-days", type=int, default=90)
    parser.add_argument("--prune-stale-state-days", type=int, default=7)
    parser.add_argument("--regime-snapshot-ttl-days", type=int, default=2)
    parser.add_argument("--selector-snapshot-ttl-days", type=int, default=14)
    parser.add_argument("--strict-trim-factor", type=float, default=2.0)
    parser.add_argument("--stale-stream-days", type=int, default=3)
    parser.add_argument("--stale-stream-maxlen", type=int, default=1000)
    args = parser.parse_args()

    r = redis.Redis(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=_env_int("REDIS_PORT", 6379),
        db=args.db,
        decode_responses=True,
    )
    r.ping()

    repo_root = Path(__file__).resolve().parents[2]
    active_strategies = _load_active_strategies(repo_root)

    rq_results_idle_sec = max(1, args.rq_results_idle_days) * 24 * 3600
    rq_results_ttl_sec = max(1, args.rq_results_ttl_days) * 24 * 3600
    rq_job_ttl_sec = max(1, args.rq_job_ttl_days) * 24 * 3600
    quantlab_active_ttl_sec = max(1, args.quantlab_active_ttl_days) * 24 * 3600
    quantlab_finished_ttl_sec = max(1, args.quantlab_finished_ttl_days) * 24 * 3600
    state_ttl_sec = max(1, args.state_ttl_days) * 24 * 3600
    prune_stale_state_sec = max(1, args.prune_stale_state_days) * 24 * 3600
    regime_snapshot_ttl_sec = max(1, args.regime_snapshot_ttl_days) * 24 * 3600
    selector_snapshot_ttl_sec = max(1, args.selector_snapshot_ttl_days) * 24 * 3600
    stale_stream_age_sec = max(1, args.stale_stream_days) * 24 * 3600
    stale_stream_maxlen = max(100, args.stale_stream_maxlen)

    print(f"[INFO] DB={args.db} apply={args.apply}")
    print(f"[INFO] active_strategies={sorted(active_strategies)}")

    summary = {
        "trimmed_streams": 0,
        "deleted_rq_results": 0,
        "expired_rq_results": 0,
        "expired_rq_jobs": 0,
        "expired_quantlab_jobs": 0,
        "expired_state_keys": 0,
        "deleted_stale_state_keys": 0,
        "expired_misc_keys": 0,
    }

    # 1) Stream trimming policy
    for stream, maxlen in STREAM_MAXLEN_POLICY.items():
        if maxlen <= 0:
            continue
        if r.type(stream) != "stream":
            continue
        try:
            length = _safe_int(r.xlen(stream))
        except Exception:
            continue
        if length <= maxlen:
            continue
        strict_trim = length > int(maxlen * max(1.0, args.strict_trim_factor))
        trim_mode = "exact" if strict_trim else "approx"
        _apply_or_print(
            args.apply,
            f"[TRIM] {stream} len={length} -> maxlen={maxlen} mode={trim_mode}",
            r.xtrim,
            stream,
            maxlen=maxlen,
            approximate=not strict_trim,
        )
        summary["trimmed_streams"] += 1

    # 1-b) Extra aggressive trim for stale legacy streams.
    for stream in sorted(LEGACY_STALE_STREAMS):
        if r.type(stream) != "stream":
            continue
        try:
            length = _safe_int(r.xlen(stream))
        except Exception:
            continue
        if length <= stale_stream_maxlen:
            continue
        age_sec = _last_entry_age_sec(r, stream)
        if age_sec is None or age_sec < stale_stream_age_sec:
            continue
        _apply_or_print(
            args.apply,
            f"[TRIM] stale-legacy {stream} len={length} age={age_sec}s -> maxlen={stale_stream_maxlen} mode=exact",
            r.xtrim,
            stream,
            maxlen=stale_stream_maxlen,
            approximate=False,
        )
        summary["trimmed_streams"] += 1

    # 2) Delete stale rq:results:* streams / normalize TTL
    for key in r.scan_iter(match="rq:results:*", count=1000):
        if r.type(key) != "stream":
            continue
        idle = _safe_int(r.object("idletime", key))
        if idle < rq_results_idle_sec:
            ttl = _safe_int(r.ttl(key), -1)
            if ttl == -1 or ttl > rq_results_ttl_sec:
                _apply_or_print(args.apply, f"[EXPIRE] {key} ttl->{rq_results_ttl_sec}s", r.expire, key, rq_results_ttl_sec)
                summary["expired_rq_results"] += 1
            continue
        _apply_or_print(args.apply, f"[DEL] stale {key} idle={idle}s", r.delete, key)
        summary["deleted_rq_results"] += 1

    # 3) RQ job TTL normalization
    for key in r.scan_iter(match="rq:job:*", count=1000):
        ttl = _safe_int(r.ttl(key), -1)
        if ttl == -2:
            continue
        if ttl == -1 or ttl > rq_job_ttl_sec:
            _apply_or_print(args.apply, f"[EXPIRE] {key} ttl->{rq_job_ttl_sec}s", r.expire, key, rq_job_ttl_sec)
            summary["expired_rq_jobs"] += 1

    # 4) QuantLab job TTL policy
    for key in r.scan_iter(match="quant_lab:job:*", count=500):
        data = r.hgetall(key) or {}
        status = str(data.get("status", "")).strip('"').lower()
        ttl_target = quantlab_finished_ttl_sec if status in {"completed", "failed", "cancelled"} else quantlab_active_ttl_sec
        ttl = _safe_int(r.ttl(key), -1)
        if ttl == -2:
            continue
        if ttl == -1 or ttl > ttl_target:
            _apply_or_print(args.apply, f"[EXPIRE] {key} status={status or '-'} ttl->{ttl_target}s", r.expire, key, ttl_target)
            summary["expired_quantlab_jobs"] += 1

    # 5) State key TTL + stale unknown strategy purge
    for key in r.scan_iter(match="state:*", count=2000):
        key_str = str(key)
        parts = key_str.split(":")

        if len(parts) >= 4 and parts[1] == "index":
            ttl = _safe_int(r.ttl(key_str), -1)
            if ttl == -1 or ttl > state_ttl_sec:
                _apply_or_print(args.apply, f"[EXPIRE] {key_str} ttl->{state_ttl_sec}s", r.expire, key_str, state_ttl_sec)
                summary["expired_state_keys"] += 1
            continue

        if len(parts) < 4:
            continue

        strategy_name = parts[1]
        idle = _safe_int(r.object("idletime", key_str))
        if strategy_name and strategy_name not in active_strategies and idle >= prune_stale_state_sec:
            _apply_or_print(args.apply, f"[DEL] stale-state {key_str} strategy={strategy_name} idle={idle}s", r.delete, key_str)
            summary["deleted_stale_state_keys"] += 1
            continue

        ttl = _safe_int(r.ttl(key_str), -1)
        if ttl == -1 or ttl > state_ttl_sec:
            _apply_or_print(args.apply, f"[EXPIRE] {key_str} ttl->{state_ttl_sec}s", r.expire, key_str, state_ttl_sec)
            summary["expired_state_keys"] += 1

    # 6) Misc stale legacy keys
    legacy_ttl_map = {
        "account": 7 * 24 * 3600,
        "backtest:list": 14 * 24 * 3600,
    }
    for key, ttl_target in legacy_ttl_map.items():
        if r.type(key) == "none":
            continue
        ttl = _safe_int(r.ttl(key), -1)
        if ttl == -1 or ttl > ttl_target:
            _apply_or_print(args.apply, f"[EXPIRE] {key} ttl->{ttl_target}s", r.expire, key, ttl_target)
            summary["expired_misc_keys"] += 1

    # 7) Snapshot key TTL normalization
    if r.type("regime:latest") != "none":
        ttl = _safe_int(r.ttl("regime:latest"), -1)
        if ttl == -1 or ttl > regime_snapshot_ttl_sec:
            _apply_or_print(args.apply, f"[EXPIRE] regime:latest ttl->{regime_snapshot_ttl_sec}s", r.expire, "regime:latest", regime_snapshot_ttl_sec)
            summary["expired_misc_keys"] += 1

    for key in r.scan_iter(match="strategy:selector:latest:*", count=500):
        ttl = _safe_int(r.ttl(key), -1)
        if ttl == -1 or ttl > selector_snapshot_ttl_sec:
            _apply_or_print(args.apply, f"[EXPIRE] {key} ttl->{selector_snapshot_ttl_sec}s", r.expire, key, selector_snapshot_ttl_sec)
            summary["expired_misc_keys"] += 1

    print("[SUMMARY]", json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
