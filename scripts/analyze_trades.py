#!/usr/bin/env python3
"""Analyze structured trade logs from logs/trades.jsonl.

Usage:
    python scripts/analyze_trades.py                    # Today's summary
    python scripts/analyze_trades.py --date 2026-01-25  # Specific date
    python scripts/analyze_trades.py --last 7           # Last 7 days
    python scripts/analyze_trades.py --filter BTC       # Filter by symbol
    python scripts/analyze_trades.py --event FILL       # Filter by event type

Log format (JSONL - one JSON object per line):
    {"ts":"2026-01-25T12:00:00","event":"ENTRY","symbol":"BTC","price":100000,...}
"""
import argparse
import json
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path


def parse_args():
    parser = argparse.ArgumentParser(description="Analyze structured trade logs")
    parser.add_argument("--file", default="logs/trades.jsonl", help="Log file path")
    parser.add_argument("--date", help="Filter by date (YYYY-MM-DD)")
    parser.add_argument("--last", type=int, help="Last N days")
    parser.add_argument("--filter", help="Filter by symbol")
    parser.add_argument("--event", help="Filter by event type (ENTRY, EXIT, FILL, PNL, DECISION)")
    parser.add_argument("--strategy", help="Filter by strategy name")
    parser.add_argument("--raw", action="store_true", help="Output raw JSON lines")
    return parser.parse_args()


def load_logs(file_path: str, filters: dict) -> list[dict]:
    """Load and filter log entries."""
    path = Path(file_path)
    if not path.exists():
        print(f"Log file not found: {file_path}")
        return []

    entries = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entry = json.loads(line)

                # Apply filters
                if filters.get("date"):
                    if not entry.get("ts", "").startswith(filters["date"]):
                        continue

                if filters.get("start_date"):
                    entry_date = entry.get("ts", "")[:10]
                    if entry_date < filters["start_date"]:
                        continue

                if filters.get("symbol"):
                    if entry.get("symbol") != filters["symbol"].upper():
                        continue

                if filters.get("event"):
                    if entry.get("event") != filters["event"].upper():
                        continue

                if filters.get("strategy"):
                    if filters["strategy"] not in entry.get("strategy", ""):
                        continue

                entries.append(entry)
            except json.JSONDecodeError:
                continue

    return entries


def summarize_trades(entries: list[dict]) -> None:
    """Print trade summary statistics."""
    if not entries:
        print("No matching entries found.")
        return

    # Group by event type
    by_event = defaultdict(list)
    for e in entries:
        by_event[e.get("event", "UNKNOWN")].append(e)

    print("\n" + "=" * 60)
    print("TRADE LOG ANALYSIS")
    print("=" * 60)
    print(f"Total entries: {len(entries)}")
    print(f"Date range: {entries[0].get('ts', 'N/A')[:10]} to {entries[-1].get('ts', 'N/A')[:10]}")
    print()

    # Event breakdown
    print("Events by type:")
    for event_type, event_entries in sorted(by_event.items()):
        print(f"  {event_type}: {len(event_entries)}")
    print()

    # Entry/Exit analysis
    entries_list = by_event.get("ENTRY", [])
    exits_list = by_event.get("EXIT", [])

    if entries_list:
        print(f"ENTRIES ({len(entries_list)}):")
        by_symbol = defaultdict(list)
        for e in entries_list:
            by_symbol[e.get("symbol", "?")].append(e)
        for symbol, symbol_entries in sorted(by_symbol.items()):
            print(f"  {symbol}: {len(symbol_entries)} entries")
        print()

    if exits_list:
        print(f"EXITS ({len(exits_list)}):")
        total_pnl = 0
        wins = 0
        losses = 0
        by_symbol = defaultdict(lambda: {"pnl": 0, "count": 0, "wins": 0})

        for e in exits_list:
            pnl = e.get("pnl", 0)
            symbol = e.get("symbol", "?")
            by_symbol[symbol]["pnl"] += pnl
            by_symbol[symbol]["count"] += 1
            if pnl > 0:
                by_symbol[symbol]["wins"] += 1
                wins += 1
            else:
                losses += 1
            total_pnl += pnl

        for symbol, data in sorted(by_symbol.items()):
            win_rate = data["wins"] / data["count"] * 100 if data["count"] > 0 else 0
            print(f"  {symbol}: {data['count']} exits, P&L: ${data['pnl']:+.2f}, Win rate: {win_rate:.1f}%")

        print()
        print(f"  Total P&L: ${total_pnl:+.2f}")
        print(f"  Win/Loss: {wins}/{losses}")
        if wins + losses > 0:
            print(f"  Win rate: {wins / (wins + losses) * 100:.1f}%")
        print()

    # Strategy breakdown
    by_strategy = defaultdict(lambda: {"entries": 0, "exits": 0, "pnl": 0})
    for e in entries_list:
        by_strategy[e.get("strategy", "?")]["entries"] += 1
    for e in exits_list:
        by_strategy[e.get("strategy", "?")]["exits"] += 1
        by_strategy[e.get("strategy", "?")]["pnl"] += e.get("pnl", 0)

    if by_strategy:
        print("By Strategy:")
        for strategy, data in sorted(by_strategy.items(), key=lambda x: -x[1]["pnl"]):
            print(f"  {strategy}: {data['entries']} entries, {data['exits']} exits, P&L: ${data['pnl']:+.2f}")
        print()

    # Decision analysis
    decisions = by_event.get("DECISION", [])
    if decisions:
        by_decision = defaultdict(int)
        for d in decisions:
            by_decision[d.get("decision", "?")] += 1
        print(f"DECISIONS ({len(decisions)}):")
        for decision, count in sorted(by_decision.items(), key=lambda x: -x[1]):
            print(f"  {decision}: {count}")
        print()

    print("=" * 60)


def print_raw(entries: list[dict]) -> None:
    """Print raw JSON entries."""
    for e in entries:
        print(json.dumps(e))


def main():
    args = parse_args()

    filters = {}
    if args.date:
        filters["date"] = args.date
    elif args.last:
        start = datetime.now() - timedelta(days=args.last)
        filters["start_date"] = start.strftime("%Y-%m-%d")

    if args.filter:
        filters["symbol"] = args.filter
    if args.event:
        filters["event"] = args.event
    if args.strategy:
        filters["strategy"] = args.strategy

    entries = load_logs(args.file, filters)

    if args.raw:
        print_raw(entries)
    else:
        summarize_trades(entries)


if __name__ == "__main__":
    main()
