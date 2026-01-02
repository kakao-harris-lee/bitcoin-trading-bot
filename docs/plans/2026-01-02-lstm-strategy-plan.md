# LSTM Trend Prediction Strategy - Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a PyTorch LSTM model for H4 trend prediction (UP/DOWN/SIDEWAYS) with Docker-based GPU training and CPU production inference.

**Architecture:** Separate `lstm_trainer/` package for training (portable to GPU server), with inference class integrated into main trading bot. Per-window normalized OHLCV input, 3-class classification output.

**Tech Stack:** PyTorch 2.1+, Pandas, PyArrow, Docker Compose, CUDA

---

## Task 1: Create Project Structure

**Files:**
- Create: `lstm_trainer/README.md`
- Create: `lstm_trainer/requirements.txt`
- Create: `lstm_trainer/.gitignore`

**Step 1: Create lstm_trainer directory structure**

```bash
mkdir -p lstm_trainer/{src,data/raw,data/processed,models,config,notebooks}
```

**Step 2: Create requirements.txt**

```text
# lstm_trainer/requirements.txt
torch>=2.1.0
pandas>=2.0.0
pyarrow>=14.0.0
numpy>=1.24.0
scikit-learn>=1.3.0
tqdm>=4.65.0
pyyaml>=6.0
jupyter>=1.0.0
matplotlib>=3.7.0
```

**Step 3: Create .gitignore**

```text
# lstm_trainer/.gitignore
__pycache__/
*.pyc
*.pth
*.pt
data/raw/
data/processed/
models/
logs/
.ipynb_checkpoints/
```

**Step 4: Create README.md**

```markdown
# LSTM Trend Trainer

PyTorch LSTM for Bitcoin H4 trend prediction.

## Quick Start

### Local Development (CPU)
```bash
python src/export_data.py --db-path ../data/upbit_bitcoin.db
python src/dev_mode.py
```

### GPU Training (Docker)
```bash
docker compose run trainer
```

### Download Model
```bash
scp server:~/lstm_trainer/models/trading_lstm.pth ./models/
```
```

**Step 5: Commit**

```bash
git add lstm_trainer/
git commit -m "feat(lstm): create project structure"
```

---

## Task 2: Create Configuration

**Files:**
- Create: `lstm_trainer/config/default.yaml`
- Create: `lstm_trainer/src/config.py`

**Step 1: Create default.yaml**

```yaml
# lstm_trainer/config/default.yaml
model:
  input_size: 5          # OHLCV
  hidden_size: 64
  num_layers: 2
  dropout: 0.2
  num_classes: 3         # UP/DOWN/SIDEWAYS

data:
  seq_len: 60            # 10 days of H4
  threshold: 0.015       # ±1.5% for labels
  train_end: "2023-12-31"
  val_end: "2024-06-30"

training:
  batch_size: 64
  learning_rate: 0.001
  weight_decay: 0.0001
  max_epochs: 100
  early_stopping_patience: 10
  scheduler_patience: 5

paths:
  data_raw: "data/raw"
  data_processed: "data/processed"
  models: "models"
  logs: "logs"
```

**Step 2: Create config.py**

```python
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
```

**Step 3: Commit**

```bash
git add lstm_trainer/config/ lstm_trainer/src/config.py
git commit -m "feat(lstm): add configuration"
```

---

## Task 3: Create LSTM Model

**Files:**
- Create: `lstm_trainer/src/model.py`
- Create: `lstm_trainer/tests/test_model.py`

**Step 1: Write the test**

```python
# lstm_trainer/tests/test_model.py
"""Tests for LSTM model."""

import torch
import pytest


def test_model_forward_shape():
    """Model output should have correct shape."""
    from src.model import TrendLSTM

    model = TrendLSTM(input_size=5, hidden_size=64, num_layers=2, num_classes=3)
    x = torch.randn(32, 60, 5)  # batch=32, seq=60, features=5

    output = model(x)

    assert output.shape == (32, 3), f"Expected (32, 3), got {output.shape}"


def test_model_inference_mode():
    """Model should work in eval mode without gradients."""
    from src.model import TrendLSTM

    model = TrendLSTM()
    model.eval()
    x = torch.randn(1, 60, 5)

    with torch.no_grad():
        output = model(x)
        probs = torch.softmax(output, dim=1)

    assert probs.sum().item() == pytest.approx(1.0, abs=1e-5)


def test_model_small_config():
    """Model should accept different configurations."""
    from src.model import TrendLSTM

    model = TrendLSTM(hidden_size=32, num_layers=1, dropout=0.0)
    x = torch.randn(8, 60, 5)

    output = model(x)

    assert output.shape == (8, 3)
```

