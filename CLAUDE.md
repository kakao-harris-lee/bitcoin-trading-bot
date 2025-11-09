# 비트코인 트레이딩 봇 - 프로젝트 가이드

**최종 업데이트**: 2025-11-08

---

## 🏆 현재 최고 전략

### v35 Optimized (검증 완료, Production Ready)

**핵심 설정**:
```yaml
타임프레임: Day (일봉)
진입 조건: 7-Level 시장 분류 + 동적 전략
익절/손절: 동적 (시장별 TP 5~20%)
포지션 크기: 고정 50%
```

**검증된 성과**:
| 연도 | 수익률 | Sharpe | MDD | Buy&Hold |
|------|--------|--------|-----|----------|
| 2023 | **+13.64%** | 2.24 | -2.33% | +170% |
| 2024 | **+25.91%** | 2.24 | -2.33% | +137% |
| 2025 | **+14.20%** | 2.24 | -2.33% | - |

**핵심 특징**:
- ✅ Sharpe 2.24 (매우 높은 안정성)
- ✅ MDD -2.33% (극도로 안전)
- ✅ 3년 연속 10%+ 수익
- ✅ 검증 가능한 실제 성과

**위치**: `strategies/v35_optimized/`

### ⚠️ v43/v45 복리 버그 경고

**중요**: v43/v45는 치명적인 복리 계산 버그로 **사용 금지**

```python
# 버그: position을 BTC 수량이 아닌 비율로 계산
position = capital / (capital × 1.0007)  # = 0.9993 (잘못됨!)
```

**결과**: 실제 연평균 83% → 버그로 508% 과장 (6.1배 왜곡)

**상세 분석**: `strategies/251020-1740_V43_MECHANISM_EXPLAINED.md`

---

## 🚀 현재 진행 중: v-a 시리즈

**목표**: 완벽한 정답 시그널 45,254개를 최대한 재현

### 완벽한 정답 시그널 (Perfect Signals)

**개념**: 미래 데이터로 추출한 100% 최적 매매 타이밍
- **45,254개** 시그널 (2020-2024, 5개 타임프레임)
- 평균 수익률: day **14.52%** / minute60 3.20% / minute5 1.71%
- 📖 상세: `strategies/v41_scalping_voting/analysis/perfect_signals/`

**재현율 기반 평가**:
```yaml
재현율 공식:
  신호_재현율 = (전략_시그널 / 완벽_시그널) × 0.4
  수익_재현율 = (전략_수익률 / 완벽_수익률) × 0.6
  종합_재현율 = 신호_재현율 + 수익_재현율

성공 기준:
  S-Tier (배포 가능): 70%+
  A-Tier (최적화 필요): 50-70%
  B-Tier (재설계 필요): 30-50%
  C-Tier (폐기): <30%
```

### v-a 시리즈 로드맵

**전략 계획**:
- **v-a-01~03**: 기반 구축 (Signal Loader, 단순 재현, Multi-Indicator)
- **v-a-04~07**: 단일 타임프레임 최적화 (Day, M60, M240, 최적 선택)
- **v-a-08~11**: 복합 전략 (Dual TF, Triple TF, All TF Voting, Adaptive)
- **v-a-12~14**: 고급 최적화 (ML Pattern, Optuna, Dynamic Exit)
- **v-a-15**: 최종 통합 (Ultimate Perfect Reproducer)

### 진행 상황

**✅ v-a-01 완료** (C-Tier, 폐기):
- RSI + MFI 단순 조합
- 종합 재현율: 7.74%
- 결론: 단순 지표로는 재현 불가

**✅ v-a-02 완료** (A-Tier, S에 육박):
- v42 Score Engine 활용 (7차원 지표)
- S-Tier 버전 종합 재현율: **74.12%**
- v-a-01 대비 **9.6배 향상**
- 시그널 재현율: 75.19% (200/266 매칭)
- 평균 거래 수익률: 11.28% (Perfect 15.37% 대비 73.4%)

**⏳ 다음 작업**:
- v-a-02 A/B-Tier 검증
- v-a-03 이후 단계 설계

### 주요 도구

**PerfectSignalLoader**:
```python
from utils.perfect_signal_loader import PerfectSignalLoader

loader = PerfectSignalLoader()
df = loader.load_perfect_signals('day', 2024)  # 266개 시그널
```

**ReproductionCalculator**:
```python
from utils.reproduction_calculator import ReproductionCalculator

calc = ReproductionCalculator(tolerance_days=1)
result = calc.calculate_reproduction_rate(
    strategy_signals=strategy_df,
    perfect_signals=perfect_df,
    strategy_return=0.0048,
    perfect_return=0.1537
)
```

