# v07 Enhanced DAY 전략 개발 계획서

**작성일**: 2025-10-18
**전략명**: Enhanced DAY with MACD Entry
**버전**: v07
**타임프레임**: DAY (일봉)

---

## 1. 이전 버전 분석

### v05 Multi-Cascade Autotuning (DAY)

**성과**:
- 수익률: **94.77%** (검증 완료)
- Sharpe Ratio: 1.42
- Max Drawdown: -21.89%
- 거래 횟수: **4회**
- 승률: 50%

**진입 조건**:
- EMA(12) Golden Cross over EMA(26)

**청산 조건**:
- Trailing Stop: 21%
- Stop Loss: 10%

**문제점**:
1. **거래 횟수 부족**: 연 4~5회만 진입
2. **기회 손실**: 2024년 중간 조정 구간에서 추가 진입 불가
3. **RSI 조건 작동 불가**: 2024년 강한 상승장에서 RSI < 35 한 번도 발생 안 함

**강점**:
- 안정적인 Sharpe Ratio (1.42)
- 제한적인 MDD (-21.89%)
- 명확한 트렌드 추종 로직

---

## 2. 핵심 가설

### 가설 1: MACD 골든크로스 추가 진입 조건
**내용**: MACD 골든크로스를 추가 진입 조건으로 사용하면 진입 기회가 2배 증가하고 수익률이 +25~45%p 개선될 것

**근거**:
- 2024년 MACD 골든크로스 발생: **9회**
- 평균 수익률 (7일 보유): **+9.03%**
- 승률: **77.8%**
- 최대 손실: **-2.98%** (제한적)

**검증 방법**:
- EMA Golden Cross (5회) + MACD Golden Cross (9회) 조합
- 중복 진입 방지 로직 추가
- 백테스팅으로 실제 수익률 확인

### 가설 2: 청산 조건 유지
**내용**: v05의 검증된 청산 조건(Trailing Stop 21%, Stop Loss 10%)을 유지하면 안정성 확보

**근거**:
- v05에서 MDD -21.89%로 제한적
- 상승장에서 충분한 이익 실현

---

## 3. 구현 계획

### A. 지표 추가
```python
# 기존 (v05)
- EMA(12)
- EMA(26)

# 추가 (v07)
- MACD(12, 26, 9)
  - MACD Line
  - Signal Line
```

### B. 진입 로직
```python
# 조건 A: EMA Golden Cross
ema_golden_cross = (prev_ema12 <= prev_ema26) and (ema12 > ema26)

# 조건 B: MACD Golden Cross (신규)
macd_golden_cross = (prev_macd <= prev_macd_signal) and (macd > macd_signal)

# 진입 신호
if ema_golden_cross or macd_golden_cross:
    if not has_position:  # 중복 진입 방지
        return {'action': 'buy', 'fraction': 0.95}
```

### C. 청산 로직 (v05 유지)
```python
# Trailing Stop
if current_price <= highest_price_since_entry * (1 - trailing_stop_pct):
    return {'action': 'sell', 'fraction': 1.0}

# Stop Loss
if current_price <= entry_price * (1 - stop_loss_pct):
    return {'action': 'sell', 'fraction': 1.0}
```

### D. 포지션 사이징
```python
# v05와 동일
position_fraction = 0.95  # 95% 투자
```

---

## 4. 하이퍼파라미터

### 초기값 (v05 기반)
```json
{
  "strategy_name": "enhanced_day_macd",
  "version": "v07",
  "timeframe": "day",

  "indicators": {
    "ema_fast": 12,
    "ema_slow": 26,
    "macd_fast": 12,
    "macd_slow": 26,
    "macd_signal": 9
  },

  "entry": {
    "use_ema_golden_cross": true,
    "use_macd_golden_cross": true
  },

  "exit": {
    "trailing_stop_pct": 0.21,
    "stop_loss_pct": 0.10
  },

  "position": {
    "position_fraction": 0.95
  },

  "trading": {
    "initial_capital": 10000000,
    "fee_rate": 0.0005,
    "slippage": 0.0002
  }
}
```

### 최적화 대상 (Optuna)
```yaml
macd_fast: [8, 10, 12, 14, 16]
macd_slow: [20, 24, 26, 28, 32]
macd_signal: [7, 8, 9, 10, 11]
trailing_stop_pct: [0.15, 0.18, 0.21, 0.24, 0.27]
stop_loss_pct: [0.08, 0.10, 0.12, 0.15]
```

---

## 5. 예상 성과

### 보수적 시나리오
**가정**: MACD 추가 진입 4회, 평균 수익률 +5%

- v05 수익률: 94.77%
- MACD 추가 기여: +20%p
- **예상 수익률**: **115%**

### 중간 시나리오
**가정**: MACD 추가 진입 6회, 평균 수익률 +7%

- v05 수익률: 94.77%
- MACD 추가 기여: +35%p
- **예상 수익률**: **130%**

### 낙관적 시나리오
**가정**: MACD 추가 진입 8회, 평균 수익률 +9%