**Step 2: Run test to verify it fails**

Run: `cd lstm_trainer && python -m pytest tests/test_model.py -v`
Expected: FAIL with "ModuleNotFoundError: No module named 'src.model'"

**Step 3: Create model.py**

```python
# lstm_trainer/src/model.py
"""LSTM model for trend prediction."""

import torch
import torch.nn as nn


class TrendLSTM(nn.Module):
    """LSTM classifier for UP/DOWN/SIDEWAYS trend prediction."""

    def __init__(
        self,
        input_size: int = 5,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        num_classes: int = 3,
    ):
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """
        Forward pass.

        Args:
            x: Input tensor of shape (batch, seq_len, input_size)

        Returns:
            Logits of shape (batch, num_classes)
        """
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]  # Take last timestep
        return self.fc(last_hidden)
```

**Step 4: Create __init__.py files**

```python
# lstm_trainer/src/__init__.py
"""LSTM trainer source."""

# lstm_trainer/tests/__init__.py
"""LSTM trainer tests."""
```

**Step 5: Run test to verify it passes**

Run: `cd lstm_trainer && python -m pytest tests/test_model.py -v`
Expected: PASS (3 tests)

**Step 6: Commit**

```bash
git add lstm_trainer/src/model.py lstm_trainer/src/__init__.py lstm_trainer/tests/
git commit -m "feat(lstm): add TrendLSTM model"
```

---

## Task 4: Create Dataset Class

**Files:**
- Create: `lstm_trainer/src/dataset.py`
- Create: `lstm_trainer/tests/test_dataset.py`

**Step 1: Write the test**

```python
# lstm_trainer/tests/test_dataset.py
"""Tests for dataset class."""

import numpy as np
import pandas as pd
import torch
import pytest


def test_dataset_length():
    """Dataset length should be data_length - seq_len."""
    from src.dataset import TrendDataset

    # Create dummy data
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="4h"),
        "open": np.random.randn(100).cumsum() + 100,
        "high": np.random.randn(100).cumsum() + 101,
        "low": np.random.randn(100).cumsum() + 99,
        "close": np.random.randn(100).cumsum() + 100,
        "volume": np.abs(np.random.randn(100)) * 1000,
    })

    dataset = TrendDataset(df, seq_len=60, threshold=0.015)

    # Should have 100 - 60 - 1 = 39 samples (need next candle for label)
    assert len(dataset) == 39


def test_dataset_item_shape():
    """Each item should have correct tensor shapes."""
    from src.dataset import TrendDataset

    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="4h"),
        "open": np.random.randn(100).cumsum() + 100,
        "high": np.random.randn(100).cumsum() + 101,
        "low": np.random.randn(100).cumsum() + 99,
        "close": np.random.randn(100).cumsum() + 100,
        "volume": np.abs(np.random.randn(100)) * 1000,
    })

    dataset = TrendDataset(df, seq_len=60)
    x, y = dataset[0]

    assert x.shape == (60, 5), f"Expected (60, 5), got {x.shape}"
    assert isinstance(y, int) and y in [0, 1, 2]


def test_label_distribution():
    """Labels should be 0 (UP), 1 (DOWN), or 2 (SIDEWAYS)."""
    from src.dataset import TrendDataset

    # Create trending data
    closes = [100 + i * 0.5 for i in range(100)]  # Uptrend
    df = pd.DataFrame({
        "timestamp": pd.date_range("2024-01-01", periods=100, freq="4h"),
        "open": closes,
        "high": [c + 1 for c in closes],
        "low": [c - 1 for c in closes],
        "close": closes,
        "volume": [1000] * 100,
    })

    dataset = TrendDataset(df, seq_len=60, threshold=0.005)

    labels = [dataset[i][1] for i in range(len(dataset))]
    assert all(l in [0, 1, 2] for l in labels)
```

**Step 2: Run test to verify it fails**

