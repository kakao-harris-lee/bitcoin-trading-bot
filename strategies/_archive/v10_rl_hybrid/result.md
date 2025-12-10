# v10 RL Hybrid 전략 결과 보고서

## 📊 Executive Summary

**v10 전략**: Reinforcement Learning (PPO) 기반 하이브리드 전략
**목표**: v5 (293.38%) 초과, RL로 복잡한 패턴 학습
**결과**: **완전 실패** - 0% 수익률, 거래 0회

## ❌ 최종 성과 (2025-10-19)

### Train Set (2018-09-04 ~ 2023-12-31)
```yaml
수익률: 0.00%
거래: 0회
승률: N/A
Action 분포:
  - Buy: 0회 (0.0%)
  - Sell: 1,880회 (100.0%)
  - Hold: 0회 (0.0%)
```

### Validation 2024 (2024-01-01 ~ 2024-12-30)
```yaml
수익률: 0.00%
거래: 0회
승률: N/A
vs v5: -293.38%p
vs Buy&Hold (137.49%): -137.49%p
Action 분포:
  - Buy: 0회 (0.0%)
  - Sell: 300회 (100.0%)
  - Hold: 0회 (0.0%)
```

### Test 2025 (2025-01-01 ~ 2025-10-17)
```yaml
수익률: 0.00%
거래: 0회
승률: N/A
vs v5: -124.93%p
vs Buy&Hold (20.15%): -20.15%p
Action 분포:
  - Buy: 0회 (0.0%)
  - Sell: 225회 (100.0%)
  - Hold: 0회 (0.0%)
```

## 🎯 목표 달성 여부

| 목표 | 달성 여부 | 실제 결과 |
|------|-----------|-----------|
| 2024 수익률 150-180% | ❌ | 0.00% (-150.00%p) |
| 2025 수익률 40-60% | ❌ | 0.00% (-40.00%p) |
| 오버피팅 <50% | N/A | 측정 불가 (수익 없음) |
| v5 (293.38%) 초과 | ❌ | 0.00% (-293.38%p) |

## 🔍 실패 원인 분석

### 1. Reward Function 설계 오류

**문제**: Agent가 "아무것도 하지 않는 것"을 학습

```python
# 현재 Reward 구조
- 포지션 없음 + 액션 없음: Reward 0
- 매수/매도 시: Reward -0.05% (수수료 패널티)
- 이익 실현 시: Reward +profit_pct
```

**Agent의 학습 결과**:
- "거래하면 수수료 손실 → 거래 안 하면 손실 없음"
- "매수하지 않으면 손실 위험도 없음"
- **결론**: 매도 액션만 반복 (포지션 없는 상태에서 매도는 무효 → Reward 0 유지)

### 2. State Space의 초기값 문제

**관측값 초기 상태**:
```
Position: 0 (포지션 없음)
Cash Fraction: 1.0 (현금 100%)
Profit: 0 (수익 없음)
```

**Agent 학습**:
- 이 상태에서 Hold → Reward 0
- 이 상태에서 Buy → Reward -0.0005 (수수료)
- 이 상태에서 Sell (무효) → Reward 0

→ **Sell 액션이 가장 안전** (수수료 없이 Reward 0 유지)

### 3. Exploration vs Exploitation 실패

**PPO 설정**:
```yaml
Learning Rate: 0.0003
Gamma: 0.99
n_steps: 2048
Exploration: Entropy Coefficient 0.0
```

**문제**:
- Entropy Coefficient 0.0 → 탐험 부족
- 초기부터 Sell 액션 선호 → 다른 액션 시도 안 함
- PPO의 Conservative 특성 → 안전한 전략(Sell) 고수

### 4. Episode Length vs Timesteps 불일치

**환경**:
- Episode Length: 1,880 (5.3년 DAY 데이터)
- Total Timesteps: 100,000

**실제 학습**:
- 100,000 / 1,880 = 약 53 에피소드
- 에피소드당 학습 기회 너무 적음
- Long-term Reward를 학습하기 부족

### 5. 암묵적 Buy&Hold 전략 학습 실패

**기대**:
- Agent가 "매수 후 상승 시 보유, 하락 시 매도"를 학습

**실제**:
- "매수" 자체를 학습하지 못함
- Sell 액션만 반복 → 거래 0회 → Reward 0 고착

## 🧪 학습 과정 분석

### Training Log 요약

```
Iteration 1:  ep_rew_mean: -441
Iteration 10: ep_rew_mean: -514
Iteration 20: ep_rew_mean: -512
Iteration 30: ep_rew_mean: -480
Iteration 49: ep_rew_mean: -467
```

