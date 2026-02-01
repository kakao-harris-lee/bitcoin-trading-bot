# MLP Direction Strategy Implementation Plan

**Date**: 2026-02-01
**Design Doc**: `2026-02-01-mlp-direction-strategy-design.md`
**Status**: Ready for Implementation

---

## Implementation Summary

논문 기반 MLP 방향 예측 전략을 5개 Phase로 구현합니다.

```
Phase 1 (Foundation) → Phase 2 (Training) → Phase 3 (Strategy) → Phase 4 (Validation) → Phase 5 (Live)
```

---

## Phase 1: Foundation

### Task 1.1: Feature Extraction Module

**파일**: `trading/indicators/mlp_features.py`

```python
# 구현할 함수들:
def calculate_mlp_features(df: pd.DataFrame, bwin: int = 5) -> pd.DataFrame:
    """13개 피처 계산"""
    pass

def extract_single_features(market_data: MarketData, indicators: dict) -> np.ndarray:
    """실시간 단일 바용 피처 추출"""
    pass
```

**피처 목록** (13개):
1. Bollinger %B
2. RSI (normalized)
3. Ultimate Oscillator
4. EMA Cross 1/21
5. EMA Cross 21/50
6. EMA Cross 50/100
7. EMA Cross 1/50
8. Price Z-Score
9. Volume Z-Score
10. Hour of Day (normalized)
11. Day of Week (normalized)
12. Month (normalized)
13. Close % Change

**테스트**: `tests/indicators/test_mlp_features.py`

---

### Task 1.2: Labeling Algorithm

**파일**: `core/mlp_labeling.py`

```python
def compute_labels(
    df: pd.DataFrame,
    bwin: int = 5,
    fwin: int = 2,
    alpha: float = 0.038,
    beta: float = 0.24,
    fee: float = 0.001
) -> pd.Series:
    """
    3-class 라벨링: 0=Hold, 1=Buy, 2=Sell
    """
    pass

def get_label_distribution(labels: pd.Series) -> dict:
    """클래스 분포 확인"""
    pass
```

**테스트**: `tests/core/test_mlp_labeling.py`

---

### Task 1.3: MLP Model Definition

**파일**: `mlp_trainer/src/mlp_model.py`

```python
class MLPDirectionClassifier(nn.Module):
    """
    Architecture: Input(13) → 128 → 64 → 32 → 3 (softmax)
    Activation: LeakyReLU
    Regularization: BatchNorm + Dropout
    """

    def __init__(self, input_dim=13, hidden_dims=[128, 64, 32], num_classes=3, dropout=0.2):
        pass

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        pass

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        """Inference용 softmax 확률"""
        pass

    def save(self, path: str):
        pass

    @classmethod
    def load(cls, path: str) -> 'MLPDirectionClassifier':
        pass
```

**테스트**: `tests/mlp_trainer/test_mlp_model.py`

---

## Phase 2: Training Pipeline

### Task 2.1: Multi-Asset Data Collector

**파일**: `scripts/collectors/multi_asset_collector.py`

```python
class MultiAssetCollector:
    """Binance에서 400+ USDT 페어 4H 데이터 수집"""

    async def collect_all_usdt_pairs(self, start_date, end_date) -> dict:
        pass

    async def _fetch_klines(self, symbol, start_date, end_date) -> pd.DataFrame:
        pass

    def save_to_parquet(self, datasets: dict, output_path: str):
        pass
```

**실행**:
```bash
python scripts/collectors/multi_asset_collector.py \
    --start 2017-08-17 \
    --end 2024-12-31 \
    --output data/multi_asset_4h.parquet
```

---

### Task 2.2: Dataset Builder

**파일**: `mlp_trainer/src/dataset_builder.py`