Run: `cd lstm_trainer && python -m pytest tests/test_dataset.py -v`
Expected: FAIL with "ModuleNotFoundError"

**Step 3: Create dataset.py**

```python
# lstm_trainer/src/dataset.py
"""PyTorch Dataset for LSTM training."""

import numpy as np
import pandas as pd
import torch
from torch.utils.data import Dataset


class TrendDataset(Dataset):
    """Dataset for trend prediction with per-window normalization."""

    # Label mapping
    UP = 0
    DOWN = 1
    SIDEWAYS = 2

    def __init__(
        self,
        df: pd.DataFrame,
        seq_len: int = 60,
        threshold: float = 0.015,
    ):
        """
        Initialize dataset.

        Args:
            df: DataFrame with columns [timestamp, open, high, low, close, volume]
            seq_len: Sequence length for LSTM input
            threshold: Threshold for UP/DOWN classification (default ±1.5%)
        """
        self.seq_len = seq_len
        self.threshold = threshold

        # Extract OHLCV as numpy array
        self.data = df[["open", "high", "low", "close", "volume"]].values.astype(np.float32)
        self.closes = df["close"].values.astype(np.float32)

        # Valid indices: need seq_len candles + 1 for label
        self.valid_indices = list(range(seq_len, len(df) - 1))

    def __len__(self) -> int:
        return len(self.valid_indices)

    def __getitem__(self, idx: int) -> tuple[torch.Tensor, int]:
        """Get normalized sequence and label."""
        end_idx = self.valid_indices[idx]
        start_idx = end_idx - self.seq_len

        # Extract window
        window = self.data[start_idx:end_idx].copy()

        # Normalize
        x = self._normalize_window(window)

        # Create label from next candle
        current_close = self.closes[end_idx]
        next_close = self.closes[end_idx + 1]
        label = self._make_label(current_close, next_close)

        return torch.from_numpy(x), label

    def _normalize_window(self, window: np.ndarray) -> np.ndarray:
        """Normalize OHLCV relative to first candle's close."""
        base_close = window[0, 3]  # First candle's close
        base_volume = window[:, 4].mean() + 1e-8  # Mean volume

        normalized = window.copy()
        # Normalize prices as % change from base
        normalized[:, :4] = (window[:, :4] - base_close) / (base_close + 1e-8)
        # Normalize volume as ratio to mean
        normalized[:, 4] = window[:, 4] / base_volume

        return normalized

    def _make_label(self, current_close: float, next_close: float) -> int:
        """Create label based on price change threshold."""
        pct_change = (next_close - current_close) / (current_close + 1e-8)

        if pct_change > self.threshold:
            return self.UP
        elif pct_change < -self.threshold:
            return self.DOWN
        else:
            return self.SIDEWAYS

    def get_class_weights(self) -> torch.Tensor:
        """Compute class weights for imbalanced data."""
        labels = [self[i][1] for i in range(len(self))]
        counts = np.bincount(labels, minlength=3)
        weights = 1.0 / (counts + 1e-8)
        weights = weights / weights.sum() * 3  # Normalize
        return torch.tensor(weights, dtype=torch.float32)
```

**Step 4: Run test to verify it passes**

Run: `cd lstm_trainer && python -m pytest tests/test_dataset.py -v`
Expected: PASS (3 tests)

**Step 5: Commit**

```bash
git add lstm_trainer/src/dataset.py lstm_trainer/tests/test_dataset.py
git commit -m "feat(lstm): add TrendDataset class"
```

---

## Task 5: Create Data Export Script

**Files:**
- Create: `lstm_trainer/src/export_data.py`

**Step 1: Create export_data.py**

