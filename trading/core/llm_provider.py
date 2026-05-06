"""LLM provider health checks used at startup and for operator visibility."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Any

import requests


@dataclass(frozen=True)
class LLMProviderHealth:
    """Resolved health status for one configured LLM-backed strategy."""

    strategy: str
    provider: str
    model: str
    api_base_url: str
    healthy: bool
    reason: str
    fallback_enabled: bool


def collect_llm_provider_health(
    config: dict[str, Any],
    *,
    timeout_seconds: float = 3.0,
) -> list[LLMProviderHealth]:
    """Collect provider health for enabled LLM entry strategies."""
    strategies = config.get("strategies", {})
    if not isinstance(strategies, dict):
        return []

    results: list[LLMProviderHealth] = []
    for strategy_name, strategy_cfg in strategies.items():
        if not isinstance(strategy_cfg, dict) or strategy_cfg.get("enabled") is False:
            continue

        entry_cfg = strategy_cfg.get("entry") or {}
        if not isinstance(entry_cfg, dict):
            continue
        if entry_cfg.get("class") != "LLMDecisionEntryStrategy":
            continue

        params = entry_cfg.get("params") or {}
        if not isinstance(params, dict):
            params = {}

        fallback_cfg = strategy_cfg.get("entry_fallback") or {}
        fallback_enabled = bool(
            isinstance(fallback_cfg, dict) and fallback_cfg.get("enabled", False)
        )
        provider = str(params.get("provider", "ollama") or "ollama").strip().lower()
        model = str(params.get("model", "") or "").strip()
        api_base_url = str(
            params.get("api_base_url", "http://127.0.0.1:11434") or ""
        ).strip()

        if provider == "ollama":
            results.append(
                _check_ollama_health(
                    strategy=strategy_name,
                    model=model,
                    api_base_url=api_base_url,
                    timeout_seconds=timeout_seconds,
                    fallback_enabled=fallback_enabled,
                )
            )
            continue

        if provider == "openai":
            api_key_env = str(
                params.get("api_key_env", "OPENAI_API_KEY") or "OPENAI_API_KEY"
            ).strip()
            api_key = os.getenv(api_key_env, "").strip()
            results.append(
                LLMProviderHealth(
                    strategy=strategy_name,
                    provider=provider,
                    model=model,
                    api_base_url=api_base_url,
                    healthy=bool(api_key),
                    reason="ok" if api_key else f"missing_api_key_env:{api_key_env}",
                    fallback_enabled=fallback_enabled,
                )
            )
            continue

        results.append(
            LLMProviderHealth(
                strategy=strategy_name,
                provider=provider,
                model=model,
                api_base_url=api_base_url,
                healthy=False,
                reason=f"unsupported_provider:{provider}",
                fallback_enabled=fallback_enabled,
            )
        )

    return results


def summarize_llm_provider_health(
    reports: list[LLMProviderHealth],
    *,
    mode: str,
) -> tuple[list[str], list[str]]:
    """Return `(warnings, errors)` suitable for startup logging."""
    warnings: list[str] = []
    errors: list[str] = []

    for report in reports:
        base = (
            f"{report.strategy}: provider={report.provider} model={report.model or '-'} "
            f"healthy={'yes' if report.healthy else 'no'} reason={report.reason}"
        )
        if report.healthy:
            continue
        if report.fallback_enabled:
            warnings.append(f"{base} fallback=enabled")
        elif mode == "live":
            errors.append(f"{base} fallback=disabled")
        else:
            warnings.append(f"{base} fallback=disabled")

    return warnings, errors


def _check_ollama_health(
    *,
    strategy: str,
    model: str,
    api_base_url: str,
    timeout_seconds: float,
    fallback_enabled: bool,
) -> LLMProviderHealth:
    url = api_base_url.rstrip("/") + "/api/tags"
    try:
        response = requests.get(url, timeout=timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        return LLMProviderHealth(
            strategy=strategy,
            provider="ollama",
            model=model,
            api_base_url=api_base_url,
            healthy=False,
            reason=f"connect_error:{exc}",
            fallback_enabled=fallback_enabled,
        )
    except ValueError as exc:
        return LLMProviderHealth(
            strategy=strategy,
            provider="ollama",
            model=model,
            api_base_url=api_base_url,
            healthy=False,
            reason=f"invalid_json:{exc}",
            fallback_enabled=fallback_enabled,
        )

    names: set[str] = set()
    models = payload.get("models")
    if isinstance(models, list):
        for item in models:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name", "") or "").strip()
            if name:
                names.add(name)

    if model and names and model not in names:
        return LLMProviderHealth(
            strategy=strategy,
            provider="ollama",
            model=model,
            api_base_url=api_base_url,
            healthy=False,
            reason=f"model_missing:{model}",
            fallback_enabled=fallback_enabled,
        )

    return LLMProviderHealth(
        strategy=strategy,
        provider="ollama",
        model=model,
        api_base_url=api_base_url,
        healthy=True,
        reason="ok",
        fallback_enabled=fallback_enabled,
    )
