"""MLflow configuration dataclass."""

import os
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class MLflowConfig:
    """MLflow tracking configuration.

    Supports creation from:
    - Direct instantiation
    - Configuration dictionary (from_dict)
    - Environment variables (from_env)

    Attributes:
        enabled: Whether MLflow tracking is enabled
        tracking_uri: MLflow tracking URI (file path or server URL)
        experiment_name: Name of the MLflow experiment
        artifact_location: Custom artifact storage location (optional)
    """

    enabled: bool = True
    tracking_uri: str = "./mlruns"
    experiment_name: str = "backtest-experiments"
    artifact_location: Optional[str] = None

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "MLflowConfig":
        """Create from configuration dictionary.

        Args:
            config: Dictionary with optional 'mlflow' section containing:
                - enabled: bool
                - tracking_uri: str
                - experiment_name: str
                - artifact_location: str or None

        Returns:
            MLflowConfig instance
        """
        mlflow_config = config.get("mlflow", {})
        return cls(
            enabled=mlflow_config.get("enabled", True),
            tracking_uri=mlflow_config.get("tracking_uri", "./mlruns"),
            experiment_name=mlflow_config.get("experiment_name", "backtest-experiments"),
            artifact_location=mlflow_config.get("artifact_location"),
        )

    @classmethod
    def from_env(cls) -> "MLflowConfig":
        """Create from environment variables.

        Reads:
            - MLFLOW_ENABLED: "true"/"false" (default: true)
            - MLFLOW_TRACKING_URI: tracking URI (default: ./mlruns)
            - MLFLOW_EXPERIMENT_NAME: experiment name (default: backtest-experiments)
            - MLFLOW_ARTIFACT_LOCATION: artifact location (optional)

        Returns:
            MLflowConfig instance
        """
        return cls(
            enabled=os.getenv("MLFLOW_ENABLED", "true").lower() == "true",
            tracking_uri=os.getenv("MLFLOW_TRACKING_URI", "./mlruns"),
            experiment_name=os.getenv("MLFLOW_EXPERIMENT_NAME", "backtest-experiments"),
            artifact_location=os.getenv("MLFLOW_ARTIFACT_LOCATION"),
        )

    @classmethod
    def from_file(cls, file_path: str, base_dir: Optional[str] = None) -> "MLflowConfig":
        """Create from JSON configuration file.

        Args:
            file_path: Path to JSON config file (must have .json extension)
            base_dir: Optional base directory to restrict file access.
                      If provided, file_path must be within this directory.

        Returns:
            MLflowConfig instance

        Raises:
            ValueError: If file extension is not .json or path escapes base_dir
        """
        import json
        from pathlib import Path

        path = Path(file_path)

        # Validate file extension
        if path.suffix.lower() != ".json":
            raise ValueError(f"Config file must have .json extension, got: {path.suffix}")

        # Resolve the path to prevent symlink attacks
        resolved = path.resolve()

        # If base_dir is specified, ensure file is within it
        if base_dir is not None:
            base_resolved = Path(base_dir).resolve()
            if not str(resolved).startswith(str(base_resolved)):
                raise ValueError(f"Config file must be within {base_dir}")

        if not resolved.exists():
            return cls()

        # Check file size to prevent DoS (max 1MB for config)
        max_size = 1024 * 1024  # 1MB
        if resolved.stat().st_size > max_size:
            raise ValueError(f"Config file too large (max {max_size} bytes)")

        with open(resolved, encoding="utf-8") as f:
            config = json.load(f)

        return cls.from_dict(config)
