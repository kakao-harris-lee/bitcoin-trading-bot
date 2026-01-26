# Hybrid LSTM + RandomForest Prediction Model Design

**Date:** 2026-01-26
**Status:** Approved
**Author:** Claude

## Overview

2-layer Stacked LSTM과 RandomForest를 결합한 하이브리드 예측 모델. LSTM이 시계열 패턴에서 종가 변화율을 예측하고, RF가 LSTM 예측의 노이즈를 필터링하여 신뢰도 점수를 제공합니다.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    Hybrid Prediction Pipeline                     │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐                                               │
│  │  Scaled Data │ ← *_scaled, *_scaled_rolling (22 features)   │
│  └──────┬───────┘                                               │
│         │                                                        │
│         ▼                                                        │
│  ┌──────────────────────────────────────┐                       │
│  │  Stage 1: Stacked LSTM (PyTorch)     │                       │
│  │  ─────────────────────────────────   │                       │
│  │  Input: (batch, seq_len=60, 22)      │                       │
│  │  LSTM Layer 1: hidden=64             │                       │
│  │  LSTM Layer 2: hidden=64             │                       │
│  │  Output: predicted_close_delta       │                       │
│  │  + hidden_state (for RF)             │                       │
│  └──────────────┬───────────────────────┘                       │
│                 │                                                │
│         ┌───────┴───────┐                                       │
│         │               │                                        │
│         ▼               ▼                                        │
│  [lstm_pred]    [hidden_state_64]                               │
│         │               │                                        │
│         └───────┬───────┘                                       │
│                 ▼                                                │
│  ┌──────────────────────────────────────┐                       │
│  │  Stage 2: RandomForest (sklearn)     │                       │
│  │  ─────────────────────────────────   │                       │
│  │  Input: [lstm_pred, hidden_64, mfi,  │                       │
│  │          adx, regime, volatility]    │                       │
│  │  Output: confidence_score (0-1)      │                       │
│  │         + filtered_signal            │                       │
│  └──────────────────────────────────────┘                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

## Stage 1: HybridLSTM

### Model Architecture

```python
class HybridLSTM(nn.Module):
    """2-Layer Stacked LSTM for close price prediction with online learning."""

    def __init__(
        self,
        input_size: int = 22,      # scaled columns count
        hidden_size: int = 64,
        num_layers: int = 2,
        dropout: float = 0.2,
    ):
        super().__init__()

        # Stacked LSTM (2 layers)
        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        # Price prediction head (regression)
        self.price_head = nn.Linear(hidden_size, 1)

        # Direction classification head (auxiliary task)
        self.direction_head = nn.Linear(hidden_size, 3)  # UP/DOWN/SIDEWAYS

    def forward(self, x: torch.Tensor) -> dict:
        """
        Args:
            x: (batch, seq_len=60, features=22)

        Returns:
            dict with 'price_delta', 'direction_logits', 'hidden_state'
        """
        lstm_out, (h_n, c_n) = self.lstm(x)
        last_hidden = lstm_out[:, -1, :]  # (batch, 64)

        return {
            'price_delta': self.price_head(last_hidden).squeeze(-1),
            'direction_logits': self.direction_head(last_hidden),
            'hidden_state': last_hidden,  # For RF Stage 2
        }
```

### Input Features (22 columns)

스케일된 컬럼 전체 사용:
- `open_scaled`, `open_scaled_rolling`
- `high_scaled`, `high_scaled_rolling`
- `low_scaled`, `low_scaled_rolling`
- `close_scaled`, `close_scaled_rolling`
- `volume_scaled`, `volume_scaled_rolling`
- `prev_day_high_scaled`, `prev_day_high_scaled_rolling`
- `prev_day_low_scaled`, `prev_day_low_scaled_rolling`
- `prev_day_range_scaled`, `prev_day_range_scaled_rolling`
- `target_price_scaled`, `target_price_scaled_rolling`
- (기타 기술적 지표 스케일 컬럼)

### SGD Optimizer (Online Learning)

```python
optimizer = torch.optim.SGD(
    model.parameters(),
    lr=0.01,           # 높은 lr로 빠른 적응
    momentum=0.9,      # 노이즈 감소
    weight_decay=1e-4, # 과적합 방지
)
```

## Stage 2: NoiseFilterRF

### Model Design

```python
class NoiseFilterRF:
    """RandomForest that filters LSTM predictions based on market context."""

    def __init__(
        self,
        n_estimators: int = 100,
        max_depth: int = 10,
        min_samples_leaf: int = 20,
    ):
        self.rf = RandomForestRegressor(
            n_estimators=n_estimators,
            max_depth=max_depth,
            min_samples_leaf=min_samples_leaf,
            n_jobs=-1,
            random_state=42,
        )
        self.fitted = False

    def build_features(
        self,
        lstm_pred: float,
        hidden_state: np.ndarray,  # 64 features
        market_context: dict,
    ) -> np.ndarray:
        """RF 입력 피처 구성 (총 71개)."""
        features = [
            lstm_pred,                        # LSTM 예측
            abs(lstm_pred),                   # 예측 크기
            market_context['mfi'],
            market_context['adx'],
            market_context['volatility'],
            market_context['regime_encoded'],
            market_context['breakout_signal'],
        ]
        features.extend(hidden_state.tolist())
        return np.array(features)

    def predict_confidence(
        self,
        lstm_pred: float,
        hidden_state: np.ndarray,
        market_context: dict,
    ) -> tuple[float, float]:
        """
        Returns:
            (filtered_prediction, confidence_score)
        """
        if not self.fitted:
            return lstm_pred, 0.5

        features = self.build_features(lstm_pred, hidden_state, market_context)
        predicted_error = self.rf.predict(features.reshape(1, -1))[0]
        confidence = max(0, 1 - predicted_error)
        filtered_pred = lstm_pred * confidence

        return filtered_pred, confidence
```

