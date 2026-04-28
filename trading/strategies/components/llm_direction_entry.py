"""LLM-backed long entry strategy for BTC/ETH spot trading."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from typing import Any, Literal, Protocol

import aiohttp
import pandas as pd
import requests

from .models import BEAR_REGIMES, Signal, TradingContext, MarketData, MarketContext
from .registry import entry_strategy

logger = logging.getLogger(__name__)

_ALLOWED_ACTIONS = {"BUY", "HOLD"}


@dataclass(frozen=True)
class LLMTradeDecision:
    """Structured LLM decision payload used by the trading engine."""

    action: Literal["BUY", "HOLD"]
    confidence: float
    reason: str
    risk_flags: tuple[str, ...] = ()
    prompt_version: str = "v1"
    provider: str = "ollama"
    model: str = ""
    raw_response: str | None = None


@dataclass(frozen=True)
class LLMClientConfig:
    """Transport configuration for an LLM decision provider."""

    provider: Literal["ollama", "openai"] = "ollama"
    model: str = "llama3.1:8b"
    api_base_url: str = "http://127.0.0.1:11434"
    api_key_env: str = "OPENAI_API_KEY"
    timeout_seconds: float = 15.0
    max_retries: int = 1
    temperature: float = 0.0
    max_output_tokens: int = 256


class LLMDecisionClient(Protocol):
    """Provider-agnostic interface for structured trade decisions."""

    async def generate_decision_async(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
    ) -> LLMTradeDecision:
        ...

    def generate_decision(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
    ) -> LLMTradeDecision:
        ...


class _BaseHTTPDecisionClient:
    def __init__(self, config: LLMClientConfig):
        self.config = config

    @staticmethod
    def _normalize_decision(
        payload: Any,
        *,
        prompt_version: str,
        provider: str,
        model: str,
        raw_response: str | None,
    ) -> LLMTradeDecision:
        if not isinstance(payload, dict):
            raise ValueError("LLM response is not a JSON object")

        action = str(payload.get("action", "HOLD")).strip().upper()
        if action not in _ALLOWED_ACTIONS:
            action = "HOLD"

        try:
            confidence = float(payload.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(confidence, 1.0))

        reason = str(payload.get("reason", "")).strip() or "No reason provided"
        risk_flags_raw = payload.get("risk_flags", [])
        if not isinstance(risk_flags_raw, list):
            risk_flags_raw = []
        risk_flags = tuple(str(flag).strip() for flag in risk_flags_raw if str(flag).strip())

        return LLMTradeDecision(
            action=action,
            confidence=confidence,
            reason=reason,
            risk_flags=risk_flags,
            prompt_version=prompt_version,
            provider=provider,
            model=model,
            raw_response=raw_response,
        )


class OllamaDecisionClient(_BaseHTTPDecisionClient):
    """Ollama JSON decision client using direct HTTP requests."""

    def _build_payload(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        prompt = (
            f"SYSTEM:\n{system_prompt.strip()}\n\n"
            f"USER:\n{user_prompt.strip()}\n\n"
            "Return JSON only."
        )
        return {
            "model": self.config.model,
            "prompt": prompt,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": self.config.temperature,
                "num_predict": self.config.max_output_tokens,
            },
        }

    def _parse_response(self, body: dict[str, Any], prompt_version: str) -> LLMTradeDecision:
        raw_response = str(body.get("response", "")).strip()
        if not raw_response:
            raise ValueError("Ollama response body missing 'response'")
        payload = json.loads(raw_response)
        return self._normalize_decision(
            payload,
            prompt_version=prompt_version,
            provider="ollama",
            model=self.config.model,
            raw_response=raw_response,
        )

    async def generate_decision_async(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
    ) -> LLMTradeDecision:
        url = self.config.api_base_url.rstrip("/") + "/api/generate"
        payload = self._build_payload(system_prompt, user_prompt)
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        attempts = max(1, int(self.config.max_retries) + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                async with aiohttp.ClientSession(timeout=timeout) as session:
                    async with session.post(url, json=payload) as response:
                        response.raise_for_status()
                        body = await response.json()
                        return self._parse_response(body, prompt_version)
            except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
        raise RuntimeError(f"Ollama decision request failed: {last_error}") from last_error

    def generate_decision(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
    ) -> LLMTradeDecision:
        url = self.config.api_base_url.rstrip("/") + "/api/generate"
        payload = self._build_payload(system_prompt, user_prompt)
        attempts = max(1, int(self.config.max_retries) + 1)
        last_error: Exception | None = None
        for attempt in range(attempts):
            try:
                response = requests.post(url, json=payload, timeout=self.config.timeout_seconds)
                response.raise_for_status()
                return self._parse_response(response.json(), prompt_version)
            except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
        raise RuntimeError(f"Ollama decision request failed: {last_error}") from last_error


class OpenAIDecisionClient(_BaseHTTPDecisionClient):
    """OpenAI-compatible JSON decision client using raw HTTP requests."""

    def _headers(self) -> dict[str, str]:
        api_key = os.getenv(self.config.api_key_env, "").strip()
        if not api_key:
            raise RuntimeError(f"Missing API key env: {self.config.api_key_env}")
        return {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }

    def _build_payload(self, system_prompt: str, user_prompt: str) -> dict[str, Any]:
        return {
            "model": self.config.model,
            "temperature": self.config.temperature,
            "max_tokens": self.config.max_output_tokens,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }

    def _parse_response(self, body: dict[str, Any], prompt_version: str) -> LLMTradeDecision:
        choices = body.get("choices") or []
        if not choices:
            raise ValueError("OpenAI response missing choices")
        message = choices[0].get("message") or {}
        raw_response = str(message.get("content", "")).strip()
        if not raw_response:
            raise ValueError("OpenAI response missing message content")
        payload = json.loads(raw_response)
        return self._normalize_decision(
            payload,
            prompt_version=prompt_version,
            provider="openai",
            model=self.config.model,
            raw_response=raw_response,
        )

    async def generate_decision_async(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
    ) -> LLMTradeDecision:
        url = self.config.api_base_url.rstrip("/") + "/v1/chat/completions"
        timeout = aiohttp.ClientTimeout(total=self.config.timeout_seconds)
        payload = self._build_payload(system_prompt, user_prompt)
        attempts = max(1, int(self.config.max_retries) + 1)
        last_error: Exception | None = None
        headers = self._headers()
        for attempt in range(attempts):
            try:
                async with aiohttp.ClientSession(timeout=timeout, headers=headers) as session:
                    async with session.post(url, json=payload) as response:
                        response.raise_for_status()
                        body = await response.json()
                        return self._parse_response(body, prompt_version)
            except (aiohttp.ClientError, asyncio.TimeoutError, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
        raise RuntimeError(f"OpenAI decision request failed: {last_error}") from last_error

    def generate_decision(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        prompt_version: str,
    ) -> LLMTradeDecision:
        url = self.config.api_base_url.rstrip("/") + "/v1/chat/completions"
        payload = self._build_payload(system_prompt, user_prompt)
        attempts = max(1, int(self.config.max_retries) + 1)
        last_error: Exception | None = None
        headers = self._headers()
        for attempt in range(attempts):
            try:
                response = requests.post(
                    url,
                    json=payload,
                    headers=headers,
                    timeout=self.config.timeout_seconds,
                )
                response.raise_for_status()
                return self._parse_response(response.json(), prompt_version)
            except (requests.RequestException, json.JSONDecodeError, ValueError) as exc:
                last_error = exc
                if attempt + 1 >= attempts:
                    break
        raise RuntimeError(f"OpenAI decision request failed: {last_error}") from last_error


@dataclass
class LLMDecisionEntryParams:
    """Parameters for LLM-driven long entry."""

    position_size: float = 0.01
    market: Literal["spot"] = "spot"

    provider: Literal["ollama", "openai"] = "ollama"
    model: str = "llama3.1:8b"
    api_base_url: str = "http://127.0.0.1:11434"
    api_key_env: str = "OPENAI_API_KEY"
    request_timeout_seconds: float = 15.0
    max_retries: int = 1
    temperature: float = 0.0
    max_output_tokens: int = 256
    prompt_version: str = "v1"
    context_window_bars: int = 48

    confidence_threshold: float = 0.60
    allowed_regimes: list[str] | None = None
    block_bear_regime: bool = True
    adx_min: float = 0.0
    use_ema200_filter: bool = False
    require_close_above_ema120: bool = False
    min_volume_ratio: float = 0.0


def create_llm_decision_client(config: LLMClientConfig) -> LLMDecisionClient:
    provider = str(config.provider or "ollama").strip().lower()
    if provider == "ollama":
        return OllamaDecisionClient(config)
    if provider == "openai":
        return OpenAIDecisionClient(config)
    raise ValueError(f"Unsupported LLM provider: {config.provider}")


@entry_strategy(params_class=LLMDecisionEntryParams)
class LLMDecisionEntryStrategy:
    """Entry strategy that consumes structured BUY/HOLD decisions from an LLM."""

    def __init__(
        self,
        params: LLMDecisionEntryParams | None = None,
        client: LLMDecisionClient | None = None,
    ):
        self.params = params or LLMDecisionEntryParams()
        self._client = client
        self._decision_cache: dict[str, dict[str, Any]] = {}
        self._last_rejection_reason: dict[str, str] = {}

    def get_last_rejection_reason(self, symbol: str) -> str | None:
        return self._last_rejection_reason.get(symbol)

    def _set_rejection_reason(self, symbol: str, reason: str) -> None:
        self._last_rejection_reason[symbol] = reason

    def _clear_rejection_reason(self, symbol: str) -> None:
        self._last_rejection_reason.pop(symbol, None)

    def _get_client(self) -> LLMDecisionClient:
        if self._client is None:
            self._client = create_llm_decision_client(
                LLMClientConfig(
                    provider=self.params.provider,
                    model=self.params.model,
                    api_base_url=self.params.api_base_url,
                    api_key_env=self.params.api_key_env,
                    timeout_seconds=self.params.request_timeout_seconds,
                    max_retries=self.params.max_retries,
                    temperature=self.params.temperature,
                    max_output_tokens=self.params.max_output_tokens,
                )
            )
        return self._client

    async def prepare_entry_decision_async(
        self,
        ctx: TradingContext,
        history_df: pd.DataFrame | None,
    ) -> None:
        symbol = ctx.market.symbol
        market_data = ctx.market
        context = ctx.regime
        positions = ctx.positions
        candle_ts = int(getattr(market_data, "timestamp", 0) or 0)
        cached = self._decision_cache.get(symbol)
        if cached and int(cached.get("candle_timestamp", -1)) == candle_ts:
            return

        gate_reason = self._preflight_policy_block(symbol, market_data, context)
        if gate_reason is not None:
            self._cache_decision(
                symbol,
                candle_ts,
                LLMTradeDecision(
                    action="HOLD",
                    confidence=0.0,
                    reason=gate_reason,
                    prompt_version=self.params.prompt_version,
                    provider=self.params.provider,
                    model=self.params.model,
                ),
            )
            return

        system_prompt, user_prompt = self._build_prompts(
            symbol=symbol,
            market_data=market_data,
            context=context,
            positions=positions,
            history_df=history_df,
        )
        try:
            decision = await self._get_client().generate_decision_async(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                prompt_version=self.params.prompt_version,
            )
        except Exception as exc:
            logger.warning("%s: LLM decision failed: %s", symbol, exc)
            decision = LLMTradeDecision(
                action="HOLD",
                confidence=0.0,
                reason=f"LLM provider error: {exc}",
                prompt_version=self.params.prompt_version,
                provider=self.params.provider,
                model=self.params.model,
            )
        self._cache_decision(symbol, candle_ts, decision)

    def prepare_entry_decision(
        self,
        ctx: TradingContext,
        history_df: pd.DataFrame | None,
    ) -> None:
        symbol = ctx.market.symbol
        market_data = ctx.market
        context = ctx.regime
        positions = ctx.positions
        candle_ts = int(getattr(market_data, "timestamp", 0) or 0)
        cached = self._decision_cache.get(symbol)
        if cached and int(cached.get("candle_timestamp", -1)) == candle_ts:
            return

        gate_reason = self._preflight_policy_block(symbol, market_data, context)
        if gate_reason is not None:
            self._cache_decision(
                symbol,
                candle_ts,
                LLMTradeDecision(
                    action="HOLD",
                    confidence=0.0,
                    reason=gate_reason,
                    prompt_version=self.params.prompt_version,
                    provider=self.params.provider,
                    model=self.params.model,
                ),
            )
            return

        system_prompt, user_prompt = self._build_prompts(
            symbol=symbol,
            market_data=market_data,
            context=context,
            positions=positions,
            history_df=history_df,
        )
        try:
            decision = self._get_client().generate_decision(
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                prompt_version=self.params.prompt_version,
            )
        except Exception as exc:
            logger.warning("%s: LLM decision failed: %s", symbol, exc)
            decision = LLMTradeDecision(
                action="HOLD",
                confidence=0.0,
                reason=f"LLM provider error: {exc}",
                prompt_version=self.params.prompt_version,
                provider=self.params.provider,
                model=self.params.model,
            )
        self._cache_decision(symbol, candle_ts, decision)

    def check_entry(self, ctx: TradingContext) -> Signal | None:
        symbol = ctx.market.symbol
        decision = self._get_cached_decision(symbol, ctx.market.timestamp)
        if decision is None:
            self._set_rejection_reason(symbol, "LLM decision unavailable")
            return None

        if decision.action != "BUY":
            self._set_rejection_reason(
                symbol,
                f"LLM predicted HOLD (conf={decision.confidence:.2f}): {decision.reason}",
            )
            return None

        if decision.confidence < self.params.confidence_threshold:
            self._set_rejection_reason(
                symbol,
                f"Low LLM confidence ({decision.confidence:.2f} < {self.params.confidence_threshold:.2f})",
            )
            return None

        self._clear_rejection_reason(symbol)
        reason = (
            f"LLMDirection entry: BUY conf={decision.confidence:.2f} "
            f"provider={decision.provider} model={decision.model} prompt={decision.prompt_version} "
            f"reason={decision.reason}"
        )
        logger.info("%s: %s", symbol, reason)
        return Signal(
            symbol=symbol,
            side="buy",
            market=self.params.market,
            quantity=self.params.position_size,
            reason=reason,
        )

    def _cache_decision(self, symbol: str, candle_ts: int, decision: LLMTradeDecision) -> None:
        self._decision_cache[symbol] = {
            "candle_timestamp": int(candle_ts),
            "decision": decision,
        }

    def _get_cached_decision(self, symbol: str, candle_ts: int) -> LLMTradeDecision | None:
        cached = self._decision_cache.get(symbol)
        if not cached:
            return None
        if int(cached.get("candle_timestamp", -1)) != int(candle_ts):
            return None
        decision = cached.get("decision")
        return decision if isinstance(decision, LLMTradeDecision) else None

    def _preflight_policy_block(
        self,
        symbol: str,
        market_data: MarketData,
        context: MarketContext,
    ) -> str | None:
        if self.params.block_bear_regime and context.regime in BEAR_REGIMES:
            return f"LLM blocked by bear regime ({context.regime})"
        if self.params.allowed_regimes and context.regime not in set(self.params.allowed_regimes):
            return f"LLM regime not allowed ({context.regime})"
        if self.params.adx_min > 0 and market_data.adx < self.params.adx_min:
            return f"LLM blocked by ADX ({market_data.adx:.1f} < {self.params.adx_min:.1f})"
        if self.params.use_ema200_filter and market_data.ema_200 > 0 and market_data.close < market_data.ema_200:
            return f"LLM blocked: below EMA200 ({market_data.close:.4f} < {market_data.ema_200:.4f})"
        if (
            self.params.require_close_above_ema120
            and market_data.ema_120 > 0
            and market_data.close < market_data.ema_120
        ):
            return f"LLM blocked: below EMA120 ({market_data.close:.4f} < {market_data.ema_120:.4f})"
        if self.params.min_volume_ratio > 0 and market_data.avg_volume_20 > 0:
            volume_ratio = market_data.volume / market_data.avg_volume_20
            if volume_ratio < self.params.min_volume_ratio:
                return f"LLM blocked by volume ratio ({volume_ratio:.2f} < {self.params.min_volume_ratio:.2f})"
        return None

    def _build_prompts(
        self,
        *,
        symbol: str,
        market_data: MarketData,
        context: MarketContext,
        positions: Any,
        history_df: pd.DataFrame | None,
    ) -> tuple[str, str]:
        system_prompt = (
            "You are a conservative long-only crypto swing trading analyst. "
            "Use only the supplied market data. Do not assume any external news, sentiment, or hidden data. "
            "Return a JSON object with keys action, confidence, reason, risk_flags. "
            "Valid actions are BUY or HOLD. Confidence must be between 0 and 1. "
            "Use HOLD when evidence is mixed, weak, or conditions are bearish."
        )
        history_payload = self._build_history_payload(history_df)
        user_payload = {
            "prompt_version": self.params.prompt_version,
            "symbol": symbol,
            "position_open": bool(positions),
            "market": {
                "close": round(float(market_data.close), 6),
                "open": round(float(market_data.open), 6),
                "high": round(float(market_data.high), 6),
                "low": round(float(market_data.low), 6),
                "volume": round(float(market_data.volume), 6),
                "mfi": round(float(market_data.mfi), 4),
                "adx": round(float(market_data.adx), 4),
                "rsi": round(float(market_data.rsi), 4),
                "atr": round(float(market_data.atr), 6),
                "ema_20": round(float(market_data.ema_20), 6),
                "ema_120": round(float(market_data.ema_120), 6),
                "ema_200": round(float(market_data.ema_200), 6),
                "breakout_signal": int(market_data.breakout_signal),
                "timestamp": int(market_data.timestamp),
            },
            "regime": {
                "trend": context.trend,
                "regime": context.regime,
                "volatility_score": round(float(context.volatility_score), 6),
                "is_extreme_volatility": bool(context.is_extreme_volatility),
                "volume_ratio": round(float(context.volume_ratio), 4),
                "is_high_volume": bool(context.is_high_volume),
                "drawdown": round(float(context.drawdown), 6),
            },
            "recent_candles": history_payload,
            "task": (
                "Decide whether to open a new long position for the next 1-3 four-hour bars. "
                "Prefer BUY only when trend, momentum, and price structure are aligned."
            ),
        }
        return system_prompt, json.dumps(user_payload, ensure_ascii=True, separators=(",", ":"))

    def _build_history_payload(self, history_df: pd.DataFrame | None) -> list[dict[str, Any]]:
        if history_df is None or history_df.empty:
            return []
        history = history_df.tail(max(1, int(self.params.context_window_bars))).copy()
        records: list[dict[str, Any]] = []
        columns = [
            "timestamp", "open", "high", "low", "close", "volume",
            "mfi", "adx", "rsi", "atr", "ema_20", "ema_120", "ema_200",
            "macd", "macd_signal", "trix", "trix_signal",
        ]
        for _, row in history.iterrows():
            record: dict[str, Any] = {}
            for col in columns:
                if col not in row:
                    continue
                value = row[col]
                if pd.isna(value):
                    continue
                if hasattr(value, "timestamp"):
                    record[col] = int(value.timestamp() * 1000)
                elif isinstance(value, (int, float)):
                    record[col] = round(float(value), 6)
                else:
                    record[col] = str(value)
            records.append(record)
        return records
