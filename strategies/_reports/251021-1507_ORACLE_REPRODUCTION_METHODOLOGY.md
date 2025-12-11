# 완벽한 시그널 재현 기반 개발 방법론 (Oracle Reproduction Methodology)

**생성일시**: 2025-10-21 15:07
**목적**: 미래 데이터로 추출한 "완벽한 정답" 시그널을 기준으로 전략 성과를 측정하고 개선하는 체계적 방법론

---

## 📖 개념 정의

### Oracle (오라클)
금융 공학에서 **미래 정보를 알고 있는 가상의 전지적 존재**를 의미합니다. 이 프로젝트에서는:

- **입력**: 과거 시장 데이터 (2020-2024)
- **처리**: 각 시점에서 미래 1/3/5/7/14/30일 보유 시 수익률 계산
- **출력**: 최대 수익을 내는 "완벽한 정답" 매매 시그널 45,254개

### 재현율 (Reproduction Rate)
전략이 완벽한 정답 시그널을 얼마나 잘 재현하는지 측정하는 지표:

```
재현율 = (신호_재현율 × 40%) + (수익_재현율 × 60%)

신호_재현율 = (전략_포착_시그널 / 완벽한_정답_시그널) × 100
수익_재현율 = (전략_수익률 / 완벽한_정답_수익률) × 100
```

**예시** (Day, 2024년):
- 완벽한 정답: 266개 시그널, 평균 15.37%
- v42 전략: 180개 시그널, 평균 11.20%
- 신호 재현율: 67.7%
- 수익 재현율: 72.9%
- **종합 재현율: 70.8%** (S-Tier 달성)

---

## 🎯 방법론의 핵심 원리

### 1. Look-Ahead Bias의 의도적 사용

**전통적 ML 경고**: Look-ahead bias는 오버피팅의 주범!
**이 방법론**: Look-ahead bias를 **목적적으로 활용**하여 이상적 기준선 생성

```python
# 전통적 접근 (금지)
def predict_price(current_data):
    return model.predict(current_data + future_data)  # ❌ 부정행위

# Oracle 접근 (허용, 학습 목적)
def create_perfect_signals(historical_data):
    """미래 데이터로 정답지 생성 (직접 매매 금지, 기준선으로만 사용)"""
    for candle in historical_data:
        future_returns = [
            calculate_return(candle, hold_days=d)
            for d in [1, 3, 5, 7, 14, 30]
        ]
        best_return = max(future_returns)
        if best_return > threshold:
            perfect_signals.append({
                'timestamp': candle.timestamp,
                'best_return': best_return,
                'best_hold_days': future_returns.index(best_return)
            })
    return perfect_signals  # ✅ 기준선으로 사용
```

### 2. Supervised Learning의 새로운 패러다임

#### 전통적 Supervised Learning
```
X (features) → Model → Y (labels: up/down)
                           ↓
                    실전에서 정확도 50-60%
```

#### Oracle Reproduction Methodology
```
완벽한 정답 시그널 (Oracle)
         ↓
패턴 분석 (지표 조합 연구)
         ↓
재현 전략 개발
         ↓
재현율 측정 (60-80% 목표)
         ↓
반복 개선
```

**차이점**:
- 전통: "미래 가격 방향 예측" (불가능)
- Oracle: "이미 알고 있는 최적 시점 재현" (가능)

### 3. 학습 기법 연관성

연구 조사 결과, 이 방법론은 다음 ML 기법들과 유사한 철학을 공유합니다:

#### Triple Barrier Labeling (2023-2024)
- **개념**: 가격 움직임을 3가지 장벽(이익, 손실, 시간)으로 라벨링
- **유사점**: 다양한 보유 기간(1/3/5/7/14/30일)을 테스트하여 최적값 선택
- **출처**: MDPI Mathematics 2024, "Enhanced GA-Driven Triple Barrier Labeling"

#### N-Period Volatility Labeling (2024)
- **개념**: 단순 가격 차이 대신 변동성을 고려한 라벨 생성
- **유사점**: 단순 상승/하락이 아닌 "최대 수익" 기준으로 라벨링
- **출처**: Wiley Complexity 2024, "N-Period Volatility Labeling and Instance Selection"

