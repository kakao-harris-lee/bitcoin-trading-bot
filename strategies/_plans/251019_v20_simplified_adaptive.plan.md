# v20 전략 계획서: 단순화 적응형 전략 (Simplified Adaptive)

**작성일**: 2025-10-19
**버전**: v20
**타임프레임**: day
**전략 유형**: 규칙 기반 + 단순 시장 적응

---

## 1. v19 실패 원인 분석

### 문제점

| 항목 | v19 결과 | 문제 |
|------|---------|------|
| 2022 (하락장) | -2.49% | 목표 -30% 대비 양호하나 BH -63% 대비 방어 부족 |
| 2023 (상승장) | -2.12% | **치명적**: BH +168% 상승장을 놓침 |
| 2024 (상승장) | +1.77% | **치명적**: BH +134% 상승장을 놓침 |
| 2025 (횡보장) | +4.78% | 양호 |

### 근본 원인

**1. 시장 분류가 너무 엄격**
```python
# v19 상승장 조건
if ADX >= 25 AND return_20d >= 0.15:  # 너무 까다로움
    market = "BULL"
```
→ 2023-2024년 대부분 기간이 이 조건을 만족하지 못함
→ 횡보장(SIDEWAYS)으로 잘못 분류
→ RSI 30/70 전략만 작동 (진입 기회 거의 없음)

**2. VWAP Breakout 전략 미작동**
- 상승장으로 분류되지 않아 VWAP 전략 자체가 실행 안됨
- 2023년 8월, 2024년 8월에 각각 단 1회만 거래

**3. 거래 빈도 극단적으로 낮음**
- 연평균 1.8회 (v17의 3.5회보다 낮음)
- 자본 활용도 극히 낮음

---

## 2. v20 핵심 아이디어

### 전략 단순화

> **"복잡한 시장 분류를 버리고, 검증된 단일 전략을 상황별 파라미터만 조정"**

**v17 성공 요소 재활용**:
- VWAP Breakout은 2024년 +140.75% 달성
- 문제는 2022 하락장 대응 부족

**v20 접근**:
1. **기본 전략**: VWAP Breakout (v17과 동일)
2. **하락 감지**: 20일 수익률 < -5% → 포지션 크기 축소 + 손절 강화
3. **상승 감지**: 20일 수익률 > +5% → 포지션 크기 확대 + Trailing Stop 완화

---

## 3. 전략 설계

### 3.1 매수 전략 (통합)

```python
def v20_buy_signal(df, i, config):
    """
    VWAP Breakout 기본 전략
    + 추세 강도에 따라 포지션 크기 조정
    """
    close = df.iloc[i]['close']
    vwap = df.iloc[i]['vwap']
    prev_close = df.iloc[i-1]['close']
    prev_vwap = df.iloc[i-1]['vwap']

    # VWAP 돌파 (v17과 동일)
    if prev_close <= prev_vwap and close > vwap:
        # 20일 수익률로 포지션 크기 조정
        return_20d = (close - df.iloc[i-20]['close']) / df.iloc[i-20]['close']

        if return_20d < -0.05:
            # 하락 추세: 포지션 30%
            fraction = 0.30
            risk_mode = "DEFENSIVE"
        elif return_20d > 0.15:
            # 강한 상승 추세: 포지션 90%
            fraction = 0.90
            risk_mode = "AGGRESSIVE"
        else:
            # 중립 추세: 포지션 60%
            fraction = 0.60
            risk_mode = "NEUTRAL"

        return {
            'action': 'buy',
            'fraction': fraction,
            'risk_mode': risk_mode,
            'return_20d': return_20d
        }

    return {'action': 'hold'}
```

### 3.2 매도 전략 (동적)

```python
def v20_sell_signal(df, i, position, config):
    """
    리스크 모드에 따라 익절/손절 동적 조정
    """
    close = df.iloc[i]['close']
    entry_price = position['entry_price']
    risk_mode = position['risk_mode']

    pnl_pct = (close - entry_price) / entry_price

    # 리스크 모드별 파라미터
    if risk_mode == "DEFENSIVE":
        take_profit = 0.10   # +10%
        stop_loss = -0.05    # -5%
        trailing_stop = 0.15 # 15%
    elif risk_mode == "AGGRESSIVE":
        take_profit = 0.35   # +35%
        stop_loss = -0.10    # -10%
        trailing_stop = 0.20 # 20%
    else:  # NEUTRAL
        take_profit = 0.20   # +20%
        stop_loss = -0.07    # -7%
        trailing_stop = 0.18 # 18%

    # 익절
    if pnl_pct >= take_profit:
        return {'action': 'sell', 'fraction': 1.0, 'reason': f'TP_{take_profit*100:.0f}%'}

    # Trailing Stop
    high_since_entry = position.get('high_price', entry_price)
    if close > high_since_entry:
        position['high_price'] = close
        high_since_entry = close

    drawdown = (close - high_since_entry) / high_since_entry
    if pnl_pct > 0 and drawdown <= -trailing_stop:
        return {'action': 'sell', 'fraction': 1.0, 'reason': f'TRAILING_{trailing_stop*100:.0f}%'}

    # 손절
    if pnl_pct <= stop_loss:
        return {'action': 'sell', 'fraction': 1.0, 'reason': f'SL_{abs(stop_loss)*100:.0f}%'}

    return {'action': 'hold'}
```

