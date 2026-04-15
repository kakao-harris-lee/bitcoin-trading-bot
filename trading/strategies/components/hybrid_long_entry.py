"""Hybrid long entry strategy (MLP + RegimeLongV2 routing)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .mlp_direction_entry import MLPDirectionEntryParams, MLPDirectionEntryStrategy
from .models import Signal, TradingContext
from .regime_long_v2_entry import RegimeLongV2EntryParams, RegimeLongV2EntryStrategy
from .registry import entry_strategy

logger = logging.getLogger(__name__)


def _dataclass_field_names(cls) -> set[str]:
    return set(cls.__dataclass_fields__.keys())  # type: ignore[attr-defined]


@dataclass
class HybridLongEntryParams(MLPDirectionEntryParams):
    """Hybrid entry params: inherit MLP params + routing params."""

    mlp_route_regimes: list[str] = field(
        default_factory=lambda: ["BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"]
    )
    fallback_to_regime_when_mlp_none: bool = True
    fallback_allowed_regimes: list[str] | None = None
    fallback_on_mlp_unavailable: bool = True
    fallback_on_mlp_non_buy: bool = False
    fallback_on_mlp_low_confidence: bool = False
    fallback_on_mlp_filter_block: bool = False
    fallback_blocked_symbols: list[str] | None = None
    fallback_quality_allowlist_symbols: list[str] | None = None
    fallback_to_mlp_when_regime_none: bool = False
    annotate_reason: bool = True

    mlp_params: dict[str, Any] | None = None
    regime_params: dict[str, Any] | None = None


@entry_strategy(params_class=HybridLongEntryParams)
class HybridLongEntryStrategy:
    """Route entry between MLP and RegimeLongV2 by current regime."""

    def __init__(self, params: HybridLongEntryParams | None = None):
        self.params = params or HybridLongEntryParams()
        self._mlp_route_regimes = set(self.params.mlp_route_regimes or [])
        self._mlp = self._build_mlp_strategy(self.params)
        self._regime = self._build_regime_strategy(self.params)
        self._last_rejection_reason: dict[str, str] = {}

    def get_last_rejection_reason(self, symbol: str) -> str | None:
        return self._last_rejection_reason.get(symbol)

    def _set_rejection_reason(self, symbol: str, reason: str) -> None:
        self._last_rejection_reason[symbol] = reason

    def _clear_rejection_reason(self, symbol: str) -> None:
        self._last_rejection_reason.pop(symbol, None)

    @staticmethod
    def _child_rejection_reason(child: object, symbol: str) -> str:
        get_reason = getattr(child, "get_last_rejection_reason", None)
        if callable(get_reason):
            try:
                reason = get_reason(symbol)
            except TypeError:
                reason = get_reason()
            if isinstance(reason, str) and reason.strip():
                return reason.strip()
        fallback = getattr(child, "last_rejection_reason", None)
        if isinstance(fallback, str) and fallback.strip():
            return fallback.strip()
        return "No entry signal"

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        symbol = ctx.market.symbol
        regime_name = ctx.regime.regime
        primary = "mlp" if ctx.regime.regime in self._mlp_route_regimes else "regime"

        if primary == "mlp":
            signal = self._mlp.check_entry(ctx)
            if signal is not None:
                self._clear_rejection_reason(symbol)
                return self._annotate(signal, "mlp")
            primary_reason = self._child_rejection_reason(self._mlp, symbol)
            if self._should_try_regime_fallback(symbol, regime_name, primary_reason):
                signal = self._regime.check_entry(ctx)
                if signal is not None:
                    self._clear_rejection_reason(symbol)
                    return self._annotate(signal, "regime_fallback")
                fallback_reason = self._child_rejection_reason(self._regime, symbol)
                self._set_rejection_reason(
                    symbol,
                    f"HybridLong[mlp] blocked: {primary_reason}; "
                    f"fallback[regime] blocked: {fallback_reason}",
                )
                return None
            if self.params.fallback_to_regime_when_mlp_none:
                self._set_rejection_reason(
                    symbol,
                    f"HybridLong[mlp] blocked: {primary_reason}; fallback[regime] skipped by policy",
                )
                return None
            self._set_rejection_reason(symbol, f"HybridLong[mlp] blocked: {primary_reason}")
            return None

        signal = self._regime.check_entry(ctx)
        if signal is not None:
            self._clear_rejection_reason(symbol)
            return self._annotate(signal, "regime")
        primary_reason = self._child_rejection_reason(self._regime, symbol)
        if self.params.fallback_to_mlp_when_regime_none:
            signal = self._mlp.check_entry(ctx)
            if signal is not None:
                self._clear_rejection_reason(symbol)
                return self._annotate(signal, "mlp_fallback")
            fallback_reason = self._child_rejection_reason(self._mlp, symbol)
            self._set_rejection_reason(
                symbol,
                f"HybridLong[regime] blocked: {primary_reason}; "
                f"fallback[mlp] blocked: {fallback_reason}",
            )
            return None
        self._set_rejection_reason(symbol, f"HybridLong[regime] blocked: {primary_reason}")
        return None

    def _should_try_regime_fallback(
        self,
        symbol: str,
        regime_name: str,
        primary_reason: str,
    ) -> bool:
        if not self.params.fallback_to_regime_when_mlp_none:
            return False
        normalized_symbol = str(symbol or "").upper()
        blocked_symbols = {str(item).upper() for item in (self.params.fallback_blocked_symbols or []) if str(item)}
        if normalized_symbol in blocked_symbols:
            return False
        allowed_regimes = set(self.params.fallback_allowed_regimes or [])
        if allowed_regimes and regime_name not in allowed_regimes:
            return False
        category = self._categorize_mlp_rejection(primary_reason)
        quality_allowlist = {
            str(item).upper() for item in (self.params.fallback_quality_allowlist_symbols or []) if str(item)
        }
        if (
            category in {"non_buy", "low_confidence", "filter_block"}
            and quality_allowlist
            and normalized_symbol not in quality_allowlist
        ):
            return False
        if category == "unavailable":
            return self.params.fallback_on_mlp_unavailable
        if category == "non_buy":
            return self.params.fallback_on_mlp_non_buy
        if category == "low_confidence":
            return self.params.fallback_on_mlp_low_confidence
        return self.params.fallback_on_mlp_filter_block

    @staticmethod
    def _categorize_mlp_rejection(reason: str) -> str:
        text = (reason or "").lower()
        if any(
            token in text
            for token in (
                "model unavailable",
                "prediction unavailable",
                "feature extraction failed",
                "warmup",
                "unavailable",
            )
        ):
            return "unavailable"
        if "low mlp confidence" in text:
            return "low_confidence"
        if "predicted hold" in text or "predicted sell" in text or "(not buy)" in text:
            return "non_buy"
        return "filter_block"

    def _build_mlp_strategy(
        self, params: HybridLongEntryParams
    ) -> MLPDirectionEntryStrategy:
        field_names = _dataclass_field_names(MLPDirectionEntryParams)
        mlp_cfg = {
            name: getattr(params, name) for name in field_names if hasattr(params, name)
        }
        override = params.mlp_params or {}
        for key, value in override.items():
            if key in field_names:
                mlp_cfg[key] = value
        return MLPDirectionEntryStrategy(MLPDirectionEntryParams(**mlp_cfg))

    def _build_regime_strategy(
        self, params: HybridLongEntryParams
    ) -> RegimeLongV2EntryStrategy:
        field_names = _dataclass_field_names(RegimeLongV2EntryParams)
        regime_cfg: dict[str, Any] = {
            "position_size": params.position_size,
            "market": params.market,
        }
        override = params.regime_params or {}
        for key, value in override.items():
            if key in field_names:
                regime_cfg[key] = value
        return RegimeLongV2EntryStrategy(RegimeLongV2EntryParams(**regime_cfg))

    def _annotate(self, signal: Signal, route: str) -> Signal:
        if not self.params.annotate_reason:
            return signal
        reason = f"HybridLong[{route}] {signal.reason}"
        return Signal(
            symbol=signal.symbol,
            side=signal.side,
            market=signal.market,
            quantity=signal.quantity,
            reason=reason,
            trigger_price=signal.trigger_price,
        )
