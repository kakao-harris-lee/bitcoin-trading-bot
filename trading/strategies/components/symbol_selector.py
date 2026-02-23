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
    startup_grace_seconds: float = 0.0
    volume_burst_ratio: float = 1.2
    compression_bbw_threshold: float = 0.12
    score_jump_threshold: float = 0.18
    entry_ready_score: float = 0.42
    max_signal_events: int = 6
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
            startup_grace_seconds=max(
                0.0,
                _safe_float(data.get("startup_grace_seconds", 0.0), 0.0),
            ),
            volume_burst_ratio=max(
                0.0,
                _safe_float(data.get("volume_burst_ratio", 1.2), 1.2),
            ),
            compression_bbw_threshold=max(
                0.0,
                _safe_float(data.get("compression_bbw_threshold", 0.12), 0.12),
            ),
            score_jump_threshold=max(
                0.0,
                _safe_float(data.get("score_jump_threshold", 0.18), 0.18),
            ),
            entry_ready_score=max(
                0.0,
                _safe_float(data.get("entry_ready_score", 0.42), 0.42),
            ),
            max_signal_events=max(1, int(data.get("max_signal_events", 6))),
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
    ignition_score: float = 0.0
    breakout_ratio: float = 0.0
    volume_burst: float = 0.0
    compression_score: float = 0.0
    ema_alignment: float = 0.0
    mfi_bias: float = 0.0
    eligible: bool = True
    selected: bool = False
    reason: str = "eligible"


@dataclass(frozen=True)
class SymbolSignalEvent:
    """State transition event for selector monitoring and alerting."""

    event_type: str
    symbol: str
    score: float
    reason: str = ""
    delta: float = 0.0


