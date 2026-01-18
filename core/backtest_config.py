"""Configuration dataclasses for backtest visualization and MLflow integration."""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class VisualizationConfig:
    """Chart visualization settings."""

    width: int = 12  # inches
    height: int = 6  # inches
    dpi: int = 150
    format: str = "png"  # png, svg, pdf

    # Colors
    strategy_color: str = "#1f77b4"  # Blue
    benchmark_color: str = "#ff7f0e"  # Orange

    # Style
    strategy_linestyle: str = "-"
    benchmark_linestyle: str = "--"
    grid: bool = True
    legend_location: str = "upper left"

    @classmethod
    def from_dict(cls, config: Dict[str, Any]) -> "VisualizationConfig":
        """Create from configuration dictionary."""
        viz_config = config.get("visualization", {})
        return cls(
            width=viz_config.get("chart_width", 12),
            height=viz_config.get("chart_height", 6),
            dpi=viz_config.get("dpi", 150),
            format=viz_config.get("format", "png"),
        )
