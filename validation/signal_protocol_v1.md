# 시그널 표준 프로토콜 v1.0

**작성일**: 2025-10-21
**목적**: 모든 트레이딩 전략의 매매 시그널을 표준화하여 공용 평가 엔진에서 처리 가능하도록 함

---

## 📐 설계 철학

### Signal-Evaluation 분리 아키텍처

```
전략 (Signal Generator)  →  시그널 JSON  →  공용 평가 엔진  →  결과
     ↓                         ↓                  ↓
시그널만 생성          표준 형식 저장      2020-2025 × 23개 보유기간 평가
백테스팅 로직 없음      확장 가능           6년 × 23 = 138개 백테스트
```

**핵심 개념**:
- 전략은 "언제 매수/매도할지" 결정만 함 (시그널 생성)
- 평가 엔진이 "얼마나 보유할지, 어떻게 청산할지" 결정 (백테스팅)
- 동일한 시그널로 다양한 보유 기간/청산 방식 테스트 가능

---

## 📋 표준 시그널 형식

### 파일 구조

```
strategies/v{NN}_{name}/signals/
├── 2020_signals.json
├── 2021_signals.json
├── 2022_signals.json
├── 2023_signals.json
├── 2024_signals.json
└── 2025_signals.json
```

### JSON 형식 (v1.0)

```json
{
  "metadata": {
    "strategy": "v46_example",
    "version": "1.0",
    "timeframe": "minute60",
    "source_strategy": "v35_optimized",
    "generated_at": "2025-10-21T15:30:00",
    "description": "Oracle reproduction scalping strategy",
    "author": "Claude",

    "statistics": {
      "total_signals": 245,
      "period_start": "2024-01-01",
      "period_end": "2024-12-31",
      "avg_score": 42.5
    }
  },

  "signals": [
    {
      "timestamp": "2024-01-15 09:00:00",
      "action": "BUY",
      "price": 58839000,

      "score": 42.5,
      "confidence": 0.85,
      "market_state": "BULL_MODERATE",
      "reason": "MOMENTUM_BREAKOUT",

      "metadata": {
        "mfi": 65,
        "rsi": 45,
        "volume_ratio": 1.8,
        "entry_strategy": "Breakout",
        "tier": "S",
        "perfect_signal_match": true,
        "indicators": {
          "macd": 120.5,
          "signal": 95.3,
          "histogram": 25.2
        }
      }
    }
  ]
}
```

---

## 🔑 필수 필드

### metadata (필수)

| 필드 | 타입 | 설명 |
|------|------|------|
| `strategy` | string | 전략 이름 (예: "v46_scalping") |
| `version` | string | 전략 버전 (예: "1.0") |
| `timeframe` | string | 타임프레임 ("day", "minute5", "minute15", "minute60", "minute240") |
| `generated_at` | ISO 8601 | 시그널 생성 시각 |

### signals[] (필수)

| 필드 | 타입 | 설명 | 예시 |
|------|------|------|------|
| `timestamp` | ISO 8601 | 시그널 발생 시각 | "2024-01-15 09:00:00" |
| `action` | string | 매매 액션 | "BUY", "SELL" |
| `price` | float | 진입 가격 (KRW) | 58839000 |

---

## 🎨 선택 필드 (전략별 맞춤)

### 기본 선택 필드

| 필드 | 타입 | 설명 | 사용 전략 예시 |
|------|------|------|---------------|
| `score` | float | 시그널 점수 (0-100) | v41 voting system |
| `confidence` | float | 신뢰도 (0.0-1.0) | ML 기반 전략 |
| `market_state` | string | 시장 상태 | v34, v35 (7-level classification) |
| `reason` | string | 진입 이유 (디버깅용) | "MOMENTUM", "BREAKOUT", "MEAN_REVERSION" |

### metadata (확장 가능 dict)

**지표 정보**:
```json
"metadata": {
  "mfi": 65,
  "rsi": 45,
  "volume_ratio": 1.8,
  "bb_position": 0.85,
  "atr_pct": 2.3
}
```