class DynamicSymbolSelector:
    """Long-only symbol selector with score-based top-N rotation."""

    _DEFAULT_WEIGHTS: Mapping[str, float] = {
        "regime": 0.45,
        "momentum": 0.30,
        "volume": 0.15,
        "adx": 0.10,
        "breakout": 0.0,
        "compression": 0.0,
        "ema_alignment": 0.0,
        "mfi": 0.0,
        "volume_burst": 0.0,
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
        self._started_at: float = time.time()
        self._last_refresh_at: float = 0.0
        self._last_ranking: list[SymbolScore] = []
        self._last_evaluations: list[SymbolScore] = []
        self._last_signal_events: list[SymbolSignalEvent] = []

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

    @property
    def signal_events(self) -> list[SymbolSignalEvent]:
        return list(self._last_signal_events)

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
        prev_selected = set(self._selected)
        prev_evals = {row.symbol: row for row in self._last_evaluations}
        scores = self._score_universe(universe, market_data, contexts)
        eligible_scores = [row for row in scores if row.eligible]
        selected = {s.symbol for s in eligible_scores[: self.config.top_n]}

        if not selected:
            selected = self._fallback_selection(universe)

        scores = [replace(row, selected=(row.symbol in selected)) for row in scores]
        changed = selected != self._selected
        self._last_signal_events = self._build_signal_events(
            prev_selected=prev_selected,
            prev_evals=prev_evals,
            scores=scores,
            selected=selected,
        )
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
                        ignition_score=0.0,
                        breakout_ratio=0.0,
                        volume_burst=0.0,
                        compression_score=0.0,
                        ema_alignment=0.0,
                        mfi_bias=0.0,
                        eligible=False,
                        reason="missing_data",
                    )
                )
                continue
            price_age_seconds = max(0.0, now - (float(md.timestamp) / 1000.0)) if md.timestamp > 0 else 0.0
            score, reason, details = self._score_symbol(
                md,
                ctx,
                weights,
                price_age_seconds,
                now,
            )
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
                    ignition_score=float(details.get("ignition", 0.0)),
                    breakout_ratio=float(details.get("breakout_ratio", 0.0)),
                    volume_burst=float(details.get("volume_burst", 0.0)),
                    compression_score=float(details.get("compression_component", 0.0)),
                    ema_alignment=float(details.get("ema_alignment_component", 0.0)),
                    mfi_bias=float(details.get("mfi_component", 0.0)),
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
        now: float,
    ) -> tuple[float | None, str, dict[str, float]]:
        details = self._compute_components(md, ctx)
        effective_max_price_age = self._effective_max_price_age_seconds()
        if (
            not self._is_startup_grace_active(now)
            and
            effective_max_price_age > 0
            and md.timestamp > 0
            and price_age_seconds > effective_max_price_age
        ):
            return None, "stale_price", details
        if self.config.skip_bear_regime and ctx.regime in BEAR_REGIMES:
            return None, "bear_regime", details
        if self.config.require_above_ema200 and md.ema_200 > 0 and md.close < md.ema_200:
            return None, "below_ema200", details
        if md.adx < self.config.min_adx:
            return None, "low_adx", details

        volume_ratio = (md.volume / md.avg_volume_20) if md.avg_volume_20 > 0 else 1.0
        if volume_ratio < self.config.min_volume_ratio:
            return None, "low_volume", details

        score = (
            details["regime_component"] * weights.get("regime", 0.0)
            + details["momentum_component"] * weights.get("momentum", 0.0)
            + details["volume_component"] * weights.get("volume", 0.0)
            + details["adx_component"] * weights.get("adx", 0.0)
            + details["breakout_component"] * weights.get("breakout", 0.0)
            + details["compression_component"] * weights.get("compression", 0.0)
            + details["ema_alignment_component"] * weights.get("ema_alignment", 0.0)
            + details["mfi_component"] * weights.get("mfi", 0.0)
            + details["volume_burst_component"] * weights.get("volume_burst", 0.0)
        )
        details["ignition"] = score

        if score < self.config.min_score:
            return None, "low_score", details
        return score, "eligible", details

    def _is_startup_grace_active(self, now: float | None = None) -> bool:
        if self.config.startup_grace_seconds <= 0:
            return False
        current = now if now is not None else time.time()
        return (current - self._started_at) < self.config.startup_grace_seconds

    def _effective_max_price_age_seconds(self) -> float:
        """Return stale threshold adjusted for selector refresh cadence.

        If refresh is slower than stale cutoff, symbols can be falsely marked stale
        even when feed health is acceptable. Keep a minimum multiple of refresh.
        """
        if self.config.max_price_age_seconds <= 0:
            return 0.0
        cadence_guard = self.config.refresh_seconds * 1.5 if self.config.refresh_seconds > 0 else 0.0
        return max(self.config.max_price_age_seconds, cadence_guard)

    def _compute_components(self, md: MarketData, ctx: MarketContext) -> dict[str, float]:
        volume_ratio = (md.volume / md.avg_volume_20) if md.avg_volume_20 > 0 else 1.0
        regime_component = self._REGIME_SCORES.get(ctx.regime, -0.5)
        momentum_component = _clamp(((md.close / md.ema_20) - 1.0) * 10.0, -1.0, 1.0) if md.ema_20 > 0 else 0.0
        volume_component = _clamp(volume_ratio - 1.0, -1.0, 1.0)
        adx_component = _clamp((md.adx - self.config.min_adx) / 25.0, -1.0, 1.0)

        breakout_ratio = ((md.close / md.prev_high_20) - 1.0) if md.prev_high_20 > 0 else 0.0
        breakout_component = _clamp(breakout_ratio * 12.0, -1.0, 1.0)

        bb_width = 0.0
        if md.bb_middle > 0 and md.bb_upper > md.bb_lower:
            bb_width = (md.bb_upper - md.bb_lower) / md.bb_middle
        compression_component = 0.0
        if self.config.compression_bbw_threshold > 0:
            compression_component = _clamp(
                (self.config.compression_bbw_threshold - bb_width) / self.config.compression_bbw_threshold,
                -1.0,
                1.0,
            )

        ema_alignment_component = 0.0
        if md.ema_5 > 0 and md.ema_20 > 0:
            ema_alignment_component = _clamp(((md.ema_5 / md.ema_20) - 1.0) * 40.0, -1.0, 1.0)
        elif md.ema_10 > 0 and md.ema_20 > 0:
            ema_alignment_component = _clamp(((md.ema_10 / md.ema_20) - 1.0) * 30.0, -1.0, 1.0)

        mfi_component = _clamp((md.mfi - 50.0) / 20.0, -1.0, 1.0)
        volume_burst_component = 0.0
        if self.config.volume_burst_ratio > 0:
            volume_burst_component = _clamp(
                (volume_ratio / self.config.volume_burst_ratio) - 1.0,
                -1.0,
                1.0,
            )

        return {
            "regime_component": regime_component,
            "momentum_component": momentum_component,
            "volume_component": volume_component,
            "adx_component": adx_component,
            "breakout_component": breakout_component,
            "compression_component": compression_component,
            "ema_alignment_component": ema_alignment_component,
            "mfi_component": mfi_component,
            "volume_burst_component": volume_burst_component,
            "breakout_ratio": breakout_ratio,
            "volume_burst": volume_ratio,
            "ignition": 0.0,
        }

    def _build_signal_events(
        self,
        *,
        prev_selected: set[str],
        prev_evals: Mapping[str, SymbolScore],
        scores: list[SymbolScore],
        selected: set[str],
    ) -> list[SymbolSignalEvent]:
        events: list[SymbolSignalEvent] = []
        if not prev_evals:
            prev_selected = set()
        ranked = [row for row in scores if row.eligible]
        by_symbol = {row.symbol: row for row in scores}

        for symbol in sorted(selected - prev_selected):
            row = by_symbol.get(symbol)
            if row is None:
                continue
            events.append(
                SymbolSignalEvent(
                    event_type="NEW_CANDIDATE",
                    symbol=symbol,
                    score=row.score,
                    reason=row.regime,
                )
            )

        for symbol in sorted(prev_selected - selected):
            row = by_symbol.get(symbol)
            reason = row.reason if row is not None else "not_ranked"
            score = row.score if row is not None else -999.0
            events.append(
                SymbolSignalEvent(
                    event_type="INVALIDATED",
                    symbol=symbol,
                    score=score,
                    reason=reason,
                )
            )

        for row in ranked[: max(self.config.top_n * 2, 8)]:
            prev = prev_evals.get(row.symbol)
            if prev is None or not prev.eligible:
                continue
            delta = row.score - prev.score
            if delta >= self.config.score_jump_threshold:
                events.append(
                    SymbolSignalEvent(
                        event_type="SCORE_JUMP",
                        symbol=row.symbol,
                        score=row.score,
                        reason=row.regime,
                        delta=delta,
                    )
                )

        for row in ranked[: self.config.top_n]:
            if row.symbol not in selected:
                continue
            if row.score >= self.config.entry_ready_score:
                events.append(
                    SymbolSignalEvent(
                        event_type="ENTRY_READY",
                        symbol=row.symbol,
                        score=row.score,
                        reason=row.regime,
                    )
                )

        if len(events) <= self.config.max_signal_events:
            return events
        events.sort(key=lambda item: (-item.score, item.event_type, item.symbol))
        return events[: self.config.max_signal_events]
