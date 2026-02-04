# MLP Model Improvement Design

**Date:** 2026-02-04
**Status:** Approved
**Target:** BTC + ETH models
**Goal:** Direction Accuracy 50% → 55%+

## 1. Background

### Current State
| Model | Classification Acc | Direction Acc | RMSE |
|-------|-------------------|---------------|------|
| BTC | 61.89% | 47.09% | 1.95% |
| ETH | 51.43% | 48.92% | 2.60% |
| SOL | 22.03% | 49.65% | 2.70% |

**Problem:** Direction Accuracy ~50% = random level. Cannot cover trading fees (0.2%+).

### Key Discovery
Multi-asset training infrastructure exists but is unused:
- `data/multi_asset_4h/train_4h.parquet`: 207 coins, 996,954 samples
- `data/multi_asset_4h/validation_4h.parquet`: BTC/ETH 31,684 samples
- `mlp_trainer/src/dataset_builder.py`: Paper methodology implemented

**Current models trained on single-coin data only** → overfitting risk.

## 2. Improvement Strategy

### Phase 0: Multi-asset Training (Foundation)
Train on 207 coins, validate on BTC/ETH (paper methodology).

```bash
# Build dataset
python mlp_trainer/build_dataset.py \
    --input data/multi_asset_4h/train_4h.parquet \
    --validation data/multi_asset_4h/validation_4h.parquet \
    --bwin 5 --fwin 2 \
    --output data/mlp_datasets

# Train
python mlp_trainer/train.py \
    --dataset data/mlp_datasets/mlp_dataset_bwin5_fwin2.npz \
    --output models/mlp_direction/multiasset_v1
```

**Expected:** Direction Accuracy 47% → 50-52%

### Phase 1: Focal Loss
Replace CrossEntropyLoss with Focal Loss to handle class imbalance.

**New file:** `mlp_trainer/src/focal_loss.py`
```python
class FocalLoss(nn.Module):
    """
    FL(p_t) = -α_t * (1 - p_t)^γ * log(p_t)

    - gamma: 2.0 (focus on hard samples)
    - alpha: [0.25, 0.5, 0.5] (lower weight for Hold)
    """
```

**Modified:** `mlp_trainer/src/mlp_train.py`
- Add `--loss focal` option

**Expected:** +2-3% Direction Accuracy

### Phase 2: Time Series CV
Implement time-aware cross-validation to prevent data leakage.

**New file:** `mlp_trainer/src/time_series_cv.py`
```python
def time_series_cv_split(
    X, y, timestamps,
    n_splits=5,
    min_train_size=0.3,
) -> Iterator[tuple]:
    """Expanding window CV - val always after train in time."""
```

**Modified:**
- `mlp_trainer/src/mlp_train.py`: Add `--cv-folds 5` option
- `core/mlp_labeling.py`: Add `split_time_series_cv()` function

**Expected:** Reliable validation metrics, overfitting detection

### Phase 3: Cross-asset Features
Add market context features.

**New features (8):**
| Feature | Description |
|---------|-------------|
| btc_return_4h | BTC 4-hour return |
| btc_return_24h | BTC 24-hour return |
| btc_volatility | BTC 20-period volatility |
| btc_correlation | Correlation with BTC |
| market_momentum | Top 10 coins avg return |
| market_volatility | Top 10 coins avg volatility |
| volume_ratio | Current / 20-day avg volume |
| dominance_change | BTC dominance change rate |

**Total features:** 36 (existing) + 8 (new) = 44

**Modified:** `trading/indicators/mlp_features.py`
- Add `calculate_cross_asset_features()`
- Add `FEATURE_SET_CROSS = "cross_44"`

**Expected:** +1-2% Direction Accuracy

## 3. Final Evaluation (RMSE)

### Evaluation Pipeline
```python
def evaluate_model_comprehensive(model_path, test_data_path, price_data_path):
    return {
        "classification": {...},      # Accuracy, Precision, Recall
        "direction_accuracy": 0.55,   # Core KPI
        "rmse_probability": 0.42,     # Brier Score style
        "rmse_return": 0.018,         # Return RMSE
        "backtest_summary": {...},
    }
```

### Success Criteria
| Metric | Current (BTC) | Target | Method |
|--------|--------------|--------|--------|
| Direction Accuracy | 47.09% | ≥55% | Out-of-sample (BTC/ETH) |
| Buy Precision | ~33% | ≥50% | Confusion Matrix |
| RMSE (probability) | - | ≤0.45 | Brier Score |
| RMSE (return) | 1.95% | ≤1.5% | Backtest |

## 4. File Changes Summary

| File | Action | Phase |
|------|--------|-------|
| `mlp_trainer/src/focal_loss.py` | Create | 1 |
| `mlp_trainer/src/time_series_cv.py` | Create | 2 |
| `mlp_trainer/src/mlp_train.py` | Modify | 1, 2 |
| `trading/indicators/mlp_features.py` | Modify | 3 |
| `mlp_trainer/src/dataset_builder.py` | Modify | 3 |
| `mlp_trainer/evaluate.py` | Modify | Final |
| `core/mlp_labeling.py` | Modify | 2 |

## 5. Expected Results

| Phase | Direction Accuracy |
|-------|-------------------|
| Current | 47-49% |
| Phase 0 (Multi-asset) | 50-52% |
| Phase 1 (+Focal Loss) | 52-54% |
| Phase 2 (+Time Series CV) | Validation stabilization |
| Phase 3 (+Cross-asset) | 54-56% |

## 6. Execution Commands

### Phase 0: Multi-asset Training
```bash
# 1. Build multi-asset dataset
python mlp_trainer/build_dataset.py \
    --input data/multi_asset_4h/train_4h.parquet \
    --validation data/multi_asset_4h/validation_4h.parquet \
    --bwin 5 --fwin 2

# 2. Train baseline model
python mlp_trainer/train.py \
    --dataset data/mlp_datasets/mlp_dataset_bwin5_fwin2.npz \
    --output models/mlp_direction/multiasset_v1 \
    --epochs 100 --patience 10

# 3. Evaluate on BTC/ETH
python mlp_trainer/evaluate.py \
    --model models/mlp_direction/multiasset_v1/model_final.pt \
    --validation-data data/mlp_datasets/validation_BTCUSDT_bwin5_fwin2.npz
```

### Phase 1-3: Incremental Improvements
```bash
# Phase 1: Focal Loss
python mlp_trainer/train.py \
    --dataset data/mlp_datasets/mlp_dataset_bwin5_fwin2.npz \
    --output models/mlp_direction/multiasset_focal_v1 \
    --loss focal --focal-gamma 2.0

# Phase 2: Time Series CV
python mlp_trainer/train.py \
    --dataset data/mlp_datasets/mlp_dataset_bwin5_fwin2.npz \
    --cv-folds 5 \
    --loss focal

# Phase 3: Cross-asset Features
python mlp_trainer/build_dataset.py \
    --input data/multi_asset_4h/train_4h.parquet \
    --feature-set cross_44 \
    --bwin 5 --fwin 2

python mlp_trainer/train.py \
    --dataset data/mlp_datasets/mlp_dataset_cross44_bwin5_fwin2.npz \
    --loss focal --cv-folds 5
```

### Final Evaluation
```bash
python mlp_trainer/evaluate.py \
    --model models/mlp_direction/multiasset_final/model_final.pt \
    --validation-data data/mlp_datasets/validation_BTCUSDT_bwin5_fwin2.npz \
    --price-data data/binance_bitcoin.db \
    --comprehensive
```