```python
class MLPDatasetBuilder:
    def __init__(self, bwin, fwin, alpha, beta):
        pass

    def build_from_multi_asset(self, datasets: dict) -> tuple[np.ndarray, np.ndarray]:
        """전체 데이터셋 구축"""
        pass

    def balance_classes(self, X, y) -> tuple[np.ndarray, np.ndarray]:
        """Random undersampling"""
        pass

    def split_train_val_test(self, X, y, val_ratio=0.15, test_ratio=0.15):
        """Stratified split"""
        pass

    def save_dataset(self, output_path: str):
        pass
```

**실행**:
```bash
python mlp_trainer/build_dataset.py \
    --input data/multi_asset_4h.parquet \
    --bwin 5 --fwin 2 \
    --alpha 0.038 --beta 0.24 \
    --output data/mlp_dataset.npz
```

---

### Task 2.3: Training Script

**파일**: `mlp_trainer/src/mlp_train.py`

```python
class MLPTrainer:
    def __init__(self, model, device='cuda'):
        pass

    def train(self, X, y, epochs=100, batch_size=256, val_split=0.3) -> dict:
        """학습 실행, history 반환"""
        pass

    def evaluate(self, X_test, y_test) -> dict:
        """테스트셋 평가"""
        pass

def main():
    """CLI entry point"""
    pass
```

**실행**:
```bash
python mlp_trainer/train.py \
    --dataset data/mlp_dataset.npz \
    --epochs 100 \
    --batch-size 256 \
    --output models/mlp_direction/btc_5_2.pt
```

**MLflow 로깅**:
- Parameters: bwin, fwin, alpha, beta, hidden_dims, dropout, lr
- Metrics: train_loss, val_loss, val_accuracy, precision, recall, f1
- Artifacts: model checkpoint, confusion matrix, learning curves

---

### Task 2.4: Model Evaluation

**파일**: `mlp_trainer/src/mlp_evaluate.py`

```python
def evaluate_on_btc_eth(model_path: str, data_dir: str) -> dict:
    """
    BTC/ETH 검증 (학습에 포함 안됨)
    Returns: accuracy, precision, recall per class
    """
    pass

def plot_confusion_matrix(y_true, y_pred, save_path: str):
    pass

def shap_feature_importance(model, X_sample, feature_names) -> pd.DataFrame:
    """SHAP 분석으로 피처 중요도 확인"""
    pass
```

---

## Phase 3: Strategy Components

### Task 3.1: Entry Strategy

**파일**: `trading/strategies/components/mlp_direction_entry.py`

```python
@dataclass
class MLPDirectionEntryParams:
    model_path: str = "models/mlp_direction/model.pt"
    confidence_threshold: float = 0.6
    backward_window: int = 5

@entry_strategy(params_class=MLPDirectionEntryParams)
class MLPDirectionEntryStrategy(IEntryStrategy):
    def __init__(self, params: MLPDirectionEntryParams):
        pass

    def check_entry(self, ctx: TradingContext) -> Optional[Signal]:
        """Buy 신호 + 확신도 체크"""
        pass

    def _load_model(self):
        pass

    def _extract_features(self, ctx: TradingContext) -> Optional[np.ndarray]:
        pass
```

---

### Task 3.2: Exit Strategy

**파일**: `trading/strategies/components/mlp_direction_exit.py`

```python
@dataclass
class MLPDirectionExitParams:
    stop_loss_pct: float = 10.0
    take_profit_pct: float = 0.0  # 0 = unlimited
    use_model_exit: bool = True

@exit_strategy(params_class=MLPDirectionExitParams)
class MLPDirectionExitStrategy(IExitStrategy):
    def __init__(self, params: MLPDirectionExitParams, model=None):
        pass

    def check_exit(self, ctx: TradingContext, position: Position) -> Optional[Signal]:
        """Stop Loss + 모델 Sell 신호"""
        pass
```

---

### Task 3.3: Registry & Factory Integration

**파일 수정**: `trading/strategies/components/registry.py`

```python
# 추가
from .mlp_direction_entry import MLPDirectionEntryStrategy
from .mlp_direction_exit import MLPDirectionExitStrategy

STRATEGY_REGISTRY["mlp_direction"] = (MLPDirectionEntryStrategy, MLPDirectionExitStrategy)
```

---

