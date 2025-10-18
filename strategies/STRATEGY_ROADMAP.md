# 트레이딩 전략 로드맵 (2025-10-18 ~ 2026-03-31)

## 📊 현재 상황 분석 (수동 검증 완료)

**검증일**: 2025-10-19
**방법**: Decimal 정밀도 수동 계산

### ⚠️ 중요 발견: 백테스터 버그
- core.Backtester: 수익률 2~3배 과대평가
- 모든 전략을 수동 검증으로 재평가 완료

### 검증된 성과 (2024년)
- 🥇 **v07 Enhanced DAY**: **126.39%** (10거래, EMA+MACD)
- 🥈 **v11 Multi-Entry**: **113.78%** (6거래, Breakout+RSI)
- 🥉 **v05 Simple DAY**: **94.77%** (8거래, EMA만)
- **Buy&Hold**: 137.49%
- **최고 전략 격차**: v07 -11.10%p (Buy&Hold 대비)

### 현재 문제점
1. ✅ 진입 기회 → v07(10회), v11(6회)로 개선됨
2. ❌ Buy&Hold 미달 → v07도 -11.10%p 부족
3. ❌ 목표 150% 미달 → 최고 v07 126.39%

### 강점
1. ✅ v07: 126.39% (v05 대비 +31.62%p)
2. ✅ v11: 113.78% (정교한 Multi-Entry 작동 확인)
3. ✅ 안정적 MDD (v05: 29.10%)
4. ✅ 수동 검증 프로세스 확립

---

## 🎯 전략 로드맵

### Phase A: 단기 개선 (v07~v09) - 목표 150%

**기간**: 2025-10-18 ~ 2025-11-30
**베이스라인**: v05 DAY (94.77%)
**목표**: 150% (Buy&Hold + 2.48%p)

#### v07: Enhanced DAY - 진입 기회 확대
**핵심 아이디어**: RSI 과매도 구간 추가 진입

**변경 사항**:
1. **기존 진입**: EMA12 > EMA26 (골든크로스)
2. **추가 진입**: RSI < 30 AND 가격 > EMA26
3. **기대 효과**: 4거래 → 8~10거래

**예상 성과**: 120~140%

**구현**:
```python
def enhanced_entry(df, i):
    # 기존: 골든크로스
    golden_cross = (ema12 > ema26)

    # 추가: RSI 과매도 + 추세 확인
    rsi_oversold = (rsi < 30) and (price > ema26)

    return golden_cross or rsi_oversold
```

#### v08: Adaptive Trailing Stop - 손실 최소화
**핵심 아이디어**: ADX 기반 동적 Trailing Stop

**변경 사항**:
1. **강추세 (ADX > 30)**: Trailing Stop 25%
2. **약추세 (ADX < 25)**: Trailing Stop 15%
3. **기대 효과**: 손실 거래 감소 (2개 → 1개)

**예상 성과**: 130~150%

**구현**:
```python
def adaptive_trailing_stop(adx, highest_price, current_price):
    if adx > 30:
        threshold = 0.25  # 강추세는 여유
    else:
        threshold = 0.15  # 약추세는 빠른 청산

    drop = (highest_price - current_price) / highest_price
    return drop >= threshold
```

#### v09: Partial Exit - 수익 극대화
**핵심 아이디어**: 분할 매도로 리스크 관리

**변경 사항**:
1. **1차 매도 (50%)**: +20% 수익 시
2. **2차 매도 (50%)**: Trailing Stop
3. **기대 효과**: 큰 수익 보존 + 추가 상승 포착

**예상 성과**: 140~160%

**구현**:
```python
def partial_exit_strategy(pnl_pct, position):
    if pnl_pct >= 0.20 and position > 0.5:
        return {'action': 'sell', 'fraction': 0.5}  # 1차 매도

    if trailing_stop_triggered:
        return {'action': 'sell', 'fraction': 1.0}  # 잔량 매도
```

---

### Phase B: 중기 확장 (v10~v13) - 목표 200%

**기간**: 2025-12-01 ~ 2026-01-31
**베이스라인**: v09 (예상 150%)
**목표**: 200% (Buy&Hold + 52.48%p)

#### v10: Multi-Timeframe Fusion - DAY + 4H
**핵심 아이디어**: 일봉 추세 + 4시간봉 타이밍

**전략**:
1. **DAY**: 큰 추세 파악 (EMA 골든크로스)
2. **4H**: 세부 진입 타이밍 (RSI, MACD)
3. **기대 효과**: 진입 타이밍 개선 → 수익률 증가

