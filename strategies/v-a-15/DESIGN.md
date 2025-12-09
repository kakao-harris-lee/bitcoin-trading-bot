# v-a-15: Ultimate Perfect Signal Reproducer

**생성일**: 2025-11-18
**기반**: v-a-11 + 최신 연구 기반 개선
**목표**: 2025년 +43-59% (v-a-11 +20.42% → +23-39%p 개선)

---

## 🎯 프로젝트 목표

### 핵심 목표

**Perfect Signal 재현율**: 70%+ (S-Tier)
**2025 수익률**: +43-59%
**Sharpe Ratio**: >= 2.0
**Max Drawdown**: <= -10%
**승률**: >= 50%

### v-a-11 현황 분석

**2025년 성과**:
- 수익률: +20.42%
- 승률: 46.7%
- 거래: 30회
- 6년 평균: +66.10%/년

**핵심 문제**:
1. ❌ 승률 낮음 (39.95%, 6년 평균)
2. ❌ Stop Loss 과다 (37.5%)
3. ❌ SIDEWAYS 효율성 낮음 (거래 73.6%, 기여도 30.3%)
4. ❌ Defensive 마이너스 기여 (-35.71%p)

**핵심 강점**:
1. ✅ Trend Following 기여도 69.6% (거래 22.6%만으로)
2. ✅ 장기 안정성 (6년 평균 +66%)
3. ✅ v37 시장 분류 효과적

---

## 📊 개선 전략 (5대 핵심)

### 1. SIDEWAYS Grid Trading ⭐⭐⭐ (최우선)

**문제**: SIDEWAYS 거래 73.6%인데 기여도 30.3%만

**해결**: Grid Trading 도입

**구현**:
```python
# Support/Resistance 자동 감지
support = df['low'].rolling(20).min()
resistance = df['high'].rolling(20).max()

# Grid 레벨 생성 (5-7단계)
grid_levels = np.linspace(support, resistance, 7)

# 각 레벨에서 진입/청산
for level in grid_levels:
    if price <= level * 0.98:  # 레벨 하회
        buy(position=0.15)  # 15% 배치
    elif price >= level * 1.02:  # 레벨 상회
        sell()  # 매도
```

**예상 효과**: SIDEWAYS 수익 +30-50%, 총 +8-12%p

### 2. Kelly Criterion Position Sizing ⭐⭐

**문제**: 고정 포지션 크기 (40%)

**해결**: 승률과 수익/손실 비율 기반 동적 포지션

**구현**:
```python
# Kelly % 계산
W = win_rate  # 0.467 (v-a-11)
R = avg_win / abs(avg_loss)  # 6.51 / 3.31 = 1.97
kelly_pct = W - (1 - W) / R  # 0.197 (19.7%)

# 신뢰도 점수 (0-100)
confidence = 0
if adx > 25: confidence += 20
if volume > 2.0: confidence += 15
if rsi < 20: confidence += 25
# ... 최대 100점

# 동적 포지션
position = kelly_pct * (confidence / 100) * capital
position = np.clip(position, 0.1, 0.8)  # 10-80% 제한
```

**예상 효과**: 복리 효과 +5-10%p

### 3. ATR Dynamic Exit ⭐⭐

**문제**: 고정 TP/SL, 변동성 미반영

**해결**: ATR 기반 동적 익절/손절

**구현**:
```python
# 진입 시 ATR 기록
entry_atr = df['atr'].iloc[entry_idx]

# 동적 TP/SL (2:1 reward-risk)
dynamic_tp = entry_price + (entry_atr * 6.0)
dynamic_sl = entry_price - (entry_atr * 3.0)

# Trailing Stop
if profit > 0.10:  # 10% 이상 수익
    trailing_sl = peak_price - (entry_atr * 3.5)
```

**예상 효과**: MDD -5%p, Sharpe +0.3-0.5, 수익 +3-5%p

### 4. Trend Following 강화 ⭐

**문제**: 거래 22.6%만인데 기여도 69.6%

**해결**: 더 많은 Trend 기회 포착

**변경**:
- ADX: 25 → 20 (더 많은 추세 포착)
- MACD 조건 추가: 골든크로스 + RSI < 65
- Volume 필터 추가: > 1.5x

**예상 효과**: Trend 거래 +30%, 수익 +2-4%p

### 5. Defensive 폐기 ⭐

**문제**: 총 기여 -35.71%p (마이너스!)

**해결**: 완전 제거

**예상 효과**: 손실 -35.71%p 제거

---

## 🏗️ 아키텍처 설계

### 전체 구조