**관찰**:
- Episode Reward 항상 음수 (-400 ~ -500)
- 학습 진행해도 Reward 개선 없음
- Value Loss 높음 (8-12 범위 유지)
- Policy Loss 매우 낮음 (~0.00) → 정책 변화 거의 없음

### Evaluation 결과

```
Eval at 20k: mean_reward 0.00, episode_length 300
Eval at 40k: mean_reward 0.00, episode_length 300
Eval at 60k: mean_reward 0.00, episode_length 300
Eval at 80k: mean_reward 0.00, episode_length 300
Eval at 100k: mean_reward 0.00, episode_length 300
```

**문제**:
- 검증 환경에서 항상 Episode Length 300으로 조기 종료
- 실제 데이터는 331개인데 300에서 멈춤
- Agent가 환경을 제대로 탐색하지 못함

## 📉 v05 대비 비교

| 지표 | v05 (Baseline) | v10 (RL) | 차이 |
|------|----------------|----------|------|
| **전략** | EMA Cross (Rule) | PPO (RL) | - |
| **2024 수익률** | 293.38% | 0.00% | **-293.38%p** |
| **2025 수익률** | 124.93% | 0.00% | **-124.93%p** |
| **2024 거래** | 4회 | 0회 | -4회 |
| **2025 거래** | 5회 | 0회 | -5회 |
| **Sharpe** | 1.76 | N/A | - |
| **MDD** | 29.10% | 0.00% | 매수 없어서 손실도 없음 |
| **승률** | 50-60% | N/A | - |

## 💡 핵심 교훈

### 1. RL ≠ 만능 해결책

- 규칙 기반 전략 (v05)이 RL (v10)보다 압도적으로 우수
- RL은 Reward 설계, State 설계, 하이퍼파라미터 튜닝 모두 완벽해야 함
- 잘못된 설계 → 완전 실패

### 2. Reward Shaping의 중요성

**실패한 Reward**:
```python
reward = profit - fee - drawdown - holding_penalty
```

**개선 방향**:
```python
# 방법 1: 기준선 대비 성과
reward = (current_equity - buyhold_equity) / initial_capital

# 방법 2: Sharpe Ratio 최대화
reward = (returns.mean() / returns.std()) * sqrt(252)

# 방법 3: 정기적 Reward
reward = daily_return + long_term_profit_bonus
```

### 3. Sparse Reward 문제

**현재**:
- 거래 완료 시에만 Reward (Sparse)
- Episode 길이 1,880 → Reward 신호 너무 드문드문

**해결책**:
- Dense Reward: 매 스텝마다 Equity 변화에 대한 Reward
- Intermediate Reward: 일정 이익/손실 달성 시 보너스

### 4. Baseline Policy 부재

**문제**:
- PPO가 Random Policy에서 시작
- 좋은 전략을 발견하기까지 너무 오래 걸림

**해결책**:
- Behavioral Cloning: v05 전략을 Imitation Learning으로 초기화
- Warm Start: v05 규칙을 초기 정책으로 사용

### 5. 환경 검증 부족

**실수**:
- 환경만 테스트하고 Random Agent 검증 생략
- Random Agent만 돌려봐도 문제를 조기 발견 가능

**교훈**:
- 학습 전 Random Agent로 환경 동작 확인
- Reward 분포, Action 분포, Episode Length 검증

## 🔧 개선 방안

### 즉시 적용 가능한 개선

#### 1. Reward Function 재설계
```python
def calculate_reward(self, prev_equity, current_equity, action):
    # 1. Equity 변화율 (매 스텝)
    equity_change = (current_equity - prev_equity) / prev_equity
    reward = equity_change * 100  # 0.01 → 1.0

    # 2. Buy&Hold 대비 초과 수익
    buyhold_equity = self.initial_capital * (current_price / self.start_price)
    excess_return = (current_equity - buyhold_equity) / buyhold_equity
    reward += excess_return * 10

    # 3. 거래 보너스 (최소 활동 보장)
    if abs(action) > 0.1:
        reward += 0.1  # 거래 시도에 소량 보상

    # 4. 장기 보유 보너스
    if self.position and self.profit > 0.10:
        reward += 1.0  # 10% 이상 수익 유지 시 보너스

    return reward
```

#### 2. Curriculum Learning
```python
# Phase 1: 단순 환경 (100 캔들)
train_phase1(df[:100])

# Phase 2: 중간 환경 (500 캔들)
train_phase2(df[:500])

# Phase 3: 전체 환경 (1,880 캔들)
train_phase3(df)
```