### Task 3.4: IndicatorService Extension

**파일 수정**: `trading/indicators/indicator_service.py`

```python
class IndicatorService:
    def calculate_all(self, df: pd.DataFrame) -> dict:
        """기존 + MLP 피처 계산"""
        base_indicators = self._calculate_base(df)
        mlp_indicators = self._calculate_mlp(df)
        return {**base_indicators, **mlp_indicators}

    def _calculate_mlp(self, df: pd.DataFrame) -> dict:
        from trading.indicators.mlp_features import calculate_mlp_features
        features = calculate_mlp_features(df)
        return features.iloc[-1].to_dict()
```

---

### Task 3.5: Configuration

**파일 수정**: `config/strategies/allocation.json`

```json
{
  "strategies": {
    "mlp_direction_btc": {
      "market": "spot",
      "enabled": true,
      "entry_class": "MLPDirectionEntryStrategy",
      "exit_class": "MLPDirectionExitStrategy",
      "position_pct": 0.1,
      "symbols": ["BTC"],
      "params": {
        "model_path": "models/mlp_direction/btc_5_2.pt",
        "confidence_threshold": 0.6,
        "backward_window": 5,
        "stop_loss_pct": 10.0
      }
    },
    "mlp_direction_eth": {
      "market": "spot",
      "enabled": true,
      "entry_class": "MLPDirectionEntryStrategy",
      "exit_class": "MLPDirectionExitStrategy",
      "position_pct": 0.1,
      "symbols": ["ETH"],
      "params": {
        "model_path": "models/mlp_direction/eth_4_2.pt",
        "confidence_threshold": 0.6,
        "backward_window": 4,
        "stop_loss_pct": 10.0
      }
    }
  }
}
```

---

## Phase 4: Validation

### Task 4.1: Backtest Script

**파일**: `scripts/backtest/backtest_mlp.py`

```python
def run_backtest(
    symbol: str,
    model_path: str,
    start_date: str,
    end_date: str,
    stop_loss_pct: float = 10.0
) -> BacktestResult:
    """
    MLP 전략 백테스트
    - ComponentStrategyAdapter 사용
    - BTC/ETH 6년간 데이터
    """
    pass

def compare_with_baseline(mlp_result, baseline_results: list) -> pd.DataFrame:
    """V35, Hybrid LSTM과 비교"""
    pass
```

**실행**:
```bash
python scripts/backtest/backtest_mlp.py \
    --symbol BTC \
    --model models/mlp_direction/btc_5_2.pt \
    --start 2017-08-17 \
    --end 2024-12-31 \
    --stop-loss 10.0
```

---

### Task 4.2: Forward Test

**파일**: `scripts/backtest/forward_test_mlp.py`

```python
def run_forward_test(
    symbol: str,
    model_path: str,
    start_date: str = "2025-01-01"
) -> BacktestResult:
    """2025년 이후 미래 데이터 테스트"""
    pass
```

---

### Task 4.3: Performance Report

**출력**: `reports/mlp_direction_performance.md`

```markdown
# MLP Direction Strategy Performance Report

## Summary
| Metric | BTC | ETH | V35 (baseline) |
|--------|-----|-----|----------------|
| Total Return | X% | X% | X% |
| Sharpe Ratio | X | X | X |
| Max Drawdown | X% | X% | X% |
| Win Rate | X% | X% | X% |
| Profit Factor | X | X | X |

## Trade Analysis
- Total trades: X
- Avg holding period: X hours
- Best trade: +X%
- Worst trade: -X%

## Equity Curves
[Charts]
```

---

## Phase 5: Live Integration

### Task 5.1: 4H Feed Integration

**파일 수정**: `trading/streams/binance_feed.py`

```python
# 4H 캔들 스트림 추가
class BinanceFeedTask:
    async def subscribe_4h(self, symbols: list):
        """4H 캔들 WebSocket 구독"""
        pass
```

---

### Task 5.2: Paper Trading Test