```
v-a-15 Ultimate Adaptive Strategy
├── Entry Layer
│   ├── Trend Following (강화) ← ADX 20+, MACD+RSI+Volume
│   ├── SIDEWAYS Grid Trading (NEW) ← 5-7 Grid Levels
│   ├── SIDEWAYS Mean Reversion (강화) ← v-a-11 기존
│   └── Defensive (제거) ← -35.71%p 손실
├── Position Sizing Layer (NEW)
│   ├── Kelly Criterion 계산
│   ├── 신뢰도 점수 시스템 (0-100점)
│   └── 동적 포지션 크기 (10-80%)
├── Exit Layer (완전 재설계)
│   ├── ATR 기반 Dynamic TP/SL
│   ├── Trailing Stop (ATR × 3.5)
│   ├── 시장 상태 변화 즉시 청산
│   └── 변동성 적응형
└── Monitoring Layer (NEW)
    ├── 실시간 성과 추적
    ├── Grid 레벨 시각화
    ├── 포지션 분석
    └── 텔레그램 리포트
```

### 폴더 구조

```
strategies/v-a-15/
├── core/
│   ├── market_classifier.py      # v37 이식
│   ├── grid_manager.py            # Grid Trading Manager (NEW)
│   ├── kelly_calculator.py        # Kelly Criterion (NEW)
│   ├── atr_exit_manager.py        # ATR Dynamic Exit (NEW)
│   └── confidence_scorer.py       # 신뢰도 점수 (NEW)
├── strategies/
│   ├── trend_following.py         # 강화된 Trend
│   ├── sideways_grid.py           # Grid Trading (NEW)
│   ├── sideways_mean_reversion.py # v-a-11 유지
│   └── [defensive.py 제거]
├── utils/
│   ├── perfect_signal_loader.py   # 재활용
│   └── performance_tracker.py     # 성과 추적 (NEW)
├── generate_signals.py            # 메인 시그널 생성
├── backtest.py                    # 백테스팅
├── config.json                    # 설정
├── DESIGN.md                      # 본 문서
└── README.md
```

---

## 🔬 구현 계획 (3주)

### Week 1: 핵심 인프라 (5일)

**Day 1-2: Grid Trading Manager**
- [ ] `core/grid_manager.py` 구현
- [ ] Support/Resistance 자동 감지
- [ ] Grid 레벨 계산 (5-7단계)
- [ ] 진입/청산 로직
- [ ] 단위 테스트

**Day 3: Kelly Criterion**
- [ ] `core/kelly_calculator.py` 구현
- [ ] Kelly % 계산
- [ ] 신뢰도 점수 시스템
- [ ] 동적 포지션 크기 계산

**Day 4-5: ATR Dynamic Exit**
- [ ] `core/atr_exit_manager.py` 구현
- [ ] ATR 기반 TP/SL
- [ ] Trailing Stop
- [ ] 변동성 적응 로직

### Week 2: 전략 통합 (5일)

**Day 6: Trend Following 강화**
- [ ] ADX 임계값 완화 (25 → 20)
- [ ] MACD + RSI + Volume 조건 추가
- [ ] 백테스팅

**Day 7-8: SIDEWAYS Grid 통합**
- [ ] `strategies/sideways_grid.py` 구현
- [ ] Grid Manager 연동
- [ ] v-a-11 SIDEWAYS 전략과 병행
- [ ] 우선순위 로직

**Day 9: Defensive 제거**
- [ ] 관련 코드 제거
- [ ] 테스트 검증

**Day 10: 통합 및 초기 백테스트**
- [ ] 모든 컴포넌트 통합
- [ ] 2024년 백테스팅
- [ ] 버그 수정

### Week 3: 최적화 및 검증 (5일)

**Day 11-13: Optuna 최적화**
- [ ] 하이퍼파라미터 탐색 공간 정의
- [ ] 1000 trials 실행
- [ ] 최적 파라미터 선정

**Day 14: Walk-Forward 검증**
- [ ] 2020-2024 학습
- [ ] 2025 Out-of-Sample 테스트
- [ ] 재현율 측정

**Day 15: 문서화 및 배포 준비**
- [ ] 성과 보고서 작성
- [ ] README 업데이트
- [ ] AWS 배포 준비

---

## 📈 예상 성과

### 시나리오 분석

**보수적 시나리오**:
```
SIDEWAYS Grid: +6%p
Kelly Criterion: +3%p
ATR Exit: +2%p
Trend 강화: +2%p
Defensive 제거: 손실 방지
────────────────────
총 개선: +13%p
v-a-15: +33.42% (v-a-11 +20.42%)
```

**현실적 시나리오**:
```
SIDEWAYS Grid: +10%p
Kelly Criterion: +7%p
ATR Exit: +4%p
Trend 강화: +3%p
Defensive 제거: 손실 방지
────────────────────
총 개선: +24%p
v-a-15: +44.42%
```

**낙관적 시나리오**:
```
SIDEWAYS Grid: +15%p
Kelly Criterion: +10%p
ATR Exit: +5%p
Trend 강화: +4%p
Defensive 제거: +5%p
────────────────────
총 개선: +39%p
v-a-15: +59.42%
```

