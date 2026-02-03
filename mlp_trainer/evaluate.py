#!/usr/bin/env python3
"""
CLI entry point for model evaluation.

Usage:
    python mlp_trainer/evaluate.py \
        --model models/mlp_direction/model_final.pt \
        --data data/mlp_datasets/validation_BTCUSDT_bwin5_fwin2.npz
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mlp_trainer.src.mlp_evaluate import main

if __name__ == "__main__":
    main()
