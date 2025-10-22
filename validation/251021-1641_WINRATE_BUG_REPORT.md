# Universal Evaluation Engine - 승률 계산 버그 리포트

**생성일**: 2025-10-21 16:41
**심각도**: ⚠️ **High** (모든 전략 승률 0% 오류)
**상태**: 🔍 분석 완료, 수정 대기

---

## 📋 문제 요약

Universal Evaluation Engine의 승률 계산 로직에 치명적 버그 발견:
- **모든 전략의 승률이 0%로 보고됨**
- 총 수익률은 양수인데 개별 거래는 모두 손실로 기록
- 수동 계산 결과와 **39-50%p 차이**

---

## 🔍 검증 방법

3개 전략에 대해 수동 계산으로 개별 거래 추적:

### 1. v_simple_rsi (Day, 14d holding)

**엔진 결과** (잘못됨):
```
승률: 0.0% (0승 28패)
평균 수익률: -47.78%
총 수익률: +79.65%
```

**수동 계산** (정확함):
```
승률: 39.29% (11승 17패)
평균 수익률: +0.43%
총 수익률: +11.92%
```

**차이**: 승률 **+39.29%p**, 총 수익률 **-67.73%p**

### 2. v_momentum (Day, 14d holding)

**엔진 결과** (잘못됨):
```
승률: 0.0% (0승 22패)
평균 수익률: -43.66%
총 수익률: +277.51%
```

**수동 계산** (정확함):
```
승률: 50.00% (11승 11패)
평균 수익률: +1.32%
총 수익률: +28.98%
```

**차이**: 승률 **+50.00%p**, 총 수익률 **-248.53%p**

### 3. v_volume_spike (Minute240, 3d holding)

**엔진 결과** (잘못됨):
```
승률: 0.0% (0승 72패)
평균 수익률: -49.45%
총 수익률: +46.68%
```

**수동 계산** (정확함):
```
승률: 38.89% (28승 44패)
평균 수익률: +0.30%
총 수익률: +21.81%
```

**차이**: 승률 **+38.89%p**, 총 수익률 **-24.87%p**

---

## 🐛 원인 분석

### 문제 코드 위치

**파일**: `validation/universal_evaluation_engine.py`

#### 라인 404: 수익률 계산
```python
return_pct = (sell_revenue - position.capital_at_entry) / position.capital_at_entry * 100
```

#### 라인 364: Capital 차감
```python
capital -= entry_amount
```

#### 라인 509-510: 승패 판정
```python
winning_trades = [t for t in trades if t.return_pct > 0]
losing_trades = [t for t in trades if t.return_pct <= 0]
```

### 의심되는 원인

**가설 1**: `position.capital_at_entry`가 진입 금액이 아니라 **전체 capital**을 저장하고 있음

```python
# 라인 353-362
position = Position(
    entry_time=signal.timestamp,
    entry_price=signal.price,
    btc_amount=btc_amount,
    capital_at_entry=capital,  # ← 이게 문제?
    ...
)
```

**검증**:
- 만약 `capital_at_entry`가 진입 후 남은 capital (예: 0원)이면:
  - `return_pct = (9,782,368 - 0) / 0 * 100` → 무한대 또는 오류
- 만약 `capital_at_entry`가 진입 전 capital (10M)이면:
  - `return_pct = (9,782,368 - 10,000,000) / 10,000,000 * 100` = **-2.18%** ✅ (수동 계산과 일치)

**하지만 엔진 결과는 -47.78%** → 뭔가 다른 문제가 있음!

**가설 2**: 수수료 중복 차감 또는 BTC 양 계산 오류

**라인 349-351**:
```python
entry_amount = capital * fraction  # 10,000,000
entry_fee = entry_amount * self.total_fee  # 9,000 (0.09%)
btc_amount = (entry_amount - entry_fee) / signal.price  # 올바름
```

**라인 398-400**:
```python
sell_amount = position.btc_amount * exit_price
sell_fee = sell_amount * self.total_fee
sell_revenue = sell_amount - sell_fee  # 올바름
```

→ 수수료 계산은 정상

