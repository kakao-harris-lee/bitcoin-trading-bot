"""Hybrid exit for LLM entry strategies: protective exit + regime protection."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .llm_direction_exit import LLMDirectionExitParams, LLMDirectionExitStrategy
from .models import Position, Signal, TradingContext
from .regime_long_v2_exit import RegimeLongV2ExitParams, RegimeLongV2ExitStrategy
from .registry import exit_strategy


def _dataclass_field_names(cls) -> set[str]:
    return set(cls.__dataclass_fields__.keys())  # type: ignore[attr-defined]


@dataclass
class LLMHybridExitParams(LLMDirectionExitParams):
    """LLM hybrid exit params: protective exit plus regime protection."""

    always_apply_regime_protection: bool = True
    fallback_to_regime_when_core_none: bool = False
    annotate_reason: bool = True
    protective_params: dict[str, Any] | None = None
    regime_params: dict[str, Any] | None = None


@exit_strategy(params_class=LLMHybridExitParams)
class LLMHybridExitStrategy:
    def __init__(self, params: LLMHybridExitParams | None = None):
        self.params = params or LLMHybridExitParams()
        self._protective = self._build_protective_strategy(self.params)
        self._regime = self._build_regime_strategy(self.params)

    def check_exit(self, ctx: TradingContext, position: Position) -> Signal | None:
        regime_signal: Signal | None = None
        if self.params.always_apply_regime_protection:
            regime_signal = self._regime.check_exit(ctx, position)
            if regime_signal is not None:
                return self._annotate(regime_signal, "regime_protect")

        signal = self._protective.check_exit(ctx, position)
        if signal is not None:
            return self._annotate(signal, "protective")

        if self.params.fallback_to_regime_when_core_none:
            if regime_signal is None:
                regime_signal = self._regime.check_exit(ctx, position)
            if regime_signal is not None:
                return self._annotate(regime_signal, "regime_fallback")
        return None

    def on_position_opened(self, position: Position) -> None:
        self._protective.on_position_opened(position)
        self._regime.on_position_opened(position)

    def on_position_closed(self, symbol: str) -> None:
        self._protective.on_position_closed(symbol)
        self._regime.on_position_closed(symbol)

    def _build_protective_strategy(self, params: LLMHybridExitParams) -> LLMDirectionExitStrategy:
        field_names = _dataclass_field_names(LLMDirectionExitParams)
        protective_cfg = {name: getattr(params, name) for name in field_names if hasattr(params, name)}
        override = params.protective_params or {}
        for key, value in override.items():
            if key in field_names:
                protective_cfg[key] = value
        return LLMDirectionExitStrategy(LLMDirectionExitParams(**protective_cfg))

    def _build_regime_strategy(self, params: LLMHybridExitParams) -> RegimeLongV2ExitStrategy:
        field_names = _dataclass_field_names(RegimeLongV2ExitParams)
        regime_cfg: dict[str, Any] = {"market": params.market}
        override = params.regime_params or {}
        for key, value in override.items():
            if key in field_names:
                regime_cfg[key] = value
        return RegimeLongV2ExitStrategy(RegimeLongV2ExitParams(**regime_cfg))

    def _annotate(self, signal: Signal, route: str) -> Signal:
        if not self.params.annotate_reason:
            return signal
        return Signal(
            symbol=signal.symbol,
            side=signal.side,
            market=signal.market,
            quantity=signal.quantity,
            reason=f"LLMHybridExit[{route}] {signal.reason}",
            trigger_price=signal.trigger_price,
        )