```python
#!/usr/bin/env python3
# lstm_trainer/src/export_data.py
"""Export H4 data from SQLite to Parquet for training."""

import argparse
import sqlite3
from pathlib import Path

import pandas as pd


def export_h4_data(
    db_path: str,
    output_path: str = "data/processed/h4_candles.parquet",
) -> pd.DataFrame:
    """
    Export H4 (minute240) candles from SQLite to Parquet.

    Args:
        db_path: Path to upbit_bitcoin.db
        output_path: Output parquet file path

    Returns:
        DataFrame with exported data
    """
    print(f"Connecting to {db_path}...")

    conn = sqlite3.connect(db_path)

    query = """
    SELECT timestamp, open, high, low, close, volume
    FROM bitcoin_minute240
    ORDER BY timestamp ASC
    """

    df = pd.read_sql_query(query, conn)
    conn.close()

    print(f"Loaded {len(df):,} H4 candles")
    print(f"Date range: {df['timestamp'].iloc[0]} to {df['timestamp'].iloc[-1]}")

    # Ensure output directory exists
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    # Save to parquet
    df.to_parquet(output_path, index=False)
    print(f"Saved to {output_path}")

    return df


def main():
    parser = argparse.ArgumentParser(description="Export H4 data for LSTM training")
    parser.add_argument(
        "--db-path",
        default="../data/upbit_bitcoin.db",
        help="Path to SQLite database",
    )
    parser.add_argument(
        "--output",
        default="data/processed/h4_candles.parquet",
        help="Output parquet file path",
    )

    args = parser.parse_args()
    export_h4_data(args.db_path, args.output)


if __name__ == "__main__":
    main()
```

**Step 2: Test the script manually**

Run: `cd lstm_trainer && python src/export_data.py --db-path ../data/upbit_bitcoin.db`
Expected: Creates `data/processed/h4_candles.parquet` with ~15,000 rows

**Step 3: Commit**

```bash
git add lstm_trainer/src/export_data.py
git commit -m "feat(lstm): add data export script"
```

---

## Task 6: Create Training Script

**Files:**
- Create: `lstm_trainer/src/train.py`

**Step 1: Create train.py**

```python
#!/usr/bin/env python3
# lstm_trainer/src/train.py
"""Training script for LSTM model."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader
from tqdm import tqdm

from config import load_config
from dataset import TrendDataset
from model import TrendLSTM


def train_epoch(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    optimizer: torch.optim.Optimizer,
    device: torch.device,
) -> float:
    """Train for one epoch."""
    model.train()
    total_loss = 0.0

    for x, y in loader:
        x, y = x.to(device), y.to(device)

        optimizer.zero_grad()
        logits = model(x)
        loss = criterion(logits, y)
        loss.backward()
        optimizer.step()

        total_loss += loss.item()

    return total_loss / len(loader)


def validate(
    model: nn.Module,
    loader: DataLoader,
    criterion: nn.Module,
    device: torch.device,
) -> tuple[float, float]:
    """Validate model."""
    model.eval()
    total_loss = 0.0
    correct = 0
    total = 0

    with torch.no_grad():
        for x, y in loader:
            x, y = x.to(device), y.to(device)

            logits = model(x)
            loss = criterion(logits, y)

            total_loss += loss.item()
            preds = logits.argmax(dim=1)
            correct += (preds == y).sum().item()
            total += y.size(0)

    return total_loss / len(loader), correct / total


def train(config_path: str = "config/default.yaml"):
    """Main training function."""
    config = load_config(config_path)

    # Device
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Load data
    data_path = Path(config["paths"]["data_processed"]) / "h4_candles.parquet"
    df = pd.read_parquet(data_path)
    print(f"Loaded {len(df):,} candles")

    # Split data chronologically
    df["timestamp"] = pd.to_datetime(df["timestamp"])
    train_end = pd.Timestamp(config["data"]["train_end"])
    val_end = pd.Timestamp(config["data"]["val_end"])

    train_df = df[df["timestamp"] <= train_end]
    val_df = df[(df["timestamp"] > train_end) & (df["timestamp"] <= val_end)]
    test_df = df[df["timestamp"] > val_end]

    print(f"Train: {len(train_df):,} | Val: {len(val_df):,} | Test: {len(test_df):,}")

    # Create datasets
    seq_len = config["data"]["seq_len"]
    threshold = config["data"]["threshold"]

    train_set = TrendDataset(train_df, seq_len=seq_len, threshold=threshold)
    val_set = TrendDataset(val_df, seq_len=seq_len, threshold=threshold)

    # Class weights
    class_weights = train_set.get_class_weights().to(device)
    print(f"Class weights: {class_weights.tolist()}")

    # DataLoaders
    batch_size = config["training"]["batch_size"]
    train_loader = DataLoader(train_set, batch_size=batch_size, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=batch_size, shuffle=False)

    # Model
    model = TrendLSTM(
        input_size=config["model"]["input_size"],
        hidden_size=config["model"]["hidden_size"],
        num_layers=config["model"]["num_layers"],
        dropout=config["model"]["dropout"],
        num_classes=config["model"]["num_classes"],
    ).to(device)

    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    # Training setup
    criterion = nn.CrossEntropyLoss(weight=class_weights)
    optimizer = torch.optim.AdamW(
        model.parameters(),
        lr=config["training"]["learning_rate"],
        weight_decay=config["training"]["weight_decay"],
    )
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
        optimizer,
        mode="min",
        patience=config["training"]["scheduler_patience"],
        factor=0.5,
    )

    # Training loop
    best_val_loss = float("inf")
    patience_counter = 0
    max_patience = config["training"]["early_stopping_patience"]

    model_dir = Path(config["paths"]["models"])
    model_dir.mkdir(parents=True, exist_ok=True)

    for epoch in range(config["training"]["max_epochs"]):
        train_loss = train_epoch(model, train_loader, criterion, optimizer, device)
        val_loss, val_acc = validate(model, val_loader, criterion, device)
        scheduler.step(val_loss)

        print(
            f"Epoch {epoch+1:3d} | "
            f"Train Loss: {train_loss:.4f} | "
            f"Val Loss: {val_loss:.4f} | "
            f"Val Acc: {val_acc:.2%}"
        )

        if val_loss < best_val_loss:
            best_val_loss = val_loss
            torch.save(model.state_dict(), model_dir / "trading_lstm.pth")
            print(f"  -> Saved best model (val_loss: {val_loss:.4f})")
            patience_counter = 0
        else:
            patience_counter += 1
            if patience_counter >= max_patience:
                print(f"Early stopping at epoch {epoch+1}")
                break

    print(f"\nTraining complete. Best model saved to {model_dir / 'trading_lstm.pth'}")


def main():
    parser = argparse.ArgumentParser(description="Train LSTM model")
    parser.add_argument(
        "--config",
        default="config/default.yaml",
        help="Path to config file",
    )

    args = parser.parse_args()
    train(args.config)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add lstm_trainer/src/train.py
git commit -m "feat(lstm): add training script"
```

