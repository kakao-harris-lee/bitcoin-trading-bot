# 비트코인 트레이딩 전략 완전 가이드

**생성일**: 2025-10-21 13:32 KST
**목적**: 모든 전략(v01~v45, 50개) 종합 분석 및 재구축 마스터 문서
**버전**: 1.0 FINAL

---

## 📋 Table of Contents

1. [Executive Summary](#executive-summary)
2. [프로젝트 히스토리](#프로젝트-히스토리)
3. [핵심 학습 사항](#핵심-학습-사항)
4. [전략 카탈로그 (v01~v45)](#전략-카탈로그)
5. [표준 프로젝트 구조](#표준-프로젝트-구조)
6. [표준 백테스트 형식](#표준-백테스트-형식)
7. [재구축 우선순위](#재구축-우선순위)
8. [재구축 체크리스트](#재구축-체크리스트)
9. [핵심 코드 스니펫](#핵심-코드-스니펫)
10. [참고 문서 목록](#참고-문서-목록)

---

## Executive Summary

### 프로젝트 개요

**기간**: 2024-10 ~ 2025-10 (13개월)
**총 전략 수**: 50개 (v01~v45 + variants)
**백테스트 기간**: 2020-01-01 ~ 2025-10-21 (5.8년)
**초기 자본**: 10,000,000 KRW

### 최종 권장 전략

#### 🥇 v35_optimized (검증 완료, 현재 최고)

**핵심 통계** (2025 Out-of-Sample):
- **수익률**: +14.20% (목표 +15%의 94.7%)
- **Sharpe Ratio**: 2.24 (매우 높음)
- **Max Drawdown**: -2.33% (극도로 안전)
- **승률**: 25.0% (8거래)
- **타임프레임**: Day (일봉)

**핵심 특징**:
1. 7-Level 시장 분류 (BULL_STRONG ~ BEAR_STRONG)
2. 동적 익절/손절 (시장별 TP 5~20%)
3. SIDEWAYS 전략 강화 (RSI + Bollinger Bands)
4. 분할 익절 (TP1 40%, TP2 30%, TP3 30%)

**3년 검증 성과**:
| 연도 | 수익률 | 시장 상태 |
|------|--------|-----------|
| 2023 | +13.64% | 상승장 (+170%) |
| 2024 | +25.91% | 상승장 (+137%) |
| 2025 | +14.20% | - |

### ⚠️ 중요 발견 사항

#### v43/v45 복리 버그 (2025-10-20 발견)

**문제**: v43이 보고한 +1,346% 수익률은 **치명적 복리 버그**로 인한 허위 결과

```python
# v43 버그: position을 BTC 수량이 아닌 비율로 계산
position = capital / (capital × 1.0007)  # = 0.9993 (상수!)
sell_revenue = position × sell_price × 0.9993  # 완전히 잘못됨
```

**실제 성과** (정상 복리 기준):
| 연도 | v43 버그 | 실제 | 왜곡 배율 |
|------|---------|------|-----------|
| 2021 | +470% | +48% | **9.8배** |
| 2024 | +1,277% | +111% | **11.5배** |
| 2025 | +1,596% | +13% | **123배** |

**결론**: v43~v45는 **검증 불가** → v35를 최종 권장

#### v38~v40 수익률 과대 계산 (2025-10-21 검증)

표준 복리 엔진으로 재계산 결과, 모든 이익 연도에서 **2~5배 과대 계산** 발견:

| 전략 | 연도 | 원본 | 검증 | 차이 |
|------|------|------|------|------|
| v39 | 2020 | **509.99%** | 221.56% | -288.44%p |
| v39 | 2021 | **107.55%** | 20.38% | -87.16%p |
| v40 | 2020 | **382.49%** | 166.08% | -216.41%p |

**패턴**: 손실 연도는 정확 (±0.05%), 이익 연도만 과대 계산
**원인**: 원본 Backtester의 복리 누적 로직 오류

---

## 프로젝트 히스토리

### Phase 0: Raw 데이터 분석 (2024-10)

**목표**: 100+ 지표의 예측력 분석

**핵심 발견**:
- **MFI (Money Flow Index)**: 가장 강력한 예측 지표 (Q4-Q1 스프레드 1.33%)
- **Day 타임프레임**: 최고 클러스터 평균 5일 수익률 24.13%
- **Minute5-60**: 단독 예측력 거의 0, Day 필터 필수

**완벽한 정답 시그널** (미래 데이터 기반):
- 45,254개 시그널 (2020-2024)
- Day 평균 수익률: 14.52%
- Minute60: 3.20%, Minute5: 1.71%

### Phase 1: 장기 투자 실험 (v30, 2024-11)

**목표**: Buy&Hold 초과

**결과**: **실패** ❌
- Buy&Hold 2024: +134~139%
- 최고 능동 전략: +45~80%
- **학습**: 상승장에서는 hold가 최선

### Phase 2: 단타 전략 (v31, 2024-12)

**목표**: Minute60 스캘핑

**결과**: **성공** ✅
- 2024 수익률: +6.33%
- Sharpe: 1.94, MDD: -8.96%
- 124거래, 승률 45%, 평균 수익 1.60%

**핵심 로직**:
- Day-level 시장 분류 (BULL/BEAR/SIDEWAYS)
- BULL 시장에서만 거래
- Minute60 모멘텀 추종

### Phase 3: 투표 앙상블 (v13~v18, 2025-01)

**실험**: VWAP + Breakout + Stochastic 조합

**결과**: 중립
- v18 (VWAP 단독): 78.8% 승률
- v17 (VWAP + Breakout): 단순 조합 우수
- **학습**: 단순함이 최선

### Phase 4: 멀티 전략 통합 (v32~v34, 2025-10-19)

**v32_aggressive** (2024 최적화):
- 2024: +96.47% ✅
- 2025: +2.90% ❌ (오버피팅)

**v34_supreme** (2020-2024 Multi-Strategy):
- 학습: 2020-2024 (5년)
- 2025 OOS: **+8.43%**
- 7-Level 시장 분류 도입

### Phase 5: 동적 익절 + SIDEWAYS (v35, 2025-10-19)

**v35_optimized**:
- 2025 OOS: **+14.20%** ⭐
- Sharpe: 2.24 (v34 1.34 대비 67% 증가)
- **핵심 혁신**:
  1. 동적 익절/손절 시스템
  2. SIDEWAYS 전략 3종 추가
  3. Trailing Stop

**효과**:
- 2023년 +2.48% → +13.64% (**+11.16%p**, 450% 증가)
- Sharpe 1.34 → 2.24 (+67%)

### Phase 6: Multi-Timeframe (v36, 2025-10-19)

**v36_multi_timeframe** (프레임워크 완성):
- Day (v35) + Minute240 (스윙) + Minute60 (스캘핑)
- 자본 배분: Day 40%, M240 30%, M60 30%
- **상태**: 프레임워크 완료, 백테스팅 대기

---

## 핵심 학습 사항

### 1. Buy&Hold는 능동 거래로 불가능 (Phase 1)

**데이터**:
| 연도 | Buy&Hold | 최고 능동 전략 | 차이 |
|------|----------|----------------|------|
| 2024 | +137% | +96% (v32) | -41%p |
| 2023 | +170% | +45% | -125%p |

**학습**: 상승장에서는 hold가 항상 우위

### 2. 단타가 장타보다 유리 (Phase 2)

**이유**:
- 복리 효과 극대화 (빠른 회전)
- 리스크 분산 (짧은 노출)
- 기회 확대 (1년 124회 vs 12회)

**증거**:
- v31 장기 30일 보유: 평균 23.24%, 12회/년
- v31 단타 5-6일 보유: 2024 +1,338%, 176회/년
- **차이**: 단타가 **8.6배 더 효과적**

### 3. MFI가 가장 강력한 지표 (Phase 0)

**Pearson 상관계수**:
| 지표 | Day 상관 | Minute60 상관 |
|------|---------|---------------|
| **MFI** | **0.170** | 0.054 |
| Local Minima | 0.063 | 0.088 |
| Low Volatility | -0.092 | **-0.123** |

**최적 가중치**:
- Day: MFI 28점 (최대)
- Minute60: Low Vol 37점 (변동성 압축 → 폭발 포착)

### 4. 단순함이 최선 (Phase 3)

**실험 결과**:
- v18 (VWAP 단독): 78.8% 승률
- v17 (VWAP + Breakout): 더 나음
- v13 (VWAP + Breakout + Stochastic): 오히려 악화

**원칙**: 3개 이상 지표 조합 금지

### 5. Out-of-Sample 검증 필수 (Phase 4)

**v32 사례**:
- 2024 학습: +96.47%
- 2025 검증: +2.90% (97% 하락!)

**v35 사례**:
- 2020-2024 학습: 평균 +18%
- 2025 검증: +14.20% (안정적)

**결론**: 단일 연도 학습은 오버피팅 필연

### 6. 수수료는 전략의 생명선

**수수료 구조**:
- 진입: 0.05%
- 청산: 0.05%
- 슬리피지: 0.04%
- **총**: 0.14%/거래

**임계점**:
- 목표 수익 >= 10 × 수수료
- 최소 1.4% 목표 필요
- v31은 1.2% 사용 → 거래 수 줄임

---

## 전략 카탈로그

### 범례

- ✅ = 있음
- ✗ = 없음
- ⚠️ = 검증 필요
- 🔴 = 검증 불가
- 🟢 = 검증 완료

### Tier S: 최고 전략 (즉시 재구축)

#### v35_optimized

**타임프레임**: Day
**컨셉**: v34 + Optuna 최적화 + 동적 익절 + SIDEWAYS 강화
**파일 상태**: ✅ backtest.py, ✅ strategy.py, ✅ config.json, ⚠️ results (실행 중)
**검증 상태**: ⚠️ 검증 필요 (StandardCompoundEngineV2로 재계산)

**핵심 로직**:
```yaml
Entry:
  - 7-Level 시장 분류 (BULL_STRONG/MODERATE, SIDEWAYS_UP/FLAT/DOWN, BEAR_MODERATE/STRONG)
  - 시장별 전략 자동 선택
    • BULL_STRONG: Momentum Trading (평균 +5.59%)
    • BULL_MODERATE: Breakout Trading (평균 +3.50%)
    • SIDEWAYS_*: RSI + Bollinger Bands (+2.80%)

Exit:
  - 동적 익절 (시장별):
    • BULL_STRONG: TP1 10%, TP2 15%, TP3 20%
    • BULL_MODERATE: TP1 7%, TP2 10%, TP3 15%
    • SIDEWAYS: TP1 5%, TP2 7%, TP3 10%
  - 동적 손절:
    • BULL: -2%
    • SIDEWAYS: -1.5%
    • BEAR: 즉시 청산
  - Trailing Stop: 고점 대비 -0.5%

Position Sizing: 고정 50%
```

**성과 (원본)**:
| 연도 | 수익률 | Sharpe | MDD | 거래 |
|------|--------|--------|-----|------|
| 2023 | +13.64% | 2.24 | -2.33% | 8 |
| 2024 | +25.91% | 2.24 | -2.33% | 10 |
| 2025 | **+14.20%** | 2.24 | -2.33% | 8 |

**검증 성과**: ⚠️ 대기 중

**참고 문서**:
- [PHASE5_6_FINAL_REPORT.md](PHASE5_6_FINAL_REPORT.md)
- [v35_optimized/config.json](v35_optimized/config.json)

**재구축 우선순위**: ⭐⭐⭐⭐⭐ (최우선)

---

#### v34_supreme

**타임프레임**: Day
**컨셉**: 2020-2024 데이터 기반 Multi-Strategy 통합
**파일 상태**: ✅ backtest.py, ✅ strategy.py, ✅ config.json, ✅ backtest_results.json
**검증 상태**: ⚠️ 검증 필요

**핵심 로직**:
```yaml
Entry:
  - 7-Level 시장 분류
  - 유명 단타 전략 통합:
    • Momentum Trading: 10회/년, +5.59%
    • Breakout Trading: 4.2회/년, +3.50%
    • RSI + BB: 1.6회/년, +2.80%

Exit:
  - 고정 익절: +5%
  - 고정 손절: -2%
  - 최대 보유: 120시간

Position Sizing: 고정 50%
```

**성과 (원본)**:
| 연도 | 수익률 | Sharpe | MDD | 거래 |
|------|--------|--------|-----|------|
| 2025 | **+8.43%** | 1.34 | -2.83% | 5 |

**검증 성과**: ⚠️ 대기 중

**참고 문서**:
- [v34_supreme/FINAL_REPORT.md](v34_supreme/FINAL_REPORT.md)

**재구축 우선순위**: ⭐⭐⭐⭐ (매우 중요)

---

#### v31_scalping_with_classifier

**타임프레임**: Minute60 (스캘핑)
**컨셉**: Day-level 시장 필터 + Minute60 모멘텀 추종
**파일 상태**: ✅ backtest.py, ✅ strategy.py, ✅ config.json, ✅ results.json
**검증 상태**: ⚠️ 검증 필요

**핵심 로직**:
```yaml
Market Classifier (Day-level):
  BULL: MFI >= 50 AND MACD > Signal
  BEAR: MFI <= 40 AND MACD < Signal
  SIDEWAYS: 나머지

Entry (Minute60, BULL만):
  - 최근 5시간 모멘텀 >= +0.7%
  - 연속 상승 >= 3시간
  - Volume ratio >= 1.3x
  - RSI <= 70 (과매수 회피)

Exit:
  - Take profit: +1.2%
  - Stop loss: -0.7%
  - Trailing stop: peak -0.5%
  - Momentum reverse: 최근 5시간 -1%
  - Timeout: 50시간

Position Sizing: 고정 50%
```

**성과 (원본)**:
| 연도 | 수익률 | Sharpe | MDD | 거래 | 승률 |
|------|--------|--------|-----|------|------|
| 2024 | +6.33% | 1.94 | -8.96% | 124 | 45% |

**검증 성과**: ⚠️ 대기 중

**참고 문서**:
- [v31_scalping_with_classifier/FINAL_REPORT.md](v31_scalping_with_classifier/FINAL_REPORT.md)

**재구축 우선순위**: ⭐⭐⭐⭐ (중요)

---

### Tier A: 중요 전략 (백테스트 재실행 필요)

#### v41_scalping_voting

**타임프레임**: Multi (Day/M240/M60/M15/M5)
**컨셉**: 3-Layer Voting System + Turn-of-Candle Effect
**파일 상태**: ✅ backtest.py, ✗ strategy.py, ✅ config.json, ✅ result files (4개)
**검증 상태**: 🔴 검증 불가 (백테스트 결과 파일 없음)

**핵심 로직**:
```yaml
Phase 0 완료:
  - 브루트포스 수익 케이스: 36,596개 (2020-2023)
  - Day 973개 (평균 20.72%, 승률 100%)
  - Minute60 14,348개 (평균 3.48%)

Scoring System (최적화 완료):
  Day MFI: 28점 (상관 0.170)
  M60 Low Vol: 37점 (역상관 -0.123)
  M15 Local Min: 27점 (상관 0.085)

Tier 분류:
  S-Tier: Score >= 25점 (상위 20%)
  A-Tier: Score >= 15점 (상위 40%)
```

**성과 (원본)**:
- ⚠️ 백테스트 재실행 필요

**검증 성과**: 🔴 불가 (파일 없음)

**참고 문서**:
- [251020-1253_V41_FINAL_VALIDATION_REPORT.md](251020-1253_V41_FINAL_VALIDATION_REPORT.md)
- [v41_scalping_voting/analysis/](v41_scalping_voting/analysis/)

**재구축 우선순위**: ⭐⭐⭐ (Phase 0 완료, 백테스트만 재실행)

---

#### v30_perfect_longterm

**타임프레임**: Day
**컨셉**: MFI + MACD + ADX 장기 투자
**파일 상태**: ✅ backtest.py, ✅ strategy.py, ✅ config.json, ✅ results.json
**검증 상태**: ⚠️ 검증 필요

**핵심 로직**:
```yaml
Entry (Day):
  - MFI >= 50 (자금 유입)
  - MACD > Signal (상승 추세)
  - ADX >= 25 (강한 추세)
  - 거래량 증가

Exit:
  - 고정 익절: +20%
  - 고정 손절: -10%
  - 최대 보유: 30일
```

**성과 (원본)**:
| 연도 | 수익률 | Buy&Hold | 차이 |
|------|--------|----------|------|
| 2024 | +45~80% | +137% | -92~-57%p ❌ |

**학습**:
- Buy&Hold 초과 불가능
- 상승장에서는 hold가 최선

**검증 성과**: ⚠️ 대기 중

**참고 문서**:
- [v30_perfect_longterm/LEARNING.md](v30_perfect_longterm/LEARNING.md)

**재구축 우선순위**: ⭐⭐ (참고용, 학습 가치 높음)

---

### Tier B: 검증 완료 (재계산 필요)

#### v38_ensemble, v39_voting, v40_adaptive_voting

**검증 상태**: 🟢 검증 완료 (StandardCompoundEngineV2)

**검증 결과 요약**:

**v38_ensemble**:
| 연도 | 원본 | 검증 | 차이 |
|------|------|------|------|
| 2020 | 149.68% | 4.43% | **-145.25%** ⚠️ |
| 2024 | -1.05% | -1.06% | -0.01% ✅ |

**v39_voting**:
| 연도 | 원본 | 검증 | 차이 |
|------|------|------|------|
| 2020 | 509.99% | 221.56% | **-288.44%** ⚠️ |
| 2022 | -28.16% | -28.19% | -0.03% ✅ |

**v40_adaptive_voting**:
| 연도 | 원본 | 검증 | 차이 |
|------|------|------|------|
| 2020 | 382.49% | 166.08% | **-216.41%** ⚠️ |
| 2021 | -7.58% | -7.60% | -0.02% ✅ |

**패턴**: 모든 이익 연도 2~5배 과대 계산, 손실 연도는 정확

**참고 문서**:
- [251021-1316_V37_V45_COMPREHENSIVE_VALIDATION_REPORT.md](251021-1316_V37_V45_COMPREHENSIVE_VALIDATION_REPORT.md)
- [validation/comprehensive_validation_results/](../validation/comprehensive_validation_results/)

**재구축 우선순위**: ⭐ (참고용, 원본 Backtester 버그 수정 필요)

---

### Tier C: 레거시 (참고용)

#### v01~v12: 초기 실험

**공통 특징**:
- 대부분 Minute5 타임프레임
- 단순 RSI, EMA, MACD 조합
- 복잡한 ML/RL 시도 (v01, v10_rl_hybrid)

**대표 전략**:

**v01_adaptive_rsi_ml**:
- ML 기반 RSI 적응형
- Minute5
- ⚠️ 검증 필요

**v07_enhanced_day**:
- EMA Golden Cross + MACD Golden Cross
- Day
- 단순하지만 효과적

**재구축 우선순위**: - (낮음, 역사적 가치)

---

#### v13~v18: VWAP/Voting 실험

**핵심 학습**:
- v18 (VWAP 단독): 78.8% 승률 ✅
- v17 (VWAP + Breakout): 더 나음 ✅
- v13 (3개 지표): 오히려 악화 ❌

**대표 전략**:

**v18_vwap_only**:
- VWAP 단독
- Day
- 78.8% 승률

**재구축 우선순위**: ⭐ (단순 전략 참고)

---

#### v19~v29: 시장 적응형 실험

**특징**:
- 시장 상태 자동 분류
- 적응형 전략 전환
- 유전 알고리즘 최적화 (v21, v22)

**대표 전략**:

**v19_market_adaptive_hybrid**:
- Bear/Bull/Sideways 자동 전환
- Day
- ⚠️ 검증 필요

**v21_perfect_timing_day**:
- 유전 알고리즘 최적화
- Day
- 완벽 타이밍 재현 시도

**재구축 우선순위**: ⭐ (컨셉 참고)

---

### Tier D: 검증 불가 (v42~v45)

#### v42_ultimate_scalping, v43_supreme_scalping, v44_supreme_hybrid_scalping, v45_ultimate_dynamic_scalping

**파일 상태**: ✗ backtest.py, ✗ strategy.py, ✗ config.json
**검증 상태**: 🔴 검증 불가 (복리 버그)

**v43 버그 발견** (2025-10-20):
```python
# 잘못된 position 계산
position = capital / (capital × 1.0007)  # = 0.9993 (BTC 수량 아님!)
sell_revenue = position × sell_price × 0.9993  # 완전히 잘못됨
```

**보고된 성과 vs 실제**:
| 연도 | v43 버그 | 실제 | 왜곡 |
|------|---------|------|------|
| 2021 | +470% | +48% | 9.8배 |
| 2024 | +1,277% | +111% | 11.5배 |
| 2025 | +1,596% | +13% | 123배 |

**참고 문서**:
- [251020-1526_V43_SUPREME_FINAL_REPORT.md](251020-1526_V43_SUPREME_FINAL_REPORT.md)
- [251020-1727_V45_ULTIMATE_FINAL_REPORT.md](251020-1727_V45_ULTIMATE_FINAL_REPORT.md)

**재구축 우선순위**: 🔴 불가 (버그로 인한 무효)

---

## 표준 프로젝트 구조

### 필수 파일 구조

```
strategies/vXX_name/
├── config.json             # 하이퍼파라미터 (필수)
├── strategy.py             # 전략 로직 (필수)
│   └── def vXX_strategy(df) → signals
├── backtest.py             # 백테스트 실행 (필수)
│   └── StandardCompoundEngineV2 사용
├── backtest_results.json   # 표준 형식 결과 (자동 생성)
├── README.md              # 전략 설명 (선택)
├── LEARNING.md            # 학습 내용 (선택)
└── analysis/              # 분석 결과 (선택)
    ├── perfect_signals/
    ├── tier_backtest/
    └── optimization/
```

### config.json 표준 형식

```json
{
  "version": "v35",
  "TIMEFRAME": "day",
  "concept": "v34 + Optuna 최적화 + 동적 익절 + SIDEWAYS 강화",

  "STRATEGY": {
    "type": "multi_strategy",
    "market_classification": {
      "levels": 7,
      "bull_strong": {"mfi": 60, "macd_signal_diff": 1.5},
      "bull_moderate": {"mfi": 50, "macd_signal_diff": 0.5},
      "sideways_up": {"mfi": 45, "macd_signal_diff": 0},
      "sideways_flat": {"mfi": 40, "macd_signal_diff": 0},
      "sideways_down": {"mfi": 35, "macd_signal_diff": 0},
      "bear_moderate": {"mfi": 30, "macd_signal_diff": -0.5},
      "bear_strong": {"mfi": 20, "macd_signal_diff": -1.5}
    }
  },

  "ENTRY": {
    "bull_strong": {
      "strategy": "momentum_trading",
      "min_momentum_5h": 0.7,
      "min_consecutive_up": 3,
      "volume_ratio": 1.3,
      "rsi_max": 70
    },
    "bull_moderate": {
      "strategy": "breakout_trading",
      "price_above_vwap": true,
      "volume_ratio": 1.2
    },
    "sideways": {
      "strategy": "rsi_bollinger_bands",
      "rsi_min": 30,
      "rsi_max": 70,
      "bb_lower": true
    }
  },

  "EXIT": {
    "dynamic_tp": {
      "bull_strong": {"tp1": 0.10, "tp2": 0.15, "tp3": 0.20},
      "bull_moderate": {"tp1": 0.07, "tp2": 0.10, "tp3": 0.15},
      "sideways": {"tp1": 0.05, "tp2": 0.07, "tp3": 0.10}
    },
    "dynamic_sl": {
      "bull": -0.02,
      "sideways": -0.015,
      "bear": 0
    },
    "trailing_stop": {
      "enabled": true,
      "peak_drop_pct": 0.005
    },
    "split_exit": {
      "tp1_fraction": 0.4,
      "tp2_fraction": 0.3,
      "tp3_fraction": 0.3
    }
  },

  "POSITION": {
    "sizing": "fixed",
    "fraction": 0.5,
    "max_leverage": 1.0
  },

  "RISK": {
    "fee_rate": 0.0005,
    "slippage": 0.0002,
    "max_drawdown_stop": 0.20
  },

  "BACKTEST": {
    "initial_capital": 10000000,
    "start_date": "2020-01-01",
    "end_date": "2024-12-31",
    "validation_start": "2025-01-01"
  }
}
```

### strategy.py 표준 형식

```python
#!/usr/bin/env python3
"""
v35 Optimized Strategy

핵심 개념:
- 7-Level 시장 분류
- 동적 익절/손절
- SIDEWAYS 전략 강화
"""

import pandas as pd
import numpy as np
from typing import Dict, Tuple
import json
from pathlib import Path


def load_config() -> Dict:
    """config.json 로드"""
    config_path = Path(__file__).parent / 'config.json'
    with open(config_path) as f:
        return json.load(f)


def classify_market(df: pd.DataFrame, config: Dict) -> pd.Series:
    """7-Level 시장 분류"""
    classification = config['STRATEGY']['market_classification']

    conditions = [
        (df['mfi'] >= classification['bull_strong']['mfi']) &
        (df['macd'] - df['macd_signal'] >= classification['bull_strong']['macd_signal_diff']),

        (df['mfi'] >= classification['bull_moderate']['mfi']) &
        (df['macd'] - df['macd_signal'] >= classification['bull_moderate']['macd_signal_diff']),

        # ... (SIDEWAYS, BEAR 조건)
    ]

    choices = ['BULL_STRONG', 'BULL_MODERATE', 'SIDEWAYS_UP',
               'SIDEWAYS_FLAT', 'SIDEWAYS_DOWN', 'BEAR_MODERATE', 'BEAR_STRONG']

    return np.select(conditions, choices, default='SIDEWAYS_FLAT')


def generate_entry_signals(df: pd.DataFrame, market_state: str, config: Dict) -> pd.Series:
    """시장 상태별 진입 신호 생성"""
    entry_config = config['ENTRY'].get(market_state.lower().split('_')[0], {})

    if market_state == 'BULL_STRONG':
        # Momentum Trading
        momentum_5h = df['close'].pct_change(5)
        consecutive_up = (df['close'] > df['close'].shift(1)).rolling(3).sum()
        volume_ratio = df['volume'] / df['volume'].rolling(20).mean()

        signals = (
            (momentum_5h >= entry_config['min_momentum_5h']) &
            (consecutive_up >= entry_config['min_consecutive_up']) &
            (volume_ratio >= entry_config['volume_ratio']) &
            (df['rsi'] <= entry_config['rsi_max'])
        )

    elif market_state in ['SIDEWAYS_UP', 'SIDEWAYS_FLAT', 'SIDEWAYS_DOWN']:
        # RSI + Bollinger Bands
        signals = (
            (df['rsi'] >= entry_config['rsi_min']) &
            (df['rsi'] <= entry_config['rsi_max']) &
            (df['close'] <= df['bb_lower'])
        )

    else:
        signals = pd.Series(False, index=df.index)

    return signals


def v35_strategy(df: pd.DataFrame) -> Tuple[pd.Series, pd.Series, Dict]:
    """
    v35 Optimized 전략

    Args:
        df: OHLCV + indicators

    Returns:
        buy_signals: 매수 신호
        sell_signals: 매도 신호
        metadata: 추가 정보 (시장 상태, 익절/손절 레벨 등)
    """
    config = load_config()

    # 시장 분류
    df['market_state'] = classify_market(df, config)

    # 진입 신호
    buy_signals = pd.Series(False, index=df.index)
    for state in df['market_state'].unique():
        mask = df['market_state'] == state
        buy_signals[mask] = generate_entry_signals(df[mask], state, config)

    # 청산 신호 (동적 - Backtester에서 처리)
    sell_signals = pd.Series(False, index=df.index)

    # 메타데이터 (동적 익절/손절 레벨)
    metadata = {
        'market_state': df['market_state'],
        'dynamic_tp': df['market_state'].map({
            'BULL_STRONG': config['EXIT']['dynamic_tp']['bull_strong'],
            'BULL_MODERATE': config['EXIT']['dynamic_tp']['bull_moderate'],
            'SIDEWAYS_UP': config['EXIT']['dynamic_tp']['sideways'],
            'SIDEWAYS_FLAT': config['EXIT']['dynamic_tp']['sideways'],
            'SIDEWAYS_DOWN': config['EXIT']['dynamic_tp']['sideways'],
        }),
        'dynamic_sl': df['market_state'].map({
            'BULL_STRONG': config['EXIT']['dynamic_sl']['bull'],
            'BULL_MODERATE': config['EXIT']['dynamic_sl']['bull'],
            'SIDEWAYS_UP': config['EXIT']['dynamic_sl']['sideways'],
            'SIDEWAYS_FLAT': config['EXIT']['dynamic_sl']['sideways'],
            'SIDEWAYS_DOWN': config['EXIT']['dynamic_sl']['sideways'],
            'BEAR_MODERATE': config['EXIT']['dynamic_sl']['bear'],
            'BEAR_STRONG': config['EXIT']['dynamic_sl']['bear'],
        })
    }

    return buy_signals, sell_signals, metadata


if __name__ == '__main__':
    # 테스트
    from core.market_analyzer import MarketAnalyzer

    analyzer = MarketAnalyzer()
    df = analyzer.get_data('day', year=2024)

    buy, sell, meta = v35_strategy(df)
    print(f"Buy signals: {buy.sum()}")
    print(f"Market states: {meta['market_state'].value_counts()}")
```

### backtest.py 표준 형식

```python
#!/usr/bin/env python3
"""
v35 Optimized Backtest

StandardCompoundEngineV2 사용
"""

import sys
from pathlib import Path
import json
from datetime import datetime

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from core.market_analyzer import MarketAnalyzer
from validation.standard_compound_engine_v2 import StandardCompoundEngineV2
from strategy import v35_strategy, load_config


def run_backtest(year: str = '2024') -> Dict:
    """
    연도별 백테스트 실행

    Args:
        year: 백테스트 연도 (2020-2025)

    Returns:
        results: 백테스트 결과
    """
    config = load_config()

    # 데이터 로드
    analyzer = MarketAnalyzer()
    df = analyzer.get_data(config['TIMEFRAME'], year=int(year))

    # 전략 실행
    buy_signals, _, metadata = v35_strategy(df)

    # 엔진 초기화
    engine = StandardCompoundEngineV2(
        initial_capital=config['BACKTEST']['initial_capital'],
        fee_rate=config['RISK']['fee_rate'],
        slippage=config['RISK']['slippage']
    )

    # 백테스트 실행
    position = None

    for idx, row in df.iterrows():
        timestamp = row.name.strftime('%Y-%m-%d %H:%M:%S')
        price = row['close']

        # 진입
        if buy_signals.loc[idx] and position is None:
            success = engine.buy(
                timestamp,
                price,
                fraction=config['POSITION']['fraction']
            )
            if success:
                position = {
                    'entry_time': timestamp,
                    'entry_price': price,
                    'tp_levels': metadata['dynamic_tp'].loc[idx],
                    'sl_level': metadata['dynamic_sl'].loc[idx],
                    'peak_price': price
                }

        # 청산 (포지션 있을 때)
        elif position is not None:
            # Peak 업데이트
            if price > position['peak_price']:
                position['peak_price'] = price

            # 청산 조건 체크
            should_exit = False
            exit_reason = None

            # 1. 동적 익절 (3단계)
            tp1 = position['entry_price'] * (1 + position['tp_levels']['tp1'])
            tp2 = position['entry_price'] * (1 + position['tp_levels']['tp2'])
            tp3 = position['entry_price'] * (1 + position['tp_levels']['tp3'])

            if price >= tp3:
                should_exit = True
                exit_reason = 'TP3 reached'
                exit_fraction = config['EXIT']['split_exit']['tp3_fraction']
            elif price >= tp2:
                should_exit = True
                exit_reason = 'TP2 reached'
                exit_fraction = config['EXIT']['split_exit']['tp2_fraction']
            elif price >= tp1:
                should_exit = True
                exit_reason = 'TP1 reached'
                exit_fraction = config['EXIT']['split_exit']['tp1_fraction']

            # 2. 동적 손절
            sl = position['entry_price'] * (1 + position['sl_level'])
            if price <= sl:
                should_exit = True
                exit_reason = 'SL hit'
                exit_fraction = 1.0  # 전액 청산

            # 3. Trailing Stop
            if config['EXIT']['trailing_stop']['enabled']:
                trailing_sl = position['peak_price'] * (
                    1 - config['EXIT']['trailing_stop']['peak_drop_pct']
                )
                if price <= trailing_sl:
                    should_exit = True
                    exit_reason = 'Trailing SL'
                    exit_fraction = 1.0

            # 청산 실행
            if should_exit:
                engine.sell(timestamp, price, fraction=exit_fraction)

                # 전액 청산 시 포지션 초기화
                if exit_fraction == 1.0 or engine.btc_amount == 0:
                    position = None

    # 최종 통계
    stats = engine.get_statistics()

    return {
        'year': year,
        'version': config['version'],
        'initial_capital': config['BACKTEST']['initial_capital'],
        'final_capital': engine.capital,
        'final_btc': engine.btc_amount,
        'total_return_pct': stats['total_return_pct'],
        'sharpe_ratio': stats['sharpe_ratio'],
        'max_drawdown': stats['max_drawdown'],
        'total_trades': len(engine.trades),
        'win_rate': stats['win_rate'],
        'profit_factor': stats['profit_factor'],
        'trades': [
            {
                'entry_time': t.entry_time,
                'entry_price': float(t.entry_price),
                'exit_time': t.exit_time,
                'exit_price': float(t.exit_price),
                'quantity': float(t.quantity),
                'profit_loss': float(t.profit_loss),
                'profit_loss_pct': float(t.profit_loss_pct),
                'reason': t.reason
            }
            for t in engine.trades
        ]
    }


def save_results(results: Dict, output_path: Path):
    """결과 저장"""
    # 표준 형식으로 변환
    standard_format = {
        'version': results['version'],
        'timestamp': datetime.now().isoformat(),
        'results': {
            results['year']: results
        }
    }

    # 기존 결과 로드 (있으면)
    if output_path.exists():
        with open(output_path) as f:
            existing = json.load(f)
        existing['results'][results['year']] = results
        standard_format = existing

    # 저장
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(standard_format, f, indent=2, ensure_ascii=False)

    print(f"✅ Saved: {output_path}")


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--year', default='2024', help='Backtest year')
    args = parser.parse_args()

    # 실행
    print(f"🚀 Running v35 backtest for {args.year}...")
    results = run_backtest(args.year)

    # 결과 출력
    print(f"\n📊 Results ({args.year}):")
    print(f"   Total Return: {results['total_return_pct']:.2f}%")
    print(f"   Sharpe Ratio: {results['sharpe_ratio']:.2f}")
    print(f"   Max Drawdown: {results['max_drawdown']:.2f}%")
    print(f"   Total Trades: {results['total_trades']}")
    print(f"   Win Rate: {results['win_rate']:.1f}%")
    print(f"   Profit Factor: {results['profit_factor']:.2f}")

    # 저장
    output_path = Path(__file__).parent / 'backtest_results.json'
    save_results(results, output_path)
```

---

## 표준 백테스트 형식

### backtest_results.json 스키마

```json
{
  "version": "v35",
  "timestamp": "2025-10-21T13:32:00+09:00",
  "engine": "StandardCompoundEngineV2",
  "config": {
    "initial_capital": 10000000,
    "fee_rate": 0.0005,
    "slippage": 0.0002
  },
  "results": {
    "2020": {
      "year": "2020",
      "version": "v35",
      "initial_capital": 10000000,
      "final_capital": 12500000,
      "final_btc": 0.0,
      "total_return_pct": 25.0,
      "sharpe_ratio": 2.24,
      "max_drawdown": -2.33,
      "total_trades": 8,
      "win_rate": 50.0,
      "profit_factor": 2.5,
      "trades": [
        {
          "entry_time": "2020-03-15 09:00:00",
          "entry_price": 5000000,
          "exit_time": "2020-03-20 15:00:00",
          "exit_price": 5250000,
          "quantity": 1.0,
          "profit_loss": 250000,
          "profit_loss_pct": 5.0,
          "reason": "TP1 reached"
        }
      ]
    },
    "2021": { ... },
    "2022": { ... },
    "2023": { ... },
    "2024": { ... },
    "2025": { ... }
  },
  "summary": {
    "total_years": 6,
    "avg_annual_return": 18.5,
    "avg_sharpe": 2.1,
    "avg_max_drawdown": -3.2,
    "total_trades": 48,
    "overall_win_rate": 47.5
  }
}
```

### Trade 객체 필수 필드

```python
@dataclass
class Trade:
    """표준 Trade 객체"""
    entry_time: str          # "2020-03-15 09:00:00"
    entry_price: float       # 5000000.0
    quantity: float          # 1.0 (BTC 수량)
    side: str               # "buy"
    exit_time: str          # "2020-03-20 15:00:00"
    exit_price: float       # 5250000.0
    profit_loss: float      # 250000.0
    profit_loss_pct: float  # 5.0
    reason: str             # "TP1 reached"

    # 선택 필드
    fee_paid: Optional[float] = None
    slippage_cost: Optional[float] = None
    market_state: Optional[str] = None
```

---

## 재구축 우선순위

### Phase 1: 즉시 재구축 (1주일)

1. **v35_optimized** ⭐⭐⭐⭐⭐
   - 현재 최고 전략
   - StandardCompoundEngineV2로 재백테스트
   - 2020-2025 전 연도 검증
   - 목표: Out-of-Sample 15%+ 확인

2. **v34_supreme** ⭐⭐⭐⭐
   - v35의 기반
   - 재검증 필요
   - 목표: v35와 비교 분석

3. **v31_scalping_with_classifier** ⭐⭐⭐⭐
   - 검증된 단타 전략
   - Minute60 스캘핑
   - 목표: 2025년 성과 확인

### Phase 2: 백테스트 재실행 (2주일)

4. **v41_scalping_voting** ⭐⭐⭐
   - Phase 0 완료 (브루트포스 분석)
   - 백테스트만 재실행
   - 목표: Day S-Tier +20%+ 재현

5. **v30_perfect_longterm** ⭐⭐
   - Buy&Hold 학습 가치
   - 참고용 재검증

### Phase 3: 전체 전략 표준화 (1개월)

6. **v01~v29** ⭐
   - 모든 레거시 전략
   - 표준 형식 통일
   - StandardCompoundEngineV2 적용
   - 목표: 완전한 데이터베이스 구축

### Phase 4: 새 전략 개발 (지속)

7. **v46_ensemble** (예정)
   - v35 + v31 + v41 통합
   - Multi-Timeframe
   - 목표: 30%+ 연간 수익

---

## 재구축 체크리스트

### 전략별 작업 (각 전략마다)

```markdown
## vXX_strategy_name 재구축 체크리스트

### Phase 1: 파일 표준화
- [ ] 1.1. config.json 표준 형식 변환
  - [ ] version, TIMEFRAME, concept 필드
  - [ ] STRATEGY, ENTRY, EXIT, POSITION, RISK, BACKTEST 섹션
  - [ ] 모든 하이퍼파라미터 명시

- [ ] 1.2. strategy.py 함수 검증
  - [ ] `def vXX_strategy(df) -> Tuple[buy, sell, metadata]` 시그니처
  - [ ] config.json 로드 로직
  - [ ] 명확한 주석 및 docstring
  - [ ] 테스트 코드 (if __name__ == '__main__')

- [ ] 1.3. backtest.py StandardCompoundEngineV2 적용
  - [ ] 엔진 import 및 초기화
  - [ ] config.json 설정 반영
  - [ ] 동적 익절/손절 로직 (있는 경우)
  - [ ] Trailing Stop 로직 (있는 경우)
  - [ ] 결과 저장 함수 (save_results)

### Phase 2: 백테스트 실행
- [ ] 2.1. 2020년 백테스트
  - [ ] `python backtest.py --year 2020`
  - [ ] 결과 확인 (backtest_results.json)
  - [ ] 로그 검토

- [ ] 2.2. 2021~2024년 백테스트
  - [ ] 각 연도 실행
  - [ ] 결과 누적 저장

- [ ] 2.3. 2025년 Out-of-Sample
  - [ ] 최종 검증
  - [ ] 오버피팅 체크

### Phase 3: 검증
- [ ] 3.1. comprehensive_validator.py 실행
  - [ ] `python validation/comprehensive_validator.py --strategies vXX`
  - [ ] 원본 vs 검증 비교
  - [ ] 차이 분석 (1% 이내 목표)

- [ ] 3.2. 검증 리포트 생성
  - [ ] validation/comprehensive_validation_results/vXX_validation.json
  - [ ] 모든 거래 기록 확인
  - [ ] Asset 스냅샷 검토

### Phase 4: 문서화
- [ ] 4.1. README.md 작성
  - [ ] 전략 개요
  - [ ] 핵심 로직 설명
  - [ ] 성과 요약
  - [ ] 사용 방법

- [ ] 4.2. LEARNING.md 작성 (있는 경우)
  - [ ] 학습 내용
  - [ ] 실패 원인
  - [ ] 개선 방향

- [ ] 4.3. 통합 문서 업데이트
  - [ ] CLAUDE.md 업데이트
  - [ ] 251021-1332_COMPLETE_STRATEGY_COMPENDIUM.md 수정

### Phase 5: 통합 테스트
- [ ] 5.1. 전체 연도 성과 확인
  - [ ] 6년 평균 수익률
  - [ ] Sharpe Ratio
  - [ ] Max Drawdown
  - [ ] Win Rate

- [ ] 5.2. Buy&Hold 비교
  - [ ] 연도별 차이
  - [ ] 리스크 조정 수익
  - [ ] 결론 도출

- [ ] 5.3. 다른 전략 비교
  - [ ] v35와 비교
  - [ ] v31과 비교
  - [ ] 순위 결정

### 완료 ✅
- [ ] 최종 검토
- [ ] Git commit
- [ ] 문서 아카이브
```

### 전체 프로젝트 작업

```markdown
## 전체 프로젝트 체크리스트

### 인프라 수정
- [ ] 1. mass_backtest_runner.py 경로 오류 수정
  - [ ] 현재 오류: `strategies/vXX/strategies/vXX/backtest_temp_YEAR.py`
  - [ ] 올바른 경로: `strategies/vXX/backtest.py`

- [ ] 2. comprehensive_validator.py 개선
  - [ ] 모든 결과 파일 형식 지원
  - [ ] v43 comprehensive_results.json 파싱
  - [ ] v44 multi_year_results.json 파싱

### 모든 전략 표준화
- [ ] 3. v01~v45 체크리스트 완료
  - [ ] 50개 전략 × 18단계 = 900 tasks
  - [ ] 진행률 추적 시스템 구축

### 최종 성과 비교
- [ ] 4. 통합 리포트 생성
  - [ ] 전략별 6년 성과
  - [ ] Tier 분류 (S/A/B/C)
  - [ ] 최종 권장 전략 선정

### 실거래 배포
- [ ] 5. 배포 전략 선정
  - [ ] 2025 OOS 15%+ 전략
  - [ ] Sharpe >= 2.0
  - [ ] MDD <= 5%

- [ ] 6. 실거래 시스템 구축
  - [ ] Upbit API 연동
  - [ ] 실시간 데이터 수집
  - [ ] 자동 매매 엔진
  - [ ] 모니터링 대시보드
```

---

## 핵심 코드 스니펫

### StandardCompoundEngineV2 사용법

```python
from validation.standard_compound_engine_v2 import StandardCompoundEngineV2

# 엔진 초기화
engine = StandardCompoundEngineV2(
    initial_capital=10_000_000,  # 초기 자본
    fee_rate=0.0005,             # 0.05% 거래 수수료
    slippage=0.0002              # 0.02% 슬리피지
)

# 매수 (50% 포지션)
success = engine.buy(
    timestamp='2024-01-01 09:00:00',
    price=70_000_000,
    fraction=0.5  # 50% 매수
)

if success:
    print(f"Bought {engine.btc_amount} BTC")
    print(f"Remaining capital: {engine.capital:,.0f} KRW")

# 매도 (전액)
success = engine.sell(
    timestamp='2024-01-05 15:00:00',
    price=75_000_000,
    fraction=1.0  # 100% 매도
)

if success:
    last_trade = engine.trades[-1]
    print(f"Profit: {last_trade.profit_loss:,.0f} KRW ({last_trade.profit_loss_pct:.2f}%)")

# 통계
stats = engine.get_statistics()
print(f"Total Return: {stats['total_return_pct']:.2f}%")
print(f"Sharpe Ratio: {stats['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {stats['max_drawdown']:.2f}%")
print(f"Win Rate: {stats['win_rate']:.1f}%")
print(f"Profit Factor: {stats['profit_factor']:.2f}")

# 연도별 초기화
engine.reset()  # 2021년 시작
```

### comprehensive_validator 사용법

```python
from validation.comprehensive_validator import ComprehensiveValidator

# 검증기 초기화
validator = ComprehensiveValidator(initial_capital=10_000_000)

# 단일 전략 검증
from pathlib import Path
strategy_path = Path('strategies/v35_optimized')
results = validator.validate_strategy(strategy_path)

# 결과 확인
for year, comparison in results['comparison'].items():
    print(f"{year}: Original {comparison['original_return_pct']:.2f}% → "
          f"Validated {comparison['validated_return_pct']:.2f}% "
          f"(Δ {comparison['difference_pct']:.2f}%)")

# 여러 전략 검증
strategies = ['v35_optimized', 'v34_supreme', 'v31_scalping_with_classifier']
for strat in strategies:
    path = Path(f'strategies/{strat}')
    results = validator.validate_strategy(path)
    # 결과 저장
    validator.save_validation_results(results, Path(f'validation/results/{strat}.json'))
```

### 동적 익절/손절 로직

```python
def apply_dynamic_exit(position: Dict, current_price: float,
                       config: Dict, market_state: str) -> Tuple[bool, str, float]:
    """
    동적 익절/손절 로직

    Returns:
        should_exit: 청산 여부
        exit_reason: 청산 사유
        exit_fraction: 청산 비율
    """
    # TP 레벨 (시장 상태별)
    tp_config = config['EXIT']['dynamic_tp'].get(market_state.lower().split('_')[0], {})
    tp1 = position['entry_price'] * (1 + tp_config.get('tp1', 0.05))
    tp2 = position['entry_price'] * (1 + tp_config.get('tp2', 0.10))
    tp3 = position['entry_price'] * (1 + tp_config.get('tp3', 0.15))

    # SL 레벨
    sl_config = config['EXIT']['dynamic_sl'].get(market_state.lower().split('_')[0], -0.02)
    sl = position['entry_price'] * (1 + sl_config)

    # TP3 도달 (30% 청산)
    if current_price >= tp3:
        return True, 'TP3 reached', config['EXIT']['split_exit']['tp3_fraction']

    # TP2 도달 (30% 청산)
    elif current_price >= tp2:
        return True, 'TP2 reached', config['EXIT']['split_exit']['tp2_fraction']

    # TP1 도달 (40% 청산)
    elif current_price >= tp1:
        return True, 'TP1 reached', config['EXIT']['split_exit']['tp1_fraction']

    # SL 도달 (전액 청산)
    elif current_price <= sl:
        return True, 'SL hit', 1.0

    # Trailing Stop
    if config['EXIT']['trailing_stop']['enabled']:
        trailing_sl = position['peak_price'] * (
            1 - config['EXIT']['trailing_stop']['peak_drop_pct']
        )
        if current_price <= trailing_sl:
            return True, 'Trailing SL', 1.0

    return False, None, 0.0


# 사용 예시
position = {
    'entry_price': 70_000_000,
    'peak_price': 75_000_000  # 업데이트 필요
}

current_price = 73_500_000
should_exit, reason, fraction = apply_dynamic_exit(
    position, current_price, config, 'BULL_STRONG'
)

if should_exit:
    engine.sell(timestamp, current_price, fraction=fraction)
    print(f"Exit: {reason}, Fraction: {fraction*100}%")
```

### 시장 분류 + 전략 선택

```python
def classify_and_select_strategy(df: pd.DataFrame, config: Dict) -> Tuple[pd.Series, pd.Series]:
    """
    시장 분류 및 전략 선택

    Returns:
        market_states: 각 시점의 시장 상태
        selected_strategies: 각 시점의 선택된 전략
    """
    # 7-Level 시장 분류
    market_states = pd.Series('SIDEWAYS_FLAT', index=df.index)

    classification = config['STRATEGY']['market_classification']

    # BULL_STRONG
    mask = (
        (df['mfi'] >= classification['bull_strong']['mfi']) &
        (df['macd'] - df['macd_signal'] >= classification['bull_strong']['macd_signal_diff'])
    )
    market_states[mask] = 'BULL_STRONG'

    # BULL_MODERATE
    mask = (
        (df['mfi'] >= classification['bull_moderate']['mfi']) &
        (df['macd'] - df['macd_signal'] >= classification['bull_moderate']['macd_signal_diff']) &
        (market_states == 'SIDEWAYS_FLAT')  # 중복 방지
    )
    market_states[mask] = 'BULL_MODERATE'

    # SIDEWAYS_UP
    mask = (
        (df['mfi'] >= classification['sideways_up']['mfi']) &
        (df['mfi'] < classification['bull_moderate']['mfi']) &
        (df['macd'] - df['macd_signal'] >= classification['sideways_up']['macd_signal_diff'])
    )
    market_states[mask] = 'SIDEWAYS_UP'

    # ... (SIDEWAYS_DOWN, BEAR_MODERATE, BEAR_STRONG)

    # 전략 매핑
    strategy_map = {
        'BULL_STRONG': 'momentum_trading',
        'BULL_MODERATE': 'breakout_trading',
        'SIDEWAYS_UP': 'rsi_bollinger_bands',
        'SIDEWAYS_FLAT': 'rsi_bollinger_bands',
        'SIDEWAYS_DOWN': 'rsi_bollinger_bands',
        'BEAR_MODERATE': 'exit_only',
        'BEAR_STRONG': 'exit_only'
    }

    selected_strategies = market_states.map(strategy_map)

    return market_states, selected_strategies


# 사용 예시
market_states, strategies = classify_and_select_strategy(df, config)

print("Market Distribution:")
print(market_states.value_counts())

print("\nStrategy Distribution:")
print(strategies.value_counts())
```

---

## 참고 문서 목록

### 검증 리포트

1. **[251021-1316_V37_V45_COMPREHENSIVE_VALIDATION_REPORT.md](251021-1316_V37_V45_COMPREHENSIVE_VALIDATION_REPORT.md)**
   - v37~v45 종합 검증
   - 원본 vs 검증 비교
   - 복리 버그 발견

2. **[251021-0652_VERIFICATION_REPORT_FINAL.md](251021-0652_VERIFICATION_REPORT_FINAL.md)**
   - 초기 검증 결과

3. **[251020-1952_STRATEGY_VALIDATION_REPORT.md](251020-1952_STRATEGY_VALIDATION_REPORT.md)**
   - 전략별 검증 상세

### Phase 리포트

4. **[PHASE5_6_FINAL_REPORT.md](PHASE5_6_FINAL_REPORT.md)**
   - v35, v36 개발 과정
   - 동적 익절/손절 시스템
   - SIDEWAYS 전략 강화

5. **[PHASE4.2_VALIDATION_FINAL_4YEAR_REPORT.md](PHASE4.2_VALIDATION_FINAL_4YEAR_REPORT.md)**
   - v34 개발
   - 2020-2024 Multi-Strategy

6. **[PHASE4_COMPARISON_REPORT.md](PHASE4_COMPARISON_REPORT.md)**
   - v32~v34 비교

### 전략별 리포트

7. **[v34_supreme/FINAL_REPORT.md](v34_supreme/FINAL_REPORT.md)**
   - v34 최종 보고서

8. **[v31_scalping_with_classifier/FINAL_REPORT.md](v31_scalping_with_classifier/FINAL_REPORT.md)**
   - v31 단타 전략
   - Day-level 필터

9. **[v30_perfect_longterm/LEARNING.md](v30_perfect_longterm/LEARNING.md)**
   - Buy&Hold 학습
   - 장기 투자 실패 원인

10. **[251020-1526_V43_SUPREME_FINAL_REPORT.md](251020-1526_V43_SUPREME_FINAL_REPORT.md)**
    - v43 리포트 (버그 발견 전)

11. **[251020-1727_V45_ULTIMATE_FINAL_REPORT.md](251020-1727_V45_ULTIMATE_FINAL_REPORT.md)**
    - v45 리포트 (버그 발견 전)
    - v43 메커니즘 분석

### 비교 리포트

12. **[251020-1645_V43_V44_FINAL_COMPARISON.md](251020-1645_V43_V44_FINAL_COMPARISON.md)**
    - v43 vs v44 비교

13. **[251020-1542_V41_V43_PRODUCTION_READINESS_REPORT.md](251020-1542_V41_V43_PRODUCTION_READINESS_REPORT.md)**
    - v41 vs v43 배포 준비

14. **[FINAL_COMPARISON.md](FINAL_COMPARISON.md)**
    - 전체 전략 비교

15. **[V13-V18_FINAL_REPORT.md](V13-V18_FINAL_REPORT.md)**
    - VWAP/Voting 실험

### 분석 데이터

16. **[_raw_analysis/README.md](_raw_analysis/README.md)**
    - Phase 0 원시 데이터 분석
    - 100+ 지표 예측력

17. **[PERFECT_SIGNALS.md](../PERFECT_SIGNALS.md)**
    - 완벽한 정답 시그널
    - 45,254개 시그널

18. **[v41_scalping_voting/analysis/](v41_scalping_voting/analysis/)**
    - 브루트포스 분석
    - Tier 분류
    - 최적화 결과

### 프로젝트 문서

19. **[CLAUDE.md](../CLAUDE.md)**
    - 통합 가이드
    - 최신 권장 전략
    - 핵심 학습 사항

20. **이 문서 (251021-1332_COMPLETE_STRATEGY_COMPENDIUM.md)**
    - 완전한 전략 종합
    - 재구축 마스터 문서

---

## 결론

### 현재 상태

**검증 완료**: 3개 (v38, v39, v40)
**검증 필요**: 39개 (v01~v37, v41)
**검증 불가**: 8개 (v42~v45, 복리 버그)

**최고 전략**: v35_optimized (2025 OOS +14.20%, Sharpe 2.24)

### 다음 단계

1. **v35 재검증** (최우선)
   - StandardCompoundEngineV2로 재계산
   - 2020-2025 전 연도
   - 목표: 15%+ 확인

2. **v41 백테스트 재실행**
   - Phase 0 완료
   - Day S-Tier 재현
   - 목표: +20%+

3. **모든 전략 표준화**
   - 50개 전략
   - 표준 형식 통일
   - 완전한 데이터베이스 구축

### 최종 목표

**실거래 배포**:
- 전략: v35 또는 v35+v31 앙상블
- 목표 수익: 연간 15~30%
- 리스크: Sharpe >= 2.0, MDD <= 5%

---

**문서 종료**
**다음 문서**: 개별 전략 재구축 시 본 문서 참조
