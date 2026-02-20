"""Dynamic multi-coin selector for long-only entry gating.

Selector runs a lightweight ranking across a configured symbol universe and
keeps only top-N symbols eligible for new entries.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from typing import Mapping

from .models import BEAR_REGIMES, MarketContext, MarketData


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def _safe_float(value, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


@dataclass(frozen=True)
class SymbolSelectorConfig:
    """Configuration for entry-time symbol rotation."""

    enabled: bool = False
    top_n: int = 2
    refresh_seconds: float = 900.0
    min_score: float = 0.0
    min_adx: float = 15.0
    min_volume_ratio: float = 0.8
    require_above_ema200: bool = True
    skip_bear_regime: bool = True
    keep_previous_on_empty: bool = True
    max_price_age_seconds: float = 0.0
    score_weights: Mapping[str, float] | None = None

    @classmethod
    def from_dict(cls, raw: dict | None) -> "SymbolSelectorConfig":
        data = raw or {}
        return cls(
            enabled=bool(data.get("enabled", False)),
            top_n=max(1, int(data.get("top_n", 2))),
            refresh_seconds=max(5.0, _safe_float(data.get("refresh_seconds", 900.0), 900.0)),
            min_score=_safe_float(data.get("min_score", 0.0), 0.0),
            min_adx=_safe_float(data.get("min_adx", 15.0), 15.0),
            min_volume_ratio=_safe_float(data.get("min_volume_ratio", 0.8), 0.8),
            require_above_ema200=bool(data.get("require_above_ema200", True)),
            skip_bear_regime=bool(data.get("skip_bear_regime", True)),
            keep_previous_on_empty=bool(data.get("keep_previous_on_empty", True)),
            max_price_age_seconds=max(
                0.0,
                _safe_float(data.get("max_price_age_seconds", 0.0), 0.0),
            ),
            score_weights=data.get("score_weights"),
        )


@dataclass(frozen=True)
class SymbolScore:
    """Scored candidate snapshot for debugging/logging."""

    symbol: str
    score: float
    regime: str
    adx: float
    volume_ratio: float
    momentum: float
    price_age_seconds: float = 0.0
    eligible: bool = True
    selected: bool = False
    reason: str = "eligible"


class DynamicSymbolSelector:
    """Long-only symbol selector with score-based top-N rotation."""

    _DEFAULT_WEIGHTS: Mapping[str, float] = {
        "regime": 0.45,
        "momentum": 0.30,
        "volume": 0.15,
        "adx": 0.10,
    }

    _REGIME_SCORES: Mapping[str, float] = {
        "BULL_STRONG": 1.00,
        "BULL_MODERATE": 0.70,
        "SIDEWAYS_UP": 0.25,
        "SIDEWAYS_FLAT": -0.15,
        "SIDEWAYS_DOWN": -0.35,
        "BEAR_MODERATE": -0.80,
        "BEAR_STRONG": -1.00,
    }

    def __init__(self, config: SymbolSelectorConfig, fallback_symbols: list[str]):
        self.config = config
        self._fallback_symbols = list(dict.fromkeys(fallback_symbols))
        self._selected: set[str] = set(self._fallback_symbols)
        self._last_refresh_at: float = 0.0
        self._last_ranking: list[SymbolScore] = []
        self._last_evaluations: list[SymbolScore] = []

    @property
    def enabled(self) -> bool:
        return self.config.enabled

    @property
    def selected_symbols(self) -> set[str]:
        return set(self._selected)

    @property
    def ranking(self) -> list[SymbolScore]:
        return list(self._last_ranking)

    @property
    def evaluations(self) -> list[SymbolScore]:
        return list(self._last_evaluations)

    def is_symbol_allowed(self, symbol: str) -> bool:
        if not self.config.enabled:
            return True
        return symbol in self._selected

    def should_refresh(self, now: float) -> bool:
        if not self.config.enabled:
            return False
        if self._last_refresh_at <= 0:
            return True
        return (now - self._last_refresh_at) >= self.config.refresh_seconds

    def refresh(
        self,
        *,
        now: float,
        symbols: list[str],
        market_data: Mapping[str, MarketData],
        contexts: Mapping[str, MarketContext],
    ) -> bool:
        """Recompute eligible symbols. Returns True when selected set changed."""
        if not self.config.enabled:
            selected = set(symbols) if symbols else set(self._fallback_symbols)
            changed = selected != self._selected
            self._selected = selected
            self._last_refresh_at = now
            return changed

        if not self.should_refresh(now):
            return False

        universe = list(dict.fromkeys(symbols or self._fallback_symbols))
        scores = self._score_universe(universe, market_data, contexts)
        eligible_scores = [row for row in scores if row.eligible]
        selected = {s.symbol for s in eligible_scores[: self.config.top_n]}

        if not selected:
            selected = self._fallback_selection(universe)

        scores = [replace(row, selected=(row.symbol in selected)) for row in scores]
        changed = selected != self._selected
        self._selected = selected
        self._last_evaluations = scores
        self._last_ranking = [row for row in scores if row.eligible]
        self._last_refresh_at = now
        return changed

    def _fallback_selection(self, universe: list[str]) -> set[str]:
        if self.config.keep_previous_on_empty and self._selected:
            return set(self._selected)
        if universe:
            return {universe[0]}
        return set(self._fallback_symbols[:1])

    def _score_universe(
        self,
        universe: list[str],
        market_data: Mapping[str, MarketData],
        contexts: Mapping[str, MarketContext],
    ) -> list[SymbolScore]:
        now = time.time()
        weights = dict(self._DEFAULT_WEIGHTS)
        if self.config.score_weights:
            for key, value in self.config.score_weights.items():
                weights[str(key)] = _safe_float(value, weights.get(str(key), 0.0))

        rows: list[SymbolScore] = []
        for symbol in universe:
            md = market_data.get(symbol)
            ctx = contexts.get(symbol)
            if md is None or ctx is None:
                rows.append(
                    SymbolScore(
                        symbol=symbol,
                        score=-999.0,
                        regime=ctx.regime if ctx is not None else "UNKNOWN",
                        adx=float(md.adx) if md is not None else 0.0,
                        volume_ratio=(
                            (md.volume / md.avg_volume_20)
                            if md is not None and md.avg_volume_20 > 0
                            else 1.0
                        ),
                        momentum=((md.close / md.ema_20) - 1.0) if md is not None and md.ema_20 > 0 else 0.0,
                        price_age_seconds=0.0,
                        eligible=False,
                        reason="missing_data",
                    )
                )
                continue
            price_age_seconds = max(0.0, now - (float(md.timestamp) / 1000.0)) if md.timestamp > 0 else 0.0
            score, reason = self._score_symbol(md, ctx, weights, price_age_seconds)
            eligible = score is not None
            rows.append(
                SymbolScore(
                    symbol=symbol,
                    score=float(score if score is not None else -999.0),
                    regime=ctx.regime,
                    adx=float(md.adx),
                    volume_ratio=(md.volume / md.avg_volume_20) if md.avg_volume_20 > 0 else 1.0,
                    momentum=((md.close / md.ema_20) - 1.0) if md.ema_20 > 0 else 0.0,
                    price_age_seconds=price_age_seconds,
                    eligible=eligible,
                    reason=reason,
                )
            )

        rows.sort(
            key=lambda item: (
                0 if item.eligible else 1,
                -item.score if item.eligible else 0.0,
                item.symbol,
            )
        )
        return rows

    def _score_symbol(
        self,
        md: MarketData,
        ctx: MarketContext,
        weights: Mapping[str, float],
        price_age_seconds: float,
    ) -> tuple[float | None, str]:
        if (
            self.config.max_price_age_seconds > 0
            and md.timestamp > 0
            and price_age_seconds > self.config.max_price_age_seconds
        ):
            return None, "stale_price"
        if self.config.skip_bear_regime and ctx.regime in BEAR_REGIMES:
            return None, "bear_regime"
        if self.config.require_above_ema200 and md.ema_200 > 0 and md.close < md.ema_200:
            return None, "below_ema200"
        if md.adx < self.config.min_adx:
            return None, "low_adx"

        volume_ratio = (md.volume / md.avg_volume_20) if md.avg_volume_20 > 0 else 1.0
        if volume_ratio < self.config.min_volume_ratio:
            return None, "low_volume"

        regime_component = self._REGIME_SCORES.get(ctx.regime, -0.5)
        momentum_component = _clamp(((md.close / md.ema_20) - 1.0) * 10.0, -1.0, 1.0) if md.ema_20 > 0 else 0.0
        volume_component = _clamp(volume_ratio - 1.0, -1.0, 1.0)
        adx_component = _clamp((md.adx - self.config.min_adx) / 25.0, -1.0, 1.0)

        score = (
            regime_component * weights.get("regime", 0.0)
            + momentum_component * weights.get("momentum", 0.0)
            + volume_component * weights.get("volume", 0.0)
            + adx_component * weights.get("adx", 0.0)
        )

        if score < self.config.min_score:
            return None, "low_score"
        return score, "eligible"