- v05 수익률: 94.77%
- MACD 추가 기여: +45%p
- **예상 수익률**: **140%**

### Buy&Hold 비교
- Buy&Hold (2024 DAY): **137.49%**
- v07 목표: **130~140%**
- **목표 달성 가능성**: 높음 (중간~낙관 시나리오)

---

## 6. 위험 요소

### 기술적 위험
1. **중복 신호**: EMA와 MACD 골든크로스 동시 발생 시 단일 진입만 실행되는지 확인 필요
2. **과적합**: MACD 파라미터 최적화 시 오버피팅 가능성
3. **청산 타이밍**: 짧은 기간 진입 시 Trailing Stop 21%가 과도할 수 있음

### 시장 위험
1. **횡보장**: 2025년 횡보장 전환 시 MACD 잦은 신호 → 손실 증가 가능
2. **급락장**: 여러 포지션 동시 Stop Loss 발생 시 MDD 증가

### 완화 방안
1. 중복 진입 방지 로직 강화
2. Walk-Forward 검증으로 과적합 방지
3. 2025년 Out-of-Sample 테스트로 범용성 확인
4. 시장 상황별 백테스팅 (상승장/하락장/횡보장)

---

## 7. 성공 기준

### 필수 조건 (모두 달성)
- ✅ 수익률 >= **120%** (Buy&Hold 137.49% 근접)
- ✅ Sharpe Ratio >= **1.0**
- ✅ Max Drawdown <= **30%**

### 우수 조건 (2개 이상 달성)
- ⭐ 수익률 >= **130%**
- ⭐ 거래 횟수 >= **8회** (v05 4회 대비 2배)
- ⭐ 승률 >= **60%**
- ⭐ Profit Factor >= **2.0**

### 탁월 조건 (3개 이상 달성)
- 🏆 수익률 >= **140%**
- 🏆 Sharpe Ratio >= **1.5**
- 🏆 Max Drawdown <= **20%**
- 🏆 승률 >= **70%**

---

## 8. 개발 일정

### Phase 1: 준비 (완료)
- [x] v05 전략 분석
- [x] 대안 진입 조건 탐색
- [x] MACD 골든크로스 검증
- [x] 계획서 작성

### Phase 2: 구현 (진행 예정)
- [ ] config.json 작성
- [ ] strategy.py 작성
- [ ] backtest.py 작성
- [ ] manual_verification.py 작성

### Phase 3: 초기 테스트
- [ ] 2024년 백테스팅 실행
- [ ] 수동 검증 (거래 내역 확인)
- [ ] 결과 분석 및 디버깅

### Phase 4: 최적화
- [ ] Optuna 하이퍼파라미터 최적화
- [ ] 최적 파라미터 선정
- [ ] 재백테스팅

### Phase 5: 검증
- [ ] 2025년 Out-of-Sample 테스트
- [ ] 시장 상황별 성과 분석
- [ ] 오버피팅 검사

### Phase 6: 문서화
- [ ] result.md 작성
- [ ] process.md 업데이트
- [ ] claude.md 갱신
- [ ] 다음 버전(v08) 제안

---

## 9. 예상 거래 시나리오 (2024년)

### EMA Golden Cross (v05 기존)
1. 2024-01-02: 60,206,000원 - 매수
2. 2024-02-03: 59,260,000원 - 매수
3. 2024-05-20: 97,260,000원 - 매수
4. 2024-07-19: 93,004,000원 - 매수
5. 2024-09-19: 83,892,000원 - 매수

### MACD Golden Cross (v07 추가)
6. 2024-02-26: 74,742,000원 - 매수 (예상 +27.77%)
7. 2024-05-13: 87,928,000원 - 매수 (예상 +10.61%)
8. 2024-06-03: 95,994,000원 - 매수 (예상 +1.34%)
9. 2024-07-13: 82,901,000원 - 매수 (예상 +13.47%)
10. 2024-08-21: 82,900,000원 - 매수 (예상 -2.81%)
11. 2024-09-11: 77,301,000원 - 매수 (예상 +6.86%)
12. 2024-10-14: 88,640,000원 - 매수 (예상 +3.97%)
13. 2024-11-06: 104,085,000원 - 매수 (예상 +23.08%)
14. 2024-12-15: 149,243,000원 - 매수 (예상 -2.98%)

**중복 제거 후 예상**: 9~12회 진입 (v05 4회 대비 2~3배)

---

## 10. 다음 단계

1. **사용자 승인 대기** ⭐
2. config.json 작성
3. strategy.py 구현
4. 백테스팅 실행
5. 결과 검증

---

## 11. 질문 및 확인 사항

### 사용자 확인 필요
1. **MACD 골든크로스 추가 진입 조건 승인 여부**
2. **청산 조건 유지 (Trailing 21%, Stop Loss 10%) 승인 여부**
3. **목표 수익률 120~140% 적정성 확인**
4. **추가 고려 사항 또는 수정 요청**

---

**작성자**: Claude (v07 개발 담당)
**다음 작업**: 사용자 승인 후 config.json 작성