**예상 성과**: 160~180%

#### v11: Bollinger Bands + Volume - 변동성 거래
**핵심 아이디어**: 볼린저 밴드 하단 터치 + 거래량 급증

**전략**:
1. **진입**: 가격 < BB 하단 AND 거래량 > 평균 150%
2. **청산**: 가격 > BB 중심선 OR Trailing Stop
3. **기대 효과**: 급락 후 반등 포착

**예상 성과**: 170~190%

#### v12: Momentum Breakout - 추세 가속 구간 포착
**핵심 아이디어**: MACD + ADX + Volume 동시 확인

**전략**:
1. **진입**: MACD 골든크로스 + ADX > 25 + Volume 급증
2. **청산**: MACD 데드크로스 OR ADX < 20
3. **기대 효과**: 강한 추세만 거래 → Win Rate 증가

**예상 성과**: 180~200%

#### v13: Ensemble Strategy - 복수 전략 조합
**핵심 아이디어**: v07~v12 중 최고 성과 3개 포트폴리오

**전략**:
1. **자본 배분**: 각 전략에 33.3%씩 할당
2. **독립 실행**: 3개 전략 동시 운영
3. **기대 효과**: 리스크 분산 + 안정적 수익

**예상 성과**: 190~210%

---

### Phase C: 장기 혁신 (v14~v17) - 목표 250%

**기간**: 2026-02-01 ~ 2026-03-31
**베이스라인**: v13 (예상 200%)
**목표**: 250% (Buy&Hold + 102.48%p)

#### v14: Reinforcement Learning - DQN
**핵심 아이디어**: 강화학습으로 복잡한 패턴 학습

**환경 설계**:
```python
State: [price, ema12, ema26, rsi, macd, adx, volume]
Action: [buy, sell, hold] × [fraction: 0.2, 0.5, 0.8, 1.0]
Reward: PnL - (MDD penalty)
```

**예상 성과**: 200~230%

#### v15: PPO (Proximal Policy Optimization)
**핵심 아이디어**: DQN보다 안정적인 학습

**개선 사항**:
1. Policy gradient 기반
2. Clipping으로 안정성 확보
3. Continuous action space

**예상 성과**: 210~240%

#### v16: Feature Engineering + XGBoost
**핵심 아이디어**: 전통 ML로 추세 예측

**피처**:
- 기술 지표: EMA, RSI, MACD, BB, ADX
- 시장 구조: 최근 N일 고가/저가, 변동성
- 거래량: 거래량 변화율, OBV

**예상 성과**: 220~250%

#### v17: Hybrid System - Rule + RL + ML
**핵심 아이디어**: 최고의 방법들을 결합

**구조**:
1. **Layer 1 (Rule-based)**: v09 Enhanced DAY (안정적 베이스)
2. **Layer 2 (RL)**: v15 PPO (단타 기회 포착)
3. **Layer 3 (ML)**: v16 XGBoost (추세 예측)

**자본 배분**: 50% / 30% / 20%

**예상 성과**: 230~260%

---

## 📊 전략별 비교표

| 버전 | 전략명 | 타임프레임 | 목표 수익률 | 난이도 | 개발 기간 |
|-----|-------|-----------|-----------|--------|----------|
| v05 | DAY Baseline | day | 94.77% | ⭐ | - |
| v07 | Enhanced DAY | day | 120~140% | ⭐⭐ | 3일 |
| v08 | Adaptive Trailing | day | 130~150% | ⭐⭐ | 3일 |
| v09 | Partial Exit | day | 140~160% | ⭐⭐⭐ | 5일 |
| v10 | Multi-TF Fusion | day + 4H | 160~180% | ⭐⭐⭐ | 7일 |
| v11 | BB + Volume | day | 170~190% | ⭐⭐⭐ | 5일 |
| v12 | Momentum Breakout | day | 180~200% | ⭐⭐⭐⭐ | 7일 |
| v13 | Ensemble | multiple | 190~210% | ⭐⭐⭐⭐ | 10일 |
| v14 | DQN | day | 200~230% | ⭐⭐⭐⭐⭐ | 14일 |
| v15 | PPO | day | 210~240% | ⭐⭐⭐⭐⭐ | 14일 |
| v16 | XGBoost | day | 220~250% | ⭐⭐⭐⭐⭐ | 14일 |
| v17 | Hybrid | multiple | 230~260% | ⭐⭐⭐⭐⭐ | 21일 |

