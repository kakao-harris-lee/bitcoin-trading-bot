# Phase 0 고도화: 다차원 시장 분석 계획

## 🎯 목표

단순 보유 분석을 넘어, **실제 트레이딩 가능한 최적 타이밍**을 발굴

---

## 📊 분석 차원 (7가지)

### 1️⃣ **Local Minima/Maxima 분석** (국지적 저점/고점)

**목적**: 구간별 최저가 매수, 최고가 매도 기회 포착

```python
분석 방법:
1. N일 rolling window에서 local minimum 탐지
   - 좌우 K개 캔들보다 낮은 지점
   - K = [3, 5, 10, 20] (다중 기간)

2. Local minimum에서 매수 시뮬레이션
   - 이후 local maximum까지의 수익률 계산
   - 평균 상승폭, 소요 시간 분석

3. Local minimum의 공통 특성 추출
   - RSI 범위, Volume 패턴
   - MACD, BB Position
   - 이전 N일 하락률

예시:
구간 A: 2024-01-05 (local min) → 2024-01-12 (local max)
  - 매수가: 50,000,000원
  - 매도가: 53,500,000원
  - 수익률: +7.0%
  - 소요 기간: 7일
  - RSI(매수 시): 28.5
  - Volume Spike: 3.2x
```

**기대 결과**:
- Local minima 패턴: ~200-500개 (타임프레임별)
- 평균 수익률: 5-15%
- 승률: 70-85%

---

### 2️⃣ **Swing Trading 구간 분석**

**목적**: 상승/하락 스윙의 시작과 끝 포착

```python
스윙 정의:
- 상승 스윙: 연속 N일 상승 후 반전
- 하락 스윙: 연속 N일 하락 후 반전

분석:
1. 하락 스윙 종료 지점 탐지
   - 연속 3-7일 하락 후 첫 반등
   - RSI < 30 탈출
   - MACD 골든크로스

2. 상승 스윙 중간 진입 분석
   - 상승 2-3일차 진입
   - 추세 지속 확률
   - 평균 추가 상승폭

3. 스윙 진폭 분석
   - 평균 하락폭: -X%
   - 평균 상승폭: +Y%
   - 스윙 주기: Z일

예시:
스윙 #1 (하락):
  2024-01-01 ~ 2024-01-05: -12% 하락
  반전 시그널: 2024-01-06 (RSI 25→32, Volume 2.5x)
  이후 상승: 2024-01-06 ~ 2024-01-15: +18%

스윙 #2 (상승):
  2024-02-01 ~ 2024-02-10: +22% 상승
  진입 지점 분석:
    - 2일차 진입 → +18% 추가 상승
    - 5일차 진입 → +8% 추가 상승
```

**기대 결과**:
- 스윙 사이클: 50-100개/년
- 하락 스윙 반전 포착률: 60-70%
- 상승 스윙 추가 수익: 평균 +8-12%

---

### 3️⃣ **Support/Resistance 레벨 분석**

**목적**: 주요 가격대 지지/저항선 식별

```python
분석 방법:
1. 과거 90일 데이터에서 자주 터치된 가격대 추출
   - Clustering (DBSCAN)
   - 3회 이상 터치 → Support/Resistance

2. 지지선 근처 매수 시나리오
   - 지지선 ±2% 도달 시 매수
   - 반등 확률 및 평균 반등폭

3. 저항선 돌파 시나리오
   - 저항선 돌파 + Volume 증가
   - 돌파 후 추가 상승 확률

예시:
Support Level: 50,000,000원
  - 터치 횟수: 5회 (2024년 내)
  - 반등 성공: 4/5 (80%)
  - 평균 반등폭: +6.5%

Resistance Level: 58,000,000원
  - 돌파 성공: 2/4 (50%)
  - 돌파 후 평균 상승: +12%
  - 실패 시 평균 하락: -3%
```

**기대 결과**:
- Support/Resistance 레벨: 10-20개
- 지지선 반등 승률: 70-80%
- 저항선 돌파 시 평균 수익: 10-15%

---

### 4️⃣ **Volatility Regime 분석** (변동성 국면)

**목적**: 시장 변동성 변화에 따른 전략 최적화

```python
변동성 분류:
1. Low Volatility (ATR < 2%)
   - 횡보장
   - 범위 거래 (Range Trading)

2. Medium Volatility (ATR 2-5%)
   - 정상 트렌드
   - 추세 추종 전략

3. High Volatility (ATR > 5%)
   - 급등/급락
   - 역추세 전략 (Mean Reversion)

분석:
- 각 regime에서 최적 전략 식별
- Regime 전환 시점 포착
- Regime별 수익률, 승률, MDD

예시:
Low Vol 구간 (2024-03-01 ~ 2024-03-20):
  - ATR 평균: 1.8%
  - 최적 전략: Range Trading (지지/저항 반복)
  - 평균 수익: +2.5% (10회 거래)

High Vol 구간 (2024-05-10 ~ 2024-05-25):
  - ATR 평균: 8.2%
  - 최적 전략: Mean Reversion (급락 후 반등)
  - 평균 수익: +12% (3회 거래)
```

