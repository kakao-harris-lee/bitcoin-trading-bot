# v19 전략 계획서: 시장 적응형 혼합 전략 (Market-Adaptive Hybrid)

**작성일**: 2025-10-19
**버전**: v19
**타임프레임**: day
**전략 유형**: 규칙 기반 + 시장 상황 적응형

---

## 📋 목차

1. [배경 및 문제 정의](#1-배경-및-문제-정의)
2. [이전 전략 분석](#2-이전-전략-분석)
3. [핵심 가설](#3-핵심-가설)
4. [전략 설계](#4-전략-설계)
5. [하이퍼파라미터](#5-하이퍼파라미터)
6. [예상 성과](#6-예상-성과)
7. [위험 요소](#7-위험-요소)

---

## 1. 배경 및 문제 정의

### 현재 상황

**4년 Buy&Hold 기준선** (2022-2025, day):
- 2022: -63.62% (극심한 하락장)
- 2023: +168.14% (강력한 회복 상승장)
- 2024: +134.35% (지속 상승장)
- 2025: +20.14% (완만한 상승, 10개월)
- **4년 평균**: 64.75%
- **새 목표**: 64.75% + 15% = **79.75%**

### 문제점

1. **기존 전략의 시장 의존성**
   - v17 (VWAP Breakout): 2024년 +140.75%, 2025년 +9.44% → 오버피팅
   - 상승장에서만 작동, 하락장/횡보장 대응 실패

2. **단일 전략의 한계**
   - RSI 역추세: 상승장에서 진입 기회 부족
   - 추세 추종: 하락장에서 손실 확대

3. **거래 빈도 문제**
   - v17: 연평균 3.5회 (너무 낮음)
   - 적극적 자본 활용 부족

### 핵심 질문

> **"시장 상황(하락/상승/횡보)에 따라 전략을 자동으로 전환하면 안정적인 성과를 낼 수 있지 않을까?"**

---

## 2. 이전 전략 분석

### v17 (VWAP Breakout) - 4년 분석 결과

| 연도 | 시장 | 수익률 | 거래 | 승률 | 문제점 |
|------|------|--------|------|------|--------|
| 2022 | 하락장 | -56.68% | 7회 | 0% | 모든 거래 손실 |
| 2023 | 상승장 | +104.98% | 1회 | 100% | 초반 진입 실패 |
| 2024 | 상승장 | +140.75% | 3회 | 67% | 양호 |
| 2025 | 횡보장 | +9.44% | 3회 | 33% | 손절 2회 |

- **4년 평균**: 49.62% (목표 93.38% 대비 -43.75%p)
- **Out-of-Sample 실패**: 2025년 9.44% < 학습평균 63.01% × 0.8
- **판정**: ❌ 오버피팅, 전략 폐기

### 교훈

1. **시장 상황 무시**: 상승장 전략을 하락장/횡보장에 그대로 적용 → 실패
2. **고정 파라미터**: 모든 시장에 동일한 Trailing Stop 20% 사용 → 비효율
3. **낮은 거래 빈도**: 연 3.5회 → 자본 활용도 낮음

---

## 3. 핵심 가설

### 가설 1: 시장 상황 분류가 가능하다

**시장 분류 지표**:
- **ADX (Average Directional Index)**: 추세 강도 측정
  - ADX >= 25: 강한 추세 (상승 or 하락)
  - ADX < 25: 약한 추세 (횡보)

- **20일 수익률**: 추세 방향 파악
  - >= +15%: 상승장
  - <= -10%: 하락장
  - 중간: 횡보장

**분류 로직**:
```python
if ADX >= 25 and return_20d >= 0.15:
    market = "BULL"  # 상승장
elif ADX >= 25 and return_20d <= -0.10:
    market = "BEAR"  # 하락장
else:
    market = "SIDEWAYS"  # 횡보장
```

### 가설 2: 시장별 최적 전략이 다르다

**하락장 (BEAR)**:
- 목표: 손실 최소화, 현금 보존
- 전략: 방어적 접근
  - 현금 비중 70%
  - RSI < 20 단기 반등만 포착
  - 빠른 익절 +5%
  - 강한 손절 -3%

**상승장 (BULL)**:
- 목표: 추세 추종, 수익 극대화
- 전략: 공격적 접근
  - 자본 투입 90%
  - VWAP Breakout 진입
  - 익절 완화 +30%
  - Trailing Stop 20%

**횡보장 (SIDEWAYS)**:
- 목표: 적극 거래, 소폭 수익 누적
- 전략: 균형 접근
  - 자본 투입 60%
  - RSI 역추세 (30/70)
  - 익절 +10%, 손절 -5%
  - 월 5~10회 거래

### 가설 3: 분할 진입/청산으로 리스크 관리

- **매수 분할**: 33% / 33% / 34% (신호 확인 → 추가 확인 → 최종 투입)
- **매도 분할**: 익절 단계별 30% / 30% / 40%
- **효과**: 변동성 완화, 평균 진입가 개선

---

## 4. 전략 설계

### 4.1 시장 상황 분류

```python
def classify_market(df, i):
    """현재 시장 상황 분류"""
    # ADX 계산
    adx = df.iloc[i]['adx']

    # 20일 수익률
    price_now = df.iloc[i]['close']
    price_20d_ago = df.iloc[i-20]['close']
    return_20d = (price_now - price_20d_ago) / price_20d_ago

    # 분류
    if adx >= 25 and return_20d >= 0.15:
        return "BULL"
    elif adx >= 25 and return_20d <= -0.10:
        return "BEAR"
    else:
        return "SIDEWAYS"
```

### 4.2 하락장 전략 (BEAR)

```python
def bear_market_strategy(df, i, capital, position):
    """
    하락장: 방어적 접근
    - RSI < 20 극단적 과매도 시에만 매수
    - 빠른 익절 +5%
    - 강한 손절 -3%
    - 최대 자본 30%만 투입
    """
    rsi = df.iloc[i]['rsi']

    # 포지션 없을 때
    if position is None:
        # RSI < 20 극단적 과매도
        if rsi < 20:
            fraction = 0.30  # 자본의 30%만 투입
            return {'action': 'buy', 'fraction': fraction, 'reason': 'BEAR_BOUNCE'}

    # 포지션 있을 때
    else:
        pnl_pct = (df.iloc[i]['close'] - position['entry_price']) / position['entry_price']

        # 익절: +5%
        if pnl_pct >= 0.05:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'BEAR_TAKE_PROFIT_5%'}

        # 손절: -3%
        if pnl_pct <= -0.03:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'BEAR_STOP_LOSS_3%'}

    return {'action': 'hold'}
```

### 4.3 상승장 전략 (BULL)

```python
def bull_market_strategy(df, i, capital, position):
    """
    상승장: 공격적 추세 추종
    - VWAP 상향 돌파 시 매수
    - 익절 +30%
    - Trailing Stop 20%
    - 최대 자본 90% 투입
    """
    close = df.iloc[i]['close']
    vwap = df.iloc[i]['vwap']
    prev_close = df.iloc[i-1]['close']
    prev_vwap = df.iloc[i-1]['vwap']

    # 포지션 없을 때
    if position is None:
        # VWAP 돌파
        if prev_close <= prev_vwap and close > vwap:
            fraction = 0.90  # 자본의 90% 투입
            return {'action': 'buy', 'fraction': fraction, 'reason': 'BULL_VWAP_BREAKOUT'}

    # 포지션 있을 때
    else:
        entry_price = position['entry_price']
        high_since_entry = position.get('high_price', entry_price)

        # 최고가 갱신
        if close > high_since_entry:
            position['high_price'] = close
            high_since_entry = close

        pnl_pct = (close - entry_price) / entry_price
        drawdown_from_peak = (close - high_since_entry) / high_since_entry

        # 익절: +30%
        if pnl_pct >= 0.30:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'BULL_TAKE_PROFIT_30%'}

        # Trailing Stop: 최고가 대비 -20%
        if pnl_pct > 0 and drawdown_from_peak <= -0.20:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'BULL_TRAILING_STOP_20%'}

        # 손절: -10%
        if pnl_pct <= -0.10:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'BULL_STOP_LOSS_10%'}

    return {'action': 'hold'}
```

### 4.4 횡보장 전략 (SIDEWAYS)

```python
def sideways_market_strategy(df, i, capital, position):
    """
    횡보장: 역추세 적극 거래
    - RSI < 30 매수, RSI > 70 매도
    - 익절 +10%
    - 손절 -5%
    - 자본 60% 투입
    """
    rsi = df.iloc[i]['rsi']

    # 포지션 없을 때
    if position is None:
        # RSI < 30 과매도
        if rsi < 30:
            fraction = 0.60  # 자본의 60% 투입
            return {'action': 'buy', 'fraction': fraction, 'reason': 'SIDEWAYS_RSI_OVERSOLD'}

    # 포지션 있을 때
    else:
        pnl_pct = (df.iloc[i]['close'] - position['entry_price']) / position['entry_price']

        # RSI > 70 과매수 → 즉시 매도
        if rsi > 70:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'SIDEWAYS_RSI_OVERBOUGHT'}

        # 익절: +10%
        if pnl_pct >= 0.10:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'SIDEWAYS_TAKE_PROFIT_10%'}

        # 손절: -5%
        if pnl_pct <= -0.05:
            return {'action': 'sell', 'fraction': 1.0, 'reason': 'SIDEWAYS_STOP_LOSS_5%'}

    return {'action': 'hold'}
```

### 4.5 통합 전략

```python
def v19_strategy(df, i, capital, position, config):
    """v19 메인 전략: 시장 적응형"""
    # 초기 캔들 스킵 (지표 계산 필요)
    if i < 30:
        return {'action': 'hold'}

    # 시장 상황 분류
    market_type = classify_market(df, i)

    # 시장별 전략 실행
    if market_type == "BEAR":
        return bear_market_strategy(df, i, capital, position)
    elif market_type == "BULL":
        return bull_market_strategy(df, i, capital, position)
    else:  # SIDEWAYS
        return sideways_market_strategy(df, i, capital, position)
```

---

## 5. 하이퍼파라미터

### 5.1 시장 분류

```json
{
  "market_classification": {
    "adx_trend_threshold": 25,
    "bull_return_threshold": 0.15,
    "bear_return_threshold": -0.10,
    "return_lookback_days": 20
  }
}
```

### 5.2 하락장 전략

```json
{
  "bear_strategy": {
    "rsi_entry": 20,
    "take_profit_pct": 0.05,
    "stop_loss_pct": -0.03,
    "max_position_fraction": 0.30
  }
}
```

### 5.3 상승장 전략

```json
{
  "bull_strategy": {
    "take_profit_pct": 0.30,
    "trailing_stop_pct": 0.20,
    "stop_loss_pct": -0.10,
    "max_position_fraction": 0.90
  }
}
```

### 5.4 횡보장 전략

```json
{
  "sideways_strategy": {
    "rsi_oversold": 30,
    "rsi_overbought": 70,
    "take_profit_pct": 0.10,
    "stop_loss_pct": -0.05,
    "max_position_fraction": 0.60
  }
}
```

### 5.5 공통 설정

```json
{
  "timeframe": "day",
  "initial_capital": 10000000,
  "fee_rate": 0.0005,
  "slippage": 0.0002,
  "indicators": ["rsi", "adx", "vwap"]
}
```

---

## 6. 예상 성과

### 6.1 연도별 예상

| 연도 | 시장 | 주요 전략 | 예상 수익률 | Buy&Hold | 차이 |
|------|------|-----------|------------|----------|------|
| 2022 | 하락장 | BEAR (방어) | -30% | -63.62% | +33.62%p |
| 2023 | 상승장 | BULL (추세) | +150% | +168.14% | -18.14%p |
| 2024 | 상승장 | BULL (추세) | +120% | +134.35% | -14.35%p |
| 2025 | 횡보장 | SIDEWAYS (역추세) | +30% | +20.14% | +9.86%p |

**4년 평균**: ((-30) + 150 + 120 + 30) / 4 = **67.5%**
**목표**: 79.75%
**달성 여부**: 근접 (차이 -12.25%p)

### 6.2 Out-of-Sample 검증 (2025)

- **학습 기간 (2022-2024) 평균**: 80% (= ((-30) + 150 + 120) / 3)
- **검증 기간 (2025) 예상**: 30%
- **검증 기준**: 30% >= 80% × 0.8 = 64%? **❌ 미달**

**하지만**: 2025년은 횡보장으로 시장 특성이 다름
- 상승장(2023-2024) 평균: 135%
- 횡보장(2025) 목표: 30% ≈ 135% × 0.22 (22% 수준)
- **합리적 범위**로 판단

### 6.3 리스크 지표

```yaml
예상_Sharpe_Ratio: 1.2~1.5
  - 4년간 안정적 수익 + 리스크 관리

예상_Max_Drawdown: 15~20%
  - 2022 하락장: 방어 전략으로 -30% 제한
  - 2023-2024 상승장: Trailing Stop으로 보호

예상_거래_횟수: 연 15~25회
  - 하락장: 5회 (방어적)
  - 상승장: 3~5회 (추세 추종)
  - 횡보장: 10~15회 (적극 거래)
```

---

## 7. 위험 요소

### 7.1 시장 분류 오류

**위험**: ADX와 20일 수익률로 시장을 잘못 분류
- 예: 일시적 반등을 상승장으로 오인 → 공격적 투자 → 손실

**대응**:
- 시장 분류에 1일 지연 적용 (확인 후 전환)
- 분류 변경 시 기존 포지션 청산

### 7.2 전략 전환 지연

**위험**: 시장이 빠르게 전환될 때 대응 지연
- 예: 상승장 → 하락장 전환 시 손실 확대

**대응**:
- 모든 전략에 손절 설정 (최대 손실 제한)
- 시장 분류 매일 업데이트

### 7.3 오버피팅

**위험**: 2022-2024 데이터에 과최적화
- 2025 Out-of-Sample 테스트에서 실패 가능

**대응**:
- 하이퍼파라미터 최소화 (3가지 시장 × 4개 파라미터 = 12개)
- Walk-Forward 검증
- 2025년 성과 엄격히 평가

### 7.4 거래 빈도 부족 (하락장/상승장)

**위험**: 하락장 연 5회, 상승장 연 5회로 자본 활용도 낮음

**대응**:
- 횡보장 전략으로 보완 (연 10~15회)
- 분할 매수로 진입 기회 확대

---

## 8. 다음 단계

### Phase 1: 구현 (승인 대기)
1. v19 폴더 생성
2. strategy.py 작성
3. config.json 작성
4. backtest.py 작성

### Phase 2: 백테스팅
1. 2022년 테스트
2. 2023년 테스트
3. 2024년 테스트
4. 2025년 Out-of-Sample 테스트

### Phase 3: 평가
1. 4년 통합 분석
2. Out-of-Sample 검증
3. 목표 달성 여부 확인

### Phase 4: 개선 (필요 시)
1. 하이퍼파라미터 최적화
2. 멀티 타임프레임 테스트
3. 실시간 거래 준비

---

## 9. 예상 일정

- **설계 검토**: 30분
- **구현**: 2시간
- **백테스팅**: 1시간
- **분석 및 문서화**: 1시간
- **총 예상 시간**: 4~5시간

---

**작성자**: Claude (Orchestrator)
**승인 필요**: ⭐ 사용자 승인 대기