---

## 🎯 우선순위 전략

### Tier S (최우선)
1. **v07 Enhanced DAY** - 빠르고 효과적, 높은 성공 확률
2. **v08 Adaptive Trailing** - 간단한 개선으로 큰 효과
3. **v09 Partial Exit** - 리스크 관리 핵심

### Tier A (중요)
4. **v10 Multi-TF** - 성과 향상 핵심
5. **v12 Momentum** - Win Rate 개선

### Tier B (선택)
6. **v11 BB + Volume** - 특수 상황 대응
7. **v13 Ensemble** - 안정성 확보

### Tier C (장기)
8. **v14~v17** - 기술적 도전, 높은 리스크

---

## 📋 개발 순서 (권장)

### Week 1-2: v07~v09 집중 개발
**목표**: 150% 달성

**Day 1-3**: v07 Enhanced DAY
- RSI 추가 진입 조건 구현
- 백테스팅 및 검증
- 목표: 120~140%

**Day 4-6**: v08 Adaptive Trailing Stop
- ADX 기반 동적 trailing stop
- v07과 결합 테스트
- 목표: 130~150%

**Day 7-11**: v09 Partial Exit
- 분할 매도 로직 구현
- v07+v08과 결합
- 목표: 140~160%

**Day 12-14**: 검증 및 문서화
- 2025년 out-of-sample 테스트
- 최종 성과 확인
- 성공 시 v10으로 진행

### Week 3-4: v10~v12 선택 개발
**조건**: v09가 150% 달성 시

**Day 15-21**: v10 Multi-Timeframe
- DAY + 4H 조합 구현
- 복잡도 증가 주의
- 목표: 160~180%

**Day 22-28**: v12 Momentum (v11 스킵)
- MACD + ADX + Volume
- Win Rate 개선 중점
- 목표: 180~200%

### Week 5-6: v13 Ensemble (Optional)
**조건**: v10 또는 v12가 180% 달성 시

**Day 29-38**: 최고 성과 3개 조합
- 포트폴리오 구성
- 리스크 분산 효과 확인
- 목표: 190~210%

### Week 7-12: v14~v17 강화학습 (Advanced)
**조건**: v13이 200% 달성 시 또는 Rule-based 한계 도달 시

---

## 🚀 빠른 시작 가이드

### 즉시 시작: v07 Enhanced DAY

**1단계: 전략 폴더 생성**
```bash
mkdir -p strategies/v07_enhanced_day
cd strategies/v07_enhanced_day
```

**2단계: 계획서 작성**
```bash
cp ../v06_dual_layer_adaptive/manual_verification.py .
# 계획서 작성 (다음 메시지에서 제공)
```

**3단계: 구현**
- `strategy.py`: Enhanced DAY 로직
- `config.json`: RSI 파라미터 추가
- `backtest.py`: 백테스팅 스크립트

**4단계: 검증**
- 수동 계산으로 정확성 확인
- 2024년 백테스팅: 목표 120~140%
- 2025년 검증: Out-of-sample 테스트

**5단계: 다음 단계**
- 목표 달성 시: v08 진행
- 목표 미달 시: v07 파라미터 최적화

---

## 📊 성공 기준

### v07~v09 (단기)
- ✅ 수익률 >= 150%
- ✅ Sharpe >= 1.0
- ✅ MDD <= 30%
- ✅ Win Rate >= 55%
- ✅ 거래 횟수: 8~15회

### v10~v13 (중기)
- ✅ 수익률 >= 200%
- ✅ Sharpe >= 1.2
- ✅ MDD <= 25%
- ✅ Win Rate >= 60%
- ✅ Profit Factor >= 3.0

### v14~v17 (장기)
- ✅ 수익률 >= 250%
- ✅ Sharpe >= 1.5
- ✅ MDD <= 20%
- ✅ Win Rate >= 65%
- ✅ Profit Factor >= 4.0

---

## 🎯 최종 권장 사항

**지금 시작**: v07 Enhanced DAY
**이유**:
1. 빠른 개발 (3일)
2. 높은 성공 확률 (80%)
3. 명확한 개선 방향
4. v05 (94.77%) 기반 점진적 향상

**다음 메시지**: v07 상세 계획서 제공

---

**작성일**: 2025-10-18
**담당**: Claude (AI Assistant)
**최종 검토**: 사용자 승인 대기
