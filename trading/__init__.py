"""
Trading Engine V2 - Main Package
"""

__version__ = "2.0.0"

from .multi_asset_engine import MultiAssetTradingEngine, MultiAssetEngineConfig

__all__ = [
    "MultiAssetTradingEngine",
    "MultiAssetEngineConfig",
]
