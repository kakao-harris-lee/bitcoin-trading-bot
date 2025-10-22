# v-a-01: Perfect Signal Loader

**생성일**: 2025-10-22
**목표**: 완벽한 정답 시그널 로드 및 기본 재현 시도

## 🎯 목표

- 완벽한 시그널 45,254개 분석
- Day 타임프레임 (266개/2024) 재현 시도
- 재현율 40%+ 달성
- Universal Evaluation Engine 검증

## 📊 완벽한 시그널 데이터

```
strategies/v41_scalping_voting/analysis/perfect_signals/
├── day_2024_perfect.csv (266개)
└── ... (18개 파일)
```

**데이터 형식**:
```
timestamp,open,high,low,close,volume,rsi,mfi,volume_ratio,...
best_hold_days,best_return,best_max_dd
```

## 🛠️ 구현

### 1. Perfect Signal Loader (`utils/perfect_signal_loader.py`)
- CSV 로드 및 파싱
- 타임프레임별 패턴 분석
- 통계 계산

### 2. 재현율 계산 (`utils/reproduction_calculator.py`)
- 시그널 매칭 (±1일 허용)
- 시그널 재현율 / 수익 재현율 / 종합 재현율
- Tier 분류 (S/A/B/C)

### 3. 시그널 생성 (`generate_signals.py`)
- 단순 RSI + MFI 조합
- Day 타임프레임 2024
- 완벽 시그널 패턴 학습

### 4. Universal Engine 검증
- Signal-Evaluation 분리
- 표준 JSON 형식 저장
- 백테스팅 실행

## 📈 예상 결과

```
시그널 재현율: ~35% (266개 → 93개 예상)
수익 재현율: ~45%
종합 재현율: ~41% (B-Tier)
```

## 🔄 다음 단계

- v-a-02: 단일 타임프레임 최적화
- v-a-03: Multi-Indicator 스캐닝