```bash
# Paper mode에서 MLP 전략 테스트
./bot.sh start --trend=paper

# 로그 확인
./bot.sh logs | grep mlp_direction
```

---

### Task 5.3: Live Deployment

```bash
# Live mode 전환
./bot.sh start --trend=live
```

---

## File Structure

```
bitcoin-trading-bot/
├── trading/
│   ├── indicators/
│   │   └── mlp_features.py          # NEW: 피처 계산
│   └── strategies/
│       └── components/
│           ├── mlp_direction_entry.py  # NEW: Entry
│           └── mlp_direction_exit.py   # NEW: Exit
├── mlp_trainer/                      # NEW: 학습 모듈
│   ├── src/
│   │   ├── mlp_model.py
│   │   ├── mlp_train.py
│   │   ├── mlp_evaluate.py
│   │   └── dataset_builder.py
│   ├── build_dataset.py
│   └── train.py
├── core/
│   └── mlp_labeling.py              # NEW: 라벨링
├── scripts/
│   ├── collectors/
│   │   └── multi_asset_collector.py  # NEW: 데이터 수집
│   └── backtest/
│       ├── backtest_mlp.py          # NEW: 백테스트
│       └── forward_test_mlp.py      # NEW: 포워드 테스트
├── models/
│   └── mlp_direction/               # NEW: 모델 저장소
│       ├── btc_5_2.pt
│       └── eth_4_2.pt
├── data/
│   ├── multi_asset_4h.parquet       # 학습 데이터
│   └── mlp_dataset.npz              # 처리된 데이터셋
└── docs/
    └── plans/
        ├── 2026-02-01-mlp-direction-strategy-design.md
        └── 2026-02-01-mlp-direction-strategy-implementation.md
```

---

## Testing Checklist

### Unit Tests
- [ ] `test_mlp_features.py` - 피처 계산 정확도
- [ ] `test_mlp_labeling.py` - 라벨링 알고리즘 검증
- [ ] `test_mlp_model.py` - 모델 forward/backward pass
- [ ] `test_mlp_entry.py` - Entry 전략 로직
- [ ] `test_mlp_exit.py` - Exit 전략 로직

### Integration Tests
- [ ] `test_mlp_backtest.py` - 전체 백테스트 파이프라인
- [ ] `test_mlp_live.py` - 실시간 신호 생성

---

## Dependencies

```txt
# requirements.txt 추가
torch>=2.0.0
shap>=0.42.0
aiohttp>=3.8.0
pyarrow>=14.0.0  # parquet 지원
```

---

## Success Criteria

| Metric | Target | Validation Method |
|--------|--------|-------------------|
| BTC ROI (6년) | > 30x | Backtest |
| ETH ROI (6년) | > 50x | Backtest |
| Win Rate | > 45% | Backtest |
| Max Drawdown | < 25% | Backtest |
| Forward Test ROI | > 0 | 2025년 데이터 |
| Test Accuracy | > 65% | Hold-out test set |
| Latency | < 100ms | Live inference |

---

## Timeline

| Phase | Duration | Start | End |
|-------|----------|-------|-----|
| Phase 1: Foundation | 3 days | Day 1 | Day 3 |
| Phase 2: Training | 4 days | Day 4 | Day 7 |
| Phase 3: Strategy | 2 days | Day 8 | Day 9 |
| Phase 4: Validation | 2 days | Day 10 | Day 11 |
| Phase 5: Live | 2 days | Day 12 | Day 13 |
| **Total** | **~2 weeks** | | |

---

## Risk Mitigation

| Risk | Impact | Mitigation |
|------|--------|------------|
| 데이터 부족 | 학습 실패 | 최소 100+ 코인 확보 |
| 오버피팅 | 실제 성과 저하 | BTC/ETH를 학습에서 완전 제외 |
| 시장 레짐 변화 | 전략 무효화 | 정기적 재학습 (월 1회) |
| Stop Loss 빈번 | 수익 감소 | Stop Loss % 최적화 (Optuna) |
| 4H 데이터 지연 | 신호 놓침 | 실시간 WebSocket 사용 |