**기대 결과**:
- Low Vol 전략 승률: 65-75%
- High Vol 전략 수익률: 10-20%
- Regime 전환 포착률: 70%

---

### 5️⃣ **Multi-Timeframe Confluence** (다중 시간대 일치)

**목적**: 여러 시간대에서 동시 시그널 발생 시 강력한 기회

```python
분석 방법:
1. 동일 시점을 여러 timeframe에서 분석
   - minute5: 단기 과매도
   - minute60: 상승 추세 시작
   - day: BULL 시장

2. Confluence Score 계산
   - 3개 이상 timeframe 일치 → Strong Signal
   - 2개 일치 → Moderate Signal
   - 1개만 → Weak Signal

3. Confluence별 성과 분석
   - Strong Signal 승률, 평균 수익
   - Weak Signal 성과 비교

예시:
2024-06-15 12:00:
  - minute5: RSI 28 (과매도) ✅
  - minute60: MACD 골든크로스 ✅
  - minute240: EMA 정배열 ✅
  - day: MFI 68 (상승장) ✅
  → Confluence Score: 4/4 (Strong Signal)
  → 실제 수익: 7일 후 +15.2%

2024-07-20 09:00:
  - minute5: RSI 32 ✅
  - minute60: MACD 데드크로스 ❌
  - day: MFI 45 (중립) ⚠️
  → Confluence Score: 1/3 (Weak Signal)
  → 실제 수익: 7일 후 -2.1%
```

**기대 결과**:
- Strong Confluence 시그널: 50-100개/년
- Strong 승률: 80-90%
- Strong 평균 수익: 10-20%

---

### 6️⃣ **Mean Reversion Distance** (평균 회귀 거리)

**목적**: 과도한 이탈 후 평균 복귀 기회 포착

```python
분석 방법:
1. 이동평균선(MA20, MA50, MA200)과의 거리 계산
   - Distance = (Price - MA) / MA

2. 극단적 이탈 지점 탐지
   - Distance < -10% (과도한 하락)
   - Distance > +15% (과도한 상승)

3. 복귀 시나리오 분석
   - 평균 복귀 시간
   - 복귀 확률
   - 오버슈팅(추가 이탈) 빈도

예시:
2024-08-10:
  Price: 45,000,000원
  MA20: 52,000,000원
  Distance: -13.5% (극단 하락)

  이후 7일:
    Day 1: 46,000,000 (-11.5%)
    Day 3: 49,000,000 (-5.8%)
    Day 7: 52,500,000 (+1.0%, 평균 복귀 완료)

  수익률: +16.7% (7일간)
```

**기대 결과**:
- 극단 이탈 케이스: 100-200개/년
- 평균 복귀 확률: 75-85%
- 평균 수익률: 8-15%

---

### 7️⃣ **Momentum Breakout** (모멘텀 돌파)

**목적**: 강한 상승 모멘텀 초기 포착

```python
분석 방법:
1. N일 최고가 돌파 탐지
   - 20일 최고가 갱신
   - 50일 최고가 갱신
   - Volume 급증 (2x 이상)

2. 돌파 후 지속 패턴 분석
   - 돌파 후 추가 상승 기간
   - 평균 추가 상승폭
   - 허위 돌파 (False Breakout) 비율

3. 돌파 강도 측정
   - Volume 배수
   - RSI 상승 속도
   - MACD Histogram 증가율

예시:
2024-09-05:
  - 20일 최고가 돌파 ✅
  - Volume: 3.5x ✅
  - RSI: 45→62 (급상승) ✅
  - MACD Hist: +20% 증가 ✅
  → Strong Breakout

  이후 14일:
    +28% 상승
    MDD: -3% (소폭 조정)
```

**기대 결과**:
- Strong Breakout: 30-50개/년
- 승률: 65-75%
- 평균 수익: 15-30%

---

## 🧪 종합 분석 프레임워크

### Phase 1: 7가지 차원 전수 분석
```python
for candle in df:
    # 1. Local Min/Max
    is_local_min = check_local_minimum(df, i)

    # 2. Swing
    swing_type = detect_swing(df, i)

    # 3. Support/Resistance
    near_support = check_support_level(df, i)
    near_resistance = check_resistance_level(df, i)

    # 4. Volatility Regime
    vol_regime = classify_volatility(df, i)

    # 5. Multi-TF Confluence
    confluence_score = calculate_confluence(df, i)

    # 6. Mean Reversion
    ma_distance = calculate_ma_distance(df, i)

    # 7. Momentum Breakout
    breakout_strength = detect_breakout(df, i)

    # 종합 점수
    total_score = weighted_sum([
        is_local_min * 0.20,
        swing_type * 0.15,
        near_support * 0.15,
        vol_regime * 0.10,
        confluence_score * 0.25,
        ma_distance * 0.10,
        breakout_strength * 0.05
    ])

    if total_score > 0.65:  # 65점 이상
        signals.append({
            'timestamp': candle['timestamp'],
            'score': total_score,
            'components': {...}
        })
```

