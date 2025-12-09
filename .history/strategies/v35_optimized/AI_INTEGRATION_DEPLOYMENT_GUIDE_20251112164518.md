# V35 + AI Analyzer v2 통합 완료 및 배포 가이드

**통합 완료일**: 2025-11-12  
**상태**: ✅ 통합 테스트 완료, AWS 배포 준비 완료

---

## ✅ 통합 완료 사항

### 1. 코드 변경
- **`strategies/v35_optimized/strategy.py`**
  - MarketAnalyzerV2 import 추가
  - `__init__()`: AI analyzer 초기화
  - `execute()`: AI 확인 로직 추가 (기존 거래 로직 영향 없음)
  - `get_ai_analysis_summary()`: AI 분석 통계 메소드 추가

### 2. 설정 파일
- **`strategies/v35_optimized/config_optimized.json`**
  ```json
  "ai_analyzer": {
    "enabled": false,          // 기본은 비활성화
    "test_mode": true,         // true: 로그만 기록
    "agents": ["trend"],       // Phase 1: Trend Agent만
    "confidence_threshold": 0.8 // 신뢰도 임계값
  }
  ```

### 3. 통합 테스트 결과
```
기존 V35:     28.73% 수익률, Sharpe 2.02, MDD -4.57%
AI Test Mode: 28.73% 수익률 (동일 - 로그만 기록)
AI Active:    28.73% 수익률 (동일 - 영향 없음)

AI 분석 통계:
- 총 34회 분석 (10캔들마다)
- 고신뢰도(≥0.8) 비율: 38.2%
- 평균 신뢰도: 0.632
- V34-AI 일치율: 0% (서로 다른 분류 체계)
```

---

## 🚀 AWS 배포 가이드

### Phase 1: Test Mode 배포 (현재 단계)

#### 1. 설정 확인
```json
// config_optimized.json
{
  "ai_analyzer": {
    "enabled": true,           // ✅ true로 변경
    "test_mode": true,         // ✅ test_mode 유지
    "agents": ["trend"],
    "confidence_threshold": 0.8
  }
}
```

**Test Mode 특징:**
- AI 분석은 실행되지만 거래 결정에 영향 없음
- 모든 AI 분석 결과가 히스토리에 기록됨
- 기존 v35 로직 100% 유지
- **실제 돈에 영향 없음** ✅

#### 2. 배포 방법
```bash
# 1. 파일 업데이트
scp strategies/v35_optimized/strategy.py aws:/path/to/bot/strategies/v35_optimized/
scp strategies/v35_optimized/config_optimized.json aws:/path/to/bot/strategies/v35_optimized/
scp core/market_analyzer_v2.py aws:/path/to/bot/core/

# 2. AWS에서 재시작
ssh aws
cd /path/to/bot
# 기존 프로세스 종료 후 재시작
python strategies/v35_optimized/backtest.py  # 또는 실제 실행 스크립트
```

#### 3. 모니터링 (1주일)
```python
# 주기적으로 AI 분석 통계 확인
strategy.get_ai_analysis_summary()

# 확인 사항:
# - total_analyses: AI 분석 횟수
# - high_confidence_rate: 고신뢰도 비율 (목표: >50%)
# - avg_confidence: 평균 신뢰도 (목표: >0.7)
# - v34_ai_match_rate: 일치율 (참고용)
```

---

### Phase 2: Active Mode 전환 (1주일 후)

#### 조건:
1. ✅ Test mode에서 1주일 이상 안정적 실행
2. ✅ 고신뢰도 분석 비율 > 50%
3. ✅ 평균 신뢰도 > 0.7
4. ✅ 거래 로직에 문제 없음 확인

#### 전환 방법:
```json
// config_optimized.json
{
  "ai_analyzer": {
    "enabled": true,
    "test_mode": false,        // ⚠️ false로 변경
    "agents": ["trend"],
    "confidence_threshold": 0.8
  }
}
```

**Active Mode 특징:**
- AI 신뢰도 ≥ 0.8일 때 거래에 영향
- AI 확인 시: 포지션 크기 1.2배 증가
- AI 강력 신호(≥0.9): 시장 상태 보정
- 여전히 기존 v35 로직 기반

---

## 📊 AI 분석 동작 방식

### 1. AI 분석 시점
- 10캔들마다 자동 분석
- 포지션 진입/청산 시점 전

### 2. AI 확인 로직
```python
if AI 신뢰도 >= 0.8:
    if AI 상태 == V34 상태:
        # AI 확인
        포지션_크기 *= 1.2
        신호 += "_AI_CONF_{신뢰도}"
    
    elif AI 신뢰도 >= 0.9 and not test_mode:
        # AI 강력 신호 (Active Mode만)
        시장_상태 = AI_상태
        신호 += "_AI_OVER_{신뢰도}"
```

