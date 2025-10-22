# v-a-15: Ultimate Adaptive Strategy

**생성일**: 2025-10-22
**기반**: v-a-11 (Sideways 전문) + Phase 1-2 연구 결과
**목표**: v-a-11 (+20.42% @ 2025) 초월 → **+43-59% 달성**

---

## 🎯 전략 개요

### 핵심 아이디어

v-a-11의 검증된 기반 + 최신 연구 4가지 통합
1. **SIDEWAYS Grid Trading** (NEW)
2. **Kelly Criterion Position Sizing** (NEW)
3. **ATR 기반 Dynamic Exit** (NEW)
4. **Trend Following 강화**

### 예상 개선 효과

| 개선 항목 | 예상 효과 | 근거 |
|----------|----------|------|
| Stop Loss 완화 | +5-8%p | v-a-14 Phase 1 실증 |
| Grid Trading | +8-12%p | 연구: SIDEWAYS 31% 시장 |
| Kelly Criterion | +5-10%p | 복리 효과 |
| ATR Dynamic Exit | +3-5%p | 변동성 적응 |
| Trend Following 강화 | +2-4%p | 거래 +30% |
| **총 개선** | **+23-39%p** | - |
| **v-a-15 목표** | **+43-59%** | v-a-11 +20.42% 기준 |

---

## 🏗️ 아키텍처

```
v-a-15/
├── core/
│   ├── market_classifier.py      # v-a-11 이식
│   ├── dynamic_thresholds.py     # v-a-11 이식
│   ├── position_sizer.py          # NEW: Kelly Criterion
│   └── exit_manager.py            # NEW: ATR Dynamic Exit
├── strategies/
│   ├── grid_trading.py            # NEW: Grid Trading
│   ├── trend_following.py         # 강화: 더 많은 기회
│   ├── sideways_mean_reversion.py # 강화: 3σ, RSI<20
│   └── defensive.py               # 선택적 (폐기 고려)
├── utils/
│   └── signal_confidence.py       # NEW: 신뢰도 점수 (0-100)
├── config.json                    # v-a-11 기반 확장
├── generate_signals.py            # 시그널 생성
├── backtest.py                    # 백테스팅
└── optimize.py                    # Optuna 1000 trials
```

---

## 📋 신규 기능 상세

### 1. SIDEWAYS Grid Trading

**문제**: v-a-11 SIDEWAYS 거래 73.6%, 기여도 30.3%만
**해결**: Grid Trading으로 SIDEWAYS 시장 효율 극대화

**구현**:
```python
# Support/Resistance 자동 감지
support = df['low'].rolling(20).min()
resistance = df['high'].rolling(20).max()

# Grid 레벨 생성 (5-7단계)
price_range = resistance - support
grid_size = 7
grid_levels = np.linspace(support, resistance, grid_size)

# 각 레벨에서 진입/청산
for i, level in enumerate(grid_levels):
    if current_price <= level * 0.98:  # 레벨 하회 2%
        # 매수 (레벨별 15% 배치)
        position_size = 0.15
        buy(price=current_price, size=position_size)

    elif current_price >= level * 1.02 and has_position[i]:  # 레벨 상회 2%
        # 매도
        sell(level_index=i)
```

**Exit 조건**:
- 각 Grid 레벨에서 +2% 도달 시 자동 매도
- 전체 레인지 이탈 시 모든 포지션 청산
- SIDEWAYS → BULL/BEAR 전환 시 즉시 청산

**예상 효과**:
- SIDEWAYS 시장 (31% of time) 수익 +30-50%
- 총 기여도: +8-12%p

### 2. Kelly Criterion Position Sizing

**문제**: v-a-11 고정 40% 포지션, 자본 효율 낮음
**해결**: 승률/Win-Loss 비율 기반 동적 포지션

**공식**:
```
Kelly % = W - (1 - W) / R

W = 승률 = 0.467 (v-a-11 2025)
R = Win/Loss 비율 = 6.51 / 3.31 = 1.97
Kelly % = 0.467 - (0.533 / 1.97) = 0.197 (19.7%)

Half Kelly (안전) = 9.85%
```

**신뢰도 점수 시스템**:
```python
confidence = 0

# 지표별 점수
if adx > 25: confidence += 20  # 강한 추세
if volume > 2.0: confidence += 15  # 높은 거래량
if rsi < 20: confidence += 25  # 극단 과매도
if stoch_gc: confidence += 20  # Stochastic 골든크로스
if bb_lower: confidence += 10  # Bollinger Band 하단
if support: confidence += 10  # Support 접근

# 최대 100점
confidence = min(confidence, 100)
```

**동적 포지션**:
```python
base_kelly = 0.0985  # Half Kelly 9.85%
position = base_kelly * (confidence / 100) * capital

# 제한
position = np.clip(position, 0.10, 0.80)  # 10-80%

# 예시:
# 신뢰도 100점 → 0.0985 × 1.0 × capital = 9.85% → 확대 불가 (위험)
# 신뢰도 80점 → 0.0985 × 0.8 × capital × 4 = 31.5% (적절)
# 신뢰도 40점 → 0.0985 × 0.4 × capital × 2 = 7.88% (보수적)

# 실제 구현: Kelly를 기준값으로, 신뢰도로 배율 조정
position = min(0.15 * (confidence / 50), 0.80)  # 신뢰도 50점 = 15%, 100점 = 30%
```

**예상 효과**:
- 고신뢰도 시그널 집중 투자
- 저신뢰도 시그널 축소
- 복리 효과: +5-10%p

