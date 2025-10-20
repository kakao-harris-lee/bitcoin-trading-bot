# Phase 0 재설계: 전수 매매 기회 탐색 계획

## 🎯 목표

기존 v41 voting ensemble 방식에서 시그널 수가 너무 적은 문제 발견:
- minute5: 2,332개 (2.22%)
- minute240: 38개 (0.35%)
- **day: 2개 (0.11%)** ← 문제!

**새로운 접근**:
- 모든 가능한 매수 시점을 전수 조사
- 각 매수 시점에서 N일 보유 시 수익률 계산
- 수익이 나는 패턴의 공통 특성 추출
- 특성 기반 시그널 감지 알고리즘 설계

---

## 📊 Step 1: 브루트포스 전수 분석

### 1.1 타임프레임별 전수 시뮬레이션

**목표**: 모든 캔들에서 매수했을 때 수익률 분포 파악

```python
for each_candle in df:
    buy_price = candle['close']

    for hold_days in [1, 3, 5, 7, 14, 30]:
        sell_price = df[candle_idx + hold_days]['close']
        profit = (sell_price - buy_price) / buy_price

        # 수익률 기록
        results.append({
            'buy_timestamp': candle['timestamp'],
            'buy_price': buy_price,
            'hold_days': hold_days,
            'sell_price': sell_price,
            'profit': profit,
            'profitable': profit > 0.01  # 1% 이상
        })
```

**분석 대상**:
- minute5: 105,123개 캔들 × 6개 보유 기간 = 630,738개 시나리오
- minute15: 67,189개 × 6 = 403,134개
- minute60: 43,791개 × 6 = 262,746개
- minute240: 10,923개 × 6 = 65,538개
- day: 1,793개 × 6 = 10,758개

**총 시나리오**: 1,372,914개

---

### 1.2 수익 창출 지점 식별

**기준**:
1. **최소 수익률**: 1% 이상
2. **최대 손실**: -2% 이하는 제외
3. **Sharpe-like**: (평균 수익) / (변동성) > 1.0

**출력**:
```csv
timestamp,buy_price,hold_days,sell_price,profit,sharpe,max_drawdown
2024-01-01 00:00,50000000,3,51500000,0.03,2.5,-0.01
2024-01-05 12:00,49000000,7,52000000,0.061,3.1,-0.005
...
```

---

## 🔎 Step 2: 수익 패턴 특성 추출

### 2.1 성공 케이스 분석

**수익이 난 매수 시점의 공통점**:

#### A. 기술적 지표 상태
```python
profitable_signals = df[df['profit'] > 0.01]

# 각 지표의 평균/중앙값/분포
rsi_dist = profitable_signals['rsi'].describe()
volume_dist = profitable_signals['volume_ratio'].describe()
bb_position_dist = profitable_signals['bb_position'].describe()
```

**분석 항목**:
- RSI: 과매도/과매수 구간
- Volume: 평균 대비 배수
- BB Position: 밴드 내 위치
- MACD: 골든/데드크로스 전후
- EMA Alignment: 정배열/역배열
- ADX: 추세 강도
- MFI: 자금 흐름
- ATR: 변동성

#### B. 시장 상태 (Day 캔들 기준)
```python
# Layer3 시장 상태 매핑
for signal in profitable_signals:
    day_candle = get_day_candle(signal['timestamp'])
    signal['market_state'] = classify_market(day_candle)
```

**시장 분류**:
- BULL (상승장): MFI > 70, MACD > Signal
- BEAR (하락장): MFI < 30, MACD < Signal
- SIDEWAYS (횡보장): 20일 변동성 < 3%

#### C. 타이밍 특성
```python
# 시간대별 패턴
profitable_signals['hour'] = pd.to_datetime(signals['timestamp']).dt.hour
hourly_dist = profitable_signals.groupby('hour')['profit'].mean()

# 요일별 패턴
profitable_signals['weekday'] = pd.to_datetime(signals['timestamp']).dt.weekday
weekly_dist = profitable_signals.groupby('weekday')['profit'].mean()
```