---

## Task 7: Create Evaluation Script

**Files:**
- Create: `lstm_trainer/src/evaluate.py`

**Step 1: Create evaluate.py**

```python
#!/usr/bin/env python3
# lstm_trainer/src/evaluate.py
"""Evaluate trained LSTM model."""

import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import classification_report, confusion_matrix
from torch.utils.data import DataLoader

from config import load_config
from dataset import TrendDataset
from model import TrendLSTM


def evaluate(config_path: str = "config/default.yaml", model_path: str = None):
    """Evaluate model on test set."""
    config = load_config(config_path)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")

    # Load data
    data_path = Path(config["paths"]["data_processed"]) / "h4_candles.parquet"
    df = pd.read_parquet(data_path)
    df["timestamp"] = pd.to_datetime(df["timestamp"])

    # Get test set
    val_end = pd.Timestamp(config["data"]["val_end"])
    test_df = df[df["timestamp"] > val_end]
    print(f"Test set: {len(test_df):,} candles")

    # Create dataset
    test_set = TrendDataset(
        test_df,
        seq_len=config["data"]["seq_len"],
        threshold=config["data"]["threshold"],
    )
    test_loader = DataLoader(test_set, batch_size=64, shuffle=False)

    # Load model
    model = TrendLSTM(
        input_size=config["model"]["input_size"],
        hidden_size=config["model"]["hidden_size"],
        num_layers=config["model"]["num_layers"],
        dropout=config["model"]["dropout"],
        num_classes=config["model"]["num_classes"],
    ).to(device)

    if model_path is None:
        model_path = Path(config["paths"]["models"]) / "trading_lstm.pth"

    model.load_state_dict(torch.load(model_path, map_location=device))
    model.eval()
    print(f"Loaded model from {model_path}")

    # Collect predictions
    all_preds = []
    all_labels = []
    all_probs = []

    with torch.no_grad():
        for x, y in test_loader:
            x = x.to(device)
            logits = model(x)
            probs = torch.softmax(logits, dim=1)
            preds = logits.argmax(dim=1)

            all_preds.extend(preds.cpu().tolist())
            all_labels.extend(y.tolist())
            all_probs.extend(probs.cpu().tolist())

    # Metrics
    labels = ["UP", "DOWN", "SIDEWAYS"]

    print("\n" + "=" * 60)
    print("Classification Report")
    print("=" * 60)
    print(classification_report(all_labels, all_preds, target_names=labels))

    print("\n" + "=" * 60)
    print("Confusion Matrix")
    print("=" * 60)
    cm = confusion_matrix(all_labels, all_preds)
    print(f"{'':>12} {'UP':>8} {'DOWN':>8} {'SIDE':>8}")
    for i, label in enumerate(labels):
        print(f"{label:>12} {cm[i, 0]:>8} {cm[i, 1]:>8} {cm[i, 2]:>8}")

    # Directional accuracy (UP/DOWN only)
    directional_mask = [l != 2 for l in all_labels]
    dir_labels = [l for l, m in zip(all_labels, directional_mask) if m]
    dir_preds = [p for p, m in zip(all_preds, directional_mask) if m]
    dir_acc = sum(l == p for l, p in zip(dir_labels, dir_preds)) / len(dir_labels)

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    overall_acc = sum(l == p for l, p in zip(all_labels, all_preds)) / len(all_labels)
    print(f"Overall Accuracy:     {overall_acc:.2%}")
    print(f"Directional Accuracy: {dir_acc:.2%}")

    return {
        "overall_accuracy": overall_acc,
        "directional_accuracy": dir_acc,
        "predictions": all_preds,
        "labels": all_labels,
    }


def main():
    parser = argparse.ArgumentParser(description="Evaluate LSTM model")
    parser.add_argument("--config", default="config/default.yaml")
    parser.add_argument("--model", default=None, help="Path to model file")

    args = parser.parse_args()
    evaluate(args.config, args.model)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add lstm_trainer/src/evaluate.py
git commit -m "feat(lstm): add evaluation script"
```