#### Hindsight Optimal Strategy (금융공학 전통)
- **개념**: 완벽한 사후 지식으로 이론적 최대 수익 계산
- **유사점**: Oracle 시그널이 바로 Hindsight Optimal Strategy의 구현
- **활용**: 전략 성과의 상한선(upper bound) 측정

---

## 📊 프로젝트 적용 현황

### 완벽한 시그널 데이터 (PERFECT_SIGNALS.md 참조)

**생성 완료** (2025-10-20):
```
총 시그널: 45,254개 (2020-2024)
타임프레임: day, minute60, minute240, minute15, minute5
평균 수익률: 4.13%
파일 위치: strategies/v41_scalping_voting/analysis/perfect_signals/
```

**타임프레임별 특성**:
| TF | 시그널 수 | 평균 수익 | 30일 보유 비율 | 특징 |
|----|----------|----------|---------------|------|
| day | 1,276 | 14.52% | 48% | 높은 수익, 적은 기회 |
| minute60 | 19,334 | 3.20% | 58% | 균형잡힌 기회/수익 |
| minute15 | 11,571 | 2.01% | 68% | 많은 기회, 낮은 수익 |
| minute5 | 8,716 | 1.71% | 70% | 매우 많은 기회, 최저 수익 |

### v41 Scalping Voting 전략 (진행 중)

**Phase 0 완료** (브루트포스 분석):
```
분석 기간: 2020-2023
방법: 모든 캔들 × 보유 기간(1/3/5/7/14/30일) 조합 테스트
발견: 수익 케이스 36,619개

day: 973개 (평균 20.72%, 승률 100%)
minute60: 14,348개 (평균 3.48%, 승률 100%)
```

**현재 상태**: 백테스팅 대기 (strategy.py 누락)

### 기존 전략들과의 비교

**v35_optimized** (현재 최고 전략):
- 2025 수익률: +14.20%, Sharpe 2.24
- 재현율 계산 가능 (day 완벽한 시그널 대비)
- **예상 재현율**: 60-70% (추정)

**v34_supreme**:
- 2025 수익률: +8.43%, Sharpe 1.34
- **예상 재현율**: 40-50% (추정)

**v31_scalping_with_classifier**:
- 2024 수익률: +6.33%, Sharpe 1.94
- **예상 재현율**: 30-40% (추정)

---

## 🔧 구현 가이드

### Step 1: 완벽한 시그널 생성 (완료)

```python
# strategies/v41_scalping_voting/phase0_perfect_signals.py
def generate_perfect_signals(df, timeframe, year):
    """브루트포스 방식으로 완벽한 시그널 추출"""
    perfect_signals = []

    for idx, row in df.iterrows():
        entry_price = row['close']
        entry_time = row['timestamp']

        # 미래 1/3/5/7/14/30일 보유 시 수익률 계산
        returns = {}
        for hold_days in [1, 3, 5, 7, 14, 30]:
            future_idx = idx + hold_days * candles_per_day
            if future_idx < len(df):
                future_price = df.iloc[future_idx]['close']
                returns[hold_days] = (future_price - entry_price) / entry_price

        # 최고 수익 선택
        if returns:
            best_hold = max(returns, key=returns.get)
            best_return = returns[best_hold]

            if best_return > 0.01:  # 1% 이상만 시그널로 저장
                perfect_signals.append({
                    'timestamp': entry_time,
                    'entry_price': entry_price,
                    'best_hold_days': best_hold,
                    'best_return': best_return,
                    'rsi': row['rsi'],
                    'mfi': row['mfi'],
                    'volume_ratio': row['volume_ratio'],
                    # ... 기타 지표
                })

    return pd.DataFrame(perfect_signals)
```

### Step 2: 재현율 계산기 구현 (필요)