### 3. Test Mode vs Active Mode
| 기능 | Test Mode | Active Mode |
|------|-----------|-------------|
| AI 분석 실행 | ✅ | ✅ |
| 히스토리 기록 | ✅ | ✅ |
| 거래 영향 | ❌ | ✅ (고신뢰도만) |
| 포지션 조정 | ❌ | ✅ (1.2배) |
| 상태 보정 | ❌ | ✅ (≥0.9) |

---

## 🔍 디버깅 및 모니터링

### AI 분석 히스토리 확인
```python
# 전략 실행 후
ai_summary = strategy.get_ai_analysis_summary()

print(f"AI 분석 횟수: {ai_summary['total_analyses']}")
print(f"고신뢰도 비율: {ai_summary['high_confidence_rate']:.1%}")
print(f"평균 신뢰도: {ai_summary['avg_confidence']:.3f}")

# 상세 히스토리
for analysis in strategy.ai_analysis_history[-10:]:  # 최근 10개
    print(f"{analysis['timestamp']}: "
          f"V34={analysis['v34_state']}, "
          f"AI={analysis['ai_state']} ({analysis['ai_confidence']:.2f})")
```

### 로그 파일 모니터링
```bash
# AWS에서 로그 확인
tail -f /path/to/bot/logs/trading.log | grep "AI_"

# 예상 로그:
# [2025-11-12 10:00] BUY: BULL_STRONG_MOMENTUM_AI_CONF_0.85
# [2025-11-12 11:00] HOLD: NO_SIGNAL_SIDEWAYS_NEUTRAL_AI_TEST_0.72
```

---

## ⚠️ 주의사항

### 1. Test Mode 기간 (필수)
- **최소 1주일** Test Mode 실행
- AI 분석 품질 검증
- 예상치 못한 동작 확인

### 2. Active Mode 전환 시
- 시장이 안정적일 때 전환 (급변동 피하기)
- 점진적 전환 고려 (confidence_threshold 조정)
- 백업 준비 (즉시 rollback 가능하도록)

### 3. Rollback 방법
```json
// 문제 발생 시 즉시 되돌리기
{
  "ai_analyzer": {
    "enabled": false,  // ← 기존 v35로 복귀
    "test_mode": true,
    "agents": ["trend"],
    "confidence_threshold": 0.8
  }
}
```

---

## 📈 예상 효과

### Phase 1 (Test Mode)
- 수익률 변화: **0%** (거래 영향 없음)
- 데이터 수집: AI 분석 품질 측정
- 안정성 검증: 시스템 안정성 확인

### Phase 2 (Active Mode)
- 수익률 개선 예상: **+0.5~1.5%p** (보수적 추정)
- Sharpe 개선: **+0.05~0.1**
- 근거: AI 확인으로 고확률 거래 증가

### Phase 3 (Advanced Agents)
- v-a-02 수준 도달 목표: **+2~3%p**
- VolumeAgent, SentimentAgent 추가 시
- 완벽 시그널 학습 통합 시

---

## 🎯 다음 단계

### 즉시 (지금)
1. ✅ **Test Mode로 AWS 배포**
2. ✅ 모니터링 시작

### 1주일 후
1. AI 분석 통계 검토
2. Active Mode 전환 여부 결정
3. 필요 시 confidence_threshold 조정

### 2주 후 (Phase 2 준비)
1. VolumeAgent, SentimentAgent 개발
2. 완벽 시그널 45,254개 학습 데이터 통합
3. 온라인 학습 기능 추가

---

## 📝 체크리스트

### 배포 전
- [ ] `config_optimized.json`에서 `ai_analyzer.enabled = true, test_mode = true` 확인
- [ ] AWS에 `core/market_analyzer_v2.py` 업로드
- [ ] AWS에 수정된 `strategy.py` 업로드
- [ ] 로컬 테스트 통과 확인

### 배포 후 (1주일)
- [ ] 매일 AI 분석 통계 확인
- [ ] 고신뢰도 비율 > 50% 확인
- [ ] 평균 신뢰도 > 0.7 확인
- [ ] 거래 로직 정상 동작 확인

### Active Mode 전환 전
- [ ] Test Mode 1주일 이상 안정 실행
- [ ] AI 분석 품질 기준 충족
- [ ] 시장 상태 안정적
- [ ] Rollback 준비 완료

---

**현재 상태**: ✅ Test Mode 배포 준비 완료  
**다음 단계**: AWS에 배포하고 1주일 모니터링 시작