**UniversalEvaluationEngine**:
```python
from validation.universal_evaluation_engine import UniversalEvaluationEngine

engine = UniversalEvaluationEngine(
    initial_capital=10_000_000,
    fee_rate=0.0005,
    slippage=0.0002
)
report = engine.evaluate_all_combinations(...)
```

---

## 📚 프로젝트 가이드

### 프로젝트 철학

- **반응형 전략**: 예측하지 않고 시장 변화에 빠르게 대응
- **결과론 회피**: Buy&Hold는 결과론, 실시간에서는 알 수 없음
- **수수료 고려**: 모든 전략은 수수료(0.14%/거래) 극복 필수
- **검증 필수**: 2020-2024 학습 + 2025 Out-of-Sample 테스트

### 환경 설정

```bash
# 가상환경
source venv/bin/activate

# 필수 라이브러리
brew install ta-lib  # macOS
pip install -r requirements.txt
```

**DB 구조**:
- `upbit_bitcoin.db`: 원본 데이터 (읽기 전용)
- `trading_results.db`: 백테스팅 결과
- `strategies/v{NN}_{name}/`: 전략별 독립 폴더

### 프로젝트 구조

```
strategies/
├── v35_optimized/           # 현재 최고 전략
├── v-a-XX/                  # 진행 중 (Perfect Signal Reproduction)
├── v41_scalping_voting/     # Perfect Signal 추출 완료
│   └── analysis/
│       ├── perfect_signals/ # 45,254개 정답 시그널
│       ├── bruteforce/      # 브루트포스 분석
│       └── optimization/    # 점수 체계 최적화
├── _raw_analysis/           # Phase 0 원시 데이터 분석
└── _templates/              # 템플릿
```

### 전략 개발 규칙

#### 1. 계획 → 승인 → 구현

```
1. _plans/{DATE}.v{NN}.{name}.plan.md 작성
2. 사용자 승인 대기 ⭐
3. 코드 작성 (strategies/v{NN}_{name}/)
4. 백테스팅 실행
5. 결과 분석 및 문서화
```

#### 2. 문서 명명 규칙

**타임스탬프 prefix 사용**:
```
YYMMDD-HHmm_document_name.md

예시:
- 251020-0215_FINAL_OPTIMAL_STRATEGY_REPORT.md
- 251019-1834_v35_optimization_results.md
```

**적용 대상**:
- 분석 보고서 (analysis/, _results/)
- 전략 계획서 (_plans/)
- 비교 리포트

**예외 (타임스탬프 없음)**:
- README.md, CLAUDE.md
- config.json, 코드 파일 (*.py)
- 데이터 파일 (*.csv, *.json)

#### 3. 필수 파일

```python
strategies/v{NN}_{name}/
├── config.json      # 하이퍼파라미터
├── strategy.py      # 전략 로직
├── backtest.py      # 백테스팅 스크립트
└── results.json     # 결과 (자동 생성)
```

### 백테스팅 표준

**기간**:
- 학습: 2020-01-01 ~ 2024-12-31 (5년)
- 검증: 2025-01-01 ~ 현재 (Out-of-Sample)

**Buy&Hold 기준선**:
- 2020: +286.05%
- 2021: +75.82%
- 2022: -63.60%
- 2023: +170.07%
- 2024: +136.67%
- 5년 누적: +1,479.09% (CAGR 73.65%)

**성공 기준**:
- Out-of-Sample 수익률: >= 15% (2025)
- Sharpe Ratio: >= 1.5
- Max Drawdown: <= 20%
- 승률: >= 50%

---

## 🔧 필수 정보

### 타임프레임 가이드

| 타임프레임 | 용도 | 거래빈도 | 목표 수익 | 특징 |
|-----------|------|----------|-----------|------|
| Day | 시장 분류/필터 | - | - | MFI 지배적, 방향성 제시 |
| Minute240 | 스윙 | 0.1/일 | +3-5% | 중기 추세 포착 |
| Minute60 | 중단타 | 0.3/일 | +1-2% | Low Vol 중요, 균형잡힌 성과 |
| Minute15 | 단타 | 0.5/일 | +1% | Local Min 강화, 높은 회전율 |
| Minute5 | 초단타 | 1/일 | +0.5% | 노이즈 많음, 비추천 |

### 수수료 계산

```
거래당 비용 = 0.05% (진입) + 0.05% (청산) + 0.04% (슬리피지) = 0.14%

목표 수익 >= 10 × 수수료
→ 최소 1.4% 목표 필요
```

### 핵심 지표 우선순위

**상관계수 기반** (v41 분석):
1. **MFI (Money Flow Index)**: day 상관 0.170 (가장 강력)
2. **Local Minima**: 상관 0.063-0.088 (바닥 반등)
3. **Low Volatility**: minute60 역상관 -0.123 (변동성 폭발 직전)

### 금지 사항