```python
# validation/reproduction_rate_calculator.py
from datetime import timedelta

class ReproductionRateCalculator:
    """전략의 재현율 계산"""

    def __init__(self, perfect_signals_path, strategy_results_path):
        self.perfect = pd.read_csv(perfect_signals_path)
        self.strategy = self.load_strategy_results(strategy_results_path)

    def calculate_signal_reproduction(self, time_tolerance_hours=24):
        """시그널 재현율: 전략이 완벽한 시그널을 얼마나 포착했는가"""
        matched = 0

        for _, perfect_signal in self.perfect.iterrows():
            perfect_time = pd.to_datetime(perfect_signal['timestamp'])

            # 전략 시그널 중 ±24시간 이내 매칭 확인
            for _, strategy_signal in self.strategy.iterrows():
                strategy_time = pd.to_datetime(strategy_signal['entry_time'])
                time_diff = abs((strategy_time - perfect_time).total_seconds() / 3600)

                if time_diff <= time_tolerance_hours:
                    matched += 1
                    break

        return (matched / len(self.perfect)) * 100

    def calculate_profit_reproduction(self):
        """수익 재현율: 전략 수익이 완벽한 시그널 수익의 몇 %인가"""
        perfect_avg_return = self.perfect['best_return'].mean()
        strategy_avg_return = self.strategy['return_pct'].mean()

        return (strategy_avg_return / perfect_avg_return) * 100

    def calculate_combined_rate(self):
        """종합 재현율"""
        signal_rate = self.calculate_signal_reproduction()
        profit_rate = self.calculate_profit_reproduction()

        combined = (signal_rate * 0.4) + (profit_rate * 0.6)

        return {
            'signal_reproduction': signal_rate,
            'profit_reproduction': profit_rate,
            'combined_reproduction': combined,
            'tier': self.get_tier(combined)
        }

    def get_tier(self, combined_rate):
        """재현율 기반 Tier 분류"""
        if combined_rate >= 70:
            return 'S'  # 배포 가능
        elif combined_rate >= 50:
            return 'A'  # 최적화 필요
        elif combined_rate >= 30:
            return 'B'  # 재설계 필요
        else:
            return 'C'  # 폐기
```

### Step 3: 패턴 학습 (ML 활용)

```python
# analysis/pattern_learner.py
from sklearn.ensemble import RandomForestClassifier
from sklearn.cluster import KMeans

def learn_perfect_signal_patterns(perfect_signals_df):
    """완벽한 시그널의 지표 패턴 학습 (직접 매매 금지, 인사이트 도출용)"""

    # 특징 추출
    features = perfect_signals_df[[
        'rsi', 'mfi', 'volume_ratio', 'bb_position',
        'macd', 'adx', 'atr_pct', 'momentum_5h'
    ]]

    # 라벨: 보유 기간 (1/3/5/7/14/30일)
    labels = perfect_signals_df['best_hold_days']

    # Random Forest로 중요도 분석
    rf = RandomForestClassifier(n_estimators=100, random_state=42)
    rf.fit(features, labels)

    importance = pd.DataFrame({
        'feature': features.columns,
        'importance': rf.feature_importances_
    }).sort_values('importance', ascending=False)

    print("🎯 완벽한 시그널의 핵심 지표:")
    print(importance.head(5))

    # 클러스터링으로 패턴 그룹 발견
    kmeans = KMeans(n_clusters=5, random_state=42)
    clusters = kmeans.fit_predict(features)

    perfect_signals_df['cluster'] = clusters

    # 클러스터별 통계
    for cluster_id in range(5):
        cluster_data = perfect_signals_df[perfect_signals_df['cluster'] == cluster_id]
        print(f"\n클러스터 {cluster_id}:")
        print(f"  시그널 수: {len(cluster_data)}")
        print(f"  평균 수익률: {cluster_data['best_return'].mean():.2%}")
        print(f"  주요 보유 기간: {cluster_data['best_hold_days'].mode()[0]}일")

    return importance, clusters
```

### Step 4: 재현 전략 개발

