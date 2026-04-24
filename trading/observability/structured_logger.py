# trading/observability/structured_logger.py
"""Structured one-line JSON logger for trade analysis.

All trade events are logged as single-line JSON for easy parsing with grep, jq, awk.

Log format:
    {"ts":"2026-01-25T12:00:00","event":"FILL","symbol":"BTC","side":"BUY",...}

Usage:
    from trading.observability.structured_logger import trade_logger
    trade_logger.entry(symbol="BTC", price=100000, qty=0.01, strategy="mlp_direction_btc")
    trade_logger.exit(symbol="BTC", price=101500, qty=0.01, pnl=15.0, pnl_pct=1.5)
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from typing import Any, Optional

# Create dedicated logger for structured trade events
_structured_logger = logging.getLogger("trade.structured")
_structured_logger.setLevel(logging.INFO)
_structured_logger.propagate = False  # Don't propagate to root logger

# File handler for trade logs
_file_handler: Optional[logging.FileHandler] = None
_logging_disabled = False
_allowed_event_types: set[str] | None = None
_allowed_decision_values: set[str] | None = None


def _is_structured_logging_enabled() -> bool:
    """Return whether structured trade logging should write to disk.

    Default behavior:
    - enabled in runtime
    - disabled under pytest to avoid polluting production logs
    """
    if os.getenv("PYTEST_CURRENT_TEST"):
        return os.getenv("ENABLE_TEST_STRUCTURED_LOGS", "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
    return True


def _init_file_handler(log_path: str | None = None) -> None:
    """Initialize file handler for trade logs."""
    if _file_handler is not None:
        return
    if not _is_structured_logging_enabled():
        globals()["_logging_disabled"] = True
        return

    resolved_path = log_path or os.getenv("TRADE_LOG_PATH", "logs/trades.jsonl")

    os.makedirs(os.path.dirname(resolved_path), exist_ok=True)

    file_handler = logging.FileHandler(resolved_path)
    file_handler.setLevel(logging.INFO)
    # No formatting - we output raw JSON
    file_handler.setFormatter(logging.Formatter("%(message)s"))
    _structured_logger.addHandler(file_handler)
    globals()["_file_handler"] = file_handler


def _parse_csv_upper(raw: str) -> set[str]:
    return {item.strip().upper() for item in raw.split(",") if item.strip()}


def _get_allowed_event_types() -> set[str] | None:
    """Get allowed structured event types from env.

    TRADE_LOG_EVENTS:
      - CSV list (default: SIGNAL,ENTRY,EXIT,DECISION,PNL,ERROR)
      - "ALL" or "*" to allow every event type.
    """
    cached = globals().get("_allowed_event_types")
    if cached is not None:
        return cached

    raw = os.getenv("TRADE_LOG_EVENTS", "SIGNAL,ENTRY,EXIT,DECISION,PNL,ERROR")
    allowed = _parse_csv_upper(raw)
    if not allowed or "ALL" in allowed or "*" in allowed:
        globals()["_allowed_event_types"] = set()
        return set()

    globals()["_allowed_event_types"] = allowed
    return allowed


def _get_allowed_decision_values() -> set[str] | None:
    """Get allowed DECISION values from env.

    TRADE_LOG_DECISIONS:
      - CSV list (default: BUY,SELL)
      - "ALL" or "*" to keep all decisions.
    """
    cached = globals().get("_allowed_decision_values")
    if cached is not None:
        return cached

    raw = os.getenv("TRADE_LOG_DECISIONS", "BUY,SELL")
    allowed = _parse_csv_upper(raw)
    if not allowed or "ALL" in allowed or "*" in allowed:
        globals()["_allowed_decision_values"] = set()
        return set()

    globals()["_allowed_decision_values"] = allowed
    return allowed


def _should_log_event(event_type: str, payload: dict[str, Any]) -> bool:
    allowed_event_types = _get_allowed_event_types()
    if allowed_event_types and event_type.upper() not in allowed_event_types:
        return False

    if event_type.upper() != "DECISION":
        return True

    allowed_decisions = _get_allowed_decision_values()
    if not allowed_decisions:
        return True

    decision = str(payload.get("decision", "")).upper().strip()
    if not decision:
        return False
    return decision in allowed_decisions


def _log_event(event_type: str, **kwargs: Any) -> None:
    """Log a structured event as single-line JSON."""
    _init_file_handler()
    if _logging_disabled:
        return
    if not _should_log_event(event_type, kwargs):
        return

    record = {
        "ts": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
        "event": event_type,
        **{k: v for k, v in kwargs.items() if v is not None},
    }

    # Output as single-line JSON
    _structured_logger.info(json.dumps(record, separators=(",", ":")))


class StructuredTradeLogger:
    """Structured logger for trade events.

    All methods log single-line JSON to logs/trades.jsonl

    Event types:
        - SIGNAL: Entry/exit signal generated
        - FILL: Order filled (entry or exit)
        - PNL: Realized P&L on position close
        - DECISION: Strategy decision with context
        - ERROR: Trade-related error
    """

    def signal(
        self,
        symbol: str,
        side: str,
        strategy: str,
        price: float,
        reason: str = "",
        regime: str = "",
        **extra: Any,
    ) -> None:
        """Log entry/exit signal generation.

        Args:
            symbol: Trading symbol (BTC, ETH, etc.)
            side: Signal side (BUY, SELL)
            strategy: Strategy name
            price: Current price when signal generated
            reason: Signal reason/trigger
            regime: Market regime (BULL_STRONG, SIDEWAYS, etc.)
        """
        _log_event(
            "SIGNAL",
            symbol=symbol,
            side=side.upper(),
            strategy=strategy,
            price=round(price, 2),
            reason=reason,
            regime=regime,
            **extra,
        )

    def fill(
        self,
        symbol: str,
        side: str,
        price: float,
        qty: float,
        strategy: str,
        order_id: str = "",
        market: str = "spot",
        mode: str = "paper",
        **extra: Any,
    ) -> None:
        """Log order fill (trade execution).

        Args:
            symbol: Trading symbol
            side: Trade side (BUY, SELL)
            price: Fill price
            qty: Fill quantity
            strategy: Strategy name
            order_id: Order ID
            market: Market type (spot)
            mode: Trading mode (paper, live)
        """
        _log_event(
            "FILL",
            symbol=symbol,
            side=side.upper(),
            price=round(price, 2),
            qty=round(qty, 8),
            notional=round(price * qty, 2),
            strategy=strategy,
            order_id=order_id,
            market=market,
            mode=mode,
            **extra,
        )

    def entry(
        self,
        symbol: str,
        price: float,
        qty: float,
        strategy: str,
        leverage: int = 1,
        mode: str = "paper",
        regime: str = "",
        **extra: Any,
    ) -> None:
        """Log position entry (convenience wrapper for fill).

        Args:
            symbol: Trading symbol
            price: Entry price
            qty: Position size
            strategy: Strategy name
            leverage: Leverage used
            mode: Trading mode
            regime: Market regime at entry
        """
        _log_event(
            "ENTRY",
            symbol=symbol,
            price=round(price, 2),
            qty=round(qty, 8),
            notional=round(price * qty, 2),
            strategy=strategy,
            leverage=leverage,
            mode=mode,
            regime=regime,
            **extra,
        )

    def exit(
        self,
        symbol: str,
        price: float,
        qty: float,
        entry_price: float,
        strategy: str,
        pnl: float,
        pnl_pct: float,
        hold_time_sec: int = 0,
        exit_reason: str = "",
        mode: str = "paper",
        **extra: Any,
    ) -> None:
        """Log position exit with P&L.

        Args:
            symbol: Trading symbol
            price: Exit price
            qty: Position size closed
            entry_price: Original entry price
            strategy: Strategy name
            pnl: Realized P&L in USDT
            pnl_pct: P&L percentage
            hold_time_sec: Position hold time in seconds
            exit_reason: Why position was closed
            mode: Trading mode
        """
        _log_event(
            "EXIT",
            symbol=symbol,
            price=round(price, 2),
            qty=round(qty, 8),
            entry_price=round(entry_price, 2),
            strategy=strategy,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 4),
            hold_sec=hold_time_sec,
            reason=exit_reason,
            mode=mode,
            **extra,
        )

    def pnl(
        self,
        symbol: str,
        pnl: float,
        pnl_pct: float,
        strategy: str,
        daily_pnl: float = 0,
        mode: str = "paper",
        **extra: Any,
    ) -> None:
        """Log realized P&L event.

        Args:
            symbol: Trading symbol
            pnl: Realized P&L
            pnl_pct: P&L percentage
            strategy: Strategy name
            daily_pnl: Running daily P&L total
            mode: Trading mode
        """
        _log_event(
            "PNL",
            symbol=symbol,
            pnl=round(pnl, 2),
            pnl_pct=round(pnl_pct, 4),
            strategy=strategy,
            daily_pnl=round(daily_pnl, 2),
            mode=mode,
            **extra,
        )

    def decision(
        self,
        symbol: str,
        strategy: str,
        decision: str,
        price: float,
        mfi: float = 0,
        adx: float = 0,
        regime: str = "",
        reason: str = "",
        **extra: Any,
    ) -> None:
        """Log strategy decision with market context.

        Args:
            symbol: Trading symbol
            strategy: Strategy name
            decision: Decision made (HOLD, BUY, SELL, SKIP)
            price: Current price
            mfi: MFI indicator value
            adx: ADX indicator value
            regime: Market regime
            reason: Decision reason
        """
        _log_event(
            "DECISION",
            symbol=symbol,
            strategy=strategy,
            decision=decision.upper(),
            price=round(price, 2),
            mfi=round(mfi, 2) if mfi else None,
            adx=round(adx, 2) if adx else None,
            regime=regime,
            reason=reason,
            **extra,
        )

    def error(
        self,
        symbol: str,
        error_type: str,
        message: str,
        strategy: str = "",
        **extra: Any,
    ) -> None:
        """Log trade-related error.

        Args:
            symbol: Trading symbol
            error_type: Error category
            message: Error message
            strategy: Strategy name (if applicable)
        """
        _log_event(
            "ERROR",
            symbol=symbol,
            error_type=error_type,
            message=message,
            strategy=strategy,
            **extra,
        )

    def balance(
        self,
        balance: float,
        mode: str = "paper",
        **extra: Any,
    ) -> None:
        """Log balance update.

        Args:
            balance: Current balance
            mode: Trading mode
        """
        _log_event(
            "BALANCE",
            balance=round(balance, 2),
            mode=mode,
            **extra,
        )


# Singleton instance
trade_logger = StructuredTradeLogger()