---

## Task 8: Create Dev Mode Script

**Files:**
- Create: `lstm_trainer/src/dev_mode.py`

**Step 1: Create dev_mode.py**

```python
#!/usr/bin/env python3
# lstm_trainer/src/dev_mode.py
"""Quick validation on CPU with recent data."""

import argparse
from pathlib import Path

import pandas as pd
import torch
import torch.nn as nn
from torch.utils.data import DataLoader, random_split
from tqdm import tqdm

from dataset import TrendDataset
from model import TrendLSTM


def dev_train(data_path: str, days: int = 30):
    """
    Fast training on recent month for logic validation.

    Args:
        data_path: Path to h4_candles.parquet
        days: Number of days of data to use
    """
    print(f"Loading data from {data_path}...")
    df = pd.read_parquet(data_path)

    # Use only recent data
    samples = days * 6  # 6 H4 candles per day
    recent = df.tail(samples + 70).copy()  # Extra for seq_len + buffer
    print(f"Using {len(recent)} candles ({days} days)")

    # Create dataset with smaller seq_len for speed
    dataset = TrendDataset(recent, seq_len=30, threshold=0.015)
    print(f"Dataset size: {len(dataset)}")

    # Split 80/20
    train_size = int(0.8 * len(dataset))
    val_size = len(dataset) - train_size
    train_set, val_set = random_split(dataset, [train_size, val_size])

    train_loader = DataLoader(train_set, batch_size=32, shuffle=True)
    val_loader = DataLoader(val_set, batch_size=32, shuffle=False)

    # Smaller model for CPU speed
    model = TrendLSTM(
        input_size=5,
        hidden_size=32,
        num_layers=1,
        dropout=0.1,
        num_classes=3,
    )

    print(f"Model parameters: {sum(p.numel() for p in model.parameters()):,}")

    criterion = nn.CrossEntropyLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=0.001)

    # Quick training
    print("\nTraining (10 epochs)...")
    for epoch in range(10):
        model.train()
        train_loss = 0.0
        for x, y in train_loader:
            optimizer.zero_grad()
            logits = model(x)
            loss = criterion(logits, y)
            loss.backward()
            optimizer.step()
            train_loss += loss.item()

        # Validate
        model.eval()
        correct = 0
        total = 0
        with torch.no_grad():
            for x, y in val_loader:
                preds = model(x).argmax(dim=1)
                correct += (preds == y).sum().item()
                total += y.size(0)

        val_acc = correct / total if total > 0 else 0
        print(f"Epoch {epoch+1:2d} | Train Loss: {train_loss/len(train_loader):.4f} | Val Acc: {val_acc:.2%}")

    print("\n" + "=" * 50)
    print("Pipeline validated - ready for full GPU training!")
    print("=" * 50)


def main():
    parser = argparse.ArgumentParser(description="Quick CPU validation")
    parser.add_argument(
        "--data",
        default="data/processed/h4_candles.parquet",
        help="Path to data file",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=30,
        help="Days of recent data to use",
    )

    args = parser.parse_args()
    dev_train(args.data, args.days)


if __name__ == "__main__":
    main()
```

