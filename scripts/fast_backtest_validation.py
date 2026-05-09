#!/usr/bin/env python3
"""Fast operational backtest validation for active spot strategies.

This command intentionally reuses the dashboard backtest engine but skips chart
generation and MLflow logging so BTC/ETH validation can run in seconds.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from web.services.backtest_runner import (  # noqa: E402
    BacktestJob,
    _load_allocation_config,
    _run_generic_backtest,
)

DEFAULT_PERIODS = (
    "2025-01-01:today",
    "2026-01-01:today",
    "2026-02-17:today",
)


@dataclass
class ValidationRow:
    strategy: str
    symbol: str
    start_date: str
    end_date: str
    backtest_end_date: str
    latest_bar: str
    total_return_pct: float
    benchmark_return_pct: float
    alpha_pct: float
    max_drawdown_pct: float
    sharpe_ratio: float
    profit_factor: float
    win_rate: float
    total_trades: int
    final_capital: float
    status: str
    status_reasons: list[str]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run fast BTC/ETH backtest validation against buy-and-hold."
    )
    parser.add_argument(
        "--strategies",
        nargs="*",
        help="Strategy IDs. Defaults to enabled spot strategies in allocation.json.",
    )
    parser.add_argument(
        "--period",
        action="append",
        dest="periods",
        help=(
            "Validation period START:END. END may be 'today'. "
            "Can be repeated. Default runs 2025, 2026 YTD, and 2026-02-17 windows."
        ),
    )
    parser.add_argument("--initial-capital", type=float, default=10_000.0)
    parser.add_argument("--min-trades", type=int, default=3)
    parser.add_argument("--max-underperform-pct", type=float, default=5.0)
    parser.add_argument("--max-drawdown-pct", type=float, default=25.0)
    parser.add_argument(
        "--output-dir",
        default=str(PROJECT_ROOT / "logs" / "backtest_reports"),
        help="Directory for JSON/Markdown report artifacts.",
    )
    parser.add_argument(
        "--no-save",
        action="store_true",
        help="Print only; do not write report artifacts.",
    )
    return parser.parse_args()


def _today() -> date:
    return date.today()


def _parse_date(value: str) -> date:
    if value == "today":
        return _today()
    return date.fromisoformat(value)


def parse_period(value: str) -> tuple[str, str, str]:
    if ":" not in value:
        raise ValueError(f"Invalid period '{value}', expected START:END")
    start_raw, end_raw = value.split(":", 1)
    start = _parse_date(start_raw)
    end = _parse_date(end_raw)
    if end < start:
        raise ValueError(f"Invalid period '{value}', END is before START")

    # DataLoader end-date filtering is inclusive at midnight. Passing end+1 day
    # includes all candles for the requested local end date.
    backtest_end = end + timedelta(days=1)
    return start.isoformat(), end.isoformat(), backtest_end.isoformat()


def resolve_strategies(requested: list[str] | None) -> list[str]:
    if requested:
        return requested

    allocation = _load_allocation_config()
    strategies = allocation.get("strategies", {})
    enabled = [
        name
        for name, config in strategies.items()
        if isinstance(config, dict)
        and config.get("enabled", True)
        and config.get("market", "spot") == "spot"
    ]
    if not enabled:
        raise ValueError("No enabled spot strategies found in allocation.json")
    return enabled


def calculate_benchmark_return(df: Any) -> float:
    if df is None or df.empty:
        return 0.0
    first = float(df.iloc[0]["close"])
    last = float(df.iloc[-1]["close"])
    if first <= 0:
        return 0.0
    return (last / first - 1.0) * 100.0


def classify_result(
    result: dict[str, Any],
    benchmark_return_pct: float,
    min_trades: int,
    max_underperform_pct: float,
    max_drawdown_pct: float,
) -> tuple[str, list[str]]:
    reasons: list[str] = []
    status = "PASS"

    total_return = float(result.get("total_return_pct", 0.0) or 0.0)
    alpha = total_return - benchmark_return_pct
    drawdown = float(result.get("max_drawdown_pct", 0.0) or 0.0)
    trades = int(result.get("total_trades", 0) or 0)
    profit_factor = float(result.get("profit_factor", 0.0) or 0.0)
    sharpe = float(result.get("sharpe_ratio", 0.0) or 0.0)

    if drawdown < -abs(max_drawdown_pct):
        status = "FAIL"
        reasons.append(f"MDD {drawdown:.2f}% < -{abs(max_drawdown_pct):.2f}%")
    if alpha < -abs(max_underperform_pct):
        status = "FAIL"
        reasons.append(
            f"alpha {alpha:.2f}% < -{abs(max_underperform_pct):.2f}%"
        )

    if status == "PASS" and trades < min_trades:
        status = "WARN"
        reasons.append(f"trades {trades} < {min_trades}")
    if status == "PASS" and profit_factor < 1.0:
        status = "WARN"
        reasons.append(f"PF {profit_factor:.2f} < 1.00")
    if status == "PASS" and sharpe < 0:
        status = "WARN"
        reasons.append(f"Sharpe {sharpe:.2f} < 0")

    if not reasons:
        reasons.append("meets fast validation gates")
    return status, reasons


def run_validation_row(
    strategy: str,
    start_date: str,
    display_end_date: str,
    backtest_end_date: str,
    initial_capital: float,
    min_trades: int,
    max_underperform_pct: float,
    max_drawdown_pct: float,
) -> ValidationRow:
    job = BacktestJob(f"fast-{strategy}", {})
    result, df = _run_generic_backtest(
        strategy, start_date, backtest_end_date, initial_capital, job
    )
    benchmark = calculate_benchmark_return(df)
    status, reasons = classify_result(
        result=result,
        benchmark_return_pct=benchmark,
        min_trades=min_trades,
        max_underperform_pct=max_underperform_pct,
        max_drawdown_pct=max_drawdown_pct,
    )
    total_return = float(result.get("total_return_pct", 0.0) or 0.0)
    latest_bar = str(df.iloc[-1]["timestamp"]) if df is not None and not df.empty else ""
    return ValidationRow(
        strategy=strategy,
        symbol=str(result.get("symbol", "")),
        start_date=start_date,
        end_date=display_end_date,
        backtest_end_date=backtest_end_date,
        latest_bar=latest_bar,
        total_return_pct=round(total_return, 2),
        benchmark_return_pct=round(benchmark, 2),
        alpha_pct=round(total_return - benchmark, 2),
        max_drawdown_pct=round(float(result.get("max_drawdown_pct", 0.0) or 0.0), 2),
        sharpe_ratio=round(float(result.get("sharpe_ratio", 0.0) or 0.0), 2),
        profit_factor=round(float(result.get("profit_factor", 0.0) or 0.0), 2),
        win_rate=round(float(result.get("win_rate", 0.0) or 0.0), 2),
        total_trades=int(result.get("total_trades", 0) or 0),
        final_capital=round(float(result.get("final_capital", 0.0) or 0.0), 2),
        status=status,
        status_reasons=reasons,
    )


def render_table(rows: list[ValidationRow]) -> str:
    headers = [
        "period",
        "strategy",
        "ret%",
        "bnh%",
        "alpha%",
        "trades",
        "win%",
        "PF",
        "MDD%",
        "Sharpe",
        "status",
    ]
    lines = [
        " | ".join(headers),
        " | ".join(["---"] * len(headers)),
    ]
    for row in rows:
        lines.append(
            " | ".join(
                [
                    f"{row.start_date}..{row.end_date}",
                    row.strategy,
                    f"{row.total_return_pct:.2f}",
                    f"{row.benchmark_return_pct:.2f}",
                    f"{row.alpha_pct:.2f}",
                    str(row.total_trades),
                    f"{row.win_rate:.2f}",
                    f"{row.profit_factor:.2f}",
                    f"{row.max_drawdown_pct:.2f}",
                    f"{row.sharpe_ratio:.2f}",
                    row.status,
                ]
            )
        )
    return "\n".join(lines)


def render_markdown(rows: list[ValidationRow], generated_at: str) -> str:
    detail_lines = []
    for row in rows:
        detail_lines.append(
            f"- `{row.strategy}` `{row.start_date}..{row.end_date}`: "
            f"{row.status} ({'; '.join(row.status_reasons)}), "
            f"latest_bar={row.latest_bar}"
        )
    return "\n".join(
        [
            f"# Fast Backtest Validation ({generated_at})",
            "",
            render_table(rows),
            "",
            "## Gate Details",
            "",
            *detail_lines,
            "",
        ]
    )


def save_reports(rows: list[ValidationRow], output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now().strftime("%Y%m%d_%H%M%S")
    payload = {
        "generated_at": generated_at,
        "rows": [asdict(row) for row in rows],
    }
    json_path = output_dir / f"fast_validation_{generated_at}.json"
    md_path = output_dir / f"fast_validation_{generated_at}.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    md_path.write_text(render_markdown(rows, generated_at), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    args = parse_args()
    periods = [parse_period(period) for period in (args.periods or DEFAULT_PERIODS)]
    strategies = resolve_strategies(args.strategies)

    rows: list[ValidationRow] = []
    for start_date, display_end_date, backtest_end_date in periods:
        for strategy in strategies:
            rows.append(
                run_validation_row(
                    strategy=strategy,
                    start_date=start_date,
                    display_end_date=display_end_date,
                    backtest_end_date=backtest_end_date,
                    initial_capital=args.initial_capital,
                    min_trades=args.min_trades,
                    max_underperform_pct=args.max_underperform_pct,
                    max_drawdown_pct=args.max_drawdown_pct,
                )
            )

    print(render_table(rows))
    for row in rows:
        print(
            f"{row.status}: {row.strategy} {row.start_date}..{row.end_date} - "
            f"{'; '.join(row.status_reasons)}"
        )

    if not args.no_save:
        json_path, md_path = save_reports(rows, Path(args.output_dir))
        print(f"Saved JSON: {json_path}")
        print(f"Saved Markdown: {md_path}")

    return 1 if any(row.status == "FAIL" for row in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
