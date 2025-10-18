# 트레이딩 전략 라이브러리

**작성일**: 2025-10-19
**목적**: 검증된 트레이딩 알고리즘의 재사용 가능한 모듈 제공

## 📚 라이브러리 구조

```
_library/
├── trend_following/      # 추세 추종 전략 (7개)
├── momentum/             # 모멘텀 지표 (6개)
├── volatility/           # 변동성 지표 (4개)
├── volume/               # 거래량 분석 (5개)
├── support_resistance/   # 지지/저항 레벨 (5개)
├── mean_reversion/       # 평균 회귀 전략 (5개)
├── ensemble/             # 앙상블 기법 (5개)
└── risk_management/      # 리스크 관리 (6개)
```

## 🎯 사용 방법

### 1. 개별 알고리즘 테스트
```python
from strategies._library.volatility.bollinger_bands import BollingerBands

# 지표 생성
bb = BollingerBands(window=20, num_std=2)
signals = bb.generate_signals(df)

# 독립 테스트
from automation.test_algorithm import AlgorithmTester
tester = AlgorithmTester('bollinger_bands')
result = tester.run(timeframe='day', period='2024-01-01:2024-12-31')
```

### 2. 전략 조합
```python
from strategies._library.ensemble.voting import VotingEnsemble

# 3개 알고리즘 조합
ensemble = VotingEnsemble([
    ('breakout', weight=2.0),
    ('ema_macd', weight=1.5),
    ('bollinger_bounce', weight=1.0)
])

signal = ensemble.vote(df, i)  # Weighted score >= 3.0이면 매수
```

### 3. 신규 전략 개발
```bash
# Step 1: 필요한 알고리즘 선택
cp _library/volatility/bollinger_bands.py strategies/v13_sideways/

# Step 2: 독립 테스트
python strategies/v13_sideways/test_bollinger.py

# Step 3: 합격 시 통합
# (시그널 >= 5, 승률 >= 55%, 평균 수익 > 8%)
```

## 📋 알고리즘 목록 (47개)

### Trend Following (7개)
- [x] `ema_crossover.py` - EMA 골든/데드 크로스
- [x] `macd.py` - MACD 지표
- [ ] `parabolic_sar.py` - Parabolic SAR
- [ ] `ichimoku.py` - Ichimoku Cloud
- [ ] `supertrend.py` - Supertrend
- [ ] `donchian.py` - Donchian Channel Breakout
- [x] `adx.py` - ADX 추세 강도

### Momentum (6개)
- [x] `rsi.py` - RSI 과매수/과매도
- [ ] `stochastic.py` - Stochastic Oscillator
- [ ] `cci.py` - Commodity Channel Index
- [ ] `williams_r.py` - Williams %R
- [ ] `roc.py` - Rate of Change
- [ ] `momentum.py` - Momentum Indicator

### Volatility (4개)
- [ ] `bollinger_bands.py` - Bollinger Bands (우선순위 1)
- [ ] `atr.py` - Average True Range (우선순위 1)
- [ ] `keltner.py` - Keltner Channels
- [ ] `std_dev_bands.py` - Standard Deviation Bands

### Volume (5개)
- [ ] `obv.py` - On-Balance Volume
- [ ] `vwap.py` - Volume Weighted Average Price
- [ ] `accumulation_distribution.py` - A/D
- [ ] `chaikin_mf.py` - Chaikin Money Flow
- [ ] `volume_profile.py` - Volume Profile

### Support/Resistance (5개)
- [ ] `fibonacci.py` - Fibonacci Retracement
- [ ] `pivot_points.py` - Pivot Points
- [ ] `price_action.py` - Price Action (High/Low)
- [ ] `trendlines.py` - Trendline Detection
- [ ] `ma_sr.py` - MA as Support/Resistance

### Mean Reversion (5개)
- [ ] `bb_bounce.py` - Bollinger Band Bounce (우선순위 1)
- [ ] `rsi_divergence.py` - RSI Divergence
- [ ] `mean_reversion_ma.py` - Mean Reversion to MA
- [ ] `zscore.py` - Z-Score
- [ ] `ppo.py` - Percent Price Oscillator

### Ensemble (5개)
- [ ] `voting.py` - Voting Ensemble (우선순위 1)
- [ ] `stacking.py` - Stacking Meta-Learner
- [ ] `weighted_average.py` - Weighted Average
- [ ] `conditional_logic.py` - IF-THEN Rules
- [ ] `ml_classification.py` - ML Classifier

### Risk Management (6개)
- [x] `fixed_trailing_stop.py` - Fixed Trailing Stop
- [ ] `atr_trailing_stop.py` - ATR-based Dynamic Stop (우선순위 1)
- [ ] `profit_ladder.py` - Profit Target Ladder
- [x] `kelly_criterion.py` - Kelly Criterion Position Sizing
- [x] `fixed_stop_loss.py` - Fixed Stop Loss
- [ ] `time_based_exit.py` - Time-based Exit

## 🔧 개발 가이드

### 알고리즘 템플릿
```python
#!/usr/bin/env python3
"""
algorithm_name.py
Category: Volatility
Purpose: Bollinger Bands 지표 생성 및 신호 감지
"""

class AlgorithmName:
    def __init__(self, **params):
        self.params = params

    def calculate(self, df):
        """지표 계산 (DataFrame에 컬럼 추가)"""
        # 구현
        return df

    def generate_signals(self, df):
        """매매 신호 생성 (BUY/SELL/HOLD)"""
        # 구현
        return signals

    def backtest(self, df, initial_capital=10_000_000):
        """간이 백테스팅"""
        # 구현
        return results
```

### 테스트 기준
```yaml
합격 기준:
  - 시그널 개수: >= 5개 (2024년)
  - 승률: >= 55%
  - 평균 수익: > 8%
  - Sharpe Ratio: > 0.8

불합격 시:
  - 파라미터 파인튜닝
  - 다른 알고리즘과 조합 시도
  - 또는 폐기
```

## 📊 검증 완료 알고리즘

| 알고리즘 | 시그널 | 승률 | 평균 수익 | 상태 |
|----------|--------|------|-----------|------|
| BREAKOUT (v12) | 13개 | 69.2% | +10.41% | ✅ 합격 |
| EMA+MACD (v07) | 13개 | 46.2% | +15.35% | ⚠️ 조합 필요 |
| RSI Bounce (v11) | 6개 | 16.7% | +3.98% | ❌ 불합격 |
| Bollinger Bands | - | - | - | 🔜 테스트 예정 |
| ATR Trailing Stop | - | - | - | 🔜 테스트 예정 |

## 🚀 우선순위

### Week 1 (필수 구현)
1. Bollinger Bands (`volatility/bollinger_bands.py`)
2. ATR (`volatility/atr.py`)
3. BB Bounce (`mean_reversion/bb_bounce.py`)
4. ATR Trailing Stop (`risk_management/atr_trailing_stop.py`)
5. Voting Ensemble (`ensemble/voting.py`)

### Week 2-3 (확장)
6. Fibonacci (`support_resistance/fibonacci.py`)
7. Ichimoku (`trend_following/ichimoku.py`)
8. Stacking (`ensemble/stacking.py`)
9. Profit Ladder (`risk_management/profit_ladder.py`)
10. Time-based Exit (`risk_management/time_based_exit.py`)

---

**업데이트 이력**:
- 2025-10-19: 라이브러리 구조 생성, 47개 알고리즘 정의
