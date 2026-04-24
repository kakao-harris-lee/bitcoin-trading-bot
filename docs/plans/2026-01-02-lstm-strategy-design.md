# LSTM Trend Prediction Strategy Design

> Archived note (2026-04-24): this document was written for an older architecture that included removed futures, short, hedge, or multi-exchange paths. The active runtime is Binance spot-only, so use this file only as historical reference.


> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build an LSTM model for H4 trend prediction (UP/DOWN/SIDEWAYS) to filter trading signals.

**Architecture:** PyTorch LSTM classifier trained on GPU server, deployed for CPU-only inference in production. Separate training package with Docker Compose for portability.

**Tech Stack:** PyTorch, Pandas, PyArrow, Docker Compose, CUDA

---

## 1. Project Structure

```
lstm_trainer/                    # Separate package (outside main trading bot)
├── docker-compose.yml           # GPU training environment
├── Dockerfile                   # PyTorch + CUDA image
├── requirements.txt             # torch, pandas, pyarrow
├── README.md
│
├── config/
│   └── default.yaml             # Hyperparameters
│
├── data/                        # Data staging
│   ├── raw/                     # Exported from main bot
│   └── processed/               # Training-ready parquet
│
├── src/
│   ├── export_data.py           # Export H4 data from SQLite → Parquet
│   ├── dataset.py               # PyTorch Dataset class
│   ├── model.py                 # LSTM architecture
│   ├── train.py                 # Training loop
│   ├── dev_mode.py              # Quick CPU validation
│   ├── evaluate.py              # Metrics & visualization
│   └── config.py                # Config loader
│
├── models/                      # Saved models
│   └── trading_lstm.pth         # Final model for production
│
└── notebooks/                   # Development/debugging
    └── quick_validation.ipynb
```

---

## 2. Model Specification

### LSTM Architecture

```python
class TrendLSTM(nn.Module):
    def __init__(
        self,
        input_size=5,        # OHLCV
        hidden_size=64,      # LSTM hidden units
        num_layers=2,        # Stacked LSTM layers
        dropout=0.2,
        num_classes=3        # UP/DOWN/SIDEWAYS
    ):
        super().__init__()
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout
        )
        self.fc = nn.Sequential(
            nn.Linear(hidden_size, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, num_classes)
        )

    def forward(self, x):  # x: (batch, seq_len=60, features=5)
        lstm_out, _ = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]  # Take last timestep
        return self.fc(last_hidden)       # (batch, 3)
```

### Design Decisions

| Parameter | Value | Rationale |
|-----------|-------|-----------|
| Input size | 5 (OHLCV) | Price-only, LSTM learns patterns implicitly |
| Sequence length | 60 (10 days of H4) | Captures medium-term trends |
| Hidden size | 64 | Small enough for CPU inference (~50KB) |
| Layers | 2 | Balance between capacity and overfitting |
| Dropout | 0.2 | Regularization |

---

## 3. Data Pipeline

### Source Data

- **Database:** `data/upbit_bitcoin.db`
- **Table:** `bitcoin_minute240` (H4 candles)
- **Range:** 2018-12 to 2025-12 (~15,000 samples)
- **Columns:** timestamp, open, high, low, close, volume

### Label Definition

```python
def make_label(current_close, next_close, threshold=0.015):
    """3-class label based on ±1.5% threshold"""
    pct_change = (next_close - current_close) / current_close
    if pct_change > threshold:
        return 0  # UP
    elif pct_change < -threshold:
        return 1  # DOWN
    else:
        return 2  # SIDEWAYS
```

Expected distribution: UP ~25%, DOWN ~25%, SIDEWAYS ~50%

### Normalization Strategy

Per-window normalization (each 60-period window normalized independently):

```python
def normalize_window(window):
    """Normalize OHLCV relative to first candle's close"""
    base_close = window[0, 3]  # First candle's close
    base_volume = window[:, 4].mean()  # Mean volume for scaling

    normalized = window.copy()
    normalized[:, :4] = (window[:, :4] - base_close) / base_close  # Price % change
    normalized[:, 4] = window[:, 4] / base_volume  # Volume ratio
    return normalized
```

---

## 4. Training Configuration

### Data Splits (Chronological)

| Split | Period | Samples | Purpose |
|-------|--------|---------|---------|
| Train | 2018-12 to 2023-12 | ~11,000 | Model training |
| Validation | 2024-01 to 2024-06 | ~1,100 | Hyperparameter tuning |
| Test | 2024-07 to 2025-12 | ~2,700 | Final evaluation |

### Training Parameters

```yaml
# config/default.yaml
model:
  input_size: 5
  hidden_size: 64
  num_layers: 2
  dropout: 0.2
  num_classes: 3

training:
  batch_size: 64
  learning_rate: 0.001
  weight_decay: 0.0001
  max_epochs: 100
  early_stopping_patience: 10

data:
  seq_len: 60
  threshold: 0.015  # ±1.5%
```

### Training Loop

- Optimizer: AdamW with weight decay
- Scheduler: ReduceLROnPlateau (patience=5)
- Loss: CrossEntropyLoss with class weights
- Early stopping: patience=10 epochs

---

## 5. Docker Setup

### docker-compose.yml

```yaml
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
      - ./src:/app/src
    command: python src/train.py --config config/default.yaml

  notebook:
    build: .
    runtime: nvidia
    ports:
      - "8888:8888"
    volumes:
      - ./:/app
    command: jupyter notebook --ip=0.0.0.0 --allow-root
```

### Dockerfile

```dockerfile
FROM pytorch/pytorch:2.1.0-cuda11.8-cudnn8-runtime

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
COPY config/ config/

CMD ["python", "src/train.py"]
```

### requirements.txt

