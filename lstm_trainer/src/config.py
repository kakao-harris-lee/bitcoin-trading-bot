# lstm_trainer/src/config.py
"""Configuration loader for LSTM trainer."""

from pathlib import Path
from typing import Any
import yaml


def load_config(config_path: str = "config/default.yaml") -> dict[str, Any]:
    """Load configuration from YAML file."""
    with open(config_path, "r") as f:
        return yaml.safe_load(f)


def get_config() -> dict[str, Any]:
    """Get default configuration."""
    return load_config()
