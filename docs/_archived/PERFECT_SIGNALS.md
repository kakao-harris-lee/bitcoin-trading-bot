# 🎯 완벽한 매매 시그널 (Perfect Trading Signals)

## 개념

**"완벽한 정답"**: 미래 데이터를 사용하여 추출한 100% 최적 매매 시그널

- **목적**: 전략 성과 측정의 기준선 (baseline)
- **방법**: 각 캔들마다 1/3/5/7/14/30일 보유 시 수익률 계산 → 최고 수익 선택
- **용도**:
  - ❌ 직접 사용 불가 (look-ahead bias 포함)
  - ✅ 재현율 측정 기준
  - ✅ ML 학습 패턴 분석
  - ✅ 전략 개선 방향 제시

---

## 📊 데이터 요약 (2020-2024)

**총 시그널**: 45,254개
**평균 수익률**: 4.13%
**분석 기간**: 2020-01-01 ~ 2024-12-31 (5년)

### 타임프레임별

| 타임프레임 | 시그널 수 | 평균 수익률 | 30일 보유 비율 |
|-----------|-----------|-------------|----------------|
| day | 1,276 | 14.52% | 48.44% |
| minute60 | 19,334 | 3.20% | 58.22% |
| minute240 | 4,357 | 4.31% | 59.23% |
| minute15 | 11,571 | 2.01% | 67.50% |
| minute5 | 8,716 | 1.71% | 70.23% |

### 연도별

| 연도 | 시그널 수 | 평균 수익률 | 시장 특성 |
|------|-----------|-------------|-----------|
| 2020 | 5,508 | 6.51% | 코로나 반등 |
| 2021 | 6,481 | 7.38% | 역대 최고가 |
| 2022 | 4,325 | 3.75% | 약세장 |
| 2023 | 8,123 | 4.22% | 회복기 |
| 2024 | 20,817 | 4.95% | 강세장 |

---

## 🎯 재현율 기반 전략 평가

### 재현율 정의

```python
신호_재현율 = (전략_포착_시그널 / 완벽한_정답_시그널) × 100
수익_재현율 = (전략_수익률 / 완벽한_정답_수익률) × 100
종합_재현율 = (신호_재현율 × 0.4) + (수익_재현율 × 0.6)
```

### 성공 기준

```yaml
S-Tier 전략: 재현율 70%+ (배포 가능)
A-Tier 전략: 재현율 50-70% (최적화 필요)
B-Tier 전략: 재현율 30-50% (재설계 필요)
C-Tier 전략: 재현율 < 30% (폐기)
```

### 예시

```
완벽한 정답 (day, 2024): 266개 시그널, 평균 15.37%
v42 전략 결과: 180개 시그널, 평균 11.20%

신호 재현율: 180 / 266 = 67.7%
수익 재현율: 11.20 / 15.37 = 72.9%
종합 재현율: (67.7 × 0.4) + (72.9 × 0.6) = 70.8%

→ S-Tier 달성 ✅
```

---

## 📁 파일 위치

```
strategies/v41_scalping_voting/analysis/perfect_signals/
├── day_2020_perfect.csv (279개)
├── day_2021_perfect.csv (254개)
├── day_2022_perfect.csv (226개)
├── day_2023_perfect.csv (251개)
├── day_2024_perfect.csv (266개)
├── minute60_2020_perfect.csv (4,234개)
├── minute60_2021_perfect.csv (5,007개)
├── minute60_2022_perfect.csv (3,351개)
├── minute60_2023_perfect.csv (2,909개)
├── minute60_2024_perfect.csv (3,833개)
├── minute240_2020_perfect.csv (995개)
├── minute240_2021_perfect.csv (1,220개)
├── minute240_2022_perfect.csv (748개)
├── minute240_2023_perfect.csv (585개)
├── minute240_2024_perfect.csv (809개)
├── minute15_2023_perfect.csv (4,378개)
├── minute15_2024_perfect.csv (7,193개)
├── minute5_2024_perfect.csv (8,716개)
├── summary_all_timeframes.json
└── INTERMEDIATE_REPORT.md
```

---

## 💻 사용 예제

### 1. 완벽한 시그널 로드

```python
import pandas as pd

# Day 2024년 완벽한 시그널
df_perfect = pd.read_csv(
    'strategies/v41_scalping_voting/analysis/perfect_signals/day_2024_perfect.csv'
)

print(f"총 시그널: {len(df_perfect)}개")
print(f"평균 수익률: {df_perfect['best_return'].mean():.2%}")
print(f"평균 보유 기간: {df_perfect['best_hold_days'].mean():.1f}일")
```

### 2. 재현율 계산

```python
from datetime import timedelta

def calculate_reproduction_rate(strategy_signals, perfect_signals):
    """재현율 계산"""
    # 시간 기준 매칭 (±1일 허용)
    matched = 0
    for sig in strategy_signals:
        for perfect in perfect_signals:
            time_diff = abs(sig['timestamp'] - perfect['timestamp'])
            if time_diff <= timedelta(days=1):
                matched += 1
                break

    signal_rate = matched / len(perfect_signals) * 100
    return signal_rate

# 사용
perfect_df = pd.read_csv('...day_2024_perfect.csv')
strategy_df = generate_strategy_signals(...)

rate = calculate_reproduction_rate(strategy_df, perfect_df)
print(f"신호 재현율: {rate:.1f}%")
```

### 3. 패턴 학습

```python
# 완벽한 시그널의 지표 패턴
features = df_perfect[[
    'rsi', 'mfi', 'volume_ratio', 'bb_position',
    'macd', 'adx', 'atr_pct'
]]

labels = df_perfect['best_hold_days']

# ML 모델 학습 (패턴 인식용)
from sklearn.ensemble import RandomForestClassifier

model = RandomForestClassifier(n_estimators=100)
model.fit(features, labels)

# 중요도 확인
importance = pd.DataFrame({
    'feature': features.columns,
    'importance': model.feature_importances_
}).sort_values('importance', ascending=False)

print(importance)
```

---

## ⚠️ 중요 참고사항

### 1. Look-ahead Bias는 의도적

- 이 데이터는 "정답지"이므로 미래 데이터 사용 필수
- 전략 학습/최적화 시 직접 사용 금지
- 성과 측정 기준선으로만 사용

### 2. 100% 재현 불가능

- 완벽한 정답은 이상적 시나리오
- 실전에서는 60-80% 재현이 현실적 목표
- 수수료, 슬리피지, 심리적 요인 고려 필요

### 3. 타임프레임별 특성

- **Day**: 높은 수익률, 적은 기회 (연 1,276개)
- **Minute60**: 많은 기회, 중간 수익 (연 19,334개)
- **Minute15**: 매우 많은 기회, 낮은 수익 (연 11,571개)
- **Minute5**: 가장 많은 기회, 가장 낮은 수익 (연 8,716개)

### 4. 보유 기간 분포

- **30일 보유가 66% 차지** (중장기 보유 우세)
- 단타 (1-3일): 4.4%만 해당
- 타임프레임이 짧을수록 장기 보유 비율 증가

---

## 🔄 업데이트 이력

- **2025-10-20**: 초기 생성 (45,254개 시그널)
  - day, minute60, minute240, minute15 (2020-2024)
  - minute5 (2024만)

---

**생성일**: 2025-10-20
**생성 도구**: `strategies/v41_scalping_voting/phase0_perfect_signals.py`
**데이터 출처**: `upbit_bitcoin.db` (2020-2024)