**가설 3**: `capital_at_entry`가 잘못된 시점의 capital을 저장

**라인 364**:
```python
capital -= entry_amount  # 진입 후 capital 차감
```

그런데 **라인 357**에서:
```python
capital_at_entry=capital,  # ← 차감 전 capital!
```

→ 이것도 정상

### 🚨 실제 원인 (추정)

엔진이 **복리 재투자** 방식으로 작동하고 있음:

1. 첫 거래: capital = 10M → 진입 10M
2. 첫 거래 종료: capital = 10M (그대로) + sell_revenue
3. **두 번째 거래**: capital이 증가한 상태 → `entry_amount = capital * 1.0` = 11M 투입?

→ 하지만 수동 계산에서는 **고정 10M 투입**

**확인 필요**: 엔진이 Fixed Position (100%)을 **전체 capital의 100%**로 해석하는지 확인

---

## 📝 수동 계산 상세 (v_simple_rsi 샘플)

### 거래 1 (패배)
```
매수: 2024-01-22 @ 54,689,000원
투입: 10,000,000원
수수료 (진입): 9,000원 (0.09%)
BTC 매수: 0.18269 BTC

매도: 2024-01-23 @ 53,595,220원 (STOP_LOSS -2%)
BTC 매도 금액: 9,791,180원
수수료 (청산): 8,812원 (0.09%)
회수: 9,782,368원

손익: -217,632원 (-2.18%)
총 수수료: 17,812원
```

**엔진 평균 손실**: -47.78%
**실제 손실**: -2.18%
**차이**: -45.60%p → **20배 이상 과대평가!**

### 거래 2 (승리)
```
매수: 2024-01-23 @ 55,389,000원
투입: 10,000,000원
BTC 매수: 0.18022 BTC

매도: 2024-01-27 @ 58,158,450원 (TAKE_PROFIT +5%)
BTC 매도 금액: 10,481,109원
수수료: 18,441원
회수: 10,481,109원

손익: +481,109원 (+4.81%)
```

**엔진 평균 승리**: 0.00원 (승리 0건)
**실제 승리**: +4.81%
**차이**: 완전히 누락!

---

## 💥 영향도 분석

### 1. 승률 계산

**모든 전략**: 0% 승률
- Sharpe Ratio 계산 왜곡 (음수)
- 전략 신뢰도 평가 불가능
- 최적 holding period 선택 오류 가능

### 2. 수익률 계산

**총 수익률**도 과대평가:
- v_simple_rsi: 엔진 79.65% vs 실제 11.92% (**6.7배 차이**)
- v_momentum: 엔진 277.51% vs 실제 28.98% (**9.6배 차이**)
- v_volume_spike: 엔진 46.68% vs 실제 21.81% (**2.1배 차이**)

### 3. 전략 비교

잘못된 지표로 전략 순위 결정:
- 엔진 기준 최고 전략: v_momentum (277%)
- 실제 최고 전략: v_momentum (28.98%) - 우연히 일치
- 하지만 수치는 **9.6배 과대평가**

### 4. 플러그인 검증

Exit Strategy 플러그인 검증 무효:
- Fixed TP/SL이 작동하는지 확인 불가
- Trailing Stop 효과 측정 불가
- Timeout 로직 검증 불가

---

## ✅ 수동 계산 검증 결과

### 계산 방법

**수수료**:
```python
TRADING_FEE = 0.0005  # 0.05%
SLIPPAGE = 0.0004     # 0.04%
TOTAL_FEE = 0.0009    # 0.09%
```

**진입**:
```python
entry_amount = 10,000,000
entry_fee = entry_amount * 0.0009 = 9,000원
btc_amount = (10,000,000 - 9,000) / entry_price
```

**청산**:
```python
sell_amount = btc_amount * exit_price
sell_fee = sell_amount * 0.0009
sell_revenue = sell_amount - sell_fee
```

**수익률**:
```python
profit = sell_revenue - entry_amount
return_pct = (profit / entry_amount) * 100
```

**승패 판정**:
```python
is_win = return_pct > 0
```

### 검증 도구

