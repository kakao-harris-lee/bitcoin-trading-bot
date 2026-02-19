"""Runtime defaults shared across app, web services, and scripts."""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ALLOCATION_PATH = PROJECT_ROOT / "config" / "strategies" / "allocation.json"
DEFAULT_SYMBOLS: tuple[str, ...] = ("BTC", "ETH", "SOL", "BNB")


def load_allocation_symbols(
    default: Sequence[str] = DEFAULT_SYMBOLS,
) -> list[str]:
    """Load configured symbols from allocation.json with safe fallback."""
    fallback = [s.upper() for s in default if isinstance(s, str) and s]
    try:
        with ALLOCATION_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        symbols = data.get("symbols", [])
        parsed = [str(s).upper() for s in symbols if str(s).strip()]
        if parsed:
            return parsed
    except Exception as exc:  # pylint: disable=broad-exception-caught
        logger.debug("Failed to load symbols from %s: %s", ALLOCATION_PATH, exc)
    return fallback


def default_backtest_date_range(days: int = 365) -> tuple[str, str]:
    """Return rolling default backtest date range (start_date, end_date)."""
    end_dt = date.today()
    start_dt = end_dt - timedelta(days=max(1, int(days)))
    return start_dt.isoformat(), end_dt.isoformat()

