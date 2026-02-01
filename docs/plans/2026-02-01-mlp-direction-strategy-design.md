# MLP Direction Strategy Design Document

**Date**: 2026-02-01
**Based on**: Parente & Rizzuti (2025) - "Trading strategy for Bitcoin and Ethereum by neural network model"
**Status**: Draft

---

## 1. Executive Summary

기존 V35, Hybrid LSTM 전략의 낮은 성공률을 개선하기 위해, 학술 논문에서 검증된 MLP 기반 방향 예측 전략을 구현합니다.

### 논문 핵심 성과
| 자산 | BWin | FWin | ROI | 거래수 | 승률 |
|------|------|------|-----|--------|------|
| **BTC** | 5 | 2 | 48.23x | 266 | 52% |
| **ETH** | 4 | 2 | 93.06x | 406 | 49% |

- **6년간** 백테스트 + 포워드 테스트 검증
- **Dummy model** 대비 압도적 성과 (Dummy는 항상 손실)
- **Bear market**에서도 자본 보호 (Stop Loss 10%)

### 핵심 혁신
1. **Multi-Asset Training**: 400+ 암호화폐로 훈련 → 일반화 능력 확보
2. **Parametric Labeling**: α/β 임계값으로 3-class 생성 (Buy/Hold/Sell)
3. **Feature Selection**: 캔들스틱 패턴 제외, EMA/RSI/Bollinger 중심
4. **Simple Architecture**: 복잡한 LSTM 대신 간단한 MLP (오버피팅 방지)

---

## 2. Strategy Architecture

### 2.1 High-Level Flow

```
┌─────────────────────────────────────────────────────────────┐
│                    MLP Direction Strategy                    │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  4H OHLCV Data                                               │
│       │                                                      │
│       ▼                                                      │
│  ┌──────────────────┐                                        │
│  │ Feature Extractor │ ─── 13 Features (논문 기반)            │
│  │ - Bollinger %B    │                                       │
│  │ - RSI             │                                       │
│  │ - EMA Crossovers  │                                       │
│  │ - Z-Score         │                                       │
│  │ - Temporal        │                                       │
│  └────────┬─────────┘                                        │
│           │                                                  │
│           ▼                                                  │
│  ┌──────────────────┐     ┌──────────────────┐              │
│  │  MLP Classifier   │────▶│ Prediction       │              │
│  │  128 → 64 → 32    │     │ Buy / Hold / Sell│              │
│  │  Softmax Output   │     └────────┬─────────┘              │
│  └──────────────────┘              │                         │
│                                    ▼                         │
│                         ┌──────────────────┐                │
│                         │ Trading Decision  │                │
│                         │ + 10% Stop Loss   │                │
│                         └──────────────────┘                │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Component Integration

```python
# allocation.json 설정 예시
{
  "strategies": {
    "mlp_direction": {
      "market": "spot",
      "entry_class": "MLPDirectionEntryStrategy",
      "exit_class": "MLPDirectionExitStrategy",
      "enabled": true,
      "timeframe": "4h",
      "backward_window": 5,
      "forward_window": 2,
      "stop_loss_pct": 10.0,
      "model_path": "models/mlp_direction/btc_model.pt",
      "confidence_threshold": 0.6  # Buy 확률 > 60%시 진입
    }
  }
}
```

---

## 3. Feature Engineering

### 3.1 Feature Set (13개 - 논문 기반 최적화)

논문의 SHAP 분석 결과, 캔들스틱 패턴은 **비효과적**이므로 제외합니다.

| 카테고리 | Feature | 계산 방법 | 근거 |
|----------|---------|-----------|------|
| **Momentum** | Bollinger %B | (Close - BB_Lower) / (BB_Upper - BB_Lower) | SHAP #1 |
| **Momentum** | RSI(14) | Standard RSI | SHAP #2 |
| **Momentum** | ULTOSC | Ultimate Oscillator (7/14/28) | 논문 사용 |
| **Trend** | EMA Cross 1/21 | EMA(1) / EMA(21) | SHAP #3 |
| **Trend** | EMA Cross 21/50 | EMA(21) / EMA(50) | SHAP #4 |
| **Trend** | EMA Cross 50/100 | EMA(50) / EMA(100) | Top 10 |
| **Trend** | EMA Cross 1/50 | EMA(1) / EMA(50) | Top 10 |
| **Volatility** | Z-Score | (Close - SMA(30)) / StdDev(30) | Top 10 |
| **Volume** | Volume Z-Score | (Vol - SMA_Vol(30)) / StdDev_Vol(30) | 논문 사용 |
| **Temporal** | Hour of Day | 0-5 (4H bar index) | Top 10 |
| **Temporal** | Day of Week | 0-6 (Monday=0) | Top 10 |
| **Temporal** | Month | 1-12 | Top 10 |
| **Price** | Close % Change | (Close - Prev_Close) / Prev_Close | 논문 사용 |

### 3.2 Feature Calculation Code

```python
# trading/indicators/mlp_features.py