### 3. ATR 기반 Dynamic Exit

**문제**: v-a-11 고정 TP/SL, 변동성 무시
**해결**: ATR 기반 변동성 적응형 Exit

**구현**:
```python
# 진입 시 ATR 기록
entry_atr = df['atr'].iloc[entry_idx]

# 동적 Stop Loss (3.0× ATR)
dynamic_sl = entry_price - (entry_atr * 3.0)

# 동적 Take Profit (6.0× ATR, 2:1 reward-risk)
dynamic_tp1 = entry_price + (entry_atr * 3.0)  # 1:1
dynamic_tp2 = entry_price + (entry_atr * 6.0)  # 2:1
dynamic_tp3 = entry_price + (entry_atr * 9.0)  # 3:1

# Trailing Stop (Peak - 3.5× ATR)
if profit > 0.10:  # 10% 이상 수익
    trailing_sl = peak_price - (entry_atr * 3.5)
    dynamic_sl = max(dynamic_sl, trailing_sl)
```

**변동성별 적응**:
```python
# 고변동성 (ATR > 0.03)
if entry_atr > 0.03:
    TP: 8-12%, SL: -3-5%, Trailing: -4-5%

# 저변동성 (ATR < 0.015)
if entry_atr < 0.015:
    TP: 3-5%, SL: -1.5-2%, Trailing: -2-3%

# 중간 변동성
else:
    TP: 5-8%, SL: -2-3%, Trailing: -3-4%
```

**예상 효과**:
- MDD 감소: -5%p
- Sharpe 증가: +0.3-0.5
- 변동성 큰 시장: SL 넓혀서 생존
- 변동성 작은 시장: TP 타이트하게 빠른 익절

### 4. Trend Following 강화

**문제**: v-a-11 거래 22.6%만, 기여도 69.6%
**해결**: Entry 조건 완화, 더 많은 기회

**변경 사항**:
```python
# Before (v-a-11)
adx_threshold: 16
volume_threshold: (없음)
position_size: 0.8 (고정)

# After (v-a-15)
adx_threshold: 12  # 16 → 12 (더 많은 추세 포착)
volume_threshold: 1.2  # NEW (최소 거래량)
position_size: 0.60-0.80  # 동적 (Kelly 기반)
```

**Entry 강화**:
```python
# 기본 조건
adx >= 12  # 완화 (16 → 12)
macd > signal  # 동일
volume > avg * 1.2  # NEW

# 신뢰도 점수
if adx > 20: +20점
if adx > 30: +10점 추가
if volume > 1.5: +15점
if rsi < 65: +10점
```

**예상 효과**:
- 거래 +30% (22.6% → 29.4%)
- 기여도 유지 (69.6%)
- 승률 약간 하락 (48% → 45%) but 총 수익 증가

---

## 🔧 구현 단계

### Phase 3-1: 핵심 모듈 구현
- [x] 프로젝트 구조 생성
- [ ] PositionSizer (Kelly Criterion)
- [ ] ExitManager (ATR Dynamic)
- [ ] SignalConfidence (신뢰도 점수)

### Phase 3-2: 전략 구현
- [ ] GridTrading (SIDEWAYS)
- [ ] TrendFollowing (강화)
- [ ] SidewaysMeanReversion (강화)
- [ ] Defensive (선택적)

### Phase 3-3: 통합 및 시그널 생성
- [ ] generate_signals.py
- [ ] 2020-2024 시그널 생성
- [ ] 시그널 검증

### Phase 3-4: 백테스팅
- [ ] backtest.py (Kelly + ATR 통합)
- [ ] 2020-2024 학습
- [ ] 2025 Out-of-Sample 검증

### Phase 3-5: 최적화
- [ ] Optuna 1000 trials
- [ ] Walk-Forward 검증
- [ ] 재최적화 (목표 미달 시)

---

## 📈 성공 기준

### 필수 달성 (Phase 5)
- [ ] 2025 수익률: **+30% 이상** (v-a-11 +20.42% 대비 +50%)
- [ ] Sharpe Ratio: **2.0 이상**
- [ ] MDD: **15% 이하**
- [ ] 승률: **50% 이상**

### 목표 달성 (Stretch)
- [ ] 2025 수익률: **+40-50%**
- [ ] 6년 평균: **+80%+**
- [ ] Sharpe Ratio: **2.5 이상**
- [ ] MDD: **10% 이하**

---

## 💡 핵심 차별점

| 항목 | v-a-11 | v-a-15 |
|------|--------|--------|
| SIDEWAYS 전략 | Mean Reversion만 | Grid Trading + Mean Rev |
| Position Sizing | 고정 40% | Kelly Criterion 동적 |
| Exit System | 고정 TP/SL | ATR 기반 동적 |
| Trend Following | 보수적 (ADX 16) | 적극적 (ADX 12) |
| 신뢰도 시스템 | 없음 | 0-100점 점수 |
| Optuna Trials | 500 | 1000 |

---

## 🚀 실행 방법

```bash
# 1. 시그널 생성 (2020-2024)
python generate_signals.py

# 2. 백테스팅 (학습)
python backtest.py --train

# 3. 최적화 (Optuna 1000 trials)
python optimize.py --trials 1000

# 4. 검증 (2025 Out-of-Sample)
python backtest.py --test

# 5. 결과 비교
python compare_with_v_a_11.py
```

---

**작성자**: Claude (v-a Series Development)
**버전**: 1.0 (Initial)
**상태**: 🚧 개발 중
