# SHORT_V1 백테스트 결과

**최종 업데이트**: 2025-12-11

---

## 최적화된 설정 (Production Ready)

### 백테스트 기간
- **시작**: 2022-01-01
- **종료**: 2024-12-31
- **타임프레임**: 4시간봉

### 성과 요약

| 지표 | 값 | KPI 기준 | 달성 |
|------|-----|----------|------|
| 총 수익률 | **+115.06%** | - | - |
| CAGR | +30.14% | - | - |
| Profit Factor | 1.51 | >= 1.5 | O |
| Sharpe Ratio | 1.06 | >= 1.0 | O |
| Max Drawdown | 21.06% | <= 20% | X (근접) |
| R:R Ratio | 2.09 | >= 2.0 | O |
| Expectancy | 1.85 | >= 0.2 | O |
| 승률 | 40.0% | - | - |

**KPI 달성: 4/5**

### 거래 통계

| 항목 | 값 |
|------|-----|
| 총 거래 | 60회 |
| 승리 | 24회 |
| 패배 | 35회 |
| 평균 PnL | +1.85% |
| 펀딩비 합계 | $452.81 |

### 청산 유형

| 유형 | 횟수 |
|------|------|
| Stop Loss | 35회 |
| Take Profit | 24회 |
| Reversal | 1회 |

---

## 최적화 파라미터

```json
{
  "indicators": {
    "ema_fast": 68,
    "ema_slow": 128,
    "adx_period": 14,
    "adx_threshold": 30
  },
  "entry": {
    "require_death_cross": true,
    "adx_min": 30,
    "di_negative_dominant": true
  },
  "exit": {
    "max_stop_loss_pct": 4.63,
    "risk_reward_ratio": 2.55
  },
  "risk_management": {
    "max_leverage": 2,
    "position_risk_pct": 1.0
  }
}
```

---

## 실패한 개선 시도

### Trailing Stop + Market Filter 적용 (실패)

| 설정 | 결과 |
|------|------|
| Trailing Stop (2% 활성화, 1.5% 트레일) | 수익률 -60.93% |
| Market Filter (100MA 필터) | MDD 63.82% |

**실패 원인**:
- Trailing Stop이 너무 빨리 청산되어 R:R 비율을 파괴
- 평균 이익 2.9%에서 청산, 평균 손실 -9.47%로 손익비 불균형
- 기존 R:R 기반 청산 로직과 충돌

**결론**: 이 전략에는 Trailing Stop과 Market Filter가 적합하지 않음

---

## 설정 비교

| 설정 | 수익률 | PF | Sharpe | MDD | R:R |
|------|--------|-----|--------|-----|-----|
| 기본 config.json | -34% | 0.89 | - | - | - |
| 최적화 (Position 0.54%) | +54.87% | 1.55 | 1.03 | 11.92% | 2.12 |
| **최적화 (Position 1.0%)** | **+115.06%** | **1.51** | **1.06** | **21.06%** | **2.09** |
| Trailing Stop 적용 | -60.93% | 0.59 | -1.40 | 63.82% | 0.42 |

---

## 실행 방법

```bash
cd strategies/SHORT_V1

# 최적화 설정으로 백테스트
python backtest.py --config config_optimized.json --quiet

# 기존 데이터 사용
python backtest.py --config config_optimized.json --data results/btcusdt_4h_with_funding_2022-01-01_2024-12-31.csv --quiet
```

---

## 주의사항

1. **MDD 21.06%**: KPI 20%를 약간 초과하므로 실거래 시 레버리지 조정 고려
2. **승률 40%**: 낮은 승률을 높은 R:R로 보완하는 전략
3. **펀딩비**: 숏 포지션 보유 시 펀딩비 수익 가능 (하락장에서 유리)

---

## 파일 구조

```
SHORT_V1/
├── config.json              # 기본 설정
├── config_optimized.json    # 최적화 설정 (사용 권장)
├── strategy.py              # 전략 로직
├── indicators.py            # 기술적 지표
├── backtest.py              # 백테스트 엔진
├── data_collector.py        # 바이낸스 데이터 수집
├── optimize.py              # Optuna 최적화
├── BACKTEST_RESULTS.md      # 이 문서
└── results/                 # 백테스트 결과
```