import numpy as np
import pandas as pd
import talib

def calculate_mlp_features(df: pd.DataFrame, bwin: int = 5) -> pd.DataFrame:
    """논문 기반 13개 피처 계산"""
    close = df['close'].values
    high = df['high'].values
    low = df['low'].values
    volume = df['volume'].values

    features = pd.DataFrame(index=df.index)

    # 1. Bollinger %B
    upper, middle, lower = talib.BBANDS(close, timeperiod=20, nbdevup=2, nbdevdn=2)
    features['bollinger_pct_b'] = (close - lower) / (upper - lower + 1e-10)

    # 2. RSI
    features['rsi'] = talib.RSI(close, timeperiod=14) / 100.0  # Normalize to 0-1

    # 3. Ultimate Oscillator
    features['ultosc'] = talib.ULTOSC(high, low, close,
                                       timeperiod1=7, timeperiod2=14, timeperiod3=28) / 100.0

    # 4-7. EMA Crossovers (ratio form)
    ema1 = talib.EMA(close, timeperiod=1)
    ema21 = talib.EMA(close, timeperiod=21)
    ema50 = talib.EMA(close, timeperiod=50)
    ema100 = talib.EMA(close, timeperiod=100)

    features['ema_cross_1_21'] = ema1 / ema21
    features['ema_cross_21_50'] = ema21 / ema50
    features['ema_cross_50_100'] = ema50 / ema100
    features['ema_cross_1_50'] = ema1 / ema50

    # 8. Price Z-Score
    sma30 = talib.SMA(close, timeperiod=30)
    std30 = talib.STDDEV(close, timeperiod=30)
    features['price_zscore'] = (close - sma30) / (std30 + 1e-10)
    features['price_zscore'] = features['price_zscore'].clip(-3, 3) / 3  # Normalize

    # 9. Volume Z-Score
    vol_sma = talib.SMA(volume.astype(float), timeperiod=30)
    vol_std = talib.STDDEV(volume.astype(float), timeperiod=30)
    features['volume_zscore'] = (volume - vol_sma) / (vol_std + 1e-10)
    features['volume_zscore'] = features['volume_zscore'].clip(-3, 3) / 3

    # 10-12. Temporal Features (normalized)
    if 'timestamp' in df.columns:
        ts = pd.to_datetime(df['timestamp'])
        features['hour_of_day'] = (ts.dt.hour // 4) / 5.0  # 0-5 for 4H bars
        features['day_of_week'] = ts.dt.dayofweek / 6.0
        features['month'] = (ts.dt.month - 1) / 11.0
    else:
        features['hour_of_day'] = 0.0
        features['day_of_week'] = 0.0
        features['month'] = 0.0

    # 13. Close % Change
    features['close_pct_change'] = df['close'].pct_change().clip(-0.1, 0.1) / 0.1

    return features.fillna(0.0)
```

---

## 4. Labeling Algorithm

### 4.1 Parametric Labeling (논문 Algorithm 1)

```python
# core/mlp_labeling.py

import numpy as np
import pandas as pd

def compute_labels(
    df: pd.DataFrame,
    bwin: int = 5,
    fwin: int = 2,
    alpha: float = 0.038,  # 최소 수익 임계값 (3.8%)
    beta: float = 0.24,    # 최대 변동성 임계값 (24%)
    fee: float = 0.001     # 거래 수수료 (0.1%)
) -> pd.Series:
    """
    논문의 라벨링 알고리즘 구현

    Returns:
        labels: 0 = Hold, 1 = Buy, 2 = Sell
    """
    close = df['close'].values
    open_price = df['open'].values

    # BWin EMA를 레퍼런스로 사용 (논문 Fig.3)
    ema_bwin = pd.Series(close).ewm(span=bwin, adjust=False).mean().values

    labels = np.zeros(len(df), dtype=int)  # Default: Hold (0)

    # β는 FWin에 따라 10%씩 증가
    adjusted_beta = beta + (fwin - 1) * 0.024

    for t in range(len(df) - fwin):
        # Forward window 끝의 종가
        future_close = close[t + fwin]
        current_open = open_price[t]

        # Return 계산 (수수료 포함)
        ret = ((1 - fee) * future_close - (1 + fee) * current_open) / current_open

        abs_ret = abs(ret)

        if alpha < abs_ret < adjusted_beta:
            if ret > 0:
                labels[t] = 1  # Buy
            else:
                labels[t] = 2  # Sell
        # else: Hold (0) - 너무 작거나 너무 큰 움직임

    return pd.Series(labels, index=df.index)
```

### 4.2 Class Distribution & Balancing

논문에 따르면 Hold가 70%로 과대표현됩니다. Random Undersampling 적용:

```python
from sklearn.utils import resample

def balance_dataset(X: np.ndarray, y: np.ndarray) -> tuple:
    """Random undersampling of majority class (Hold)"""
    df = pd.DataFrame(X)
    df['label'] = y

    # 각 클래스별 분리
    hold = df[df['label'] == 0]
    buy = df[df['label'] == 1]
    sell = df[df['label'] == 2]

    # 소수 클래스 크기로 맞춤
    min_size = min(len(hold), len(buy), len(sell))

    hold_down = resample(hold, replace=False, n_samples=min_size)
    buy_down = resample(buy, replace=False, n_samples=min_size)
    sell_down = resample(sell, replace=False, n_samples=min_size)

    balanced = pd.concat([hold_down, buy_down, sell_down])
    balanced = balanced.sample(frac=1.0)  # Shuffle

    return balanced.drop('label', axis=1).values, balanced['label'].values
```

---

## 5. Model Architecture

### 5.1 MLP Structure (논문 Section 4)

```python
# mlp_trainer/src/mlp_model.py

import torch
import torch.nn as nn

class MLPDirectionClassifier(nn.Module):
    """
    논문 기반 MLP 분류기
    Architecture: 128 → 64 → 32 → 3 (softmax)
    """

    def __init__(
        self,
        input_dim: int = 13,
        hidden_dims: list = [128, 64, 32],
        num_classes: int = 3,
        dropout: float = 0.2
    ):
        super().__init__()

        layers = []
        prev_dim = input_dim

        for hidden_dim in hidden_dims:
            layers.extend([
                nn.Linear(prev_dim, hidden_dim),
                nn.LeakyReLU(negative_slope=0.01),
                nn.BatchNorm1d(hidden_dim),
                nn.Dropout(dropout)
            ])
            prev_dim = hidden_dim

        # Output layer (no activation - CrossEntropyLoss handles softmax)
        layers.append(nn.Linear(prev_dim, num_classes))

        self.network = nn.Sequential(*layers)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.network(x)

    def predict_proba(self, x: torch.Tensor) -> torch.Tensor:
        """Softmax probabilities for inference"""
        with torch.no_grad():
            logits = self.forward(x)
            return torch.softmax(logits, dim=-1)
```

### 5.2 Training Pipeline

```python
# mlp_trainer/src/mlp_train.py

import torch
import torch.nn as nn
from torch.utils.data import DataLoader, TensorDataset
from sklearn.model_selection import train_test_split

class MLPTrainer:
    """MLP 학습 파이프라인"""

    def __init__(
        self,
        model: nn.Module,
        device: str = 'cuda' if torch.cuda.is_available() else 'cpu'
    ):
        self.model = model.to(device)
        self.device = device
        self.criterion = nn.CrossEntropyLoss()
        self.optimizer = torch.optim.Adam(model.parameters(), lr=1e-3)
        self.scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(
            self.optimizer, patience=5, factor=0.5
        )

    def train(
        self,
        X: np.ndarray,
        y: np.ndarray,
        epochs: int = 100,
        batch_size: int = 256,
        validation_split: float = 0.3
    ) -> dict:
        """
        학습 실행
        Returns: history dict with train/val loss and accuracy
        """
        # Train/Val split
        X_train, X_val, y_train, y_val = train_test_split(
            X, y, test_size=validation_split, stratify=y
        )

        train_dataset = TensorDataset(
            torch.FloatTensor(X_train),
            torch.LongTensor(y_train)
        )
        val_dataset = TensorDataset(
            torch.FloatTensor(X_val),
            torch.LongTensor(y_val)
        )

        train_loader = DataLoader(train_dataset, batch_size=batch_size, shuffle=True)
        val_loader = DataLoader(val_dataset, batch_size=batch_size)

        history = {'train_loss': [], 'val_loss': [], 'val_acc': []}
        best_val_loss = float('inf')

        for epoch in range(epochs):
            # Training
            self.model.train()
            train_loss = 0.0

            for X_batch, y_batch in train_loader:
                X_batch = X_batch.to(self.device)
                y_batch = y_batch.to(self.device)

                self.optimizer.zero_grad()
                outputs = self.model(X_batch)
                loss = self.criterion(outputs, y_batch)
                loss.backward()
                self.optimizer.step()

                train_loss += loss.item()

            # Validation
            self.model.eval()
            val_loss = 0.0
            correct = 0
            total = 0

            with torch.no_grad():
                for X_batch, y_batch in val_loader:
                    X_batch = X_batch.to(self.device)
                    y_batch = y_batch.to(self.device)

                    outputs = self.model(X_batch)
                    loss = self.criterion(outputs, y_batch)
                    val_loss += loss.item()

                    _, predicted = torch.max(outputs, 1)
                    total += y_batch.size(0)
                    correct += (predicted == y_batch).sum().item()

            val_acc = correct / total
            history['train_loss'].append(train_loss / len(train_loader))
            history['val_loss'].append(val_loss / len(val_loader))
            history['val_acc'].append(val_acc)

            self.scheduler.step(val_loss)

            # Early stopping check
            if val_loss < best_val_loss:
                best_val_loss = val_loss
                torch.save(self.model.state_dict(), 'best_model.pt')

        return history
```

---

## 6. Strategy Components

### 6.1 Entry Strategy

```python
# trading/strategies/components/mlp_direction_entry.py

from dataclasses import dataclass
from typing import Optional
import torch
import numpy as np

from trading.strategies.components.interfaces import IEntryStrategy
from trading.strategies.components.models import TradingContext, Signal
from trading.strategies.components.registry import entry_strategy
from trading.indicators.mlp_features import calculate_mlp_features

@dataclass
class MLPDirectionEntryParams:
    """Entry 파라미터"""
    model_path: str = "models/mlp_direction/model.pt"
    confidence_threshold: float = 0.6  # Buy 확률 임계값
    backward_window: int = 5

@entry_strategy(params_class=MLPDirectionEntryParams)
class MLPDirectionEntryStrategy(IEntryStrategy):
    """
    MLP 방향 예측 기반 진입 전략

    논문: Buy 신호 + 충분한 확신도일 때만 진입
    """

    def __init__(self, params: MLPDirectionEntryParams):
        self.params = params
        self.model = None
        self._load_model()

    def _load_model(self):
        """모델 로드 (lazy loading)"""
        from mlp_trainer.src.mlp_model import MLPDirectionClassifier

        self.model = MLPDirectionClassifier(input_dim=13)
        self.model.load_state_dict(
            torch.load(self.params.model_path, map_location='cpu')
        )
        self.model.eval()

    def check_entry(self, ctx: TradingContext) -> Optional[Signal]:
        """진입 신호 확인"""
        # 이미 포지션이 있으면 스킵
        if ctx.symbol in ctx.positions:
            return None

        # 피처 계산 (MarketData의 indicators에서 가져오거나 직접 계산)
        features = self._extract_features(ctx)
        if features is None:
            return None

        # 모델 예측
        with torch.no_grad():
            x = torch.FloatTensor(features).unsqueeze(0)
            probs = self.model.predict_proba(x)[0]

            # [Hold, Buy, Sell] 확률
            buy_prob = probs[1].item()
            predicted_class = probs.argmax().item()

        # Buy 신호 + 충분한 확신도
        if predicted_class == 1 and buy_prob >= self.params.confidence_threshold:
            return Signal(
                symbol=ctx.symbol,
                side="buy",
                market="spot",  # 논문: Buy-only
                quantity=0.0,   # PositionSizer가 계산
                reason=f"MLP Buy signal (prob={buy_prob:.2%})"
            )

        return None

    def _extract_features(self, ctx: TradingContext) -> Optional[np.ndarray]:
        """TradingContext에서 피처 추출"""
        md = ctx.market

        # 필요한 인디케이터가 있는지 확인
        if md.indicators is None:
            return None

        features = np.array([
            md.indicators.get('bollinger_pct_b', 0.5),
            md.indicators.get('rsi', 50.0) / 100.0,
            md.indicators.get('ultosc', 50.0) / 100.0,
            md.indicators.get('ema_cross_1_21', 1.0),
            md.indicators.get('ema_cross_21_50', 1.0),
            md.indicators.get('ema_cross_50_100', 1.0),
            md.indicators.get('ema_cross_1_50', 1.0),
            md.indicators.get('price_zscore', 0.0),
            md.indicators.get('volume_zscore', 0.0),
            md.indicators.get('hour_of_day', 0.0),
            md.indicators.get('day_of_week', 0.0),
            md.indicators.get('month', 0.0),
            md.indicators.get('close_pct_change', 0.0),
        ])

        return features
```

### 6.2 Exit Strategy

```python
# trading/strategies/components/mlp_direction_exit.py

from dataclasses import dataclass
from typing import Optional

from trading.strategies.components.interfaces import IExitStrategy
from trading.strategies.components.models import TradingContext, Signal, Position
from trading.strategies.components.registry import exit_strategy

@dataclass
class MLPDirectionExitParams:
    """Exit 파라미터"""
    stop_loss_pct: float = 10.0  # 논문: 10% Stop Loss
    take_profit_pct: float = 0.0  # 0 = 무제한 (모델이 결정)
    use_model_exit: bool = True  # 모델의 Sell 신호로 청산

@exit_strategy(params_class=MLPDirectionExitParams)
class MLPDirectionExitStrategy(IExitStrategy):
    """
    MLP 방향 예측 기반 청산 전략

    논문: 10% Stop Loss + 모델 Sell 신호
    """

    def __init__(self, params: MLPDirectionExitParams, model=None):
        self.params = params
        self.model = model  # Entry에서 공유받음

    def check_exit(
        self,
        ctx: TradingContext,
        position: Position
    ) -> Optional[Signal]:
        """청산 신호 확인"""
        current_price = ctx.market.close
        entry_price = position.entry_price

        # P&L 계산
        pnl_pct = (current_price - entry_price) / entry_price * 100

        # 1. Stop Loss 확인 (핵심!)
        if pnl_pct <= -self.params.stop_loss_pct:
            return Signal(
                symbol=ctx.symbol,
                side="sell",
                market="spot",
                quantity=position.quantity,
                reason=f"Stop Loss triggered ({pnl_pct:.2f}%)"
            )

        # 2. Take Profit (설정된 경우)
        if self.params.take_profit_pct > 0 and pnl_pct >= self.params.take_profit_pct:
            return Signal(
                symbol=ctx.symbol,
                side="sell",
                market="spot",
                quantity=position.quantity,
                reason=f"Take Profit triggered ({pnl_pct:.2f}%)"
            )

        # 3. 모델 Sell 신호 (선택적)
        if self.params.use_model_exit and self.model is not None:
            features = self._extract_features(ctx)
            if features is not None:
                import torch
                with torch.no_grad():
                    x = torch.FloatTensor(features).unsqueeze(0)
                    probs = self.model.predict_proba(x)[0]
                    predicted_class = probs.argmax().item()

                    if predicted_class == 2:  # Sell
                        return Signal(
                            symbol=ctx.symbol,
                            side="sell",
                            market="spot",
                            quantity=position.quantity,
                            reason=f"MLP Sell signal (prob={probs[2]:.2%})"
                        )

        return None

    def _extract_features(self, ctx: TradingContext):
        """Entry와 동일한 피처 추출 로직"""
        # ... (Entry와 공유)
        pass
```

---

## 7. Data Pipeline

### 7.1 Multi-Asset Data Collection

논문의 핵심: **400+ 코인으로 학습, BTC/ETH로 검증**

```python
# scripts/collectors/multi_asset_collector.py

import asyncio
import aiohttp
from datetime import datetime, timedelta
import pandas as pd

class MultiAssetCollector:
    """바이낸스에서 다중 자산 4H 데이터 수집"""

    BASE_URL = "https://api.binance.com/api/v3/klines"

    async def collect_all_usdt_pairs(
        self,
        start_date: str = "2017-08-17",
        end_date: str = "2024-12-31"
    ) -> dict[str, pd.DataFrame]:
        """모든 USDT 페어 수집"""

        # 1. 사용 가능한 USDT 페어 목록 조회
        async with aiohttp.ClientSession() as session:
            async with session.get("https://api.binance.com/api/v3/exchangeInfo") as resp:
                info = await resp.json()

        usdt_pairs = [
            s['symbol'] for s in info['symbols']
            if s['quoteAsset'] == 'USDT' and s['status'] == 'TRADING'
        ]

        # BTC, ETH는 제외 (검증용)
        train_pairs = [p for p in usdt_pairs if p not in ['BTCUSDT', 'ETHUSDT']]

        print(f"수집할 페어: {len(train_pairs)}개")

        # 2. 병렬 수집
        datasets = {}
        for pair in train_pairs[:400]:  # 논문과 동일하게 400개
            try:
                df = await self._fetch_klines(pair, start_date, end_date)
                if len(df) > 1000:  # 최소 데이터 요구
                    datasets[pair] = df
            except Exception as e:
                print(f"{pair} 실패: {e}")

        return datasets

    async def _fetch_klines(
        self,
        symbol: str,
        start_date: str,
        end_date: str,
        interval: str = "4h"
    ) -> pd.DataFrame:
        """개별 심볼 캔들 수집"""
        params = {
            'symbol': symbol,
            'interval': interval,
            'startTime': int(pd.Timestamp(start_date).timestamp() * 1000),
            'endTime': int(pd.Timestamp(end_date).timestamp() * 1000),
            'limit': 1000
        }

        all_data = []
        async with aiohttp.ClientSession() as session:
            while True:
                async with session.get(self.BASE_URL, params=params) as resp:
                    data = await resp.json()

                if not data:
                    break

                all_data.extend(data)
                params['startTime'] = data[-1][0] + 1

                if len(data) < 1000:
                    break

        df = pd.DataFrame(all_data, columns=[
            'timestamp', 'open', 'high', 'low', 'close', 'volume',
            'close_time', 'quote_volume', 'trades', 'taker_buy_base',
            'taker_buy_quote', 'ignore'
        ])

        df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
        for col in ['open', 'high', 'low', 'close', 'volume']:
            df[col] = df[col].astype(float)

        df['asset'] = symbol

        return df[['timestamp', 'open', 'high', 'low', 'close', 'volume', 'asset']]
```

### 7.2 Dataset Builder

```python
# mlp_trainer/src/dataset_builder.py

import pandas as pd
import numpy as np
from pathlib import Path

from trading.indicators.mlp_features import calculate_mlp_features
from core.mlp_labeling import compute_labels

class MLPDatasetBuilder:
    """MLP 학습용 데이터셋 구축"""

    def __init__(
        self,
        bwin: int = 5,
        fwin: int = 2,
        alpha: float = 0.038,
        beta: float = 0.24
    ):
        self.bwin = bwin
        self.fwin = fwin
        self.alpha = alpha
        self.beta = beta

    def build_from_multi_asset(
        self,
        datasets: dict[str, pd.DataFrame]
    ) -> tuple[np.ndarray, np.ndarray]:
        """다중 자산 데이터에서 학습 데이터셋 구축"""

        all_features = []
        all_labels = []

        for symbol, df in datasets.items():
            try:
                # 피처 계산
                features = calculate_mlp_features(df, self.bwin)

                # 라벨 계산
                labels = compute_labels(
                    df, self.bwin, self.fwin, self.alpha, self.beta
                )

                # NaN 제거 (초기 워밍업 기간)
                valid_idx = ~features.isna().any(axis=1)
                features = features[valid_idx]
                labels = labels[valid_idx]

                all_features.append(features.values)
                all_labels.append(labels.values)

            except Exception as e:
                print(f"{symbol} 처리 실패: {e}")

        X = np.vstack(all_features)
        y = np.concatenate(all_labels)

        print(f"총 샘플: {len(X):,}")
        print(f"클래스 분포: Hold={sum(y==0):,}, Buy={sum(y==1):,}, Sell={sum(y==2):,}")

        return X, y
```

---

## 8. Integration with Existing System

### 8.1 allocation.json 설정 추가

```json
{
  "strategies": {
    "mlp_direction_btc": {
      "market": "spot",
      "enabled": true,
      "entry_class": "MLPDirectionEntryStrategy",
      "exit_class": "MLPDirectionExitStrategy",
      "position_pct": 0.1,
      "timeframe": "4h",
      "backward_window": 5,
      "forward_window": 2,
      "stop_loss_pct": 10.0,
      "model_path": "models/mlp_direction/btc_5_2.pt",
      "confidence_threshold": 0.6
    },
    "mlp_direction_eth": {
      "market": "spot",
      "enabled": true,
      "entry_class": "MLPDirectionEntryStrategy",
      "exit_class": "MLPDirectionExitStrategy",
      "position_pct": 0.1,
      "timeframe": "4h",
      "backward_window": 4,
      "forward_window": 2,
      "stop_loss_pct": 10.0,
      "model_path": "models/mlp_direction/eth_4_2.pt",
      "confidence_threshold": 0.6
    }
  }
}
```

### 8.2 IndicatorService 확장

```python
# trading/indicators/indicator_service.py 수정

class IndicatorService:
    """확장된 인디케이터 서비스"""

    def calculate_mlp_indicators(self, df: pd.DataFrame) -> dict:
        """MLP 전략용 추가 인디케이터"""
        from trading.indicators.mlp_features import calculate_mlp_features

        features = calculate_mlp_features(df, bwin=5)

        return features.iloc[-1].to_dict() if len(features) > 0 else {}
```

### 8.3 Registry 등록

```python
# trading/strategies/components/registry.py 수정

from trading.strategies.components.mlp_direction_entry import MLPDirectionEntryStrategy
from trading.strategies.components.mlp_direction_exit import MLPDirectionExitStrategy

STRATEGY_REGISTRY = {
    # ... 기존 전략들 ...

    "mlp_direction": (MLPDirectionEntryStrategy, MLPDirectionExitStrategy),
    "mlp_direction_btc": (MLPDirectionEntryStrategy, MLPDirectionExitStrategy),
    "mlp_direction_eth": (MLPDirectionEntryStrategy, MLPDirectionExitStrategy),
}
```

---

## 9. Training & Validation Pipeline

### 9.1 전체 파이프라인

```bash
# 1. 데이터 수집 (400+ 코인)
python scripts/collectors/multi_asset_collector.py --output data/multi_asset_4h.parquet

# 2. 데이터셋 구축 (피처 + 라벨)
python mlp_trainer/build_dataset.py \
    --input data/multi_asset_4h.parquet \
    --bwin 5 --fwin 2 \
    --output data/mlp_dataset_5_2.npz

# 3. 모델 학습
python mlp_trainer/train.py \
    --dataset data/mlp_dataset_5_2.npz \
    --epochs 100 \
    --output models/mlp_direction/btc_5_2.pt

# 4. 백테스트 (BTC/ETH - 학습에 포함 안됨!)
python scripts/backtest/backtest_mlp.py \
    --symbol BTC \
    --model models/mlp_direction/btc_5_2.pt \
    --start 2017-08-17 --end 2024-12-31

# 5. 포워드 테스트 (2025년 이후 데이터)
python scripts/backtest/forward_test_mlp.py \
    --symbol BTC \
    --model models/mlp_direction/btc_5_2.pt
```

### 9.2 Quant Lab 통합

```python
# web/quant_lab/studies/mlp_study.py

def create_mlp_study(trial):
    """Optuna Study for MLP hyperparameter tuning"""

    # Labeling parameters
    bwin = trial.suggest_int('backward_window', 3, 7)
    fwin = trial.suggest_int('forward_window', 1, 3)
    alpha = trial.suggest_float('alpha', 0.02, 0.06)

    # Model parameters
    hidden1 = trial.suggest_categorical('hidden1', [64, 128, 256])
    hidden2 = trial.suggest_categorical('hidden2', [32, 64, 128])
    dropout = trial.suggest_float('dropout', 0.1, 0.4)

    # Training parameters
    lr = trial.suggest_float('learning_rate', 1e-4, 1e-2, log=True)

    # Trading parameters
    stop_loss = trial.suggest_float('stop_loss_pct', 5.0, 15.0)
    confidence = trial.suggest_float('confidence_threshold', 0.5, 0.8)

    return {
        'bwin': bwin,
        'fwin': fwin,
        'alpha': alpha,
        'hidden_dims': [hidden1, hidden2],
        'dropout': dropout,
        'lr': lr,
        'stop_loss_pct': stop_loss,
        'confidence_threshold': confidence
    }
```

---

## 10. Implementation Phases

### Phase 1: Foundation (1주)
- [ ] `trading/indicators/mlp_features.py` - 피처 계산 모듈
- [ ] `core/mlp_labeling.py` - 라벨링 알고리즘
- [ ] `mlp_trainer/src/mlp_model.py` - MLP 모델 정의
- [ ] Unit tests

### Phase 2: Training Pipeline (1주)
- [ ] `scripts/collectors/multi_asset_collector.py` - 데이터 수집
- [ ] `mlp_trainer/src/dataset_builder.py` - 데이터셋 구축
- [ ] `mlp_trainer/src/mlp_train.py` - 학습 파이프라인
- [ ] MLflow 통합

### Phase 3: Strategy Components (3일)
- [ ] `trading/strategies/components/mlp_direction_entry.py`
- [ ] `trading/strategies/components/mlp_direction_exit.py`
- [ ] Registry 등록 및 allocation.json 설정
- [ ] IndicatorService 확장

### Phase 4: Backtesting & Validation (3일)
- [ ] `scripts/backtest/backtest_mlp.py` - 백테스트 스크립트
- [ ] BTC/ETH 6년간 백테스트
- [ ] Forward test (2025년 이후)
- [ ] 성과 비교 리포트

### Phase 5: Live Integration (2일)
- [ ] 4H 타임프레임 피드 연동
- [ ] Paper trading 테스트
- [ ] Live trading 배포

---

## 11. Expected Outcomes

### 성과 목표 (논문 대비)

| 지표 | 논문 결과 | 목표 |
|------|-----------|------|
| BTC ROI | 48.23x | > 30x |
| ETH ROI | 93.06x | > 50x |
| 승률 | ~50% | > 45% |
| MDD | Not reported | < 25% |

### 기존 전략 대비 개선점

1. **일반화 능력**: 400+ 코인 학습으로 오버피팅 방지
2. **단순함**: 복잡한 LSTM 대신 간단한 MLP
3. **검증된 피처**: SHAP 분석으로 검증된 Top 10 피처만 사용
4. **명확한 손절**: 10% 고정 Stop Loss
5. **4H 타임프레임**: 노이즈 감소, 수수료 절약

---

## 12. References

1. Parente, M., & Rizzuti, L. (2025). Trading strategy for Bitcoin and Ethereum by neural network model. *Soft Computing*. https://doi.org/10.1007/s00500-025-10980-7

2. Lundberg, S. M., & Lee, S. I. (2017). A unified approach to interpreting model predictions. *Advances in Neural Information Processing Systems*, 30.

3. Buda, M., Maki, A., & Mazurowski, M. A. (2018). A systematic study of the class imbalance problem in convolutional neural networks. *Neural Networks*, 106, 249-259.