### v35 S-Tier 대비

| 전략 | 2025 수익률 | Sharpe | MDD | 거래 | 승률 |
|------|------------|--------|-----|------|------|
| v35 S-Tier | +24.38% | 2.61 | -2.63% | 5회 | 40% |
| v-a-11 | +20.42% | - | - | 30회 | 46.7% |
| **v-a-15 목표** | **+44-59%** | **2.3+** | **-8%** | **35-40회** | **52%+** |

---

## 🔍 리스크 및 대응

### 주요 리스크

**1. Grid Trading 복잡도**
- 리스크: 구현 난이도, 버그 가능성
- 대응: 단계별 구현, 철저한 테스트

**2. 오버피팅**
- 리스크: 과도한 최적화로 실전 성과 저하
- 대응: Walk-Forward 검증, Out-of-Sample 필수

**3. Kelly Criterion 과도한 포지션**
- 리스크: 잘못된 신뢰도 점수 시 큰 손실
- 대응: Half Kelly 사용, 최대 80% 제한

**4. 개발 기간 초과**
- 리스크: 3주 목표 미달성
- 대응: Week 1 핵심 기능 우선, Week 2-3 선택적

### 중단 조건

다음 경우 개발 중단 및 v-a-11 유지:
- Week 2 종료 시점 백테스트 < +30%
- Out-of-Sample 성과 < v-a-11 (+20.42%)
- Sharpe < 1.5
- MDD > -15%

---

## 💡 핵심 원칙

### 설계 원칙

1. **단순함 유지**: 복잡도 증가 최소화
2. **검증 우선**: 모든 컴포넌트 단위 테스트
3. **점진적 개선**: 한 번에 하나씩 추가
4. **백테스트 중심**: 코드 작성 → 즉시 검증
5. **문서화**: 모든 결정 기록

### 개발 원칙

1. **TDD (Test-Driven Development)**:
   - 테스트 작성 → 구현 → 검증

2. **Git 브랜치 전략**:
   ```
   main
   └── v-a-15-dev
       ├── feature/grid-trading
       ├── feature/kelly-criterion
       ├── feature/atr-exit
       └── feature/trend-enhance
   ```

3. **일일 백테스트**:
   - 매일 종료 시 2024년 백테스트
   - 성과 추적, 회귀 방지

---

## 📊 성공 지표

### Week 1 완료 기준

- [ ] Grid Manager 단위 테스트 통과
- [ ] Kelly Calculator 동작 확인
- [ ] ATR Exit Manager 구현 완료

### Week 2 완료 기준

- [ ] 2024년 백테스트: >= +35%
- [ ] Sharpe >= 1.8
- [ ] MDD <= -10%

### Week 3 완료 기준

- [ ] 2025년 Out-of-Sample: >= +40%
- [ ] Sharpe >= 2.0
- [ ] MDD <= -8%
- [ ] 재현율 >= 60% (A-Tier)

### 최종 배포 기준

- [ ] 2025년 Out-of-Sample: >= +43%
- [ ] v-a-11 대비 최소 +20%p 개선
- [ ] v35 S-Tier 대비 경쟁력 확보
- [ ] 안정성 검증 (Sharpe >= 2.0)

---

## 🚀 배포 전략

### Phase 1: 로컬 검증 (Week 3)

- 2020-2025 전체 데이터 백테스트
- Walk-Forward 검증
- 재현율 측정

### Phase 2: Paper Trading (1-2주)

- AWS에 Paper Trading 배포
- 실시간 성과 추적
- v35 S-Tier와 병행 비교

### Phase 3: 실전 배포 (조건부)

**배포 조건**:
1. Paper Trading 2주 성과 >= +3%
2. v35 대비 우위 확인
3. 리스크 지표 안정적

**배포 방법**:
- v35 50% + v-a-15 50% (분산)
- 또는 v-a-15 100% (공격적)

---

## 📝 참고 자료

### 연구 기반

**Grid Trading**:
- Coinrule, TradeSanta 베스트 프랙티스
- SIDEWAYS 시장 31% 비중 (연구 결과)

**Kelly Criterion**:
- William F. Kelly (1956)
- Half Kelly for Safety

**ATR Dynamic Exit**:
- Wilder's ATR (1978)
- 2:1 Reward-Risk 비율 (표준)

### v-a-11 분석 문서

- `strategies/v-a-11/251022-1628_PHASE1_V-A-11_COMPREHENSIVE_ANALYSIS.md`
- v-a-11 전략별 기여도 상세 분석
- 개선 방향 도출

---

**문서 버전**: v1.0
**작성일**: 2025-11-18
**작성자**: Claude Code
**상태**: 설계 완료, 구현 대기