**Step 2: Commit**

```bash
git add lstm_trainer/src/dev_mode.py
git commit -m "feat(lstm): add dev mode for CPU validation"
```

---

## Task 9: Create Docker Setup

**Files:**
- Create: `lstm_trainer/Dockerfile`
- Create: `lstm_trainer/docker-compose.yml`

**Step 1: Create Dockerfile**

```dockerfile
# lstm_trainer/Dockerfile
FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source code
COPY src/ src/
COPY config/ config/

# Default command
CMD ["python", "src/train.py"]
```

**Step 2: Create docker-compose.yml**

```yaml
# lstm_trainer/docker-compose.yml
version: '3.8'

services:
  trainer:
    build: .
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
    volumes:
      - ./data:/app/data
      - ./models:/app/models
      - ./config:/app/config
    command: python src/train.py --config config/default.yaml

  evaluate:
    build: .
    runtime: nvidia
    environment:
      - NVIDIA_VISIBLE_DEVICES=all
    volumes:
      - ./data:/app/data
      - ./models:/app/models
      - ./config:/app/config
    command: python src/evaluate.py --config config/default.yaml

  notebook:
    build: .
    runtime: nvidia
    ports:
      - "8888:8888"
    volumes:
      - ./:/app
    command: jupyter notebook --ip=0.0.0.0 --port=8888 --allow-root --no-browser
```

**Step 3: Commit**

```bash
git add lstm_trainer/Dockerfile lstm_trainer/docker-compose.yml
git commit -m "feat(lstm): add Docker setup for GPU training"
```

---

## Task 10: Create Production Inference Class

**Files:**
- Create: `trading/strategy/lstm_trend.py`
- Create: `tests/trading/test_lstm_trend.py`

**Step 1: Write the test**

```python
# tests/trading/test_lstm_trend.py
"""Tests for LSTM trend predictor."""

import numpy as np
import pandas as pd
import pytest
import torch


def test_predictor_returns_valid_output():
    """Predictor should return trend and confidence."""
    # Skip if model doesn't exist
    from pathlib import Path
    model_path = Path("models/trading_lstm.pth")
    if not model_path.exists():
        pytest.skip("Model file not found")

    from trading.strategy.lstm_trend import LSTMTrendPredictor

    predictor = LSTMTrendPredictor()

    # Create dummy H4 data
    df = pd.DataFrame({
        "open": np.random.randn(100).cumsum() + 50000,
        "high": np.random.randn(100).cumsum() + 50100,
        "low": np.random.randn(100).cumsum() + 49900,
        "close": np.random.randn(100).cumsum() + 50000,
        "volume": np.abs(np.random.randn(100)) * 1000,
    })

    result = predictor.predict(df)

    assert "trend" in result
    assert "confidence" in result
    assert result["trend"] in ["UP", "DOWN", "SIDEWAYS"]
    assert 0.0 <= result["confidence"] <= 1.0


def test_predictor_handles_insufficient_data():
    """Predictor should handle insufficient data gracefully."""
    from trading.strategy.lstm_trend import LSTMTrendPredictor

    predictor = LSTMTrendPredictor.__new__(LSTMTrendPredictor)
    predictor.seq_len = 60
    predictor.model = None  # Skip model loading

    df = pd.DataFrame({
        "close": [100] * 30,  # Less than seq_len
    })

    # Should return default without error
    result = predictor._handle_insufficient_data(df)
    assert result["trend"] == "SIDEWAYS"
    assert result["confidence"] == 0.0
```

**Step 2: Create lstm_trend.py**

