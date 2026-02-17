from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional, Tuple


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


@dataclass
class RiskConfig:
    """Minimal live-trading risk controls.

    Defaults are intentionally conservative only where it won't change paper behavior.
    """

    # Hard kill-switch: if this file exists, live trading loop stops.
    kill_switch_file: str = "analysis/KILL_SWITCH"

    # Daily max loss guard (%). When breached, new entries are blocked.
    # 0 disables the guard.
    daily_max_loss_pct: float = 2.0

    # Caps on per-entry sizing as a fraction of available cash.
    max_binance_entry_fraction: float = 1.0

    # Minimum order amounts.
    min_binance_order_usdt: float = 10.0

    # Kill-switch recommendation thresholds (notify operator; does not auto-enable).
    recommend_kill_on_daily_loss_pct: float = 4.0
    recommend_kill_on_price_failures: int = 2
    recommend_kill_on_consecutive_errors: int = 3


def resolve_kill_switch_path(path: str) -> Path:
    p = Path(path)
    if p.is_absolute():
        return p
    return _repo_root() / p


def kill_switch_active(path: str) -> bool:
    try:
        return resolve_kill_switch_path(path).exists()
    except (OSError, ValueError):
        return False


def set_kill_switch(path: str, active: bool) -> Path:
    """Create/remove the kill-switch file. Returns the resolved Path."""
    p = resolve_kill_switch_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    if active:
        p.touch(exist_ok=True)
    else:
        try:
            p.unlink(missing_ok=True)
        except TypeError:  # pragma: no cover (py<3.8)
            if p.exists():
                p.unlink()
    return p


def should_block_new_entries(
    *,
    daily_max_loss_pct: float,
    day_start_total: float,
    current_total: float,
) -> Tuple[bool, Optional[float]]:
    """Return (blocked, daily_return_pct)."""
    if daily_max_loss_pct is None:
        return (False, None)

    threshold = float(daily_max_loss_pct)
    if threshold <= 0:
        return (False, None)

    if day_start_total <= 0:
        return (False, None)

    daily_return_pct = ((current_total - day_start_total) / day_start_total) * 100
    return (daily_return_pct <= -abs(threshold), daily_return_pct)


def clamp_fraction(value: float, cap: float) -> float:
    v = max(0.0, min(1.0, float(value)))
    c = max(0.0, min(1.0, float(cap)))
    return min(v, c)


def today() -> date:
    return date.today()