```python
# strategies/v{NN}_oracle_reproduction/strategy.py
def oracle_reproduction_strategy(df, perfect_signal_patterns):
    """완벽한 시그널 패턴을 재현하는 전략"""

    # Step 1: 패턴 학습에서 발견한 핵심 지표 (예: MFI, Local Min, Low Vol)
    signals = []

    for idx, row in df.iterrows():
        score = 0

        # MFI 패턴 (완벽한 시그널에서 가장 중요한 지표)
        if row['mfi'] >= 60:
            score += 28

        # Local Minima 패턴
        if is_local_min(df, idx, window=20):
            score += 20

        # Low Volatility 패턴 (변동성 압축)
        if row['atr_pct'] < row['atr_pct_ma20']:
            score += 16

        # Volume Spike 패턴
        if row['volume_ratio'] > 1.3:
            score += 12

        # 임계값 (완벽한 시그널 재현을 위한 최소 점수)
        if score >= 25:  # 백분위수 기반 최적화 임계값
            signals.append({
                'timestamp': row['timestamp'],
                'score': score,
                'entry_price': row['close']
            })

    return signals
```

### Step 5: 백테스팅 및 재현율 측정

```python
# strategies/v{NN}_oracle_reproduction/backtest.py
from validation.reproduction_rate_calculator import ReproductionRateCalculator

# 1. 백테스팅 실행
results = run_backtest(strategy_signals, ...)

# 2. 재현율 계산
calculator = ReproductionRateCalculator(
    perfect_signals_path='strategies/v41_scalping_voting/analysis/perfect_signals/day_2024_perfect.csv',
    strategy_results_path='strategies/v{NN}_oracle_reproduction/backtest_results.json'
)

reproduction = calculator.calculate_combined_rate()

print(f"신호 재현율: {reproduction['signal_reproduction']:.1f}%")
print(f"수익 재현율: {reproduction['profit_reproduction']:.1f}%")
print(f"종합 재현율: {reproduction['combined_reproduction']:.1f}%")
print(f"Tier: {reproduction['tier']}")

# 3. Tier에 따른 액션
if reproduction['tier'] == 'S':
    print("✅ 배포 가능! 실전 거래 검토")
elif reproduction['tier'] == 'A':
    print("🔧 최적화 필요: 임계값 조정, 지표 가중치 재조정")
elif reproduction['tier'] == 'B':
    print("🔄 재설계 필요: 다른 패턴 조합 시도")
else:
    print("❌ 폐기: 완벽한 시그널과 상관관계 없음")
```

---

## ✅ 장점 및 한계

### 장점

1. **명확한 목표선**
   - "완벽한 정답"이라는 이상적 기준선 존재
   - 상대적 성과(Buy&Hold 대비)가 아닌 절대적 재현율로 평가

2. **오버피팅 방지**
   - 완벽한 시그널 자체를 학습 데이터로 사용하지 않음
   - 패턴 분석 → 전략 개발 → 재현율 측정의 순환 구조

3. **현실적 기대치**
   - 100% 재현 불가능 인정
   - 60-80% 재현율을 현실적 목표로 설정

4. **지속적 개선 가능**
   - 재현율 측정으로 개선 방향 명확
   - A/B 테스트로 어떤 변경이 재현율을 높이는지 정량화

### 한계

1. **Look-Ahead Bias의 양날의 검**
   - 기준선 생성에는 필수적
   - 하지만 실전 매매에 직접 사용 시 100% 실패

2. **과거 패턴의 미래 지속성 불확실**
   - 2020-2024 완벽한 시그널 패턴이 2025년에도 유효하다는 보장 없음
   - Out-of-Sample 검증 필수

3. **수수료 및 슬리피지 미반영**
   - 완벽한 시그널은 이론적 최대 수익
   - 실전에서는 0.14% 거래 비용 고려 필요

4. **심리적 요인 무시**
   - 완벽한 시그널은 감정 없는 로봇 전제
   - 실전에서는 공포/탐욕 개입

---

## 🚀 다음 단계 (실행 계획)

