# v-a-04 실행 가이드

## 📋 실행 순서

### 1. 시그널 생성

```bash
python strategies/v-a-04/generate_signals.py
```

**출력**:
- `signals/day_2024_signals.json`: 시그널 JSON
- `analysis/day_2024_signal_analysis.json`: 통계

**예상 결과**:
```
Total Signals: ~50-100개 (2024 day)
Market Distribution:
  BULL_STRONG: 30-40%
  SIDEWAYS: 30-40%
  BEAR_MODERATE: 10-20%
```

### 2. 백테스팅

```bash
python strategies/v-a-04/backtest.py
```

**출력**:
- `results/day_2024_backtest.json`: 백테스팅 결과

**예상 결과**:
```
Total Return: +15-25%
Win Rate: 50-60%
Max Drawdown: -5 ~ -10%
```

### 3. (선택) 재현율 측정

```bash
python strategies/v-a-04/measure_reproduction.py
```

**출력**:
- 완벽한 시그널 대비 재현율 계산
- Tier 분류 (S/A/B/C)

---

## 🎯 기대 성과

### v37 vs v-a-04 비교

| 지표 | v37 (2024) | v-a-04 예상 |
|------|-----------|-------------|
| 수익률 | +83.7% | +15-25% |
| 승률 | 69.2% | 50-60% |
| MDD | -5.2% | -5 ~ -10% |
| 거래 | 13회 | 50-100회 |

### 왜 수익률이 낮은가?

**v37**: 복잡한 Exit (TP1/2, Trailing Stop, Dynamic)
**v-a-04**: 단순 Exit (TP +5%, SL -2%, 30일)

→ Entry는 같지만 Exit이 단순해서 수익률 하락
→ 목표는 "완벽한 시그널 재현"이지 "수익률 극대화"가 아님

---

## 🔍 디버깅

### 시그널이 너무 적은 경우

```python
# generate_signals.py에서 임계값 완화
bull_strong_gen = BullStrongSignals({
    'trend_adx_threshold': 20  # 25 → 20
})
```

### 손실이 큰 경우

```python
# backtest.py에서 Exit 조정
result = simple_backtest(
    take_profit=0.03,  # 5% → 3%
    stop_loss=-0.01,   # -2% → -1%
    max_hold_days=15   # 30일 → 15일
)
```

---

## 📊 다음 단계

1. **재현율 측정**: 완벽한 시그널 대비 몇 % 재현했는지
2. **Exit 최적화**: TP/SL 조정으로 수익률 개선
3. **Multi-Timeframe**: Day + M60 + M240 통합
4. **v-a-05**: Optuna로 재현율 기준 최적화

---

**작성일**: 2025-10-22
**상태**: ✅ 구현 완료, 테스트 대기