#### 3. Exploration Bonus
```python
# PPO 설정
model = PPO(
    policy="MlpPolicy",
    env=env,
    ent_coef=0.01,  # 0.0 → 0.01 (탐험 장려)
    exploration_fraction=0.5,  # 학습 초반 50%는 탐험
    ...
)
```

#### 4. Behavioral Cloning (v05 전략 모방)
```python
# v05 전략으로 Expert Trajectory 생성
expert_actions = run_v05_on_training_data()

# BC로 초기 정책 학습
bc_model.train(expert_actions)

# BC 정책으로 PPO 초기화
ppo_model.load_policy(bc_model)
ppo_model.learn(total_timesteps=100_000)
```

### 장기적 개선 방향

#### 1. 멀티 Agent 앙상블
- Conservative Agent (DQN)
- Balanced Agent (PPO)
- Aggressive Agent (SAC)
- 시장 상황별 Agent 선택

#### 2. Meta-Learning
- MAML (Model-Agnostic Meta-Learning)
- 다양한 시장 조건에서 빠르게 적응

#### 3. Hierarchical RL
- High-Level: 시장 상황 분류 (Bull/Bear/Sideways)
- Low-Level: 각 상황별 거래 전략

#### 4. Transformer-based Policy
- Attention Mechanism으로 장기 의존성 학습
- Time-series Transformer

## 🎯 다음 버전 제안: v11

### v11A: Reward Redesign (빠른 검증)
- Reward Function 재설계
- Behavioral Cloning으로 v05 모방
- Timesteps 50만 → 100만
- **예상 기간**: 2-3일
- **예상 성과**: 50-100% (v05 대비 여전히 낮음)

### v11B: Rule-based + RL Hybrid (보수적)
- v05 전략을 기본으로 사용
- RL Agent는 Position Sizing만 결정
- Entry/Exit는 v05 규칙 유지
- **예상 기간**: 1-2일
- **예상 성과**: 100-150% (v05와 유사)

### v11C: v05 최적화 (현실적)
- RL 포기, v05 개선에 집중
- Optuna로 파라미터 정밀 튜닝
- Multi-Entry Conditions 추가
- Dynamic Trailing Stop
- **예상 기간**: 1일
- **예상 성과**: 150-200% (v05 대비 +50%p)

## 권장 사항

### ✅ 즉시 실행: v11C (v05 최적화)
**이유**:
1. RL은 시간 대비 성과가 불확실
2. v05는 이미 검증된 우수한 전략
3. 작은 개선으로도 큰 효과 가능 (293% → 350%+)

**구체적 계획**:
1. Optuna로 v05 파라미터 재최적화 (trailing_stop 19-23% 탐색)
2. Multi-Entry Conditions (EMA + RSI + Breakout + Momentum)
3. Adaptive Trailing Stop (변동성 기반 15-25%)
4. Walk-Forward Validation (2024년 12개월)

**예상 결과**:
- 2024: 150-180% (목표 170%)
- 2025: 40-60% (목표 50%)
- 오버피팅: <50%

### ⚠️ 장기 과제: RL 재도전 (v12+)
**조건**:
- v11C 성공 후
- Reward Function 재설계 완료
- Baseline Policy (v11C) 확보
- 충분한 시간 투자 가능 (1주+)

## 📁 파일 구조

```
strategies/v10_rl_hybrid/
├── trading_env.py              # Gym 환경 (문제: Reward 설계 오류)
├── train_ppo.py                # PPO 학습 스크립트 (실행 완료)
├── train_dqn.py                # DQN 스크립트 (미실행, Action Space 불일치)
├── ppo_results.json            # 결과 (0% 수익률)
├── train_ppo.log               # 학습 로그
├── models/ppo_balanced/        # 학습된 모델
│   ├── ppo_final.zip
│   ├── best_model.zip
│   └── ppo_checkpoint_*.zip
├── logs/                       # Tensorboard 로그
├── requirements.txt            # 의존성
└── result.md                   # 본 문서
```

## 📊 최종 평가

| 지표 | 목표 | 달성 | 평가 |
|------|------|------|------|
| 2024 수익률 >= v05 | ✅ | ❌ 0% (vs v05 293%) | **FAIL** |
| 2025 수익률 >= v05 | ✅ | ❌ 0% (vs v05 125%) | **FAIL** |
| 오버피팅 < 50% | ✅ | N/A | **N/A** |
| 거래 빈도 15-25/년 | ✅ | ❌ 0회/년 | **FAIL** |
| Sharpe >= 2.0 | ✅ | N/A | **N/A** |

**종합 평가**: **F (실패)** 😞

---

**작성일**: 2025-10-19
**작성자**: Claude (v10 Developer)
**버전**: v10 Final Report
**다음 단계**: v11C (v05 최적화) 권장