```
torch>=2.1.0
pandas>=2.0.0
pyarrow>=14.0.0
numpy>=1.24.0
scikit-learn>=1.3.0
tqdm>=4.65.0
pyyaml>=6.0
jupyter>=1.0.0
```

---

## 6. Production Integration

### Inference Class

```python
# trading/strategy/lstm_trend.py
class LSTMTrendPredictor:
    """CPU-only inference for production"""

    LABELS = {0: "UP", 1: "DOWN", 2: "SIDEWAYS"}

    def __init__(self, model_path: str = "models/trading_lstm.pth"):
        self.device = torch.device("cpu")
        self.model = TrendLSTM()
        self.model.load_state_dict(torch.load(model_path, map_location="cpu"))
        self.model.eval()
        self.seq_len = 60

    def predict(self, df: pd.DataFrame) -> dict:
        """
        Args:
            df: Last 60+ H4 candles with OHLCV columns

        Returns:
            {"trend": "UP"|"DOWN"|"SIDEWAYS", "confidence": 0.0-1.0}
        """
        if len(df) < self.seq_len:
            return {"trend": "SIDEWAYS", "confidence": 0.0}

        window = df.tail(self.seq_len)[["open", "high", "low", "close", "volume"]]
        x = self._normalize(window.values)
        x = torch.tensor(x, dtype=torch.float32).unsqueeze(0)

        with torch.no_grad():
            logits = self.model(x)
            probs = torch.softmax(logits, dim=1)
            pred_class = torch.argmax(probs, dim=1).item()
            confidence = probs[0, pred_class].item()

        return {"trend": self.LABELS[pred_class], "confidence": confidence}
```

### Strategy Integration

```python
# Use as regime filter with existing strategies
lstm_predictor = LSTMTrendPredictor()

def should_trade(df_h4):
    prediction = lstm_predictor.predict(df_h4)

    if prediction["confidence"] < 0.6:
        return False, "LSTM uncertain"

    if prediction["trend"] == "UP":
        return True, "LSTM bullish"
    elif prediction["trend"] == "DOWN":
        return False, "LSTM bearish"
    else:
        return False, "LSTM sideways"
```

---

## 7. Development Workflow

### Local Development (CPU)

```python
# src/dev_mode.py - Quick validation with recent month
def dev_train(days=30):
    df = pd.read_parquet("data/processed/h4_candles.parquet")
    recent = df.tail(days * 6)  # 180 samples

    model = TrendLSTM(hidden_size=32, num_layers=1)  # Smaller for speed

    for epoch in range(10):
        train_epoch(model, train_set)
        val_loss, val_acc = validate(model, val_set)
        print(f"Epoch {epoch}: val_acc={val_acc:.2%}")

    print("Pipeline validated - ready for GPU training")
```

### Complete Workflow

```
┌─────────────────────────────────────────────────────────────────┐
│  LOCAL (MacBook CPU)                                            │
├─────────────────────────────────────────────────────────────────┤
│  1. Export data:     python src/export_data.py                  │
│  2. Quick test:      python src/dev_mode.py (2-3 min)           │
│  3. Upload:          scp -r lstm_trainer/ server:~/             │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  GPU SERVER                                                     │
├─────────────────────────────────────────────────────────────────┤
│  4. Train:           docker compose run trainer (30-60 min)     │
│  5. Evaluate:        docker compose run trainer python eval.py  │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  LOCAL → PRODUCTION                                             │
├─────────────────────────────────────────────────────────────────┤
│  6. Download:        scp server:~/lstm_trainer/models/*.pth ./  │
│  7. Deploy:          Copy to trading bot models/ directory      │
│  8. Integrate:       LSTMTrendPredictor in trading engine       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 8. Success Criteria

### Metrics

| Metric | Minimum | Target | Excellent |
|--------|---------|--------|-----------|
| Overall Accuracy | >40% | >50% | >55% |
| Directional Accuracy (UP/DOWN) | >55% | >60% | >65% |
| Confidence Calibration | - | Pred confidence ≈ actual accuracy | - |
| Inference Time (CPU) | <10ms | <5ms | <1ms |

### Rationale

- Random baseline for 3-class is 33%
- >55% directional accuracy provides edge after fees (0.14%)
- Combined with existing strategies as filter, even 55% adds value

### Evaluation Script

```python
def evaluate_model(model, test_loader):
    all_preds, all_labels, all_probs = [], [], []

    with torch.no_grad():
        for x, y in test_loader:
            logits = model(x)
            probs = torch.softmax(logits, dim=1)
            preds = torch.argmax(probs, dim=1)

            all_preds.extend(preds.tolist())
            all_labels.extend(y.tolist())
            all_probs.extend(probs.tolist())

    accuracy = accuracy_score(all_labels, all_preds)
    report = classification_report(all_labels, all_preds,
                                   target_names=["UP", "DOWN", "SIDEWAYS"])

    # Directional accuracy (UP/DOWN only)
    directional_mask = [l != 2 for l in all_labels]
    dir_acc = accuracy_score(
        [l for l, m in zip(all_labels, directional_mask) if m],
        [p for p, m in zip(all_preds, directional_mask) if m]
    )

    return {"accuracy": accuracy, "directional_accuracy": dir_acc, "report": report}
```

---

## 9. Risk Mitigation

| Risk | Mitigation |
|------|------------|
| Overfitting | Dropout, early stopping, weight decay, chronological splits |
| Class imbalance | Class-weighted loss function |
| Price regime shift | Per-window normalization (relative prices) |
| Slow inference | Small model (64 hidden), CPU-optimized |
| Data leakage | Strict chronological train/val/test splits |

---

**Created:** 2026-01-02
**Status:** Design approved, ready for implementation