### RF Training Data

```
X: [lstm_pred, abs(lstm_pred), mfi, adx, volatility, regime, breakout, hidden_64]
y: abs(lstm_pred - actual_close_delta)  # LSTM 예측 오차
```

RF는 "LSTM이 언제 틀리는지"를 학습하여 노이즈 필터링 수행.

## Online Learning

### Update 주기

- **Batch size**: 32 캔들
- **Update 빈도**: 32개 캔들마다 1회 SGD update
- **60분 캔들 기준**: 약 32시간마다 1회

### OnlineTrainer

```python
class OnlineTrainer:
    """Background service for online learning."""

    def __init__(self, predictor: HybridPredictor, batch_size: int = 32):
        self.predictor = predictor
        self.batch_size = batch_size
        self.buffer = []

    def add_experience(self, x: torch.Tensor, actual_delta: float):
        self.buffer.append((x, actual_delta))

        if len(self.buffer) >= self.batch_size:
            self._train_batch()

    def _train_batch(self):
        batch_x = torch.stack([x for x, _ in self.buffer])
        batch_y = torch.tensor([y for _, y in self.buffer])

        self.predictor.lstm.train()
        self.predictor.optimizer.zero_grad()

        output = self.predictor.lstm(batch_x)
        loss = F.mse_loss(output['price_delta'], batch_y)
        loss.backward()
        self.predictor.optimizer.step()

        self.predictor.lstm.eval()
        self.buffer.clear()
```

## File Structure

```
lstm_trainer/
├── src/
│   ├── model.py              # 기존 TrendLSTM
│   ├── price_model.py        # 기존 PriceLSTM
│   ├── hybrid_model.py       # 🆕 HybridLSTM
│   ├── noise_filter.py       # 🆕 NoiseFilterRF
│   ├── hybrid_predictor.py   # 🆕 통합 HybridPredictor
│   ├── hybrid_train.py       # 🆕 초기 학습 스크립트
│   └── online_trainer.py     # 🆕 Online learning 서비스
│
├── models/
│   ├── hybrid_lstm.pth       # 학습된 LSTM
│   └── noise_filter_rf.pkl   # 학습된 RF
│
└── config/
    └── hybrid.yaml           # 하이퍼파라미터

trading/
└── strategy/
    └── hybrid_lstm.py        # 🆕 프로덕션 추론 클래스
```

## Configuration

```yaml
# config/hybrid.yaml
model:
  input_size: 22
  hidden_size: 64
  num_layers: 2
  dropout: 0.2
  seq_len: 60

rf:
  n_estimators: 100
  max_depth: 10
  min_samples_leaf: 20

training:
  batch_size: 64
  learning_rate: 0.001
  weight_decay: 0.0001
  max_epochs: 100
  early_stopping_patience: 10

online:
  batch_size: 32
  sgd_lr: 0.01
  sgd_momentum: 0.9

inference:
  confidence_threshold: 0.6
  prediction_threshold: 0.01  # 1% for buy/sell signal
```

## Integration with Trading System

```python
# trading/strategy/hybrid_lstm.py
class HybridLSTMStrategy:
    """Integration with existing trading system."""

    def __init__(self, config: dict):
        self.predictor = HybridPredictor(
            model_path="models/hybrid_lstm.pth",
            rf_path="models/noise_filter_rf.pkl",
        )
        self.online_trainer = OnlineTrainer(self.predictor, batch_size=32)

    def should_enter(self, df: pd.DataFrame, market_context: dict) -> tuple[bool, str]:
        """Check if entry conditions met."""
        result = self.predictor.predict(df, market_context)

        if result['confidence'] < 0.6:
            return False, f"Low confidence: {result['confidence']:.2f}"

        if result['signal'] == "BUY":
            return True, f"Hybrid BUY (pred={result['prediction']:.3f}, conf={result['confidence']:.2f})"

        return False, f"No signal: {result['signal']}"

    def update(self, x: torch.Tensor, actual_delta: float):
        """Online learning update."""
        self.online_trainer.add_experience(x, actual_delta)
```

## Success Criteria

| Metric | Minimum | Target |
|--------|---------|--------|
| Direction Accuracy | >55% | >60% |
| Confidence Calibration | >0.7 correlation | >0.8 |
| Inference Time (CPU) | <10ms | <5ms |
| Online Update Time | <100ms | <50ms |

## Dependencies

```
torch>=2.0.0
scikit-learn>=1.3.0
pandas>=2.0.0
numpy>=1.24.0
joblib>=1.3.0
```

## Implementation Order

1. `hybrid_model.py` - HybridLSTM 클래스
2. `noise_filter.py` - NoiseFilterRF 클래스
3. `hybrid_predictor.py` - 통합 HybridPredictor
4. `hybrid_train.py` - 초기 학습 스크립트
5. `online_trainer.py` - Online learning 서비스
6. `trading/strategy/hybrid_lstm.py` - 프로덕션 통합
7. Tests