---

## 4. 하이퍼파라미터

```json
{
  "strategy_name": "simplified_adaptive",
  "version": "v20",
  "timeframe": "day",

  "position_sizing": {
    "defensive_threshold": -0.05,
    "aggressive_threshold": 0.15,
    "defensive_fraction": 0.30,
    "neutral_fraction": 0.60,
    "aggressive_fraction": 0.90
  },

  "defensive_mode": {
    "take_profit_pct": 0.10,
    "stop_loss_pct": -0.05,
    "trailing_stop_pct": 0.15
  },

  "neutral_mode": {
    "take_profit_pct": 0.20,
    "stop_loss_pct": -0.07,
    "trailing_stop_pct": 0.18
  },

  "aggressive_mode": {
    "take_profit_pct": 0.35,
    "stop_loss_pct": -0.10,
    "trailing_stop_pct": 0.20
  },

  "indicators": {
    "vwap_enabled": true,
    "return_lookback_days": 20
  },

  "backtest_settings": {
    "initial_capital": 10000000,
    "fee_rate": 0.0005,
    "slippage": 0.0002
  }
}
```

---

## 5. 예상 성과

### 5.1 로직 검증

**2022년 (하락장)**:
- 20일 수익률 대부분 < -5%
- DEFENSIVE 모드: 포지션 30%, 손절 -5%
- 예상: -15% (BH -63% 대비 +48%p)

**2023년 (상승장)**:
- 3월~12월 강한 상승 (20일 수익률 > +15%)
- AGGRESSIVE 모드: 포지션 90%, 익절 +35%
- VWAP 돌파 3~5회 예상
- 예상: +120% (BH +168% 대비 -48%p)

**2024년 (상승장)**:
- 상반기 상승 (20일 수익률 > +15%)
- AGGRESSIVE 모드: 포지션 90%, 익절 +35%
- 예상: +100% (BH +134% 대비 -34%p)

**2025년 (횡보장)**:
- 20일 수익률 -5% ~ +15% 사이
- NEUTRAL 모드: 포지션 60%, 익절 +20%
- 예상: +15% (BH +20% 대비 -5%p)

**4년 평균**: ((-15) + 120 + 100 + 15) / 4 = **55%**
**목표**: 79.75%
**차이**: -24.75%p (여전히 미달이지만 v19의 0.48%보다 대폭 개선)

---

## 6. v19 vs v20 비교

| 항목 | v19 | v20 |
|------|-----|-----|
| **시장 분류** | ADX + 20일 수익률 (3가지) | 20일 수익률만 (연속값) |
| **기본 전략** | 시장별 다른 전략 | VWAP Breakout 단일 |
| **포지션 크기** | 고정 (30%/60%/90%) | 동적 (20일 수익률 기반) |
| **2023 예상** | -2.12% (실제) | +120% (개선) |
| **2024 예상** | +1.77% (실제) | +100% (개선) |
| **4년 평균** | 0.48% | 55% (+54.52%p) |
| **복잡도** | 높음 (3전략 × 4파라미터) | 낮음 (1전략 × 3모드) |

---

## 7. 위험 요소

1. **여전히 목표 미달**: 55% < 79.75%
   - 상승장에서 BH 대비 -30~50%p 손실
   - VWAP Breakout 자체의 한계

2. **하락장 방어 불확실**: -15% 예상이지만 실제로는 더 클 수 있음

3. **거래 빈도**: v19보다 개선되겠지만 여전히 낮을 가능성

---

## 8. 다음 단계

1. v20 구현 및 백테스팅
2. 결과 분석
   - 4년 평균 >= 79.75% 달성 시 → 성공
   - 미달 시 → v21 또는 다른 접근 필요
     - Bollinger Band Breakout
     - Momentum 전략
     - 다중 지표 조합

---

**작성자**: Claude
**예상 소요**: 1시간 (구현 30분 + 백테스팅 30분)