---

### 2.2 실패 케이스 분석

**손실이 난 매수 시점의 공통점**:

```python
losing_signals = df[df['profit'] < -0.01]

# 손실 케이스의 지표 분포
losing_rsi = losing_signals['rsi'].describe()
losing_volume = losing_signals['volume_ratio'].describe()

# 성공 vs 실패 비교
compare_features(profitable_signals, losing_signals)
```

**회피 패턴 도출**:
- "RSI < 20 AND Volume > 5x AND Day MFI < 30" → 손실 확률 80%
- "BB Position < 0.1 AND MACD < -1000" → 추가 하락 가능성

---

## 🧬 Step 3: 패턴 기반 시그널 설계

### 3.1 Decision Tree 방식

```python
from sklearn.tree import DecisionTreeClassifier

# Feature 준비
X = df[['rsi', 'volume_ratio', 'bb_position', 'macd', 'ema_fast', 'ema_slow', ...]]
y = (df['profit_7d'] > 0.01).astype(int)  # 7일 보유 시 1% 이상 수익

# 결정 트리 학습
clf = DecisionTreeClassifier(max_depth=5, min_samples_leaf=100)
clf.fit(X, y)

# 규칙 추출
from sklearn.tree import export_text
rules = export_text(clf, feature_names=X.columns)
print(rules)
```

**예상 출력**:
```
|--- rsi <= 35.0
|   |--- volume_ratio > 2.0
|   |   |--- bb_position <= 0.3
|   |   |   |--- day_mfi > 50
|   |   |   |   class: BUY (확률 85%)
|   |   |   |--- day_mfi <= 50
|   |   |   |   class: WAIT (확률 45%)
...
```

---

### 3.2 클러스터링 방식

```python
from sklearn.cluster import KMeans

# 수익 케이스 클러스터링
profitable_features = profitable_signals[feature_columns]
kmeans = KMeans(n_clusters=10)
clusters = kmeans.fit_predict(profitable_features)

# 각 클러스터 특성
for i in range(10):
    cluster_data = profitable_signals[clusters == i]
    print(f"Cluster {i}:")
    print(f"  평균 수익: {cluster_data['profit'].mean():.2%}")
    print(f"  승률: {(cluster_data['profit'] > 0).mean():.2%}")
    print(f"  RSI 범위: {cluster_data['rsi'].min():.1f} ~ {cluster_data['rsi'].max():.1f}")
    print(f"  Volume 배수: {cluster_data['volume_ratio'].median():.1f}x")
```

---

### 3.3 상관관계 분석

```python
import seaborn as sns

# Feature 간 상관관계
corr_matrix = profitable_signals[feature_columns].corr()
sns.heatmap(corr_matrix, annot=True, cmap='coolwarm')

# 수익률과의 상관관계
profit_corr = profitable_signals.corr()['profit'].sort_values(ascending=False)
print(profit_corr)
```

**기대 결과**:
- Volume Ratio: 0.45 (강한 양의 상관)
- RSI: -0.32 (낮을수록 수익)
- BB Position: -0.28 (하단 근처일수록 수익)
- Day MFI: 0.51 (상승장일수록 수익)

---

## 🎯 Step 4: 알고리즘 설계

### 4.1 Multi-Condition 시그널

**패턴 1: 강한 반등 (Bounce)**
```python
def signal_strong_bounce(df, i):
    """
    조건:
    - RSI < 30 (과매도)
    - Volume > 2x 평균 (거래량 급증)
    - BB Position < 0.2 (하단 근처)
    - Day MFI > 50 (상승장)
    - 직전 3캔들 연속 하락

    예상 수익: 3일 보유 시 평균 2.5%
    승률: 68%
    """
    if i < 30:
        return False

    cond1 = df.iloc[i]['rsi'] < 30
    cond2 = df.iloc[i]['volume'] > df.iloc[i]['volume_sma'] * 2.0
    cond3 = df.iloc[i]['bb_position'] < 0.2
    cond4 = df.iloc[i]['day_mfi'] > 50
    cond5 = all(df.iloc[i-j]['close'] < df.iloc[i-j-1]['close'] for j in range(3))

    return all([cond1, cond2, cond3, cond4, cond5])
```