**스크립트**: `validation/verify_winrate_calculation.py`
- 3개 전략 × 최적 holding period 검증
- 개별 거래 상세 추적
- 엔진 결과와 비교

**실행**:
```bash
python validation/verify_winrate_calculation.py
```

**출력**:
- 거래 통계 (승률, 평균 수익률)
- 청산 사유 분포
- 샘플 거래 10개 상세 내역
- 엔진 결과와 차이 비교

---

## 🔧 권장 조치

### 즉시 (Priority 1)

1. **`capital_at_entry` 값 확인**
   - Position 생성 시점에 정확한 값 저장하는지 디버깅
   - 첫 거래 vs 두 번째 거래 비교

2. **수익률 계산 로직 검증**
   - `return_pct` 계산식 재확인
   - 첫 3개 거래 디버그 출력 추가

3. **Fixed Position 플러그인 확인**
   - `fraction = 1.0`이 전체 capital의 100%인지 확인
   - 고정 금액 모드 추가 필요성 검토

### 단기 (Priority 2)

4. **Trade 객체 로깅**
   - 모든 거래를 CSV/JSON으로 저장
   - entry_amount, sell_revenue, return_pct 모두 기록
   - 수동 검증 용이하게

5. **Unit 테스트 추가**
   - 단일 거래 시뮬레이션 테스트
   - 알려진 가격 데이터로 예상 수익률 검증
   - 수수료 계산 정확도 테스트

### 중기 (Priority 3)

6. **수동 계산 스크립트 통합**
   - `verify_winrate_calculation.py`를 테스트 스위트에 추가
   - CI/CD에서 자동 검증

7. **문서화**
   - 수익률 계산 공식 명확히 문서화
   - capital_at_entry의 정확한 의미 정의

---

## 📊 예상 수정 후 결과

### v_simple_rsi
- 승률: 0% → **39.29%**
- 총 수익률: 79.65% → **11.92%**
- Sharpe: -10.47 → 양수 예상
- 평균 수익: -47.78% → **+0.43%**

### v_momentum
- 승률: 0% → **50.00%**
- 총 수익률: 277.51% → **28.98%**
- Sharpe: -8.77 → 양수 예상
- 평균 수익: -43.66% → **+1.32%**

### v_volume_spike
- 승률: 0% → **38.89%**
- 총 수익률: 46.68% → **21.81%**
- Sharpe: -23.82 → 양수 예상
- 평균 수익: -49.45% → **+0.30%**

---

## 🎯 근본 원인 (최종 추정)

엔진이 **복리 재투자** 방식으로 작동:

1. 첫 거래: 10M 투입 → 수익 발생
2. **두 번째 거래**: (10M + 수익) 전액 재투입
3. 손실 발생 시: **이전 수익까지 포함한 금액 손실**
4. `capital_at_entry`가 **투입 금액이 아니라 이전 total capital**

**결과**:
- 작은 손실 (-2%)도 **이전 수익을 포함하여** 큰 손실로 계산
- 예: 첫 거래 +50% (15M) → 두 번째 거래 15M 투입 → -2% 손실 = 14.7M
  - 실제 손실: 15M → 14.7M = -2%
  - 엔진 계산: (14.7M - 10M) / 10M = +47% (?)
  - 또는: (14.7M - 15M) / 15M = -2% (정상)

→ **라인 404의 `position.capital_at_entry`가 무엇인지 정확히 확인 필요**

---

## 📎 참고 자료

- **검증 스크립트**: `validation/verify_winrate_calculation.py`
- **엔진 코드**: `validation/universal_evaluation_engine.py`
  - 라인 404: return_pct 계산
  - 라인 353-362: Position 객체 생성
  - 라인 364: capital 차감
  - 라인 509-510: 승패 판정
- **검증 리포트**: `validation/251021-1641_ENGINE_VALIDATION_REPORT.md`

---

**리포트 작성**: Claude (Win Rate Bug Hunter)
**발견일**: 2025-10-21
**검증 방법**: 수동 계산 + 엔진 비교
**다음 단계**: capital_at_entry 값 디버깅 → 수정 → 재검증
