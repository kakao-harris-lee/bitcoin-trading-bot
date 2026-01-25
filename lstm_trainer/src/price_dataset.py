"""Dataset for price forecasting with LSTM."""

from __future__ import annotations

from typing import Tuple

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


class PriceDataset(Dataset):
    """Sliding-window dataset for next-close regression."""

    def __init__(self, df: pd.DataFrame, seq_len: int = 120):
        self.seq_len = seq_len
        # Ensure sorted by time
        df = df.sort_values("timestamp").reset_index(drop=True)
        self.data = df[["open", "high", "low", "close", "volume"]].values.astype(np.float32)

        # Build index of start positions where target exists
        self.indices = []
        for i in range(len(self.data) - seq_len):
            self.indices.append(i)

    def __len__(self) -> int:
        return len(self.indices)

    def __getitem__(self, idx: int) -> Tuple[torch.Tensor, torch.Tensor]:
        start = self.indices[idx]
        end = start + self.seq_len
        window = self.data[start:end]  # (seq_len, 5)
        target_close = self.data[end, 3]  # next close

        # Normalize relative to first close
        base_close = window[0, 3]
        base_vol = window[:, 4].mean() + 1e-8

        norm = window.copy()
        norm[:, :4] = (window[:, :4] - base_close) / (base_close + 1e-8)
        norm[:, 4] = window[:, 4] / base_vol

        # Target as log-return to next close
        target = np.log((target_close + 1e-8) / (base_close + 1e-8))

        x = torch.from_numpy(norm)  # (seq_len, 5)
        y = torch.tensor(target, dtype=torch.float32)
        return x, y