**패턴 2: 트렌드 전환 (Reversal)**
```python
def signal_trend_reversal(df, i):
    """
    조건:
    - MACD 골든크로스 직후 (2캔들 이내)
    - ADX > 25 (강한 추세)
    - RSI 30~50 (과매도 탈출)
    - EMA 정배열 전환

    예상 수익: 7일 보유 시 평균 5.1%
    승률: 72%
    """
    if i < 30:
        return False

    # MACD 골든크로스
    macd_cross = (df.iloc[i-1]['macd'] <= df.iloc[i-1]['macd_signal']) and \
                 (df.iloc[i]['macd'] > df.iloc[i]['macd_signal'])

    cond1 = macd_cross or (i >= 1 and df.iloc[i-1]['macd'] > df.iloc[i-1]['macd_signal'])
    cond2 = df.iloc[i]['adx'] > 25
    cond3 = 30 < df.iloc[i]['rsi'] < 50
    cond4 = df.iloc[i]['ema_fast'] > df.iloc[i]['ema_slow']

    return all([cond1, cond2, cond3, cond4])
```

**패턴 3: 상승 모멘텀 (Momentum)**
```python
def signal_momentum_continuation(df, i):
    """
    조건:
    - RSI 50~70 (중립~과열 초입)
    - Volume > 1.5x (지속적 관심)
    - MACD Histogram 증가 (모멘텀 강화)
    - 직전 5캔들 중 4개 상승
    - Day MFI > 60 (강한 상승장)

    예상 수익: 5일 보유 시 평균 3.8%
    승률: 65%
    """
    if i < 30:
        return False

    cond1 = 50 < df.iloc[i]['rsi'] < 70
    cond2 = df.iloc[i]['volume'] > df.iloc[i]['volume_sma'] * 1.5
    cond3 = df.iloc[i]['macd_hist'] > df.iloc[i-1]['macd_hist']

    # 최근 5캔들 중 4개 상승
    recent_ups = sum(1 for j in range(5) if df.iloc[i-j]['close'] > df.iloc[i-j-1]['close'])
    cond4 = recent_ups >= 4

    cond5 = df.iloc[i]['day_mfi'] > 60

    return all([cond1, cond2, cond3, cond4, cond5])
```

---

### 4.2 확률 기반 시그널 (Probabilistic)

```python
def calculate_signal_probability(df, i):
    """
    각 feature의 수익 확률 기여도 계산
    """
    prob = 0.5  # 기본 50%

    # RSI 기여도
    if df.iloc[i]['rsi'] < 30:
        prob += 0.15
    elif df.iloc[i]['rsi'] < 40:
        prob += 0.08
    elif df.iloc[i]['rsi'] > 70:
        prob -= 0.10

    # Volume 기여도
    vol_ratio = df.iloc[i]['volume'] / df.iloc[i]['volume_sma']
    if vol_ratio > 3.0:
        prob += 0.12
    elif vol_ratio > 2.0:
        prob += 0.08
    elif vol_ratio < 0.5:
        prob -= 0.05

    # BB Position 기여도
    bb_pos = df.iloc[i]['bb_position']
    if bb_pos < 0.2:
        prob += 0.10
    elif bb_pos > 0.8:
        prob -= 0.08

    # Day MFI 기여도
    if df.iloc[i]['day_mfi'] > 70:
        prob += 0.18
    elif df.iloc[i]['day_mfi'] > 50:
        prob += 0.10
    elif df.iloc[i]['day_mfi'] < 30:
        prob -= 0.15

    # MACD 기여도
    if df.iloc[i]['macd'] > df.iloc[i]['macd_signal']:
        prob += 0.08

    return min(max(prob, 0.0), 1.0)  # 0~1 범위로 제한

# 사용
prob = calculate_signal_probability(df, i)
if prob > 0.65:  # 65% 이상일 때만 매수
    return 'BUY'
```

