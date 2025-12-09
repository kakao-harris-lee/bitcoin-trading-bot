# Market Analyzer v2 - AI Agent 계획서

**생성일**: 2025-11-11  
**기반**: 현재 v35_optimized + v-a 시리즈 + v10_rl_hybrid 경험

---

## 🎯 목표

기존의 단순한 TA-Lib 기반 market_analyzer를 **AI Agent 기반 시장 분석 엔진**으로 업그레이드

### 핵심 개선 사항
1. **시장 상태 예측**: 단순 분류 → AI 기반 예측
2. **다중 타임프레임 통합**: 11개 타임프레임 동시 분석
3. **실시간 적응**: 시장 변화에 실시간 학습 및 적응
4. **신뢰도 점수**: 각 분석 결과에 신뢰도 제공

---

## 🏗️ 아키텍처 설계

```
core/
├── market_analyzer_v2.py           # 메인 AI 엔진
├── agents/
│   ├── trend_analyzer_agent.py     # 트렌드 분석 전담
│   ├── volatility_agent.py         # 변동성 분석 전담
│   ├── volume_agent.py             # 거래량 패턴 분석
│   ├── sentiment_agent.py          # 시장 심리 분석
│   └── coordinator_agent.py        # 에이전트 통합 조정
├── models/
│   ├── timeframe_fusion.py         # 다중 타임프레임 융합
│   ├── market_state_predictor.py   # LSTM/Transformer 기반
│   └── confidence_calculator.py    # 신뢰도 계산 모델
├── training/
│   ├── data_preprocessor.py        # 45,254 완벽 시그널 활용
│   ├── train_agents.py             # 각 에이전트 학습
│   └── validation.py               # 성능 검증
└── utils/
    ├── feature_engineer.py         # 고급 특성 추출
    └── real_time_adapter.py        # 실시간 학습
```

---

## 🤖 AI Agent 구성

### 1. Trend Analyzer Agent
**역할**: 트렌드 방향과 강도 분석
```python
class TrendAnalyzerAgent:
    def __init__(self):
        self.model = TrendLSTM()  # LSTM 기반
        self.confidence_threshold = 0.7
    
    def analyze(self, df: pd.DataFrame) -> Dict:
        return {
            'trend_direction': 'BULL_STRONG' | 'BULL_WEAK' | 'SIDEWAYS' | 'BEAR_WEAK' | 'BEAR_STRONG',
            'trend_strength': 0.0-1.0,
            'confidence': 0.0-1.0,
            'timeframe_consistency': Dict  # 타임프레임별 일치도
        }
```

### 2. Volatility Agent
**역할**: 변동성 패턴 및 예측
```python
class VolatilityAgent:
    def __init__(self):
        self.model = VolatilityGAN()  # GAN 기반 변동성 예측
        
    def analyze(self, df: pd.DataFrame) -> Dict:
        return {
            'current_volatility': float,
            'predicted_volatility_24h': float,
            'volatility_regime': 'LOW' | 'NORMAL' | 'HIGH' | 'EXTREME',
            'breakout_probability': 0.0-1.0
        }
```

### 3. Volume Agent
**역할**: 거래량 패턴 분석
```python
class VolumeAgent:
    def __init__(self):
        self.model = VolumeTransformer()  # Transformer 기반
        
    def analyze(self, df: pd.DataFrame) -> Dict:
        return {
            'volume_trend': 'INCREASING' | 'DECREASING' | 'STABLE',
            'anomaly_score': 0.0-1.0,
            'institutional_activity': 0.0-1.0,
            'retail_activity': 0.0-1.0
        }
```

### 4. Sentiment Agent
**역할**: 시장 심리 및 패턴 분석
```python
class SentimentAgent:
    def __init__(self):
        self.model = SentimentCNN()  # CNN 기반 패턴 인식
        
    def analyze(self, df: pd.DataFrame) -> Dict:
        return {
            'fear_greed_index': 0.0-1.0,
            'momentum_sentiment': 'BULLISH' | 'BEARISH' | 'NEUTRAL',
            'pattern_recognition': List[str],  # ['DOUBLE_BOTTOM', 'TRIANGLE', ...]
            'support_resistance': Dict
        }
```

### 5. Coordinator Agent
**역할**: 모든 에이전트 결과 통합 및 최종 결론
```python
class CoordinatorAgent:
    def __init__(self):
        self.fusion_model = MultiAgentFusion()
        
    def coordinate(self, agent_results: Dict) -> Dict:
        return {
            'market_state': str,  # v35 호환 7-level 분류
            'market_state_v2': Dict,  # 확장된 AI 분석
            'overall_confidence': 0.0-1.0,
            'action_recommendation': Dict,
            'risk_assessment': Dict,
            'timeframe_consensus': Dict
        }
```

---

