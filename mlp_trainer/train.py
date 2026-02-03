#!/usr/bin/env python3
"""
CLI entry point for model training.

Usage:
    python mlp_trainer/train.py \
        --dataset data/mlp_datasets/mlp_dataset_bwin5_fwin2.npz \
        --epochs 100 \
        --batch-size 256
"""

import sys
from pathlib import Path

# Add project root to path
PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from mlp_trainer.src.mlp_train import main

if __name__ == "__main__":
    main()
