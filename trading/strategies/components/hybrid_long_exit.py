"""Hybrid long exit strategy (MLP + RegimeLongV2 routing)."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from .mlp_direction_exit import MLPDirectionExitParams, MLPDirectionExitStrategy
from .models import Position, Signal, TradingContext
from .regime_long_v2_exit import RegimeLongV2ExitParams, RegimeLongV2ExitStrategy
from .registry import exit_strategy

logger = logging.getLogger(__name__)


def _dataclass_field_names(cls) -> set[str]:
    return set(cls.__dataclass_fields__.keys())  # type: ignore[attr-defined]


@dataclass
class HybridLongExitParams(MLPDirectionExitParams):
    """Hybrid exit params: inherit MLP params + routing params."""

    mlp_route_regimes: list[str] = field(
        default_factory=lambda: ["BULL_STRONG", "BULL_MODERATE", "SIDEWAYS_UP"]
    )
    always_apply_regime_protection: bool = True
    fallback_to_regime_when_mlp_none: bool = False
    fallback_to_mlp_when_regime_none: bool = False
    annotate_reason: bool = True

    mlp_params: dict[str, Any] | None = None
    regime_params: dict[str, Any] | None = None


@exit_strategy(params_class=HybridLongExitParams)
class HybridLongExitStrategy:
    """Route exit between MLP and RegimeLongV2 by current regime."""

    def __init__(self, params: HybridLongExitParams | None = None):
        self.params = params or HybridLongExitParams()
        self._mlp_route_regimes = set(self.params.mlp_route_regimes or [])
        self._mlp = self._build_mlp_strategy(self.params)
        self._regime = self._build_regime_strategy(self.params)

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        primary = "mlp" if ctx.regime.regime in self._mlp_route_regimes else "regime"
        regime_checked_signal: Signal | None = None

        if primary == "mlp":
            if self.params.always_apply_regime_protection:
                regime_checked_signal = self._regime.check_exit(ctx, position)
                if regime_checked_signal is not None:
                    return self._annotate(regime_checked_signal, "regime_protect")

            signal = self._mlp.check_exit(ctx, position)
            if signal is not None:
                return self._annotate(signal, "mlp")

            if self.params.fallback_to_regime_when_mlp_none:
                if (
                    regime_checked_signal is None
                    and not self.params.always_apply_regime_protection
                ):
                    regime_checked_signal = self._regime.check_exit(ctx, position)
                if regime_checked_signal is not None:
                    return self._annotate(regime_checked_signal, "regime_fallback")
            return None

        signal = self._regime.check_exit(ctx, position)
        if signal is not None:
            return self._annotate(signal, "regime")
        if self.params.fallback_to_mlp_when_regime_none:
            signal = self._mlp.check_exit(ctx, position)
            if signal is not None:
                return self._annotate(signal, "mlp_fallback")
        return None

    def on_position_opened(self, position: Position) -> None:
        self._mlp.on_position_opened(position)
        self._regime.on_position_opened(position)

    def on_position_closed(self, symbol: str) -> None:
        self._mlp.on_position_closed(symbol)
        self._regime.on_position_closed(symbol)

    def _build_mlp_strategy(
        self, params: HybridLongExitParams
    ) -> MLPDirectionExitStrategy:
        field_names = _dataclass_field_names(MLPDirectionExitParams)
        mlp_cfg = {
            name: getattr(params, name) for name in field_names if hasattr(params, name)
        }
        override = params.mlp_params or {}
        for key, value in override.items():
            if key in field_names:
                mlp_cfg[key] = value
        return MLPDirectionExitStrategy(MLPDirectionExitParams(**mlp_cfg))

    def _build_regime_strategy(
        self, params: HybridLongExitParams
    ) -> RegimeLongV2ExitStrategy:
        field_names = _dataclass_field_names(RegimeLongV2ExitParams)
        regime_cfg: dict[str, Any] = {
            "market": params.market,
        }
        override = params.regime_params or {}
        for key, value in override.items():
            if key in field_names:
                regime_cfg[key] = value
        return RegimeLongV2ExitStrategy(RegimeLongV2ExitParams(**regime_cfg))

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