## 📊 학습 데이터 활용

### 1. Perfect Signals (45,254개)
- **용도**: Supervised Learning의 Ground Truth
- **위치**: `strategies/v41_scalping_voting/analysis/perfect_signals/`
- **활용**: 최적 매매 타이밍 학습

### 2. v35 Market Classification
- **용도**: 7-level 시장 상태 레이블링
- **데이터**: 2017-2025 (8년) 검증된 분류
- **활용**: 시장 상태 예측 모델 학습

### 3. v-a 시리즈 결과
- **v-a-02**: 74.12% 재현율 달성 패턴
- **v-a-15**: 다중 전략 통합 경험
- **활용**: 특성 엔지니어링 및 모델 구조 참조

---

## 🔧 구현 단계

### Phase 1: 기반 구조 (2주)
1. **core/market_analyzer_v2.py** 골격 구현
2. **기존 호환성** 보장 (v35_optimized 등)
3. **데이터 파이프라인** 구축

### Phase 2: 기본 Agent 구현 (3주)
1. **Trend Analyzer Agent** - LSTM 기반
2. **Volatility Agent** - GARCH + ML 융합
3. **기본 통합 로직**

### Phase 3: 고급 Agent 추가 (3주)
1. **Volume Agent** - Transformer 기반
2. **Sentiment Agent** - CNN 패턴 인식
3. **Coordinator Agent** 고도화

### Phase 4: 실시간 최적화 (2주)
1. **Online Learning** 구현
2. **성능 모니터링** 시스템
3. **프로덕션 배포** 준비

---

## 📈 예상 성과

### 정량적 목표
- **시장 상태 예측 정확도**: 85%+ (현재 v35 대비 +10%)
- **신호 재현율**: 80%+ (v-a-02 74.12% 대비 +6%)
- **실시간 응답**: <100ms (현재 TA-Lib 대비 유사)

### 정성적 개선
- **다중 타임프레임 일관성**: 11개 타임프레임 통합 분석
- **적응성**: 시장 변화에 실시간 학습
- **신뢰성**: 각 분석에 신뢰도 점수 제공
- **확장성**: 새로운 에이전트 쉽게 추가 가능

---

## 🎛️ 설정 및 사용법

### 기본 사용법
```python
from core.market_analyzer_v2 import MarketAnalyzerV2

analyzer = MarketAnalyzerV2(
    config={
        'agents': ['trend', 'volatility', 'volume', 'sentiment'],
        'timeframes': ['minute5', 'minute60', 'day'],
        'confidence_threshold': 0.7,
        'real_time_learning': True
    }
)

# 기존 호환성 유지
df_with_indicators = analyzer.add_indicators(df)

# 새로운 AI 분석
analysis = analyzer.analyze_market_state(df)
print(f"Market State: {analysis['market_state']}")
print(f"Confidence: {analysis['overall_confidence']:.2f}")
```

### v35 전략과 통합
```python
# v35_optimized 전략에서 사용
class V35OptimizedStrategy:
    def __init__(self, config):
        self.analyzer = MarketAnalyzerV2()  # 기존 classifier 대체
        
    def execute(self, df, i):
        # AI 기반 시장 분석
        analysis = self.analyzer.analyze_market_state(df.iloc[:i+1])
        market_state = analysis['market_state']  # 기존 7-level 호환
        confidence = analysis['overall_confidence']
        
        # 신뢰도 기반 전략 조정
        if confidence < 0.5:
            return {'action': 'hold', 'reason': 'LOW_CONFIDENCE'}
            
        # 기존 로직 그대로 사용
        return self._check_entry_conditions(df, i, market_state)
```

---

## 🚀 차별화 요소

### 1. 완벽 신호 재현 기술
- v-a 시리즈로 검증된 45,254개 완벽 시그널 활용
- 이론적 최적해에 근접한 학습 데이터

### 2. 검증된 안정성
- v35_optimized의 Sharpe 2.24, MDD -2.33% 안정성 계승
- 프로덕션 환경 검증 완료

### 3. 실시간 적응성
- 온라인 학습으로 시장 변화 적응
- 신뢰도 기반 자동 조정

### 4. 확장성
- Agent 기반 모듈형 설계
- 새로운 분석 Agent 쉽게 추가 가능

---

## 💡 성공 전략

1. **점진적 도입**: 기존 시스템과 호환성 보장하며 단계적 적용
2. **성능 중심**: 이론보다는 실제 수익성 개선에 집중  
3. **검증 기반**: v35, v-a-02 등 검증된 결과 기반 개발
4. **실용성 우선**: 복잡한 AI보다는 실용적인 성능 개선

이 계획을 통해 현재의 안정적인 성과를 유지하면서도 AI의 장점을 활용한 차세대 시장 분석 엔진을 구축할 수 있습니다.