### Phase 1: 재현율 계산기 구현 ✅ 우선순위
```bash
# 1. ReproductionRateCalculator 클래스 작성
touch validation/reproduction_rate_calculator.py

# 2. 기존 전략들 재현율 측정
python validation/calculate_all_reproduction_rates.py \
  --strategies v35_optimized,v34_supreme,v31_scalping_with_classifier \
  --perfect-signals strategies/v41_scalping_voting/analysis/perfect_signals/

# 3. 결과 문서화
# → strategies/251021-{time}_REPRODUCTION_RATE_REPORT.md
```

### Phase 2: v41 백테스팅 완료
```bash
# 1. strategy.py 구현 (패턴 학습 결과 기반)
# 2. 백테스팅 실행 (2020-2024)
# 3. 재현율 측정
# 4. 재현율 70%+ 달성 시 v46으로 업그레이드
```

### Phase 3: 신규 전략 개발 (Oracle Reproduction 전용)
```bash
# v46_oracle_reproduction_day
# - 타겟: day 완벽한 시그널 재현율 75%+
# - 방���: 패턴 학습 + 투표 시스템 + 동적 TP/SL

# v47_oracle_reproduction_minute60
# - 타겟: minute60 완벽한 시그널 재현율 70%+
# - 방법: 고빈도 시그널 + 빠른 회전
```

### Phase 4: 문서화 및 표준화
```bash
# 1. 재현율 계산을 CLAUDE.md 표준 평가 지표에 추가
# 2. 모든 신규 전략은 재현율 70%+ 목표
# 3. 기존 전략 카탈로그에 재현율 컬럼 추가
```

---

## 📚 참고 문헌

### 학술 연구
1. **Triple Barrier Labeling** (MDPI Mathematics, 2024)
   - "Enhanced Genetic-Algorithm-Driven Triple Barrier Labeling Method"
   - 다양한 보유 기간 테스트 → 최적 라벨 선택

2. **N-Period Volatility Labeling** (Wiley Complexity, 2024)
   - "Improving the Machine Learning Stock Trading System"
   - 변동성 고려 라벨링 → 안정적 장기 시스템

3. **Look-Ahead Bias Prevention** (ML4Trading.io, 2024)
   - Point-in-time 데이터 관리
   - 훈련/검증/테스트 데이터 오염 방지

### 프로젝트 내부 문서
- [PERFECT_SIGNALS.md](PERFECT_SIGNALS.md): 완벽한 시그널 데이터 요약
- [CLAUDE.md](CLAUDE.md): 프로젝트 통합 가이드
- [251021-1428_STRATEGY_CATALOG.md](strategies/251021-1428_STRATEGY_CATALOG.md): 전략 카탈로그
- [251021-1316_V37_V45_COMPREHENSIVE_VALIDATION_REPORT.md](strategies/251021-1316_V37_V45_COMPREHENSIVE_VALIDATION_REPORT.md): 검증 보고서

---

## 💡 핵심 요약

**이 방법론은**:
1. 미래 데이터로 "완벽한 정답" 시그널 생성 (Look-Ahead Bias 의도적 활용)
2. 완벽한 시그널의 패턴 분석 (지표 조합, 클러스터링)
3. 패턴 재현 전략 개발 (직접 복사 금지, 패턴 학습)
4. 재현율 측정 (신호 40% + 수익 60%)
5. 재현율 기반 반복 개선 (S-Tier 70%+ 목표)

**전통적 ML과의 차이**:
- 전통: "미래 가격 예측" (불가능) → 정확도 50-60%
- Oracle: "이상적 시점 재현" (가능) → 재현율 60-80%

**적용 현황**:
- ✅ 완벽한 시그널 45,254개 생성 (2020-2024)
- 🔧 v41 Phase 0 완료 (브루트포스 분석)
- ⏳ 재현율 계산기 구현 대기
- ⏳ v35/v34/v31 재현율 측정 대기

**다음 작업**: 재현율 계산기 구현 → 기존 전략 재평가 → v46 Oracle Reproduction 전략 개발

---

**업데이트 이력**:
- 2025-10-21 15:07: 초기 작성 (웹 검색 결과 + 프로젝트 현황 통합)
