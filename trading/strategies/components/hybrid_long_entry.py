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

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        primary = "mlp" if ctx.regime.regime in self._mlp_route_regimes else "regime"

        if primary == "mlp":
            signal = self._mlp.check_entry(ctx)
            if signal is not None:
                return self._annotate(signal, "mlp")
            if self.params.fallback_to_regime_when_mlp_none:
                signal = self._regime.check_entry(ctx)
                if signal is not None:
                    return self._annotate(signal, "regime_fallback")
            return None

        signal = self._regime.check_entry(ctx)
        if signal is not None:
            return self._annotate(signal, "regime")
        if self.params.fallback_to_mlp_when_regime_none:
            signal = self._mlp.check_entry(ctx)
            if signal is not None:
                return self._annotate(signal, "mlp_fallback")
        return None

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
