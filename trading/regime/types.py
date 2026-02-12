"""Typed schema definitions for multimodal regime features."""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


@dataclass(frozen=True)
class RegimeFeatureRow:
    """Canonical feature row for regime model training/inference."""

    timestamp: str
    symbol: str
    close: float

    volume: float = 0.0
    mfi: float = 0.0
    adx: float = 0.0
    atr: float = 0.0

    onchain_activity_score: float = 0.0
    sentiment_score: float = 0.0
    open_interest_change: float = 0.0
    funding_rate: float = 0.0
    policy_event_score: float = 0.0

    derivatives_stress_score: float = 0.0
    external_regime_score: float = 0.0
    volatility_jump: int = 0
    data_quality_score: float = 0.0

    trend_1h: str = "NEUTRAL"
    trend_4h: str = "NEUTRAL"
    trend_1d: str = "NEUTRAL"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "RegimeFeatureRow":
        return cls(
            timestamp=str(payload.get("timestamp", "")),
            symbol=str(payload.get("symbol", "")),
            close=float(payload.get("close", 0.0)),
            volume=float(payload.get("volume", 0.0)),
            mfi=float(payload.get("mfi", 0.0)),
            adx=float(payload.get("adx", 0.0)),
            atr=float(payload.get("atr", 0.0)),
            onchain_activity_score=float(payload.get("onchain_activity_score", 0.0)),
            sentiment_score=float(payload.get("sentiment_score", 0.0)),
            open_interest_change=float(payload.get("open_interest_change", 0.0)),
            funding_rate=float(payload.get("funding_rate", 0.0)),
            policy_event_score=float(payload.get("policy_event_score", 0.0)),
            derivatives_stress_score=float(payload.get("derivatives_stress_score", 0.0)),
            external_regime_score=float(payload.get("external_regime_score", 0.0)),
            volatility_jump=int(payload.get("volatility_jump", 0)),
            data_quality_score=float(payload.get("data_quality_score", 0.0)),
            trend_1h=str(payload.get("trend_1h", "NEUTRAL")),
            trend_4h=str(payload.get("trend_4h", "NEUTRAL")),
            trend_1d=str(payload.get("trend_1d", "NEUTRAL")),
        )