**전략 특화 정보**:
```json
"metadata": {
  "entry_strategy": "Breakout",          // v35 multi-strategy
  "tier": "S",                            // v41 tier system
  "perfect_signal_match": true,           // Oracle reproduction
  "voting_details": {                     // v41 voting
    "momentum_vote": true,
    "breakout_vote": true,
    "mean_reversion_vote": false
  }
}
```

**시장 분석**:
```json
"metadata": {
  "market_regime": "TRENDING",
  "volatility_level": "MEDIUM",
  "liquidity_score": 8.5,
  "sentiment": "BULLISH"
}
```

---

## 🔄 지원 액션 타입

### 기본 액션 (v1.0)

| 액션 | 설명 | 사용 사례 |
|------|------|----------|
| `BUY` | 롱 진입 | 대부분의 전략 (v01-v45) |
| `SELL` | 숏 진입 | 롱/숏 전략 (미래 확장) |

### 확장 액션 (v1.1+ 예정)

| 액션 | 설명 | 사용 사례 |
|------|------|----------|
| `CLOSE_LONG` | 롱 청산 | 수동 청산 시그널 |
| `CLOSE_SHORT` | 숏 청산 | 숏 포지션 청산 |
| `SCALE_IN` | 포지션 추가 | v02a split entry |
| `SCALE_OUT` | 포지션 감소 | v02b split exit |
| `REBALANCE` | 리밸런싱 | 포트폴리오 전략 |

---

## 📚 사용 예시

### 예시 1: 단순 모멘텀 전략 (v31 스타일)

```json
{
  "metadata": {
    "strategy": "v46_simple_momentum",
    "version": "1.0",
    "timeframe": "minute60",
    "generated_at": "2025-10-21T16:00:00"
  },
  "signals": [
    {
      "timestamp": "2024-03-15 14:00:00",
      "action": "BUY",
      "price": 62450000,
      "reason": "MOMENTUM_5H_POSITIVE"
    },
    {
      "timestamp": "2024-03-18 09:00:00",
      "action": "BUY",
      "price": 61890000,
      "reason": "MOMENTUM_5H_POSITIVE"
    }
  ]
}
```

### 예시 2: 투표 시스템 (v41 스타일)

```json
{
  "metadata": {
    "strategy": "v41_scalping_voting",
    "version": "1.0",
    "timeframe": "minute60",
    "generated_at": "2025-10-21T16:00:00"
  },
  "signals": [
    {
      "timestamp": "2024-05-20 11:00:00",
      "action": "BUY",
      "price": 67200000,
      "score": 78,
      "tier": "S",
      "metadata": {
        "is_local_min": true,
        "mfi_bullish": true,
        "low_vol": true,
        "volume_spike": true,
        "swing_end": false,
        "voting_breakdown": {
          "local_min": 27,
          "mfi": 20,
          "low_vol": 16,
          "volume": 12,
          "total": 78
        }
      }
    }
  ]
}
```

### 예시 3: 시장 분류 기반 (v35 스타일)

```json
{
  "metadata": {
    "strategy": "v35_optimized",
    "version": "1.0",
    "timeframe": "day",
    "generated_at": "2025-10-21T16:00:00"
  },
  "signals": [
    {
      "timestamp": "2024-08-10 09:00:00",
      "action": "BUY",
      "price": 71500000,
      "market_state": "BULL_STRONG",
      "confidence": 0.92,
      "reason": "MOMENTUM_TRADING",
      "metadata": {
        "entry_strategy": "Momentum Trading",
        "mfi": 68,
        "macd_signal_diff": 2.3,
        "momentum_5h": 1.8,
        "expected_tp": [0.10, 0.15, 0.20]
      }
    }
  ]
}
```

---

## 🔍 검증 규칙

### 자동 검증 (JSON Schema)

평가 엔진은 시그널 로드 시 자동 검증:

1. **필수 필드 존재 확인**
   - metadata.strategy
   - metadata.version
   - metadata.timeframe
   - signals[].timestamp
   - signals[].action
   - signals[].price

