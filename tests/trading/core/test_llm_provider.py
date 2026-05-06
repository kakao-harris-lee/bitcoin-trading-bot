from unittest.mock import MagicMock, patch

import requests

from trading.core.llm_provider import (
    collect_llm_provider_health,
    summarize_llm_provider_health,
)


def test_collect_ollama_health_reports_unhealthy_with_fallback():
    config = {
        "strategies": {
            "llm_direction_btc": {
                "enabled": True,
                "entry": {
                    "class": "LLMDecisionEntryStrategy",
                    "params": {
                        "provider": "ollama",
                        "model": "llama3.1:8b",
                        "api_base_url": "http://127.0.0.1:11434",
                    },
                },
                "entry_fallback": {"enabled": True},
            }
        }
    }

    with patch(
        "trading.core.llm_provider.requests.get",
        side_effect=requests.RequestException("boom"),
    ):
        reports = collect_llm_provider_health(config)

    assert len(reports) == 1
    report = reports[0]
    assert report.strategy == "llm_direction_btc"
    assert report.healthy is False
    assert report.fallback_enabled is True


def test_collect_ollama_health_reports_model_missing():
    response = MagicMock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"models": [{"name": "llama3.2:3b"}]}
    config = {
        "strategies": {
            "llm_direction_btc": {
                "enabled": True,
                "entry": {
                    "class": "LLMDecisionEntryStrategy",
                    "params": {
                        "provider": "ollama",
                        "model": "llama3.1:8b",
                        "api_base_url": "http://127.0.0.1:11434",
                    },
                },
            }
        }
    }

    with patch("trading.core.llm_provider.requests.get", return_value=response):
        reports = collect_llm_provider_health(config)

    assert reports[0].healthy is False
    assert reports[0].reason == "model_missing:llama3.1:8b"


def test_summarize_provider_health_blocks_live_without_fallback():
    config = {
        "strategies": {
            "llm_direction_btc": {
                "enabled": True,
                "entry": {
                    "class": "LLMDecisionEntryStrategy",
                    "params": {
                        "provider": "openai",
                        "model": "gpt-test",
                        "api_key_env": "MISSING_KEY",
                    },
                },
            }
        }
    }

    reports = collect_llm_provider_health(config)
    warnings, errors = summarize_llm_provider_health(reports, mode="live")

    assert warnings == []
    assert len(errors) == 1
