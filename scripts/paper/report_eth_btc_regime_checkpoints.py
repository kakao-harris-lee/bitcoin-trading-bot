#!/usr/bin/env python3
"""Automated ETH/BTC regime-protect checkpoint report.

Tracks three checkpoints:
1. ETH/BTC regime_protect recurrence counts
2. trailing_stop reach share in the same windows
3. 24h follow-through re-evaluation for a focus ETH exit and any pending exits
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRADE_LOG = PROJECT_ROOT / "logs" / "trades.runtime.jsonl"
DEFAULT_REPORT_DIR = PROJECT_ROOT / "logs" / "paper_soak"
DB_SOURCES: dict[str, tuple[Path, str]] = {
    "ETH": (PROJECT_ROOT / "data" / "binance_ethereum.db", "ethereum_minute60"),
    "BTC": (PROJECT_ROOT / "data" / "binance_bitcoin.db", "binance_minute60"),
}
EVENT_ORDER = {"DECISION": 0, "SIGNAL": 1, "ENTRY": 2, "EXIT": 3}


@dataclass(frozen=True)
class TradeRecord:
    ts: datetime
    event: str
    strategy: str
    symbol: str
    price: float
    pnl: float
    pnl_pct: float
    hold_sec: float
    reason: str


@dataclass(frozen=True)
class ExitTrade:
    entry_ts: datetime | None
    entry_price: float
    exit_ts: datetime
    exit_price: float
    symbol: str
    strategy: str
    pnl: float
    pnl_pct: float
    hold_sec: float
    reason: str


@dataclass(frozen=True)
class Candle:
    ts: datetime
    high: float
    low: float
    close: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ETH/BTC regime checkpoint report")
    parser.add_argument("--trade-log", default=str(DEFAULT_TRADE_LOG))
    parser.add_argument("--report-dir", default=str(DEFAULT_REPORT_DIR))
    parser.add_argument("--lookback-days", type=int, default=7)
    parser.add_argument(
        "--patch-ts",
        default="2026-04-23T10:08:29",
        help="Timestamp when the latest ETH/BTC regime guard patch was deployed",
    )
    parser.add_argument(
        "--focus-exit-ts",
        default="2026-04-23T09:16:49",
        help="Specific ETH exit timestamp to keep re-evaluating",
    )
    parser.add_argument(
        "--trade-log-tz-offset-hours",
        type=int,
        default=9,
        help="Offset between naive trade-log timestamps and UTC candle DB timestamps",
    )
    parser.add_argument("--output", default="")
    return parser.parse_args()


def parse_iso(raw: str) -> datetime:
    return datetime.fromisoformat(raw.strip())


def parse_record_timestamp(obj: dict) -> datetime | None:
    raw = obj.get("ts") or obj.get("timestamp")
    if not raw:
        return None
    try:
        return parse_iso(str(raw))
    except ValueError:
        return None


def load_trade_records(path: Path) -> list[TradeRecord]:
    rows: list[TradeRecord] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = parse_record_timestamp(obj)
            if ts is None:
                continue
            strategy = str(obj.get("strategy") or "")
            symbol = str(obj.get("symbol") or "").upper()
            if strategy not in {"mlp_direction_eth", "mlp_direction_btc"}:
                continue
            if symbol not in {"ETH", "BTC"}:
                continue
            rows.append(
                TradeRecord(
                    ts=ts,
                    event=str(obj.get("event") or ""),
                    strategy=strategy,
                    symbol=symbol,
                    price=float(obj.get("price") or 0.0),
                    pnl=float(obj.get("pnl") or 0.0),
                    pnl_pct=float(obj.get("pnl_pct") or 0.0),
                    hold_sec=float(obj.get("hold_sec") or 0.0),
                    reason=str(obj.get("reason") or ""),
                )
            )
    return sorted(rows, key=lambda row: (row.ts, EVENT_ORDER.get(row.event, 9)))


def build_exits(records: list[TradeRecord]) -> list[ExitTrade]:
    open_positions: dict[tuple[str, str], tuple[datetime, float]] = {}
    exits: list[ExitTrade] = []
    for row in records:
        key = (row.strategy, row.symbol)
        if row.event == "ENTRY":
            open_positions[key] = (row.ts, row.price)
            continue
        if row.event != "EXIT":
            continue
        entry_ts, entry_price = open_positions.pop(key, (None, 0.0))
        exits.append(
            ExitTrade(
                entry_ts=entry_ts,
                entry_price=entry_price,
                exit_ts=row.ts,
                exit_price=row.price,
                symbol=row.symbol,
                strategy=row.strategy,
                pnl=row.pnl,
                pnl_pct=row.pnl_pct,
                hold_sec=row.hold_sec,
                reason=row.reason,
            )
        )
    return exits


def classify_exit(reason: str) -> str:
    text = (reason or "").lower()
    if "regime_protect" in text and "below ema_120" in text:
        return "regime_protect_ema120"
    if "trailing stop" in text:
        return "trailing_stop"
    if "bear_regime_exit" in text:
        return "bear_regime_exit"
    if "peak drawdown" in text:
        return "regime_drawdown"
    if "stop loss intrabar" in text:
        return "stop_loss_intrabar"
    if "stop loss" in text:
        return "stop_loss"
    return "other"


def is_regime_protect(reason: str) -> bool:
    return classify_exit(reason) == "regime_protect_ema120"


def is_trailing_stop(reason: str) -> bool:
    return classify_exit(reason) == "trailing_stop"


def load_candles(symbol: str) -> list[Candle]:
    source = DB_SOURCES[symbol]
    db_path, table_name = source
    if not db_path.exists():
        return []
    with sqlite3.connect(str(db_path)) as conn:
        rows = conn.execute(
            f"""
            SELECT timestamp, high, low, close
            FROM {table_name}
            ORDER BY timestamp ASC
            """
        ).fetchall()
    candles: list[Candle] = []
    for ts_raw, high, low, close in rows:
        try:
            ts = parse_iso(str(ts_raw))
        except ValueError:
            continue
        candles.append(
            Candle(
                ts=ts,
                high=float(high or 0.0),
                low=float(low or 0.0),
                close=float(close or 0.0),
            )
        )
    return candles


def align_trade_ts_to_db_hour(ts: datetime, tz_offset_hours: int) -> datetime:
    aligned = ts - timedelta(hours=tz_offset_hours)
    return aligned.replace(minute=0, second=0, microsecond=0)


def summarize_window(exits: list[ExitTrade], start: datetime, end: datetime) -> dict[str, dict[str, float]]:
    summary: dict[str, dict[str, float]] = {}
    for strategy in ("mlp_direction_eth", "mlp_direction_btc"):
        rows = [trade for trade in exits if trade.strategy == strategy and start <= trade.exit_ts <= end]
        closed = len(rows)
        regime_count = sum(1 for trade in rows if is_regime_protect(trade.reason))
        trailing_count = sum(1 for trade in rows if is_trailing_stop(trade.reason))
        summary[strategy] = {
            "closed": float(closed),
            "regime_count": float(regime_count),
            "trailing_count": float(trailing_count),
            "pnl": sum(trade.pnl for trade in rows),
            "regime_pnl": sum(trade.pnl for trade in rows if is_regime_protect(trade.reason)),
            "trailing_pnl": sum(trade.pnl for trade in rows if is_trailing_stop(trade.reason)),
        }
    return summary


def find_exit(exits: list[ExitTrade], symbol: str, ts: datetime) -> ExitTrade | None:
    for trade in exits:
        if trade.symbol == symbol and trade.exit_ts == ts:
            return trade
    return None


def evaluate_follow_through(
    trade: ExitTrade,
    candles: list[Candle],
    tz_offset_hours: int,
) -> dict[str, object]:
    aligned_exit = align_trade_ts_to_db_hour(trade.exit_ts, tz_offset_hours)
    latest_candle_ts = candles[-1].ts if candles else None
    result: dict[str, object] = {
        "aligned_exit": aligned_exit,
        "latest_candle_ts": latest_candle_ts,
        "covered_24h": False,
        "status": "pending",
        "verdict": "pending",
    }
    if not candles:
        return result

    future = [candle for candle in candles if aligned_exit < candle.ts <= aligned_exit + timedelta(hours=24)]
    for hours in (6, 12, 24):
        window = [candle for candle in future if candle.ts <= aligned_exit + timedelta(hours=hours)]
        if not window:
            result[f"up_high_{hours}h_pct"] = None
            result[f"up_close_{hours}h_pct"] = None
            result[f"down_low_{hours}h_pct"] = None
            continue
        max_high = max(candle.high for candle in window)
        max_close = max(candle.close for candle in window)
        min_low = min(candle.low for candle in window)
        if trade.exit_price > 0:
            result[f"up_high_{hours}h_pct"] = ((max_high / trade.exit_price) - 1.0) * 100.0
            result[f"up_close_{hours}h_pct"] = ((max_close / trade.exit_price) - 1.0) * 100.0
            result[f"down_low_{hours}h_pct"] = ((min_low / trade.exit_price) - 1.0) * 100.0
        else:
            result[f"up_high_{hours}h_pct"] = 0.0
            result[f"up_close_{hours}h_pct"] = 0.0
            result[f"down_low_{hours}h_pct"] = 0.0

    if latest_candle_ts and latest_candle_ts >= aligned_exit + timedelta(hours=24):
        result["covered_24h"] = True
        result["status"] = "complete"
        up_24h = result.get("up_high_24h_pct")
        down_24h = result.get("down_low_24h_pct")
        if up_24h is not None and down_24h is not None and up_24h >= 2.0 and down_24h > -3.0:
            result["verdict"] = "likely oversensitive"
        else:
            result["verdict"] = "not clearly oversensitive"
    return result


def pct(count: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return (count / total) * 100.0


def format_window_section(label: str, summary: dict[str, dict[str, float]]) -> list[str]:
    lines = [f"## {label}", ""]
    for strategy, symbol in (("mlp_direction_eth", "ETH"), ("mlp_direction_btc", "BTC")):
        item = summary[strategy]
        closed = item["closed"]
        regime_count = item["regime_count"]
        trailing_count = item["trailing_count"]
        lines.append(f"### {symbol}")
        lines.append(f"- closed exits: `{int(closed)}`")
        lines.append(
            f"- checkpoint 1: regime_protect recurrence `{int(regime_count)}` / `{int(closed)}` ({pct(regime_count, closed):.2f}%), pnl `{item['regime_pnl']:.2f}`"
        )
        lines.append(
            f"- checkpoint 2: trailing_stop reach share `{int(trailing_count)}` / `{int(closed)}` ({pct(trailing_count, closed):.2f}%), pnl `{item['trailing_pnl']:.2f}`"
        )
        lines.append(f"- total realized pnl: `{item['pnl']:.2f}`")
        lines.append("")
    return lines


def format_follow_through_row(title: str, trade: ExitTrade, review: dict[str, object]) -> list[str]:
    lines = [f"### {title}", ""]
    lines.append(f"- Exit ts: `{trade.exit_ts.isoformat(timespec='seconds')}`")
    if trade.entry_ts is not None:
        lines.append(f"- Entry ts: `{trade.entry_ts.isoformat(timespec='seconds')}`")
    lines.append(f"- Exit price: `{trade.exit_price:.2f}`")
    lines.append(f"- Realized: pnl `{trade.pnl:.2f}`, pnl_pct `{trade.pnl_pct:.2f}%`, hold `{trade.hold_sec / 3600:.2f}h`")
    lines.append(f"- Reason: `{trade.reason}`")
    lines.append(f"- DB-aligned exit hour (UTC): `{review['aligned_exit'].isoformat(timespec='seconds')}`")
    if review["latest_candle_ts"] is not None:
        lines.append(
            f"- Latest local candle: `{review['latest_candle_ts'].isoformat(timespec='seconds')}`"
        )
    lines.append(f"- checkpoint 3 status: `{review['status']}`")
    if review["covered_24h"]:
        lines.append(
            f"- +24h follow-through: high `{review['up_high_24h_pct']:.2f}%`, close `{review['up_close_24h_pct']:.2f}%`, low `{review['down_low_24h_pct']:.2f}%`"
        )
        lines.append(f"- Verdict: `{review['verdict']}`")
    else:
        lines.append("- +24h follow-through: pending local candle coverage")
    lines.append("")
    return lines


def build_adjustment_decision_lines(
    patch_ts: datetime,
    summary_post_patch: dict[str, dict[str, float]],
    focus_review: dict[str, object] | None,
    completed_reviews: list[tuple[ExitTrade, dict[str, object]]],
) -> list[str]:
    lines = ["## Adjustment Decision", ""]

    post_patch_closed = sum(int(item["closed"]) for item in summary_post_patch.values())
    post_patch_regime = sum(int(item["regime_count"]) for item in summary_post_patch.values())
    post_patch_trailing = sum(int(item["trailing_count"]) for item in summary_post_patch.values())
    oversensitive_completed = sum(
        1 for _, review in completed_reviews if review.get("verdict") == "likely oversensitive"
    )

    lines.append(f"- Patch anchor: `{patch_ts.isoformat(timespec='seconds')}`")
    lines.append(f"- Post-patch ETH/BTC closed exits: `{post_patch_closed}`")
    lines.append(f"- Post-patch regime_protect exits: `{post_patch_regime}`")
    lines.append(f"- Post-patch trailing_stop exits: `{post_patch_trailing}`")
    lines.append(f"- Completed pre-patch oversensitive follow-through cases: `{oversensitive_completed}`")
    lines.append("")

    if post_patch_closed == 0:
        lines.append("- Decision: `hold current patch`")
        lines.append("- Reason:")
        lines.append("  - The latest guard change is already deployed, but there is no ETH/BTC post-patch exit sample yet.")
        lines.append("  - Another relaxation now would stack changes without isolating the effect of the current patch.")
        if focus_review is not None and not bool(focus_review.get("covered_24h")):
            lines.append("  - The focus ETH exit is still pending 24h follow-through completion in the local candle DB.")
        lines.append("")
        return lines

    if post_patch_regime == 0 and post_patch_trailing > 0:
        lines.append("- Decision: `hold current patch`")
        lines.append("- Reason:")
        lines.append("  - Post-patch exits no longer show regime_protect recurrence, and trailing stops are being reached.")
        lines.append("")
        return lines

    if post_patch_regime == 0 and post_patch_trailing == 0:
        lines.append("- Decision: `hold current patch`")
        lines.append("- Reason:")
        lines.append("  - Post-patch exits exist, but there is still no evidence that ETH/BTC need a second relaxation.")
        lines.append("")
        return lines

    lines.append("- Decision: `consider second relaxation`")
    lines.append("- Trigger:")
    lines.append("  - Regime-protect exits are still recurring after the latest guard patch.")
    lines.append("- Candidate next changes:")
    lines.append("  - Increase `ema_slow_grace_seconds_after_entry` from `43200` to `64800`.")
    lines.append("  - Increase `ema_slow_min_drawdown_from_hwm_pct` from `0.025` to `0.035`.")
    lines.append("  - Keep `ema_slow_require_fast_below_slow=true` and re-check after the next 24h/7d report.")
    lines.append("")
    return lines


def main() -> int:
    args = parse_args()
    report_dir = Path(args.report_dir)
    report_dir.mkdir(parents=True, exist_ok=True)

    trade_log = Path(args.trade_log)
    records = load_trade_records(trade_log)
    exits = build_exits(records)

    now = datetime.now()
    window_24h_start = now - timedelta(hours=24)
    window_7d_start = now - timedelta(days=args.lookback_days)
    patch_ts = parse_iso(args.patch_ts)
    summary_24h = summarize_window(exits, window_24h_start, now)
    summary_7d = summarize_window(exits, window_7d_start, now)
    summary_post_patch = summarize_window(exits, patch_ts, now)

    candles = {symbol: load_candles(symbol) for symbol in ("ETH", "BTC")}

    focus_exit = None
    if args.focus_exit_ts:
        focus_exit = find_exit(exits, "ETH", parse_iso(args.focus_exit_ts))

    pending_reviews: list[tuple[ExitTrade, dict[str, object]]] = []
    completed_reviews: list[tuple[ExitTrade, dict[str, object]]] = []
    for trade in exits:
        if trade.exit_ts < window_7d_start:
            continue
        if not is_regime_protect(trade.reason):
            continue
        if focus_exit is not None and trade.symbol == focus_exit.symbol and trade.exit_ts == focus_exit.exit_ts:
            continue
        review = evaluate_follow_through(
            trade,
            candles[trade.symbol],
            args.trade_log_tz_offset_hours,
        )
        target = completed_reviews if review["covered_24h"] else pending_reviews
        target.append((trade, review))

    output_path = (
        Path(args.output)
        if args.output
        else report_dir / f"eth_btc_regime_checkpoints_{now.strftime('%Y%m%d_%H%M%S')}.md"
    )

    lines = [
        "# ETH/BTC Regime Checkpoints",
        "",
        f"- Generated: `{now.isoformat(timespec='seconds')}`",
        f"- 24h window: `{window_24h_start.isoformat(timespec='seconds')}` -> `{now.isoformat(timespec='seconds')}`",
        f"- 7d window: `{window_7d_start.isoformat(timespec='seconds')}` -> `{now.isoformat(timespec='seconds')}`",
        "",
    ]
    lines.extend(format_window_section("24h Checkpoints", summary_24h))
    lines.extend(format_window_section("7d Checkpoints", summary_7d))

    lines.extend(["## Checkpoint 3", ""])
    focus_review: dict[str, object] | None = None
    if focus_exit is not None:
        focus_review = evaluate_follow_through(
            focus_exit,
            candles[focus_exit.symbol],
            args.trade_log_tz_offset_hours,
        )
        lines.extend(
            format_follow_through_row(
                f"Focus ETH Exit {focus_exit.exit_ts.isoformat(timespec='seconds')}",
                focus_exit,
                focus_review,
            )
        )
    else:
        lines.append(f"- Focus exit `{args.focus_exit_ts}` not found in the trade log.")
        lines.append("")

    lines.extend(["## Recent Regime-Protect Follow-through", ""])
    if completed_reviews:
        for trade, review in completed_reviews:
            lines.extend(
                format_follow_through_row(
                    f"{trade.symbol} {trade.exit_ts.isoformat(timespec='seconds')}",
                    trade,
                    review,
                )
            )
    else:
        lines.append("- No completed regime_protect follow-through cases in the current lookback window.")
        lines.append("")

    lines.extend(["## Pending Follow-through", ""])
    if pending_reviews:
        for trade, review in pending_reviews:
            lines.extend(
                format_follow_through_row(
                    f"{trade.symbol} {trade.exit_ts.isoformat(timespec='seconds')}",
                    trade,
                    review,
                )
            )
    else:
        lines.append("- No pending regime_protect follow-through cases.")
        lines.append("")

    lines.extend(build_adjustment_decision_lines(patch_ts, summary_post_patch, focus_review, completed_reviews))

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"report_md={output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