---

## 📈 Step 5: 백테스팅 및 검증

### 5.1 시그널 성과 측정

```python
# 각 패턴별 백테스팅
patterns = [
    ('strong_bounce', signal_strong_bounce),
    ('trend_reversal', signal_trend_reversal),
    ('momentum', signal_momentum_continuation)
]

for pattern_name, signal_func in patterns:
    signals = []
    for i in range(len(df)):
        if signal_func(df, i):
            signals.append(i)

    # 성과 계산
    profits = []
    for sig_idx in signals:
        buy_price = df.iloc[sig_idx]['close']
        sell_price = df.iloc[sig_idx + 7]['close']  # 7일 보유
        profit = (sell_price - buy_price) / buy_price
        profits.append(profit)

    print(f"\n{pattern_name}:")
    print(f"  신호 수: {len(signals)}")
    print(f"  평균 수익: {np.mean(profits):.2%}")
    print(f"  승률: {sum(1 for p in profits if p > 0) / len(profits):.2%}")
    print(f"  Sharpe: {np.mean(profits) / np.std(profits):.2f}")
```

---

### 5.2 타임프레임별 최적 패턴 선정

| 타임프레임 | 최적 패턴 | 신호 수 | 평균 수익 | 승률 |
|-----------|----------|---------|----------|------|
| minute5 | Momentum | 8,500 | 1.8% | 62% |
| minute15 | Strong Bounce | 4,200 | 2.5% | 68% |
| minute60 | Trend Reversal | 1,800 | 5.1% | 72% |
| minute240 | Trend Reversal | 420 | 8.2% | 75% |
| day | Trend Reversal | 85 | 12.5% | 78% |

---

## 🎯 예상 결과

### Before (v41 Voting):
- day 시그널: 2개 (0.11%)
- minute240 시그널: 38개 (0.35%)

### After (Bruteforce Pattern):
- day 시그널: **85개 (4.74%)** ✅
- minute240 시그널: **420개 (3.85%)** ✅

### 개선 효과:
- **40배 이상 시그널 증가**
- 수익 확률 기반 필터링으로 **품질 유지**
- 실제 수익 패턴 기반이므로 **오버피팅 방지**

---

## 🚀 구현 순서

1. **Bruteforce 분석 스크립트** (`phase0_bruteforce_analysis.py`)
   - 모든 캔들 × 보유 기간 조합 분석
   - 수익/손실 시나리오 저장

2. **패턴 추출 스크립트** (`phase0_pattern_extraction.py`)
   - 수익 케이스 특성 분석
   - Decision Tree / Clustering
   - 규칙 자동 생성

3. **시그널 알고리즘 구현** (`signals_detected.py`)
   - 추출된 패턴을 Python 함수로 변환
   - 확률 기반 필터링

4. **백테스팅 검증** (`validate_signals.py`)
   - 실제 데이터로 성과 측정
   - 2024년 목표 수익률(170%) 달성 여부 확인

---

## 📅 예상 소요 시간

- Step 1 (Bruteforce): 2~3시간 (1.3M 시나리오)
- Step 2 (패턴 추출): 1~2시간
- Step 3 (알고리즘 설계): 2~3시간
- Step 4 (백테스팅): 1~2시간

**총 예상 시간**: 6~10시간

---

## ✅ 성공 기준

1. ✅ day 타임프레임 시그널 >= 50개
2. ✅ minute240 시그널 >= 300개
3. ✅ 각 패턴 승률 >= 60%
4. ✅ 평균 수익률 >= 2%
5. ✅ Sharpe Ratio >= 1.5
6. ✅ 2024년 백테스팅 수익률 >= 170%

---

**Next**: Step 1 브루트포스 분석 스크립트 작성 시작