---

### Phase 2: 차원별 최적 조합 탐색

```python
# 단일 차원 성과
local_min_only: 승률 72%, 수익 8.5%
confluence_only: 승률 78%, 수익 12.2%

# 2차원 조합
local_min + confluence: 승률 85%, 수익 15.8%
swing + support: 승률 68%, 수익 10.2%

# 3차원 조합
local_min + confluence + low_vol: 승률 88%, 수익 18.5%

# 최적 조합 (Top 5)
1. local_min + confluence + mean_reversion: 승률 90%, 수익 22%
2. confluence + breakout + high_vol: 승률 82%, 수익 28%
3. swing + support + low_vol: 승률 85%, 수익 12%
4. local_min + near_support + ma_distance: 승률 87%, 수익 16%
5. confluence + swing + breakout: 승률 79%, 수익 25%
```

---

### Phase 3: 시그널 강도 분류

```python
Signal Strength:

S-Tier (최고):
  - 조건: 5개 이상 차원 충족
  - 예상 승률: 90%+
  - 예상 수익: 20%+
  - 빈도: 10-20개/년

A-Tier (강력):
  - 조건: 4개 차원 충족
  - 예상 승률: 80-85%
  - 예상 수익: 12-18%
  - 빈도: 50-80개/년

B-Tier (양호):
  - 조건: 3개 차원 충족
  - 예상 승률: 70-75%
  - 예상 수익: 8-12%
  - 빈도: 150-200개/년

C-Tier (보통):
  - 조건: 2개 차원 충족
  - 예상 승률: 55-65%
  - 예상 수익: 5-8%
  - 빈도: 300-400개/년
```

---

## 📊 타임프레임별 최적 차원

| 타임프레임 | 1순위 | 2순위 | 3순위 |
|-----------|------|------|------|
| minute5 | Momentum Breakout | Local Min | Confluence |
| minute15 | Swing | Local Min | Volatility |
| minute60 | Confluence | Mean Reversion | Support |
| minute240 | Mean Reversion | Confluence | Swing |
| day | Confluence | Breakout | Support |

---

## 🎯 예상 결과

### Day 타임프레임 (기존 vs 개선)

**기존 (단순 보유)**:
- 시그널: 973개 (55% 승률)
- 평균 수익: 6.46%

**개선 (7차원 분석)**:

| Tier | 시그널 수 | 승률 | 평균 수익 | 연간 수익 기여 |
|------|---------|------|----------|-------------|
| S-Tier | 15개 | 92% | 25% | +34.5% |
| A-Tier | 65개 | 83% | 15% | +80.9% |
| B-Tier | 180개 | 72% | 10% | +129.6% |
| C-Tier | 350개 | 58% | 6% | +121.8% |
| **합계** | **610개** | **68%** | **10.8%** | **+366.8%** |

**Buy&Hold 대비**: +366.8% vs 147.5% = **+219.3%p 초과 달성** ✅

---

## 🚀 구현 계획

### Step 1: 7차원 분석 스크립트 작성
```bash
phase0_advanced_analysis.py
- Local minima/maxima 탐지
- Swing 구간 분석
- Support/Resistance 추출
- Volatility regime 분류
- Multi-TF confluence 계산
- Mean reversion distance
- Momentum breakout 탐지
```

### Step 2: 차원별 성과 평가
```bash
phase0_dimension_evaluation.py
- 각 차원별 단독 성과
- 2-3차원 조합 성과
- 최적 조합 탐색 (Genetic Algorithm)
```

### Step 3: 시그널 등급화
```bash
phase0_signal_ranking.py
- S/A/B/C Tier 분류
- Tier별 백테스팅
- 최종 시그널 리스트 생성
```

### Step 4: 최종 전략 설계
```bash
v42_advanced_signals.py
- 7차원 통합 시그널
- Tier별 포지션 사이징
- 동적 Stop-Loss/Take-Profit
```

---

## ⏱️ 예상 소요 시간

- Step 1: 4-6시간 (구현 + 테스트)
- Step 2: 2-3시간 (조합 평가)
- Step 3: 1-2시간 (등급화)
- Step 4: 2-3시간 (전략 통합)

**총 예상**: 9-14시간

---

## ✅ 성공 기준

1. ✅ Day 타임프레임 S-Tier 시그널 >= 10개
2. ✅ A-Tier 이상 평균 승률 >= 80%
3. ✅ 2024년 백테스팅 수익률 >= 300%
4. ✅ MDD < 15%
5. ✅ Sharpe Ratio >= 2.0

---

**다음**: Step 1 구현 시작 (7차원 분석 스크립트)
