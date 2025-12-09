# Phase 2-B: AI 독립 필터화 설계

**작성일**: 2025-11-18
**목표**: AI를 v35와 독립적인 추가 필터로 사용하여 고확률 거래만 실행

---

## 🎯 핵심 아이디어

### 현재 문제점 (Active Mode)

```
v35 신호: BUY (BULL_STRONG)
AI 신호: SIDEWAYS_NEUTRAL (불일치)
→ AI가 v35 로직 override → 수익률 저하 (-4.03%p)
```

**V34-AI 일치율: 0%** → AI 확인 로직이 제대로 작동 안함

### Phase 2-B 해결 방안

```
v35 신호: BUY (BULL_STRONG)
AI 신호: BULL_STRONG (일치) + 신뢰도 0.85
→ 둘 다 동의 → 거래 실행 ✅

v35 신호: BUY (BULL_STRONG)
AI 신호: SIDEWAYS_NEUTRAL (불일치)
→ AI 필터 거부 → 거래 안함 ❌
```

**효과**:
- v35 로직 100% 유지 (override 없음)
- AI는 독립 필터 역할만
- 거래 횟수 감소, 승률 상승 예상

---

## 🔧 구현 설계

### 1. 새로운 설정 추가 (config.json)

```json
{
  "ai_analyzer": {
    "enabled": true,
    "test_mode": false,          // Phase 2-B에서는 false
    "filter_mode": true,          // ⭐ 새로 추가: 독립 필터 모드
    "filter_strict": false,       // ⭐ 새로 추가: 엄격 모드 (true: EXACT 일치, false: 방향만 일치)
    "agents": ["trend"],
    "confidence_threshold": 0.8
  }
}
```

### 2. AI 필터 메서드 구현

```python
def _ai_filter_check(self, v35_signal: str, market_state: str,
                     df: pd.DataFrame, i: int) -> Dict:
    """
    AI 독립 필터 확인

    Args:
        v35_signal: v35 신호 ('buy', 'sell', 'hold')
        market_state: v35가 판단한 시장 상태
        df: 데이터프레임
        i: 현재 인덱스

    Returns:
        {
            'approved': bool,
            'ai_state': str,
            'ai_confidence': float,
            'match_type': str,  # 'EXACT', 'DIRECTIONAL', 'NONE'
            'reason': str
        }
    """
```

**필터 로직**:

1. **AI 분석 실행**:
   - 신뢰도 < 임계값(0.8) → 거부
   - 신뢰도 >= 0.8 → 다음 단계

2. **엄격 모드** (`filter_strict = true`):
   - v35 상태 == AI 상태 (EXACT) → 승인
   - 예: BULL_STRONG == BULL_STRONG ✅
   - 예: BULL_STRONG != BULL_MODERATE ❌

3. **완화 모드** (`filter_strict = false`, 권장):
   - 방향만 일치하면 승인
   - BULL_* vs BULL_* → 승인 ✅
   - BULL_* vs SIDEWAYS_* → 조건부 승인 (SIDEWAYS_UP만)
   - BULL_* vs BEAR_* → 거부 ❌

### 3. 진입 로직 수정

**기존 (현재)**:
```python
entry_signal = self._check_entry_conditions(df, i, market_state, prev_row)
if entry_signal and entry_signal['action'] == 'buy':
    # AI 확인 없이 바로 거래
    self.in_position = True
    ...
```

**수정 후 (Phase 2-B)**:
```python
entry_signal = self._check_entry_conditions(df, i, market_state, prev_row)
if entry_signal and entry_signal['action'] == 'buy':
    # ⭐ AI 독립 필터 확인
    if self.ai_filter_mode:
        ai_filter_result = self._ai_filter_check('buy', market_state, df, i)

        if not ai_filter_result['approved']:
            # AI 필터 거부 → 거래 안함
            return {
                'action': 'hold',
                'reason': f'AI_FILTER_REJECTED_{market_state}',
                'v35_signal': entry_signal.get('reason', ''),
                'ai_state': ai_filter_result['ai_state'],
                'ai_confidence': ai_filter_result['ai_confidence'],
                'rejection_reason': ai_filter_result['reason']
            }

        # AI 필터 승인 → 거래 실행
        entry_signal['ai_approved'] = True
        entry_signal['ai_match_type'] = ai_filter_result['match_type']
        entry_signal['ai_confidence'] = ai_filter_result['ai_confidence']

    # 기존 거래 로직
    self.in_position = True
    ...
```

### 4. 청산 로직 (변경 없음)

AI 필터는 **진입 시에만** 적용, 청산은 기존 v35 로직 유지

---

## 📊 예상 효과

### 백테스트 목표 (2024)

| 지표 | Baseline (AI OFF) | Phase 2-B 목표 | 비고 |
|------|-------------------|----------------|------|
| **수익률** | 28.73% | **>= 28.73%** | 유지 또는 개선 |
| **Sharpe** | 2.02 | **>= 2.00** | 유지 |
| **거래 횟수** | 17 | **12~15** | 감소 예상 |
| **승률** | 64.7% | **70%+** | 개선 예상 |
| **MDD** | -4.57% | **< -4.57%** | 개선 또는 유지 |

### 기대 효과

**장점** ✅:
1. **거래 품질 향상**: AI + v35 둘 다 동의하는 고확률 거래만
2. **승률 상승**: 불확실한 거래 필터링
3. **v35 로직 보존**: override 없이 100% 유지
4. **리스크 감소**: 거래 횟수 감소 → 수수료 감소