```python
# trading/strategy/lstm_trend.py
"""LSTM-based trend prediction for production inference."""

from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
import torch
import torch.nn as nn


class TrendLSTM(nn.Module):
    """LSTM classifier (must match training architecture)."""

    def __init__(
        self,
        input_size: int = 5,
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
        num_classes: int = 3,
    ):
        super().__init__()

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]
        return self.fc(last_hidden)


class LSTMTrendPredictor:
    """CPU-only inference for production trading."""

    LABELS = {0: "UP", 1: "DOWN", 2: "SIDEWAYS"}

    def __init__(
        self,
        model_path: str = "models/trading_lstm.pth",
        seq_len: int = 60,
    ):
        """
        Initialize predictor.

        Args:
            model_path: Path to trained model file
            seq_len: Sequence length (must match training)
        """
        self.seq_len = seq_len
        self.device = torch.device("cpu")

        # Load model
        self.model = TrendLSTM()

        model_file = Path(model_path)
        if model_file.exists():
            self.model.load_state_dict(
                torch.load(model_path, map_location="cpu", weights_only=True)
            )
            self.model.eval()
            self._model_loaded = True
        else:
            self._model_loaded = False

    def predict(self, df: pd.DataFrame) -> dict:
        """
        Predict trend for next period.

        Args:
            df: DataFrame with at least seq_len rows
                Required columns: open, high, low, close, volume

        Returns:
            {"trend": "UP"|"DOWN"|"SIDEWAYS", "confidence": 0.0-1.0}
        """
        if len(df) < self.seq_len:
            return self._handle_insufficient_data(df)

        if not self._model_loaded:
            return {"trend": "SIDEWAYS", "confidence": 0.0, "error": "model_not_loaded"}

        # Extract last seq_len candles
        window = df.tail(self.seq_len)[["open", "high", "low", "close", "volume"]]
        x = self._normalize(window.values)
        x = torch.tensor(x, dtype=torch.float32).unsqueeze(0)  # (1, seq, 5)

        # Inference
        with torch.no_grad():
            logits = self.model(x)
            probs = torch.softmax(logits, dim=1)
            pred_class = torch.argmax(probs, dim=1).item()
            confidence = probs[0, pred_class].item()

        return {
            "trend": self.LABELS[pred_class],
            "confidence": round(confidence, 4),
        }

    def _normalize(self, window: np.ndarray) -> np.ndarray:
        """Normalize OHLCV (must match training normalization)."""
        base_close = window[0, 3]
        base_volume = window[:, 4].mean() + 1e-8

        normalized = window.copy().astype(np.float32)
        normalized[:, :4] = (window[:, :4] - base_close) / (base_close + 1e-8)
        normalized[:, 4] = window[:, 4] / base_volume

        return normalized

    def _handle_insufficient_data(self, df: pd.DataFrame) -> dict:
        """Handle case when not enough data."""
        return {
            "trend": "SIDEWAYS",
            "confidence": 0.0,
            "error": f"insufficient_data: got {len(df)}, need {self.seq_len}",
        }
```

**Step 3: Commit**

```bash
git add trading/strategy/lstm_trend.py tests/trading/test_lstm_trend.py
git commit -m "feat(lstm): add production inference class"
```

---

## Task 11: Final Integration

**Step 1: Update README in lstm_trainer**

Add complete usage instructions to `lstm_trainer/README.md`.

**Step 2: Create models directory placeholder**

```bash
mkdir -p models
touch models/.gitkeep
```

**Step 3: Final commit and push**

```bash
git add -A
git commit -m "feat(lstm): complete LSTM trend prediction package"
git push -u origin feature/lstm-strategy
```

---

## Workflow Summary

```
LOCAL DEVELOPMENT
─────────────────
1. cd lstm_trainer
2. python src/export_data.py --db-path ../data/upbit_bitcoin.db
3. python src/dev_mode.py (2-3 min CPU validation)

GPU TRAINING
────────────
4. scp -r lstm_trainer/ gpu-server:~/
5. ssh gpu-server
6. cd lstm_trainer && docker compose run trainer (30-60 min)
7. docker compose run evaluate

PRODUCTION
──────────
8. scp gpu-server:~/lstm_trainer/models/trading_lstm.pth models/
9. Use LSTMTrendPredictor in trading engine
```
