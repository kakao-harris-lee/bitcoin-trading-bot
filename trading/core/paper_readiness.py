"""Paper trading readiness checks for live mode gating."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any


@dataclass
class StrategyPaperMetrics:
    strategy: str
    exits: int = 0
    wins: int = 0
    losses: int = 0
    pnl: float = 0.0
    gross_profit: float = 0.0
    gross_loss: float = 0.0

    @property
    def win_rate(self) -> float:
        return (self.wins / self.exits * 100.0) if self.exits > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.gross_loss <= 0:
            return float("inf") if self.gross_profit > 0 else 0.0
        return self.gross_profit / self.gross_loss


@dataclass
class PaperReadinessReport:
    ready: bool
    config_path: str
    trades_log_path: str
    window_start: datetime
    window_end: datetime
    enabled_strategies: list[str]
    metrics: dict[str, StrategyPaperMetrics]
    total_exits: int
    total_wins: int
    total_losses: int
    total_pnl: float
    total_gross_profit: float
    total_gross_loss: float
    errors: list[str]
    warnings: list[str]
    ignored_strategy_counts: dict[str, int]

    @property
    def win_rate(self) -> float:
        return (self.total_wins / self.total_exits * 100.0) if self.total_exits > 0 else 0.0

    @property
    def profit_factor(self) -> float:
        if self.total_gross_loss <= 0:
            return float("inf") if self.total_gross_profit > 0 else 0.0
        return self.total_gross_profit / self.total_gross_loss


def _parse_iso_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        value = raw.strip()
        if value.endswith("Z"):
            value = value[:-1] + "+00:00"
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is not None:
            return dt.replace(tzinfo=None)
        return dt
    except ValueError:
        return None


def _load_enabled_strategies(config_path: Path) -> list[str]:
    with config_path.open() as f:
        config = json.load(f)
    strategies = config.get("strategies", {})
    if not isinstance(strategies, dict):
        return []
    return [name for name, cfg in strategies.items() if not isinstance(cfg, dict) or cfg.get("enabled", True)]


def _build_report(
    *,
    ready: bool,
    config_path: Path,
    trades_log_path: Path,
    window_start: datetime,
    window_end: datetime,
    enabled_strategies: list[str],
    metrics: dict[str, StrategyPaperMetrics],
    total_exits: int,
    total_wins: int,
    total_losses: int,
    total_pnl: float,
    total_gross_profit: float,
    total_gross_loss: float,
    errors: list[str],
    warnings: list[str],
    ignored_strategy_counts: dict[str, int],
) -> PaperReadinessReport:
    return PaperReadinessReport(
        ready=ready,
        config_path=str(config_path),
        trades_log_path=str(trades_log_path),
        window_start=window_start,
        window_end=window_end,
        enabled_strategies=enabled_strategies,
        metrics=metrics,
        total_exits=total_exits,
        total_wins=total_wins,
        total_losses=total_losses,
        total_pnl=total_pnl,
        total_gross_profit=total_gross_profit,
        total_gross_loss=total_gross_loss,
        errors=errors,
        warnings=warnings,
        ignored_strategy_counts=ignored_strategy_counts,
    )


def _calculate_profit_factor(gross_profit: float, gross_loss: float) -> float:
    if gross_loss <= 0:
        return float("inf") if gross_profit > 0 else 0.0
    return gross_profit / gross_loss


def _collect_paper_exit_metrics(
    *,
    trades_log: Path,
    metrics: dict[str, StrategyPaperMetrics],
    window_start: datetime,
    now: datetime,
) -> tuple[int, int, dict[str, int]]:
    parsed = 0
    skipped_invalid_ts = 0
    ignored_strategy_counts: dict[str, int] = {}

    with trades_log.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue

            if event.get("event") != "EXIT":
                continue
            if str(event.get("mode", "")).lower() != "paper":
                continue

            strategy = event.get("strategy")
            ts = _parse_iso_datetime(str(event.get("ts", "")))
            if ts is None:
                skipped_invalid_ts += 1
                continue
            if ts < window_start or ts > now:
                continue

            if strategy not in metrics:
                key = str(strategy) if strategy is not None else "unknown"
                ignored_strategy_counts[key] = ignored_strategy_counts.get(key, 0) + 1
                continue

            pnl_raw = event.get("pnl")
            if pnl_raw is None:
                continue
            try:
                pnl = float(pnl_raw)
            except (TypeError, ValueError):
                continue

            parsed += 1
            m = metrics[strategy]
            m.exits += 1
            m.pnl += pnl
            if pnl > 0:
                m.wins += 1
                m.gross_profit += pnl
            elif pnl < 0:
                m.losses += 1
                m.gross_loss += abs(pnl)

    return parsed, skipped_invalid_ts, ignored_strategy_counts


def _append_collection_warnings(
    warnings: list[str],
    skipped_invalid_ts: int,
    ignored_strategy_counts: dict[str, int],
) -> None:
    if skipped_invalid_ts > 0:
        warnings.append(f"Skipped {skipped_invalid_ts} records with invalid timestamp format.")
    if ignored_strategy_counts:
        total_ignored = sum(ignored_strategy_counts.values())
        top = sorted(
            ignored_strategy_counts.items(),
            key=lambda item: item[1],
            reverse=True,
        )[:5]
        top_str = ", ".join(f"{name}({count})" for name, count in top)
        warnings.append(
            f"Ignored {total_ignored} paper EXIT records for non-enabled strategies: {top_str}"
        )


def _aggregate_metrics(
    metrics: dict[str, StrategyPaperMetrics],
) -> tuple[int, int, int, float, float, float]:
    total_exits = sum(m.exits for m in metrics.values())
    total_wins = sum(m.wins for m in metrics.values())
    total_losses = sum(m.losses for m in metrics.values())
    total_pnl = sum(m.pnl for m in metrics.values())
    total_gross_profit = sum(m.gross_profit for m in metrics.values())
    total_gross_loss = sum(m.gross_loss for m in metrics.values())
    return (
        total_exits,
        total_wins,
        total_losses,
        total_pnl,
        total_gross_profit,
        total_gross_loss,
    )


def _append_readiness_threshold_errors(
    *,
    errors: list[str],
    metrics: dict[str, StrategyPaperMetrics],
    min_exits_per_strategy: int,
    min_total_exits: int,
    min_win_rate_pct: float,
    min_profit_factor: float,
    require_positive_pnl: bool,
    total_exits: int,
    total_wins: int,
    total_pnl: float,
    total_gross_profit: float,
    total_gross_loss: float,
) -> None:
    for strategy, m in metrics.items():
        if m.exits < min_exits_per_strategy:
            errors.append(
                f"{strategy}: not enough paper exits ({m.exits} < {min_exits_per_strategy})"
            )

    if total_exits < min_total_exits:
        errors.append(f"Total paper exits too low ({total_exits} < {min_total_exits})")

    win_rate = (total_wins / total_exits * 100.0) if total_exits > 0 else 0.0
    if total_exits > 0 and win_rate < min_win_rate_pct:
        errors.append(f"Paper win rate too low ({win_rate:.2f}% < {min_win_rate_pct:.2f}%)")

    profit_factor = _calculate_profit_factor(total_gross_profit, total_gross_loss)
    if total_exits > 0 and profit_factor < min_profit_factor:
        errors.append(
            f"Paper profit factor too low ({profit_factor:.2f} < {min_profit_factor:.2f})"
        )

    if require_positive_pnl and total_exits > 0 and total_pnl <= 0:
        errors.append(f"Paper total P&L must be positive (current: {total_pnl:.2f})")


def evaluate_paper_readiness(
    *,
    config_path: str = "config/strategies/allocation.json",
    trades_log_path: str = "logs/trades.jsonl",
    lookback_days: int = 14,
    min_exits_per_strategy: int = 10,
    min_total_exits: int = 40,
    min_win_rate_pct: float = 45.0,
    min_profit_factor: float = 1.0,
    require_positive_pnl: bool = True,
    now: datetime | None = None,
) -> PaperReadinessReport:
    now = now or datetime.utcnow()
    window_start = now - timedelta(days=max(1, int(lookback_days)))

    config = Path(config_path)
    trades_log = Path(trades_log_path)

    errors: list[str] = []
    warnings: list[str] = []

    if not config.exists():
        errors.append(f"Config not found: {config}")
        return _build_report(
            ready=False,
            config_path=config,
            trades_log_path=trades_log,
            window_start=window_start,
            window_end=now,
            enabled_strategies=[],
            metrics={},
            total_exits=0,
            total_wins=0,
            total_losses=0,
            total_pnl=0.0,
            total_gross_profit=0.0,
            total_gross_loss=0.0,
            errors=errors,
            warnings=warnings,
            ignored_strategy_counts={},
        )

    enabled_strategies = _load_enabled_strategies(config)
    metrics = {name: StrategyPaperMetrics(strategy=name) for name in enabled_strategies}

    if not enabled_strategies:
        errors.append("No enabled strategies found in allocation config.")

    ignored_strategy_counts: dict[str, int] = {}
    if not trades_log.exists():
        errors.append(f"Trades log not found: {trades_log}")
    else:
        parsed, skipped_invalid_ts, ignored_strategy_counts = _collect_paper_exit_metrics(
            trades_log=trades_log,
            metrics=metrics,
            window_start=window_start,
            now=now,
        )
        _append_collection_warnings(
            warnings=warnings,
            skipped_invalid_ts=skipped_invalid_ts,
            ignored_strategy_counts=ignored_strategy_counts,
        )
        if parsed == 0:
            errors.append(
                "No paper EXIT events found for enabled strategies in the readiness window."
            )

    (
        total_exits,
        total_wins,
        total_losses,
        total_pnl,
        total_gross_profit,
        total_gross_loss,
    ) = _aggregate_metrics(metrics)

    _append_readiness_threshold_errors(
        errors=errors,
        metrics=metrics,
        min_exits_per_strategy=min_exits_per_strategy,
        min_total_exits=min_total_exits,
        min_win_rate_pct=min_win_rate_pct,
        min_profit_factor=min_profit_factor,
        require_positive_pnl=require_positive_pnl,
        total_exits=total_exits,
        total_wins=total_wins,
        total_pnl=total_pnl,
        total_gross_profit=total_gross_profit,
        total_gross_loss=total_gross_loss,
    )

    return _build_report(
        ready=len(errors) == 0,
        config_path=config,
        trades_log_path=trades_log,
        window_start=window_start,
        window_end=now,
        enabled_strategies=enabled_strategies,
        metrics=metrics,
        total_exits=total_exits,
        total_wins=total_wins,
        total_losses=total_losses,
        total_pnl=total_pnl,
        total_gross_profit=total_gross_profit,
        total_gross_loss=total_gross_loss,
        errors=errors,
        warnings=warnings,
        ignored_strategy_counts=ignored_strategy_counts,
    )


def format_paper_readiness_report(report: PaperReadinessReport) -> str:
    lines: list[str] = []
    lines.append(
        f"Paper readiness window: {report.window_start.isoformat()} -> {report.window_end.isoformat()}"
    )
    lines.append(f"Config: {report.config_path}")
    lines.append(f"Trades log: {report.trades_log_path}")
    lines.append(
        f"Totals: exits={report.total_exits}, win_rate={report.win_rate:.2f}%, "
        f"pnl={report.total_pnl:.2f}, pf={report.profit_factor:.2f}"
    )
    lines.append("Per-strategy:")
    for name in report.enabled_strategies:
        m = report.metrics.get(name, StrategyPaperMetrics(strategy=name))
        lines.append(
            f"  - {name}: exits={m.exits}, win_rate={m.win_rate:.2f}%, pnl={m.pnl:.2f}, pf={m.profit_factor:.2f}"
        )
    if report.warnings:
        lines.append("Warnings:")
        for w in report.warnings:
            lines.append(f"  - {w}")
    if report.errors:
        lines.append("Errors:")
        for e in report.errors:
            lines.append(f"  - {e}")
    lines.append(f"Ready: {'YES' if report.ready else 'NO'}")
    return "\n".join(lines)