**단점** ⚠️:
1. **거래 기회 감소**: 17 → 12~15 (약 30% 감소)
2. **수익률 불확실성**: 거래 감소가 수익에 악영향 가능성

### 성공 기준

- ✅ **수익률 >= 28.73%** (필수)
- ✅ **Sharpe >= 2.00** (필수)
- ✅ **승률 >= 70%** (목표)
- ✅ **거래 횟수 >= 10** (최소)

---

## 🔄 모드 비교

| 모드 | AI 역할 | v35 로직 | 거래 영향 | 수익률 | 상태 |
|------|---------|----------|-----------|--------|------|
| **AI OFF** | 없음 | 100% | - | 28.73% | ✅ Baseline |
| **Test Mode** | 로그만 | 100% | 없음 | 28.73% | ✅ 안전 |
| **Active Mode** | Override | 왜곡됨 | 있음 | 24.70% | ❌ 저하 |
| **Filter Mode (Phase 2-B)** | 독립 필터 | 100% 유지 | 선별적 | **목표: 28.73%+** | 🔧 개발 중 |

---

## 📝 구현 단계

### Step 1: 코드 수정 (1일)

- [x] 설계 문서 작성
- [ ] `strategy.py`에 `_ai_filter_check()` 메서드 추가
- [ ] `execute()` 메서드 진입 로직 수정
- [ ] `__init__()` 설정 변수 추가
- [ ] 로깅 강화 (AI 필터 결과 기록)

### Step 2: 백테스트 검증 (1일)

- [ ] 2024 단일 연도 테스트
- [ ] 2020-2024 전체 기간 테스트
- [ ] 승률, 수익률, 거래 횟수 분석
- [ ] AI 필터 통계 분석 (승인율, 거부율)

### Step 3: 파라미터 튜닝 (1일)

- [ ] `filter_strict` 비교 (true vs false)
- [ ] `confidence_threshold` 조정 (0.7, 0.8, 0.9)
- [ ] 최적 조합 선정

### Step 4: Out-of-Sample 검증 (선택)

- [ ] 2025 데이터로 검증
- [ ] Paper Trading 1주일

### Step 5: 배포 (1일)

- [ ] 설정 파일 업데이트
- [ ] AWS EC2 배포
- [ ] 모니터링 설정

**예상 소요 시간**: 3-4일

---

## 🧪 테스트 시나리오

### 시나리오 1: 완전 일치

```
v35: BUY (BULL_STRONG)
AI: BULL_STRONG (신뢰도 0.92)
→ EXACT 일치 → 거래 실행 ✅
```

### 시나리오 2: 방향 일치 (완화 모드)

```
v35: BUY (BULL_STRONG)
AI: BULL_MODERATE (신뢰도 0.85)
→ DIRECTIONAL 일치 (둘 다 BULL) → 거래 실행 ✅
```

### 시나리오 3: 불일치

```
v35: BUY (BULL_STRONG)
AI: SIDEWAYS_NEUTRAL (신뢰도 0.88)
→ 불일치 → AI 필터 거부 ❌
```

### 시나리오 4: 저신뢰도

```
v35: BUY (BULL_STRONG)
AI: BULL_STRONG (신뢰도 0.65)
→ 신뢰도 < 0.8 → AI 필터 거부 ❌
```

### 시나리오 5: AI 오류

```
v35: BUY (BULL_STRONG)
AI: [오류 발생]
→ 안전하게 통과 처리 (fallback) ✅
```

---

## 📈 모니터링 지표

### AI 필터 통계 (신규)

```python
{
  'total_v35_signals': 20,        # v35가 낸 총 BUY 신호
  'ai_approved': 14,               # AI 필터 승인 (70%)
  'ai_rejected': 6,                # AI 필터 거부 (30%)
  'rejection_reasons': {
    'LOW_CONFIDENCE': 2,           # 신뢰도 부족
    'STATE_MISMATCH': 4            # 상태 불일치
  },
  'match_types': {
    'EXACT': 8,                    # 정확히 일치
    'DIRECTIONAL': 6               # 방향만 일치
  },
  'avg_approved_confidence': 0.87, # 승인된 거래의 평균 AI 신뢰도
  'approved_win_rate': 0.71        # 승인된 거래의 승률
}
```

### 기존 지표

- 수익률, Sharpe, MDD
- 거래 횟수, 승률
- AI 분석 품질 (평균 신뢰도, 고신뢰도 비율)

---

## 🚨 롤백 계획

Phase 2-B가 실패하면 (수익률 < 28.73%):

```json
// config.json
{
  "ai_analyzer": {
    "enabled": true,
    "test_mode": true,      // ← Test Mode로 복귀
    "filter_mode": false,   // ← 필터 비활성화
    "filter_strict": false,
    "agents": ["trend"],
    "confidence_threshold": 0.8
  }
}
```

또는 완전히 AI OFF:

```json
{
  "ai_analyzer": {
    "enabled": false,  // ← AI 완전 비활성화
    ...
  }
}
```

---

## 🎯 다음 단계 (Phase 3)

Phase 2-B 성공 시 (수익률 >= 28.73%):

1. **Multi-Agent 확장**
   - VolumeAgent, SentimentAgent 추가
   - AI 확인 정확도 70%+ 목표

2. **완벽 시그널 통합**
   - 45,254개 완벽 시그널 학습
   - v-a 시리즈 성과 통합

3. **Ensemble AI**
   - Trend + Volume + Sentiment 투표
   - 다수결 또는 가중 평균

---

**문서 버전**: v1.0
**다음 단계**: Step 1 코드 구현
**예상 완료**: 2025-11-21 (3일 후)
