# v06 Dual Layer Adaptive Strategy - STATUS

**상태**: ⏸️ 일시 중단 (Suspended)
**날짜**: 2025-10-18
**이유**: core.Backtester 버그 발견으로 인한 재검토 필요

---

## 📊 현재 상황

### 발견된 문제
1. **core.Backtester 버그**: 실제 수익률의 3배 과대평가
   - 보고값: 293.38%
   - 실제값: 94.77% (수동 검증)

2. **DualLayerBacktester 미세 오차**: 97.84% vs 94.77% (3%p 차이)
   - 간단한 테스트에서는 정확함
   - 실제 전략 실행 시 미세 차이 발생

### v06 설계
- **Layer 1 (DAY)**: v05 검증 전략 (예상 293% → 실제 95%)
- **Layer 2 (Scalping)**: DAY 수익의 일부로 단타 거래
- **목표**: 400% (현실성 없음으로 판명)

---

## 🔧 재개 조건

### Option A: DualLayerBacktester 수정 후 사용
1. 97.84% → 94.77%로 조정 (3%p 오차 수정)
2. Layer 2 로직 재검토
3. 새로운 목표 (150~200%) 설정 후 재개

### Option B: core.Backtester 수정 후 사용
1. core.Backtester 버그 원인 파악 및 수정
2. 전체 v01~v05 재검증
3. v06 재설계 및 실행

### Option C: v06 폐기
1. v07로 새롭게 시작
2. DualLayerBacktester 기반
3. 현실적 목표 (150~200%) 설정

---

## 📋 보관 파일

### 검증 스크립트
- `manual_verification.py` - 수동 계산 (정답: 94.77%)
- `simple_test_case.py` - 백테스터 테스트
- `VERIFICATION_REPORT.md` - 전체 검증 리포트

### v06 구현 파일
- `layer1_day.py` - DAY 전략 (v05 기반)
- `layer2_scalping.py` - 스캘핑 전략
- `dual_backtester.py` - 이중 레이어 백테스터
- `config.json` - 설정
- `backtest_full.py` - 전체 백테스팅 스크립트

---

## 🎯 권장 사항

**즉시**: Option C 선택 (v06 폐기, v07 새롭게 시작)

**이유**:
1. DualLayerBacktester는 간단한 경우 정확 (97.84% ≈ 94.77%)
2. 복잡한 dual layer 구조보다 **단순하고 효과적인 전략**이 필요
3. 95% 베이스라인에서 150~200% 달성이 현실적

**다음 단계**: v07 전략 수립 (별도 문서 참조)

---

**최종 업데이트**: 2025-10-18
**담당**: Claude (AI Assistant)
