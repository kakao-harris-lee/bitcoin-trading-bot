#!/usr/bin/env python3
"""
CLI entry point for dataset building.

Usage:
    python mlp_trainer/build_dataset.py \
        --input data/multi_asset_4h/train_4h.parquet \
        --output data/mlp_datasets \
        --bwin 5 --fwin 2
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mlp_trainer.src.dataset_builder import main

if __name__ == "__main__":
    main()
