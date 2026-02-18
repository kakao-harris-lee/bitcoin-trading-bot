"""Shared cooldown store for regime-long style strategies.

This provides a lightweight in-memory cooldown mechanism that can be shared
between entry/exit strategy instances in the same process.
"""

from __future__ import annotations

from typing import Dict, Tuple


_COOLDOWNS: Dict[Tuple[str, str], int] = {}
_LAST_TICK_TS: Dict[Tuple[str, str], int] = {}


def activate_cooldown(symbol: str, tag: str, bars: int) -> None:
    """Activate (or extend) cooldown for symbol/tag."""
    if bars <= 0:
        return
    key = (symbol, tag)
    _COOLDOWNS[key] = max(_COOLDOWNS.get(key, 0), int(bars))


def consume_cooldown(symbol: str, tag: str, timestamp: int) -> int:
    """Consume one cooldown bar at most once per timestamp.

    Returns remaining cooldown bars after consumption.
    """
    key = (symbol, tag)
    last_ts = _LAST_TICK_TS.get(key)
    if last_ts != int(timestamp):
        _LAST_TICK_TS[key] = int(timestamp)
        remaining = _COOLDOWNS.get(key, 0)
        if remaining > 0:
            remaining -= 1
            if remaining <= 0:
                _COOLDOWNS.pop(key, None)
            else:
                _COOLDOWNS[key] = remaining
    return _COOLDOWNS.get(key, 0)


def clear_cooldown(symbol: str, tag: str) -> None:
    """Clear cooldown state for symbol/tag."""
    key = (symbol, tag)
    _COOLDOWNS.pop(key, None)
    _LAST_TICK_TS.pop(key, None)