2. **데이터 타입 검증**
   - timestamp: ISO 8601 형식
   - action: ["BUY", "SELL", ...] 중 하나
   - price: float > 0
   - score: 0 <= float <= 100 (if exists)
   - confidence: 0.0 <= float <= 1.0 (if exists)

3. **시간순 정렬 확인**
   - signals[]는 timestamp 오름차순 정렬 필수

4. **중복 방지**
   - 동일 timestamp에 중복 시그널 경고

### 수동 검증 (권장)

```bash
# JSON Schema 검증
python validation/validate_signals.py \
  --signals strategies/v46_example/signals/2024_signals.json

# 출력:
# ✅ Schema validation: PASS
# ✅ Required fields: PASS
# ✅ Data types: PASS
# ✅ Chronological order: PASS
# ⚠️  Warning: 2 duplicate timestamps (will use first occurrence)
#
# Summary:
# - Total signals: 245
# - Date range: 2024-01-01 to 2024-12-31
# - Avg score: 42.5 (if available)
```

---

## 🚀 생성 가이드

### signal_generator.py 템플릿

```python
import json
from datetime import datetime
from pathlib import Path

class SignalGenerator:
    """시그널만 생성, 백테스팅은 하지 않음"""

    def __init__(self, config):
        self.config = config
        self.strategy_name = config['strategy']
        self.version = config.get('version', '1.0')
        self.timeframe = config['timeframe']

    def generate_all_years(self):
        """2020-2025 전체 연도 시그널 생성"""
        for year in [2020, 2021, 2022, 2023, 2024, 2025]:
            signals = self.generate_signals(year)
            self.save_signals(signals, year)
            print(f"✅ {year}: {len(signals)} signals")

    def generate_signals(self, year):
        """단일 연도 시그널 생성 (전략 로직 구현)"""
        df = self.load_data(year)
        signals = []

        for idx, row in df.iterrows():
            # 전략 로직 (기존 strategy.py 재사용 가능)
            if self.should_enter(row):
                signal = {
                    'timestamp': row['timestamp'].isoformat(),
                    'action': 'BUY',
                    'price': float(row['close']),

                    # 선택 필드 (전략별 맞춤)
                    'score': self.calculate_score(row),
                    'reason': self.get_entry_reason(row)
                }

                signals.append(signal)

        return signals

    def save_signals(self, signals, year):
        """표준 형식으로 저장"""
        output = {
            'metadata': {
                'strategy': self.strategy_name,
                'version': self.version,
                'timeframe': self.timeframe,
                'generated_at': datetime.now().isoformat(),
                'statistics': {
                    'total_signals': len(signals),
                    'period_start': f"{year}-01-01",
                    'period_end': f"{year}-12-31"
                }
            },
            'signals': signals
        }

        output_dir = Path('signals')
        output_dir.mkdir(exist_ok=True)

        output_path = output_dir / f'{year}_signals.json'
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        print(f"Saved: {output_path}")
```

---

## 🔗 관련 문서

- **평가 엔진**: `validation/universal_evaluation_engine.py`
- **JSON Schema**: `validation/signal_schema_v1.json`
- **템플릿**: `strategies/_templates/universal_signal_generator.py`
- **CLAUDE.md**: 신규 개발 프로토콜 섹션

---

## 📝 버전 히스토리

### v1.0 (2025-10-21)
- 초기 표준 정의
- 필수 필드: metadata, signals[], timestamp, action, price
- 선택 필드: score, confidence, market_state, reason, metadata
- 액션 타입: BUY, SELL
- 기존 51개 전략 패턴 호환

### v1.1 (예정)
- 확장 액션: CLOSE_LONG, CLOSE_SHORT, SCALE_IN, SCALE_OUT
- 포트폴리오 지원: 다중 자산 시그널
- 실시간 스트리밍 형식

---

**작성자**: Claude
**승인**: 2025-10-21
**최종 업데이트**: 2025-10-21 15:50