1. ❌ 예측 기반 전략 (RSI < 30 → 매수)
2. ❌ 복잡한 지표 조합 (3개 이상)
3. ❌ 과도한 최적화 (overfitting)
4. ❌ 분할 매매 (수수료 폭증)
5. ❌ Day 레벨 능동 거래 (Buy&Hold 불가능)

### 권장 사항

1. ✅ 반응형 전략 (모멘텀 추종)
2. ✅ 단순한 조건 (2-3개)
3. ✅ 시장 필터링 (BULL만 거래)
4. ✅ 큰 타겟 (1.5%+, 수수료 극복)
5. ✅ Minute60 이상 (노이즈 감소)

---

## 🤖 자동화 도구

### 멀티 타임프레임 백테스트
```bash
python automation/run_multi_timeframe_backtest.py
python automation/compare_timeframe_results.py
```

### 하이퍼파라미터 최적화
```bash
python automation/optimize_hyperparameters.py \
  --strategy v31 --timeframe minute60 --n-trials 200
```

---

## 📊 완료된 프로젝트 (요약)

### Phase 0-2: 기초 분석 및 초기 전략 (2020-10-18)

**Phase 0** (_raw_analysis/):
- 100+ 지표 계산 및 상관관계 분석
- MFI가 가장 강력한 예측 지표 발견
- 📖 `strategies/_raw_analysis/reports/comprehensive_analysis.md`

**Phase 1** (v30_perfect_longterm):
- 일간 능동 거래로 Buy&Hold 초과 불가능 확인
- 📖 `strategies/v30_perfect_longterm/LEARNING.md`

**Phase 2** (v31_scalping_with_classifier):
- Minute60 + Day 필터로 +6.33% 달성
- Sharpe 1.94, MDD 8.96%
- 📖 `strategies/v31_scalping_with_classifier/FINAL_REPORT.md`

### Phase 4-5: Multi-Strategy → v35 (2025-10-19)

**v32**: 2024 단일 연도 최적화 → 오버피팅 (2025 실패)

**v34**: 2020-2024 Multi-Strategy
- 7-Level 시장 분류 도입
- 2025: +8.43%, Sharpe 1.34

**v35**: 동적 익절 + SIDEWAYS 강화 ⭐
- 2025: +14.20%, Sharpe 2.24 (현재 최고)
- DynamicExitManager 구현
- 📖 `strategies/v35_optimized/`

### Phase 6: v36 Multi-Timeframe (2025-10-19)

**상태**: 프레임워크 완성, 미실행
- Day (40%) + M240 (30%) + M60 (30%)
- Ensemble Manager 구현 완료
- 예상 2025 수익률: +25-30%

### v41: Perfect Signal 추출 (2025-10-20)

**완료**:
- 45,254개 완벽한 정답 시그널 추출
- 브루트포스 분석 (모든 캔들 × 보유 기간)
- 점수 체계 최적화 (상관계수 기반)
- 📖 상세: `strategies/v41_scalping_voting/analysis/`

**핵심 발견**:
- day S-Tier: 평균 수익률 23.24%, Sharpe 1.27
- 2024 단타 백테스팅: **1,338%** (목표 8.6배 초과달성)
- 단타 복리 효과 >> 장기보유 높은 수익률

### v42: Ultimate Scalping (2025-10-20, 중단)

**설계**: 5-Layer 아키텍처
- 진행도: 2/18 단계 (11%)
- 중단 사유: v-a 시리즈로 방향 전환

---

## 📖 참고 자료

### 주요 문서

**현재 전략**:
- v35 Optimized: `strategies/v35_optimized/`
- v-a 시리즈: `strategies/v-a-XX/`

**분석 자료**:
- Perfect Signals: `strategies/v41_scalping_voting/analysis/perfect_signals/`
- 브루트포스 분석: `strategies/v41_scalping_voting/analysis/bruteforce/`
- 점수 최적화: `strategies/v41_scalping_voting/analysis/optimization/`
- Raw 분석: `strategies/_raw_analysis/reports/`

**과거 전략**:
- v30 학습: `strategies/v30_perfect_longterm/LEARNING.md`
- v31 결과: `strategies/v31_scalping_with_classifier/FINAL_REPORT.md`

### 데이터셋

**Perfect Signals** (45,254개):
- day: 2020-2024 (1,276개, 평균 14.52%)
- minute60: 2020-2024 (19,334개, 평균 3.20%)
- minute240: 2020-2024 (4,357개, 평균 4.31%)
- minute15: 2023-2024 (11,571개, 평균 2.01%)
- minute5: 2024 (8,716개, 평균 1.71%)

---

**문서 버전**: v2.0 (2025-11-08 정리)
**현재 상태**: v-a-02 완료, v-a-03 준비 중
**다음 목표**: v-a 시리즈로 재현율 70%+ S-Tier 달성
- to memorize