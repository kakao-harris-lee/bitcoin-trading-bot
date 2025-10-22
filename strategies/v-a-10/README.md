# v-a-04: Market-Adaptive Perfect Signal Reproducer

**생성일**: 2025-10-22
**기반**: v37 Supreme Market Classifier + v-a Signal-Evaluation 구조

## 🎯 목표

v37의 검증된 시장 분류 시스템을 활용해 완벽한 정답 시그널을 재현

- **시장 분류**: 7단계 (BULL_STRONG/MODERATE, SIDEWAYS, BEAR_MODERATE/STRONG)
- **재현율 목표**: 60-70% (A-Tier)
- **2024 목표**: +20-30% (v37 +84% 대비 현실적)

## 📊 핵심 아이디어

### v37 vs v-a-04 비교

| 항목 | v37 Supreme | v-a-04 |
|------|-------------|--------|
| 시장 분류 | 7단계 (동일) | 7단계 (동일) |
| Entry | 전략별 복잡 로직 | 단순화된 조건 |
| Exit | 전략별 다양한 Exit | Universal Engine 위임 |
| 최적화 | Optuna 500회 | 재현율 기반 |
| 목표 | Buy&Hold 초과 | 완벽 시그널 재현 |

### 핵심 변환

```
v37 복잡한 전략 → v-a 단순 Entry 조건 추출
├── MarketClassifier: 그대로 이식 ✅
├── Entry 로직: 핵심만 추출
└── Exit 로직: 제거 (Universal Engine)
```

## 🛠️ 아키텍처

```
strategies/v-a-04/
├── core/
│   ├── market_classifier.py      # v37 이식 (7단계 분류)
│   └── dynamic_thresholds.py     # v37 이식 (quantile 기반)
├── strategies/
│   ├── bull_strong_signals.py    # MACD + ADX
│   ├── bull_moderate_signals.py  # RSI + MFI
│   ├── sideways_signals.py       # 3종 조합 (v35 검증)
│   └── bear_signals.py           # 극단 RSI
├── utils/
│   └── perfect_signal_loader.py  # v-a-01 재활용
├── generate_signals.py           # 메인 시그널 생성
├── backtest.py                   # 백테스팅
├── config.json                   # v37 설정 재활용
└── README.md
```

## 📋 전략 상세

### 1. BULL_STRONG (Trend Following)
- **시장 조건**: MA20 기울기 > 1.5%/일, ADX > 26
- **Entry**: MACD 골든크로스 + ADX > 25
- **v37 재활용**: `strategies/trend_following.py` Entry 로직

### 2. BULL_MODERATE (Swing Trading)
- **시장 조건**: MA20 기울기 0.5-1.5%/일
- **Entry**: RSI 30-40 (과매도) + MFI < 50
- **v37 재활용**: `strategies/swing_trading.py` Entry 로직

### 3. SIDEWAYS (3종 조합)
- **시장 조건**: MA20 기울기 -0.2~0.2%/일
- **Entry**:
  1. RSI < 30 + BB_lower
  2. Stochastic < 20 + 골든크로스
  3. Volume > avg × 2.0 + 반등
- **v37 재활용**: `strategies/sideways_strategy.py` 전체

### 4. BEAR (Defensive)
- **시장 조건**: MA20 기울기 < -0.5%/일
- **Entry**: RSI < 20 (극단 과매도)
- **v37 재활용**: `strategies/defensive_trading.py` Entry 조건

## 🔄 구현 단계

### Phase 1: 기반 구축
- [x] 폴더 구조 생성
- [ ] MarketClassifier 이식
- [ ] DynamicThresholds 이식

### Phase 2: 시장별 Signal Generator
- [ ] BULL_STRONG 구현
- [ ] SIDEWAYS 구현 (v35 검증됨)
- [ ] BULL_MODERATE, BEAR 구현

### Phase 3: 통합 및 검증
- [ ] Ensemble Generator
- [ ] 백테스팅 (2024)
- [ ] 재현율 측정

## 📈 예상 성과

### 재현율 (시장별)
```
BULL_STRONG: 50-60% (MACD 패턴 재현)
SIDEWAYS: 70-80% (v35 검증: +14.20%)
BULL_MODERATE: 55-65%
BEAR: 40-50% (보수적)

종합: 60-70% (A-Tier 목표)
```

### 2024 성과 예상
```
v37 실제: +84%
완벽 시그널: ~+150% (추정)
v-a-04 목표: +20-30% (재현율 60% × 보수적 Exit)
```

## 💡 v37 대비 장점

1. **단순성**: Entry만 집중, Exit은 Universal Engine
2. **검증 가능**: 완벽 시그널 대비 재현율 측정
3. **안정성**: 복잡한 전략 전환 제거
4. **확장성**: 타임프레임 추가 용이

## 🚀 다음 단계

- v-a-05: Multi-Timeframe (Day + M60 + M240)
- v-a-06: ML Pattern Matching (완벽 시그널 학습)
- v-a-07: Optuna 최적화 (재현율 기준)
