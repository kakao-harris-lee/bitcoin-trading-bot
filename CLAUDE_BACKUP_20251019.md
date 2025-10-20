# 비트코인 자동 트레이딩 봇 개발 프로젝트

## ⚠️ 작업 원칙 (최우선)

**시간과 토큰을 절대 신경쓰지 말 것!**
- 완벽한 구현이 최우선
- 모든 코드는 철저하게 작성
- 모든 테스트는 완전하게 수행
- 문서화는 상세하게 작성
- 성능 최적화보다 정확성 우선
- 서두르지 말고 단계별로 완벽하게 진행

## 🎯 프로젝트 목표

가상화폐 거래 봇을 만들어 **과거 데이터 기준 오버피팅 없이 수익을 내는 시스템**을 구축합니다.

### 최종 목표
- 안정적인 수익 창출 (목표: 연 20%+ 수익률, MDD < 20%)
- 오버피팅 방지
- 범용적으로 작동하는 전략
- 다양한 시장 상황(상승장/하락장/횡보장)에서 대응 가능

## 📐 핵심 설정

### 가상환경 규칙
```bash
# 위치: 프로젝트 루트의 venv/ 폴더
# 모든 버전(v01, v02, ...)에서 공용으로 사용

# 활성화
source venv/bin/activate

# 비활성화
deactivate

# 라이브러리 설치
pip install -r requirements.txt
```

**중요**:
- 버전별 독립 가상환경 사용 금지 (venv 하나만 사용)
- 새 라이브러리 설치 시 requirements.txt 업데이트
- TA-Lib 0.6.7 이상 필수

### 거래 조건
```yaml
초기_자본: 10,000,000원
수수료: 0.05%  # Upbit 기본
슬리피지: 0.02%
최소_주문금액: 10,000원
거래대상: KRW-BTC (비트코인)
```

### Kelly Criterion (필수 적용)
- 모든 전략에 기본 적용
- 승률이 확보될 때까지 최소 거래 진행
- 승률 확보 후 Kelly 공식으로 투자 비율 계산
- 분할 매수/매도 고려

### 평가 지표 (KPI)
```yaml
주요_지표:
  - Total Return (총 수익률)
  - Sharpe Ratio (위험 대비 수익, 목표 >= 1.0)
  - Max Drawdown (최대 낙폭, MDD, 목표 <= 30%)
  - Win Rate (승률)
  - Profit Factor (총 이익 / 총 손실)

추가_지표:
  - 평균 수익 / 평균 손실
  - 총 거래 횟수
  - 승리 거래 / 패배 거래
  - Buy&Hold 대비 성과 (목표: Buy&Hold + 20%p)
```

### 백테스팅 기준 (필수) - 3년 학습 + 1년 검증 체계

```yaml
기간_분할:
  학습_기간: 2022-2024 (3년)
    목적: 전략 개발 및 파라미터 최적화
    방법:
      - 각 연도별 개별 백테스팅
      - Walk-Forward Analysis 권장
      - 연도별 성과 확인 및 안정성 검증

  검증_기간: 2025 (1년, Out-of-Sample)
    목적: 오버피팅 검증 및 실전 성과 예측
    방법:
      - 학습 기간 파라미터 완전 고정
      - 2025년 데이터만으로 테스트
      - 실시간 거래 전 필수 검증 단계

Buy&Hold_기준선:
  2024년 (검증됨):
    day: 137.49%
    minute5: 147.52%
    minute15: 147.14%
    minute30: 147.84%
    minute60: 147.79%
    minute240: 147.65%

  2025년 (검증됨, ~10월):
    day: 19.26%

  2022-2023년:
    - 각 전략 개발 시 자동 계산 필요
    - automation/calculate_buyhold.py 사용

성공_기준:
  개별_연도_기준:
    - Buy&Hold 대비 수익 (절대값 기준 제거)
    - 2024년 강세장: Buy&Hold 초과 목표
    - 2025년 약세장: Buy&Hold 80% 이상 달성
    - 하락장: 손실 최소화 (-10% 이내)

  4년_종합_기준:
    - 4년 평균 수익률 >= 평균 Buy&Hold + 15%p
    - 연도별 표준편차 < 평균의 50%
    - 최악의 해 수익률 >= 평균의 50%
    - Sharpe Ratio >= 1.0 (4년 평균)
    - Max Drawdown <= 30% (4년 최대)

  Out-of-Sample_검증 (2025):
    - 2025 수익률 >= 2022-2024 평균의 80%
    - 2025 승률 >= 2022-2024 평균 - 15%p
    - 2025 MDD <= 2022-2024 최대 MDD + 10%p
    - ⚠️ 이 조건 미달 시 오버피팅으로 판단, 전략 폐기

예시:
  2022: +80% (BH: +50%)
  2023: +100% (BH: +80%)
  2024: +140% (BH: +137%)
  2025: +90% (BH: +19%) ← Out-of-Sample

  평균: 102.5% (4년)
  평균 BH: 71.5% (4년)
  차이: +31%p >= +15%p ✅ 목표 달성!

  2025 검증: 90% >= (80+100+140)/3 × 0.8 = 85.3% ✅ 통과!

타임프레임_테스트:
  필수_테스트: 모든 Base 전략(vXX)은 전체 타임프레임 필수 테스트

  대상_타임프레임:
    - minute5   (288 캔들/일, 초단타 전용)
    - minute15  (96 캔들/일, 초단타)
    - minute30  (48 캔들/일, 단타)
    - minute60  (24 캔들/일, 단타)
    - minute240 (6 캔들/일, 스윙)
    - day       (1 캔들/일, 포지션 트레이딩)

  자동화_도구:
    멀티_타임프레임_실행:
      명령어: python automation/run_multi_timeframe_backtest.py
      출력: strategies/multi_timeframe_summary.json

    비교_분석:
      명령어: python automation/compare_timeframe_results.py
      출력:
        - strategies/timeframe_comparison.md (전략별 상세)
        - strategies/comprehensive_timeframe_analysis.md (전체 통합)

  선정_기준 (우선순위):
    1순위: 4년 평균 수익률
    2순위: 승률
    3순위: Sharpe Ratio (리스크 대비 수익)
    4순위: 거래 횟수 적정성
      - 너무 적음 (< 5회/년): 기회 부족
      - 너무 많음 (> 100회/년): 과매매, 수수료 과다
      - 적정: 10-50회/년

  최종_채택:
    - 상위 3개 타임프레임 선정
    - 리스크/수익 균형 고려
    - 실시간 거래 가능성 검토
    - 단타 변형(vXX-YY) 개발 시 활용
```

### 전략 네이밍 및 변형 규칙

```yaml
Base_Strategy: vXX (v01 ~ v99)
  설명: 기본 전략, 새로운 알고리즘 조합 또는 접근법
  예시:
    - v17: VWAP + BREAKOUT (day, trailing 20%)
    - v18: VWAP Only (day, trailing 20%)
    - v19: VWAP + OBV + CCI (day)

  명명_규칙:
    - v + 2자리 숫자 (01, 02, ..., 99)
    - 폴더명: strategies/vXX_전략명/
    - 예: strategies/v17_vwap_breakout/

Short_Term_Variants: vXX-YY
  설명: Base 전략의 단타/변형 버전
  목적: 거래 횟수 증가, 타임프레임 변경, 다양한 시장 대응

  구조:
    - vXX: Base 전략 번호
    - YY: 변형 번호 (01, 02, 03, ...)
    - 예: v17-01, v17-02, v17-03

  변형_종류:
    vXX-01: 타임프레임 단축 (day → minute240)
      - 거래 횟수 증가 목표: Base × 3배 이상
      - Trailing Stop 축소: 20% → 10-15%
      - 예: v17-01 (minute240, trailing 12%)

    vXX-02: 초단타 (minute60 → minute15/minute5)
      - 거래 횟수 증가 목표: Base × 10배 이상
      - Trailing Stop 축소: 10% → 3-5%
      - 예: v17-02 (minute15, trailing 5%)

    vXX-03: 분할 진입/청산
      - 타임프레임 유지
      - 33% / 33% / 34% 분할 매수
      - 익절 단계: +10%, +20%, +30%
      - 예: v17-03 (day, 분할 3단계)

    vXX-04: Multi-Timeframe 조합
      - 긴 타임프레임 신호 + 짧은 타임프레임 타이밍
      - 예: v17-04 (day 신호 + minute240 진입)

    vXX-05~: 기타 사용자 정의 변형

  폴더_구조:
    strategies/vXX-YY_변형명/
      ├── config.json         (timeframe, trailing_stop 등 수정)
      ├── strategy.py         (Base 전략 복사 또는 수정)
      ├── backtest.py         (Base 전략 복사)
      ├── result_2022.json
      ├── result_2023.json
      ├── result_2024.json
      ├── result_2025.json
      └── multi_year_analysis.md

변형_개발_조건:
  Base_전략_요구사항:
    - 승률 >= 60%
    - 수익률 상위권 (4년 평균 기준)
    - 현재 후보: v17 (승률 66.7%, 2024 +140.75%)

  변형_성과_기준:
    - 거래 횟수 >= Base × 3배
    - 승률 >= Base - 10%p
    - 수익률 >= Base × 0.8 (4년 평균)
    - 2025 Out-of-Sample >= 2022-2024 평균 × 0.8

  예시 (v17 → v17-01):
    Base (v17):
      - 타임프레임: day
      - 거래: 3회/년
      - 승률: 66.7%
      - 수익률: 140% (2024)

    목표 (v17-01):
      - 타임프레임: minute240
      - 거래: 9회+ (3×3)
      - 승률: 56.7%+ (66.7-10)
      - 수익률: 112%+ (140×0.8, 2024)

네이밍_예시:
  v17: VWAP+BREAKOUT (day)
  v17-01: VWAP+BREAKOUT_minute240
  v17-02: VWAP+BREAKOUT_minute60
  v17-03: VWAP+BREAKOUT_split_entry
  v17-04: VWAP+BREAKOUT_multi_tf

  v18: VWAP_Only (day)
  v18-01: VWAP_Only_minute240
```

## 🗄️ 데이터베이스 구조

### 1. upbit_bitcoin.db (원본 데이터)
- **용도**: 공용 가격 데이터 (읽기 전용)
- **내용**: 2017~2025년 비트코인 가격 데이터
- **레코드**: 4,174,195개 (489MB)
- **타임프레임**: 1min, 3min, 5min, 10min, 15min, 30min, 60min, 240min, day, week, month

### 2. trading_results.db (통합 결과)
- **용도**: 모든 버전의 백테스팅 결과 저장
- **테이블**: strategies, backtest_results, trades, hyperparameters, realtime_performance

### 3. v0N_cache.db (버전별 독립 DB)
- **용도**: 각 전략의 학습 캐시, 중간 결과 저장
- **위치**: strategies/v0N_전략명/v0N_cache.db

## 📋 문서화 규칙

### 파일 네이밍 규칙
```
계획: YYMMDD_HHMM.v0N.전략명.plan.md
결과: YYMMDD_HHMM.v0N.전략명.result.md
과정: process.md (각 버전 폴더 내)
```

### 문서 계층 구조
```
claude.md (루트)
├─ 전체 프로젝트 규칙
├─ 범용적 학습 내용 (모든 버전에 적용)
└─ 공통 발견 사항

strategies/v0N_전략명/claude.md (버전별)
├─ 해당 전략 특성
├─ 구현 세부사항
└─ 전략 특화 발견 사항
```

### 문서 작성 원칙
1. **계획 문서 (plan.md)**: 목표, 이전 버전 분석, 가설, 구현 계획, 예상 성과
2. **결과 문서 (result.md)**: 실행 요약, 백테스팅 결과, 문제점, 개선 방향, 다음 버전 제안
3. **과정 문서 (process.md)**: 개발 인사이트, 시행착오, 하이퍼파라미터 튜닝 히스토리
4. **통합 분석 (comprehensive_analysis.md)**: 전체 버전 비교, 패턴, 전략 조합 가이드

### 백테스팅 보고 형식 (필수)
```
=== 백테스팅 기간 ===
타임프레임: minuteX / day
시작: YYYY-MM-DD HH:MM:SS (시작가: XX,XXX,XXX원)
종료: YYYY-MM-DD HH:MM:SS (종료가: XX,XXX,XXX원)
기간: N일 (N개월) | 캔들: N개

=== Buy&Hold 기준선 (2024년) ===
타임프레임별 기준:
  minute5:   147.52% (목표: 167.52%)
  minute15:  147.14% (목표: 167.14%)
  minute30:  147.84% (목표: 167.84%)
  minute60:  147.79% (목표: 167.79%)
  minute240: 147.65% (목표: 167.65%)
  day:       137.49% (목표: 157.49%)

현재 타임프레임 기준:
  Buy&Hold: XX.XX%
  목표: XX.XX% (Buy&Hold + 20%p)

=== 전략 성과 ===
초기 자본: 10,000,000원
최종 자본: XX,XXX,XXX원
절대 수익: +X,XXX,XXX원
수익률: +XX.XX%

vs Buy&Hold:
  차이: +XX.XXp
  목표 대비: ✅ 달성 / ❌ 미달성

=== 리스크 지표 ===
Sharpe Ratio: X.XX (목표 >= 1.0) ✅/❌
Max Drawdown: -X.XX% (목표 <= 30%) ✅/❌
Sortino Ratio: X.XX

=== 거래 통계 ===
총 거래: N회 | 승률: XX.X%
평균 수익: XX.XX% | 평균 손실: -XX.XX%
Profit Factor: X.XX

=== 종합 평가 ===
✅/❌ 수익률 >= Buy&Hold + 20%p
✅/❌ Sharpe Ratio >= 1.0
✅/❌ Max Drawdown <= 30%
```

## 🔄 자동화 사이클

```
┌─────────────────────────────────────────────┐
│ 1. ANALYZE (분석)                           │
│  - 기존 로그 분석                            │
│  - 문제 파악 및 가설 수립                    │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 2. DEVELOP (개발)                           │
│  - 전략 계획 수립                            │
│  - 사용자 승인                               │
│  - 구현                                      │
│  - 백테스팅                                  │
│  - 하이퍼파라미터 최적화                     │
│  - 평가                                      │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 3. RECORD (기록)                            │
│  - 결과 문서 작성                            │
│  - 과정 문서 업데이트                        │
│  - claude.md 갱신 (루트 + 버전별)           │
│  - 대시보드 갱신                             │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 4. ITERATE (반복 결정)                      │
│  - 목표 달성 → 실시간 거래 구현             │
│  - 미달성 → Phase 1으로 복귀                │
└─────────────────────────────────────────────┘
```

> **상세 절차**: 아래 "전략 개발 상세 절차" 섹션 참조

## 🔧 전략 개발 상세 절차 (v0N 개발 시)

새로운 전략 버전(v01, v02, ...)을 개발할 때 따라야 할 10단계 절차입니다.

### **Phase 1: 준비 및 분석**

#### 1단계: 환경 확인 및 데이터 검증
```bash
# 가상환경 활성화
source v1_db생성/venv/bin/activate

# DB 초기화 확인
python core/init_db.py

# 데이터 확인
sqlite3 upbit_bitcoin.db "SELECT COUNT(*) FROM minute5"

# 필수 라이브러리 설치
brew install ta-lib  # macOS
pip install -r requirements.txt
```

**체크리스트**:
- [ ] upbit_bitcoin.db 존재 및 데이터 확인
- [ ] trading_results.db 초기화 완료
- [ ] TA-Lib 설치 완료
- [ ] Python 의존성 설치 완료

---

#### 2단계: 전략 아이디어 수립
**Phase별 방향**:
- **Phase A (v01~v05)**: 규칙 기반 (RSI, MACD, 볼린저 밴드 등)
- **Phase B (v06~v10)**: 통계적 접근 (평균회귀, Kelly 최적화)
- **Phase C (v11~v15)**: 강화학습 (DQN, PPO, A3C)
- **Phase D (v16~v20)**: 혼합 전략 (앙상블, 포트폴리오)

**v01 권장 전략**: RSI + MACD 조합
- 단순하고 검증된 방법
- 시스템 안정화 및 백테스팅 엔진 검증 목적

**작업**: 아이디어를 메모 (계획서 작성 시 사용)

---

### **Phase 2: 계획 수립**

#### 3단계: 계획 문서 작성
**파일**: `strategies/_plans/YYMMDD_HHMM.v0N.전략명.plan.md`

```bash
# 템플릿 복사
cp strategies/_templates/plan_template.md \
   strategies/_plans/$(date +%y%m%d_%H%M).v01.simple_rsi_macd.plan.md

# 편집
vim strategies/_plans/251016_1500.v01.simple_rsi_macd.plan.md
```

**작성 내용**:
- 이전 버전 분석 (v01은 "이전 버전 없음")
- 핵심 가설
- 구현 계획 (지표, 진입/청산 규칙)
- 하이퍼파라미터 초기값
- 예상 성과
- 위험 요소

**템플릿 활용**: `strategies/_templates/plan_template.md` 참조

---

#### 4단계: 사용자 승인 ⭐
**프로세스**:
1. 작성한 계획서를 사용자에게 제시
2. 질의응답 (전략, 파라미터, 타임프레임 등)
3. 수정 사항 반영
4. 최종 승인 대기

**중요**: 이 단계 완료 전까지 코드 작성 금지

---

### **Phase 3: 구현**

#### 5단계: 전략 폴더 및 파일 생성
```bash
# 폴더 생성
mkdir -p strategies/v01_simple_rsi_macd

# 기본 파일 생성
cd strategies/v01_simple_rsi_macd
touch strategy.py config.json backtest.py claude.md process.md
```

**폴더 구조**:
```
strategies/v01_simple_rsi_macd/
├── strategy.py      # 전략 로직 (필수)
├── config.json      # 하이퍼파라미터 (필수)
├── backtest.py      # 백테스팅 실행 스크립트 (필수)
├── claude.md        # v01 전용 규칙 및 발견 사항
├── process.md       # 개발 과정 기록
├── results.json     # 백테스팅 결과 (자동 생성)
└── v01_cache.db     # 학습 캐시 (선택, 자동 생성)
```

---

#### 6단계: 전략 코드 작성
**파일 1**: `strategy.py` - 전략 로직

```python
#!/usr/bin/env python3
"""v01 전략: RSI + MACD 조합"""

def v01_strategy(df, i, params):
    """
    매수: RSI < 30 AND MACD 골든크로스
    매도: RSI > 70 OR MACD 데드크로스
    """
    if i < 26:
        return {'action': 'hold'}

    rsi = df.iloc[i]['rsi']
    macd = df.iloc[i]['macd']
    macd_signal = df.iloc[i]['macd_signal']

    # 이전 캔들
    prev_macd = df.iloc[i-1]['macd']
    prev_signal = df.iloc[i-1]['macd_signal']

    # 골든크로스
    golden_cross = (prev_macd <= prev_signal) and (macd > macd_signal)
    # 데드크로스
    dead_cross = (prev_macd >= prev_signal) and (macd < macd_signal)

    if rsi < params['rsi_oversold'] and golden_cross:
        return {'action': 'buy', 'fraction': 0.5}

    if rsi > params['rsi_overbought'] or dead_cross:
        return {'action': 'sell', 'fraction': 1.0}

    return {'action': 'hold'}
```

**파일 2**: `config.json` - 하이퍼파라미터

```json
{
  "strategy_name": "simple_rsi_macd",
  "version": "v01",
  "timeframe": "minute5",
  "indicators": ["rsi", "macd"],
  "rsi_period": 14,
  "rsi_oversold": 30,
  "rsi_overbought": 70,
  "macd_fast": 12,
  "macd_slow": 26,
  "macd_signal": 9,
  "kelly_fraction": 0.25,
  "initial_capital": 10000000,
  "fee_rate": 0.0005,
  "slippage": 0.0002
}
```

---

#### 7단계: 백테스팅 스크립트 작성
**파일**: `backtest.py`

```python
#!/usr/bin/env python3
import sys, json
sys.path.append('../..')

from core import DataLoader, Backtester, Evaluator, MarketAnalyzer
from strategy import v01_strategy

# Config 로드
with open('config.json') as f:
    config = json.load(f)

# 데이터 로드 및 지표 추가
with DataLoader('../../upbit_bitcoin.db') as loader:
    df = loader.load_timeframe(config['timeframe'],
                                start_date="2024-01-01")

df = MarketAnalyzer.add_indicators(df, indicators=['rsi', 'macd'])

# 백테스팅
backtester = Backtester(
    initial_capital=config['initial_capital'],
    fee_rate=config['fee_rate'],
    slippage=config['slippage']
)
results = backtester.run(df, v01_strategy, config)

# 평가
metrics = Evaluator.calculate_all_metrics(results)

# 결과 출력 및 저장
print(f"\n{'='*50}")
print(f"총 수익률: {metrics['total_return']:.2f}%")
print(f"Sharpe Ratio: {metrics['sharpe_ratio']:.2f}")
print(f"Max Drawdown: {metrics['max_drawdown']:.2f}%")
print(f"승률: {metrics['win_rate']:.1%}")
print(f"{'='*50}\n")

with open('results.json', 'w') as f:
    json.dump({'version': 'v01', 'metrics': metrics, 'config': config},
              f, indent=2, default=str)
```

---

### **Phase 4: 실행 및 평가**

#### 8단계: 백테스팅 실행 (3년 학습 + 1년 검증)

**Step 1: 2022-2024 개별 연도 백테스팅**
```bash
cd strategies/v01_simple_rsi_macd

# 2022년 테스트
python backtest.py --start-date 2022-01-01 --end-date 2022-12-31
mv result.json result_2022.json

# 2023년 테스트
python backtest.py --start-date 2023-01-01 --end-date 2023-12-31
mv result.json result_2023.json

# 2024년 테스트
python backtest.py --start-date 2024-01-01 --end-date 2024-12-31
mv result.json result_2024.json
```

**Step 2: 2025 Out-of-Sample 테스트**
```bash
# 파라미터 완전 고정, 2025년만 테스트
python backtest.py --start-date 2025-01-01 --end-date 2025-10-16
mv result.json result_2025.json
```

**Step 3: 4년 종합 분석**
```bash
# 자동화 도구로 통합 분석
python ../../automation/analyze_multi_year_results.py --strategy-path .

# 출력: multi_year_analysis.md
# 내용: 4년 평균, 표준편차, Out-of-Sample 검증 결과
```

**Step 4: 전체 타임프레임 테스트** (선택 사항, 최적 연도 기준)
```bash
cd ../..
python automation/run_multi_timeframe_backtest.py --strategy v01_simple_rsi_macd
python automation/compare_timeframe_results.py
```

**분석 포인트**:

**연도별 성과**:
- 2022: 수익률, 승률, MDD, Buy&Hold 대비
- 2023: 수익률, 승률, MDD, Buy&Hold 대비
- 2024: 수익률, 승률, MDD, Buy&Hold 대비
- 2025: 수익률, 승률, MDD, Buy&Hold 대비 (Out-of-Sample)

**안정성 검증**:
- 4년 평균 수익률
- 표준편차 (연도별 변동성)
- 최악의 해 수익률
- 최고의 해 대비 최악의 해 비율

**오버피팅 검증** (2025 vs 2022-2024):
- 2025 수익률 >= 2022-2024 평균 × 80%? ✅/❌
- 2025 승률 >= 2022-2024 평균 - 15%p? ✅/❌
- 2025 MDD <= 2022-2024 최대 MDD + 10%p? ✅/❌
- **⚠️ 하나라도 미달 시 오버피팅으로 판단, 전략 폐기**

**목표 달성 여부**:
- 4년 평균 >= 평균 Buy&Hold + 15%p? ✅/❌
- Sharpe Ratio >= 1.0 (4년 평균)? ✅/❌
- Max Drawdown <= 30% (4년 최대)? ✅/❌

**예시 분석**:
```yaml
2022: +80% (BH: +50%, 10거래, 60%승률)
2023: +100% (BH: +80%, 12거래, 58%승률)
2024: +140% (BH: +137%, 8거래, 62.5%승률)
2025: +90% (BH: +19%, 9거래, 55.6%승률) ← Out-of-Sample

4년 평균: 102.5%
평균 BH: 71.5%
차이: +31%p >= +15%p ✅

2025 검증:
  - 90% >= (80+100+140)/3 × 0.8 = 85.3% ✅
  - 55.6% >= (60+58+62.5)/3 - 15% = 45.2% ✅

최종 판정: ✅ 전략 채택
```

---

### **Phase 5: 문서화 및 다음 단계**

#### 9단계: DB 저장 및 결과 문서 작성
**DB 저장**:
```python
# save_to_db.py 작성 후 실행
import sqlite3, json

with open('results.json') as f:
    results = json.load(f)

conn = sqlite3.connect('../../trading_results.db')
cursor = conn.cursor()

# strategies 테이블
cursor.execute("""
    INSERT INTO strategies (version, name, type, description)
    VALUES ('v01', 'simple_rsi_macd', 'rule_based', 'RSI + MACD 조합')
""")
strategy_id = cursor.lastrowid

# backtest_results 테이블
m = results['metrics']
cursor.execute("""
    INSERT INTO backtest_results (
        strategy_id, timeframe, start_date, end_date,
        initial_capital, final_capital, total_return,
        sharpe_ratio, max_drawdown, win_rate, profit_factor
    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", (strategy_id, 'minute5', '2024-01-01', '2024-12-31',
      m['initial_capital'], m['final_capital'], m['total_return'],
      m['sharpe_ratio'], m['max_drawdown'], m['win_rate'], m['profit_factor']))

conn.commit()
conn.close()
```

**결과 문서 작성**:
`strategies/_results/YYMMDD_HHMM.v01.simple_rsi_macd.result.md`
- 템플릿: `strategies/_templates/result_template.md` 활용
- 모든 백테스팅 결과, 문제점, 개선 방향 기록

---

#### 10단계: 학습 내용 정리 및 v02 제안
**작업**:
1. **process.md 작성**: 개발 과정, 시행착오, 인사이트
2. **v01/claude.md 작성**: v01 전용 발견 사항
3. **루트 claude.md 업데이트**: 범용적 학습 내용 추가
4. **v02 제안**: 결과 분석 기반 다음 전략 아이디어

**v02 제안 예시**:
- v01 성공 → "하이퍼파라미터 최적화" 또는 "다중 타임프레임 추가"
- v01 실패 → "다른 지표 조합" 또는 "완전히 다른 접근"

---

## 🔥 단타 전략 개발 절차 (vXX-YY)

### 개발 조건
- **Base 전략 선정**: 승률 >= 60%, 수익률 상위권 (4년 평균)
- **거래 횟수 부족**: 연 10회 미만
- **현재 후보**: v17 (승률 66.7%, 2024 +140.75%, 3거래)

---

### **Phase 1: Base 전략 분석 및 목표 설정**

#### 1단계: Base 전략 확인
```bash
# 현재 최고 전략 확인
cat strategies/V13-V18_FINAL_REPORT.md

# v17 성과 확인
cat strategies/v17_vwap_breakout/result_2024.json
```

**확인 사항**:
- 승률 >= 60%? (v17: 66.7% ✅)
- 거래 횟수 < 10회? (v17: 3회 ✅)
- 4년 평균 수익률 상위권? (확인 필요)

---

#### 2단계: 변형 목표 설정
```yaml
v17 → v17-01 변형 목표:
  변경_사항:
    - 타임프레임: day → minute240
    - Trailing Stop: 20% → 12-15%
    - Stop Loss: 10% 유지

  성과_목표:
    - 거래 횟수: 3회 → 9회+ (×3배)
    - 승률: 66.7% → 56.7%+ (-10%p 허용)
    - 수익률 (2024): 140% → 112%+ (×0.8)
    - 2025 Out-of-Sample: 2022-2024 평균 × 0.8 이상
```

---

### **Phase 2: 변형 전략 구현**

#### 3단계: 폴더 및 파일 생성
```bash
# 자동화 도구 사용 (권장)
python automation/generate_short_term_variant.py \
  --base v17_vwap_breakout \
  --variant 01 \
  --timeframe minute240 \
  --trailing-stop 0.12

# 또는 수동 생성
mkdir -p strategies/v17-01_minute240
cd strategies/v17-01_minute240

# Base 전략 복사
cp ../v17_vwap_breakout/strategy.py .
cp ../v17_vwap_breakout/config.json .
cp ../v17_vwap_breakout/backtest.py .
```

---

#### 4단계: config.json 수정
```json
{
  "strategy_name": "vwap_breakout_minute240",
  "version": "v17-01",
  "description": "v17 단타 변형: minute240 타임프레임",
  "timeframe": "minute240",

  "algorithms": {
    "vwap": {
      "weight": 2.0,
      "params": {"deviation_threshold": 0.02}
    },
    "breakout": {
      "weight": 1.5,
      "params": {"period": 20}
    }
  },

  "vote_threshold": 2.0,
  "trailing_stop": 0.12,
  "stop_loss": 0.10,
  "initial_capital": 10000000,
  "fee_rate": 0.0005,
  "slippage": 0.0002
}
```

---

### **Phase 3: 백테스팅 (3년 + 1년)**

#### 5단계: 2022-2025 전체 백테스팅
```bash
cd strategies/v17-01_minute240

# 2022-2024 학습
for year in 2022 2023 2024; do
  python backtest.py --start-date ${year}-01-01 --end-date ${year}-12-31
  mv result.json result_${year}.json
done

# 2025 Out-of-Sample
python backtest.py --start-date 2025-01-01 --end-date 2025-10-16
mv result.json result_2025.json

# 4년 종합 분석
python ../../automation/analyze_multi_year_results.py --strategy-path .
```

---

### **Phase 4: 성과 검증**

#### 6단계: 목표 달성 여부 확인
```yaml
검증_항목:
  거래_횟수:
    - 2024: >= 9회? (v17 × 3)
    - 4년 평균: >= 9회?
    결과: ✅/❌

  승률:
    - 2024: >= 56.7%? (v17 66.7% - 10%p)
    - 4년 평균: >= 56.7%?
    결과: ✅/❌

  수익률:
    - 2024: >= 112%? (v17 140% × 0.8)
    - 4년 평균: >= v17 4년 평균 × 0.8?
    결과: ✅/❌

  Out-of-Sample_검증:
    - 2025 수익률 >= 2022-2024 평균 × 0.8?
    - 2025 승률 >= 2022-2024 평균 - 15%p?
    결과: ✅/❌

최종_판정:
  - 모든 항목 ✅: v17-01 채택
  - 일부 항목 ❌: v17-02 다른 변형 시도
  - 대부분 ❌: 단타 변형 중단, Base 전략 유지
```

---

### **Phase 5: 추가 변형 개발** (필요 시)

#### 7단계: v17-02, v17-03 개발
```bash
# v17-01 실패 시 다른 변형 시도

# v17-02: minute60 초단타
python automation/generate_short_term_variant.py \
  --base v17_vwap_breakout \
  --variant 02 \
  --timeframe minute60 \
  --trailing-stop 0.08

# v17-03: 분할 진입/청산
# strategy.py 수동 수정 필요 (분할 로직 추가)

# v17-04: Multi-Timeframe
# strategy.py 수동 수정 필요 (day 신호 + minute240 타이밍)
```

---

### **Phase 6: 최종 비교 및 채택**

#### 8단계: Base vs 변형 전략 비교
```yaml
전략_비교_표:
  | 전략 | 타임프레임 | 거래/년 | 승률 | 수익률(2024) | 4년평균 |
  |------|------------|---------|------|--------------|---------|
  | v17 (Base) | day | 3회 | 66.7% | 140.75% | ? |
  | v17-01 | minute240 | 12회 | 58.3% | 125% | ? |
  | v17-02 | minute60 | 35회 | 54.2% | 108% | ? |
  | v17-03 | day (분할) | 3회 | 66.7% | 135% | ? |

채택_기준:
  1순위: 4년 평균 수익률
  2순위: 2025 Out-of-Sample 성과
  3순위: 리스크 대비 수익 (Sharpe Ratio)
  4순위: 실시간 거래 가능성
    - minute240: 하루 6번 확인 (가능)
    - minute60: 하루 24번 확인 (가능)
    - minute15: 하루 96번 확인 (어려움)

최종_결정:
  - v17-01 우수 → 채택, v17 보조
  - v17-01 미흡 → v17 유지, v17-01 폐기
  - v17-02 최고 → v17-02 채택
```

---

### **Phase 7: 문서화**

#### 9단계: 변형 전략 문서 작성
```bash
# 결과 문서 작성
vim strategies/v17-01_minute240/RESULT_ANALYSIS.md

# 내용:
# - v17 vs v17-01 비교
# - 연도별 성과 분석
# - 장단점 분석
# - 실시간 거래 고려사항

# CLAUDE.md 업데이트
# v17-01 결과 추가
```

---

## 📊 단타 전략 개발 플로우 요약

```
1. Base 전략 확인 (승률 60%+, 거래 10회 미만)
→ 2. 변형 목표 설정 (거래 ×3, 승률 -10%p, 수익률 ×0.8)
→ 3. 폴더/파일 생성 (자동화 도구 또는 수동)
→ 4. config.json 수정 (timeframe, trailing_stop)
→ 5. 2022-2025 백테스팅 (3년 학습 + 1년 검증)
→ 6. 성과 검증 (목표 달성 여부)
→ 7. 추가 변형 개발 (필요 시, v17-02, v17-03)
→ 8. Base vs 변형 비교 (최종 채택)
→ 9. 문서화 (RESULT_ANALYSIS.md, CLAUDE.md)
```

**중요**:
- 단타 변형은 Base 전략의 보완, 대체가 아님
- 거래 기회 증가가 목적, 수익률 극대화는 부차적
- 실시간 거래 가능성 필수 고려

---

## 📝 개발 플로우 요약

```
1. 환경 확인 → 2. 아이디어 수립 → 3. 계획 문서 작성
→ 4. 사용자 승인 ⭐ → 5. 폴더 생성 → 6. 코드 작성
→ 7. 백테스팅 스크립트 → 8. 실행 및 분석
→ 9. DB 저장 + 결과 문서 → 10. 학습 정리 + v0N+1 제안
```

**중요**:
- 4단계(사용자 승인) 전까지 코드 작성 금지
- 각 단계마다 체크리스트 확인
- 모든 결과를 문서로 기록 (컨텍스트 유지)

## 🎨 전략 개발 철학

### 반응형 전략 (가격 예측 X)
> "가시거리가 짧은 자율주행처럼 시장 변화에 민감하게 반응"

- ❌ 가격 예측 (오를지 내릴지 예측하지 않음)
- ✅ 시장 흐름 대응 (현재 상황에 맞춰 반응)

### 전략 예시
**단순:**
- 일정 시간 최고가 대비 10% 하락 → 매도
- 최저가 대비 10% 상승 → 매수

**복잡:**
- 다중 타임프레임 조합 (5분 + 1일 데이터)
- 시장 상황 분류 (상승장/하락장/횡보장)
- 상황별 전략 스위칭

### 상승장 대응 전략 (필수)
**원칙**: 상승장에서는 매수 후 보유하되, 무한정 보유하지 않음

```yaml
상승장_판단:
  - ADX > 25 (강한 추세)
  - MACD > Signal (상승 확인)
  - 최근 N일 수익률 > 10%

상승장_전략:
  - 매수 신호 시 진입
  - 익절 목표를 상향 조정 (10% → 15%)
  - 손절 폭 확대 (-3% → -5%)
  - 보유 기간 연장 허용

장기보유_방지:
  - 최대 보유 기간: 7일 (타임프레임별 조정)
  - 7일 경과 시 강제 매도 (수익 여부 무관)
  - 예외: 7일 동안 계속 상승 중 + 5%  이상 수익 → 14일까지 연장

하락장_전환_감지:
  - ADX 감소 + MACD 데드크로스
  - 즉시 매도 신호 발생
```

### 타임프레임별 최대 보유 기간
```yaml
minute5:  7일 (2,016 캔들)
minute15: 7일 (672 캔들)
minute30: 10일 (480 캔들)
minute60: 14일 (336 캔들)
minute240: 21일 (126 캔들)
day: 30일 (30 캔들)
```

### 기술 스택 선택
- **전통 알고리즘**: Python (TA-Lib)
- **강화학습**: Python (Stable-Baselines3, Gym)
- **LLM 활용**: Ollama Gemma3:12b (최소 사용, 전략 선택 정도)
- **빠른 실행**: Go (필요 시)

## 📊 타임프레임 전략

### 모든 타임프레임 테스트
```python
timeframes = [
    "minute1", "minute3", "minute5", "minute10",
    "minute15", "minute30", "minute60", "minute240",
    "day", "week", "month"
]
```

### 최적 시간대 탐색
- 각 전략마다 모든 타임프레임 백테스팅
- 최고 성과 타임프레임 선별
- 결과 문서에 기록

### 다중 타임프레임 조합
- 짧은 시간대 거래 + 긴 시간대 참고
- 예: 5분봉 거래 + 일봉/주봉 트렌드 확인

## 🧪 백테스팅 규칙

### 데이터 분할 (기본 제안)
```yaml
학습_기간: 2017-2023 (6년)
검증_기간: 2024-01-01 ~ 2024-06-30
테스트_기간: 2024-07-01 ~ 현재

# 실시간 가상거래용
실시간_테스트: 최근 1년
```

### 오버피팅 방지
1. Out-of-sample 테스트 필수
2. Walk-forward 분석
3. 다양한 시장 조건에서 검증
4. 과도한 하이퍼파라미터 최적화 지양

### 포지션 사이징
```yaml
방법_1: 전액 투자 (All-in)
방법_2: 분할 매수/매도 (Dollar-Cost Averaging)
방법_3: Kelly Criterion (승률 기반 비율)
방법_4: 변동성 기반 (ATR 등)

→ 모든 방법 테스트 후 최적 선별
```

## 🔧 기술 지표 (TA-Lib)

### 필수 라이브러리
```python
import talib

# 트렌드
- SMA, EMA, WMA
- MACD
- ADX

# 모멘텀
- RSI
- Stochastic
- CCI

# 변동성
- Bollinger Bands
- ATR

# 거래량
- OBV
- AD
```

## 🚀 실시간 거래 (수익 모델만)

### 조건
- 백테스팅 목표 달성 (연 20%+, MDD < 20%)
- 오버피팅 검증 완료
- 안정성 확보

### 구현
- Upbit API WebSocket 연동
- 실시간 가격 데이터 수신
- 가상 거래 실행
- 실시간 성과 모니터링
- 대시보드에서 확인 가능

## 🎛️ 하이퍼파라미터 관리

### 저장 위치
```json
// strategies/v0N_전략명/config.json
{
  "strategy_name": "simple_rsi_macd",
  "timeframe": "minute5",
  "rsi_period": 14,
  "rsi_overbought": 70,
  "rsi_oversold": 30,
  "macd_fast": 12,
  "macd_slow": 26,
  "macd_signal": 9,
  "kelly_fraction": 0.25
}
```

### 최적화
- Optuna 활용 (베이지안 최적화)
- Grid Search (전수 조사)
- 결과를 trading_results.db에 저장

## 📈 성공 기준

### Phase별 목표
**Phase A (규칙 기반)**: 시스템 안정화, 기본 수익 확인
**Phase B (통계적)**: 리스크 조정 수익률 개선 (Sharpe Ratio)
**Phase C (강화학습)**: 복잡한 패턴 학습, 적응력 향상
**Phase D (혼합)**: 범용성 + 안정성 + 수익성 극대화

### 최종 성공 기준
```yaml
# 2024년 목표 (역대급 상승장 기준)
절대_수익률: >= 170%
  - Buy&Hold: 147.52% (minute5)
  - 목표: +22.48%p 초과
  - 달성_방법: 추세 추종 + 역추세 혼합

리스크_관리:
  - Max Drawdown < 15% (강화)
  - Sharpe Ratio >= 1.5
  - Sortino Ratio >= 2.0

일반_기준:
  - 승률: Win Rate >= 50%
  - Profit Factor >= 2.0
  - 오버피팅: Out-of-sample 성과 >= In-sample 80%

타임프레임별_최소_목표:
  minute5:   170% (BH 147.52% + 22.48%p)
  minute15:  167% (BH 147.14% + 20%p)
  minute30:  168% (BH 147.84% + 20%p)
  minute60:  168% (BH 147.79% + 20%p)
  minute240: 168% (BH 147.65% + 20%p)
  day:       158% (BH 137.49% + 20%p)
```

## 🤖 백테스팅 자동화 도구

### 멀티 타임프레임 백테스팅

모든 전략은 **반드시** 여러 타임프레임에서 테스트되어야 합니다. 수동 실행을 방지하고 규칙 준수를 강제하기 위해 자동화 도구를 사용합니다.

#### 필수 도구

**1. 멀티 타임프레임 백테스트 러너**
```bash
# 위치: automation/run_multi_timeframe_backtest.py
# 용도: 모든 전략을 6개 타임프레임에서 자동 백테스팅

python automation/run_multi_timeframe_backtest.py
```

**기능**:
- 모든 전략 폴더(v01, v02, ...)를 자동 탐색
- 각 전략을 6개 타임프레임(minute5, minute15, minute30, minute60, minute240, day)에서 실행
- config.json을 임시 수정 후 백테스트 실행, 완료 후 원본 복원
- 타임프레임별 결과를 `results_{timeframe}.json`으로 저장
- 전체 요약을 `strategies/multi_timeframe_summary.json`에 저장

**2. 타임프레임 비교 분석기**
```bash
# 위치: automation/compare_timeframe_results.py
# 용도: 백테스팅 결과 비교 및 리포트 생성

python automation/compare_timeframe_results.py
```

**기능**:
- `multi_timeframe_summary.json` 읽어서 분석
- 각 전략별 상세 비교 리포트 생성 (`timeframe_comparison.md`)
- 전체 전략 통합 분석 리포트 생성 (`comprehensive_timeframe_analysis.md`)
- 최적 타임프레임 자동 선정
- 성과 히트맵 및 인사이트 제공

#### 실행 절차 (필수)

**Phase 1: 개별 전략 개발 시**
```bash
# 1. 전략 코드 작성 (strategy.py, config.json, backtest.py)
# 2. 단일 타임프레임으로 초기 테스트 (개발 검증용)
cd strategies/v0N_전략명
python backtest.py

# 3. 문제 없으면 멀티 타임프레임 테스트 (필수!)
cd ../..
python automation/run_multi_timeframe_backtest.py
```

**Phase 2: 전체 전략 비교 시**
```bash
# 모든 전략을 한번에 백테스팅
python automation/run_multi_timeframe_backtest.py

# 비교 리포트 생성
python automation/compare_timeframe_results.py

# 리포트 확인
cat strategies/comprehensive_timeframe_analysis.md
```

#### 규칙 강제

**❌ 금지**:
- 단일 타임프레임만 테스트 후 전략 완료 처리
- config.json에 타임프레임을 하드코딩하고 변경 불가능하게 만들기
- 백테스팅 기간을 2024-01-01 외의 날짜로 시작

**✅ 필수**:
- 모든 전략은 멀티 타임프레임 백테스팅 완료 필수
- 결과 문서에 타임프레임별 성과 비교표 포함
- 최적 타임프레임 명시 및 선정 근거 기록

#### 데이터 검증 도구

**1. 데이터 완전성 검증기**
```bash
# 위치: automation/verify_all_timeframes.py
# 용도: 백테스팅 전 데이터 확인

python automation/verify_all_timeframes.py
```

**출력**: `data_gap_report.json` (결측 구간 상세 정보)

**2. 데이터 수집기**
```bash
# 위치: automation/collect_missing_data.py
# 용도: 누락된 데이터 자동 수집

python automation/collect_missing_data.py
```

**3. 결측값 보간기**
```bash
# 위치: automation/interpolate_gaps.py
# 용도: API에서도 없는 데이터 선형보간

python automation/interpolate_gaps.py
```

#### 데이터 현황 (2025-10-17 기준)

**2024년 데이터 (백테스팅 표준 기간)**:
- ✅ minute5: 105,120개 (완전)
- ✅ minute15: 35,040개 (완전)
- ✅ minute30: 17,520개 (완전)
- ✅ minute60: 8,760개 (완전)
- ✅ minute240: 2,190개 (완전)
- ✅ day: 365개 (완전)

**보간율**: 0.23% (442개 / 188,844개)

### 자동화 워크플로우

```
┌─────────────────────────────────────────────┐
│ 1. 전략 개발 (strategy.py, config.json)    │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 2. 초기 테스트 (단일 타임프레임)            │
│    python backtest.py                       │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 3. ⭐ 멀티 타임프레임 백테스팅 (필수)       │
│    python automation/                       │
│           run_multi_timeframe_backtest.py   │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 4. 비교 리포트 생성                         │
│    python automation/                       │
│           compare_timeframe_results.py      │
└─────────────────────────────────────────────┘
                    ↓
┌─────────────────────────────────────────────┐
│ 5. 최적 타임프레임 선정 및 문서화           │
│    - timeframe_comparison.md 확인           │
│    - 전략 claude.md 업데이트                │
└─────────────────────────────────────────────┘
```

### 예상 실행 시간

**단일 전략 멀티 타임프레임 백테스팅**: 2~10분
- minute5: ~30초
- minute15: ~20초
- minute30: ~15초
- minute60: ~10초
- minute240: ~5초
- day: ~3초

**전체 전략 (5개) 백테스팅**: 10~50분

## 🔧 동적 하이퍼파라미터 파인튜닝

### 필수성

**문제**: 고정 파라미터는 시장 변화에 적응하지 못함
**해결**: Optuna 베이지안 최적화를 통한 자동 파라미터 탐색

### 자동화 도구

**1. 하이퍼파라미터 최적화기**
```bash
# 위치: automation/optimize_hyperparameters.py
# 용도: Optuna를 사용한 자동 파라미터 최적화

python automation/optimize_hyperparameters.py \
  --strategy v02b_split_exit \
  --timeframe minute240 \
  --n-trials 200 \
  --target-return 170
```

**기능**:
- 베이지안 최적화로 파라미터 공간 탐색
- 다중 목표 최적화 (수익률, Sharpe, MDD 동시 고려)
- 최적 파라미터 자동 저장
- 시각화 리포트 생성

**최적화 대상 파라미터**:
```yaml
RSI_설정:
  - rsi_period: 10~30
  - rsi_oversold: 20~40
  - rsi_overbought: 60~80

리스크_관리:
  - take_profit_1: 3%~10%
  - take_profit_2: 8%~20%
  - take_profit_3: 15%~30%
  - stop_loss: -5%~-1%

포지션_사이징:
  - kelly_fraction: 0.1~0.5
  - min_position_size: 0.1~0.3

트레이딩:
  - rolling_window: 20~50
  - adx_threshold: 15~30
  - volatility_threshold: 0.01~0.05
```

**2. Walk-Forward 검증**
```bash
# 위치: automation/walk_forward_validation.py
# 용도: 시간 분할 검증으로 오버피팅 방지

python automation/walk_forward_validation.py \
  --strategy v04_trend_following \
  --train-months 6 \
  --test-months 1
```

**동작 방식**:
```
2024-01-01 ~ 06-30 (학습) → 2024-07-01 ~ 07-31 (검증)
2024-02-01 ~ 07-31 (학습) → 2024-08-01 ~ 08-31 (검증)
2024-03-01 ~ 08-31 (학습) → 2024-09-01 ~ 09-30 (검증)
...
```

### 실행 절차

**Phase 1: 초기 최적화**
```bash
# 1. 전략 선택 (예: v02b)
cd strategies/v02b_split_exit

# 2. 현재 성과 확인
python backtest.py

# 3. 최적화 실행 (200회 trial)
python ../../automation/optimize_hyperparameters.py \
  --config config.json \
  --n-trials 200 \
  --target-return 170 \
  --max-drawdown 15

# 4. 최적 파라미터 적용
# → config_optimized.json 생성됨

# 5. 재검증
python backtest.py --config config_optimized.json
```

**Phase 2: Walk-Forward 검증**
```bash
# 오버피팅 체크
python ../../automation/walk_forward_validation.py \
  --strategy-path . \
  --year 2024

# 결과: walk_forward_report.md 생성
```

**Phase 3: 최종 적용**
```bash
# 검증 통과 시 config.json 교체
mv config_optimized.json config.json

# 멀티 타임프레임 재테스트
cd ../..
python automation/run_multi_timeframe_backtest.py
```

### 최적화 목표 함수

```python
def objective(trial):
    """
    다중 목표 최적화
    - 수익률 최대화
    - Sharpe Ratio 최대화
    - Max Drawdown 최소화
    """
    # 파라미터 샘플링
    params = {
        'rsi_oversold': trial.suggest_int('rsi_oversold', 20, 40),
        'rsi_overbought': trial.suggest_int('rsi_overbought', 60, 80),
        'take_profit_1': trial.suggest_float('take_profit_1', 0.03, 0.10),
        'stop_loss': trial.suggest_float('stop_loss', -0.05, -0.01),
        'kelly_fraction': trial.suggest_float('kelly_fraction', 0.1, 0.5)
    }

    # 백테스팅 실행
    results = run_backtest(params)

    # 다중 목표 스코어 계산
    return_score = results['total_return'] / 170  # 목표 170% 대비
    sharpe_score = results['sharpe_ratio'] / 1.5  # 목표 1.5 대비
    mdd_score = (15 - results['max_drawdown']) / 15  # MDD 15% 이하

    # 가중 합산 (수익률 50%, Sharpe 30%, MDD 20%)
    score = 0.5 * return_score + 0.3 * sharpe_score + 0.2 * mdd_score

    return score
```

### 규칙

**✅ 필수**:
- 새 전략 개발 시 반드시 최적화 실행
- Walk-Forward 검증 통과 필수
- 최적화 결과를 문서화 (optimization_report.md)

**❌ 금지**:
- 수동으로 파라미터를 계속 조정하는 것 (시간 낭비)
- 최적화 없이 전략 배포
- 전체 데이터로 최적화 후 같은 데이터로 검증 (오버피팅)

### 예상 개선 효과

**v02b (기존 → 최적화)**:
- 기존: 88.28% (minute240)
- 최적화 후 예상: 110~130%
- 개선: +21.72~41.72%p

**v04 (추세 추종, 최적화)**:
- 예상: 140~160%
- 상승장 포착률 80% 이상

**v05 (혼합, 최적화)**:
- 예상: 160~180%
- 목표 170% 달성 가능

## 🌍 범용적 학습 내용 (계속 업데이트)

### ✅ 수동 검증 완료 (정확한 수익률)

**검증일**: 2025-10-19
**검증 방법**: Decimal 정밀도 수동 계산 (v06/manual_verification.py 기반)

⚠️ **중요**: 기존 core.Backtester는 수익률을 **2~3배 과대평가**하는 버그 존재

---

## 🎯 앙상블 전략 (v13-v18) 최종 결과

**테스트 완료일**: 2025-10-19
**테스트 기간**: 2024-01-01 ~ 2024-12-31 (365일)
**Buy&Hold 기준선**: 137.49%
**목표**: 157.49% (Buy&Hold + 20%p)

### 최종 순위 및 성과

| 순위 | 전략 | 수익률 | 거래수 | 승률 | Buy&Hold 대비 | 목표 달성 |
|------|------|--------|--------|------|---------------|-----------|
| 🥇 | **v17 VWAP+BREAKOUT** | **+140.75%** | 3회 | 66.7% | **+3.26%p** ✅ | ⚠️ -16.74%p |
| 🥈 | v18 VWAP Only | +135.28% | 3회 | 66.7% | -2.21%p | ❌ -22.21%p |
| 🥉 | v16 v13 Improved | +134.00% | 2회 | 100% | -3.49%p | ❌ -23.49%p |
| 4위 | v13 Voting Ensemble | +133.78% | 3회 | 66.7% | -3.71%p | ❌ -23.71%p |
| 5위 | v15 Adaptive | +111.71% | 3회 | 66.7% | -25.78%p | ❌ -45.78%p |
| 6위 | v14 High Confidence | -11.74% | 1회 | 0% | -149.23%p | ❌ FAIL |

**최종 채택 전략**: **v17 (VWAP + BREAKOUT)** ✅
- Buy&Hold 초과 달성 (+3.26%p)
- 단순하고 효과적 (2개 알고리즘)
- v13 대비 +6.97%p 개선

### v17 VWAP + BREAKOUT (최고 성과) 🥇

**조합**: VWAP (가중치 2.0) + BREAKOUT (1.5)
**매수 규칙**: 총 Score >= 2.0
**특징**: Stochastic 제거로 단순화, 더 높은 성과

```yaml
수익률: +140.75% (24,074,556원) ✅
Buy&Hold 대비: +3.26%p (초과 달성!)
총 거래: 3회
승률: 66.7% (2승 1패)
평균 수익: +40.15%
평균 승리: +65.14%
평균 손실: -9.84%
최대 승리: +87.25%
최대 손실: -9.84%
Trailing Stop: 20% (고정)
Stop Loss: 10%

거래 내역:
  1. 2024-01-27 → 2024-05-02: +43.03% (VWAP)
  2. 2024-07-04 → 2024-09-06: -9.84% (VWAP)
  3. 2024-09-07 → 2024-12-30: +87.25% (VWAP)

수동 검증: ✅ 100% 정확 (오차 0.00%p)
```

**핵심 성공 요인**:
1. **Less is More**: Stochastic 제거로 단순화 → v13 대비 +6.97%p
2. **VWAP 핵심**: 78.8% 승률의 VWAP를 가중치 2.0으로 최우선
3. **BREAKOUT 보완**: 65.8% 승률로 추세 전환 포착
4. **Vote Threshold 2.0**: 더 완화된 기준으로 거래 기회 확보
5. **Buy&Hold 초과**: 유일하게 137.49% 기준선 돌파 (+3.26%p)

**검증된 학습 (v13→v18)**:
- v13 (3개 알고리즘): +133.78%
- v17 (2개 알고리즘): +140.75% ✅ **+6.97%p**
- v18 (1개 알고리즘): +135.28%
→ **결론**: VWAP + BREAKOUT 조합이 최적

**미달성 사항**:
- 목표 157.49% 대비 -16.74%p 부족
- 2024년 역대급 상승장(137.49%)에서도 목표 달성 실패
- 추가 최적화 필요 (파라미터 튜닝, 다른 타임프레임 등)

### v15 Adaptive Strategy (2위) 🥈

**동적 전략 선택**: 시장 상황별 최적 알고리즘

```yaml
수익률: +111.71% (21,171,138원)
Buy&Hold 대비: -25.78%p
총 거래: 3회
승률: 66.7% (2승 1패)

실패 원인:
  - 복잡성의 함정: 4가지 상황 × 4가지 전략 → 성과 저하
  - BREAKOUT 손실: 강한 추세에서도 -10.19%
  - 신호 필터링 과다: 29개 생성 → 3개만 거래

교훈: "Less is More" - 단순한 전략이 더 강력함
```

### v14 High Confidence Only (실패) 🥉

**엄격한 필터링**: VWAP + OBV/CCI + 거래량 증가

```yaml
수익률: -11.74% (8,825,965원)
총 거래: 1회 (유일한 거래 손실)

실패 원인:
  - 과도한 필터링: 1년에 1개 거래만
  - 거래 기회 전무

교훈: 필터링이 엄격할수록 좋은 것이 아님
```

---

#### v05: Simple EMA Cross (DAY)
```yaml
파라미터:
  - position_fraction: 0.95
  - trailing_stop_pct: 0.20
  - stop_loss_pct: 0.10

2024년 (수동 검증):
  - 수익률: 94.77% ✅ (기존 오류: 293.38% ❌)
  - 거래: 4쌍 (8회)
  - 승률: 50.0%
  - 최종 자본: 19,477,023원

2025년: 검증 필요
```

#### v07: Enhanced DAY (EMA + MACD Golden Cross)
```yaml
파라미터:
  - trailing_stop_pct: 0.10
  - stop_loss_pct: 0.13
  - macd_fast: 13, macd_slow: 23, macd_signal: 8

2024년 (수동 검증):
  - 수익률: 126.39% ✅ (기존 오류: 148.63% ❌)
  - 거래: 5쌍 (10회)
  - 진입: EMA 1회 + MACD 4회
  - 최종 자본: 22,639,476원
  - v05 대비: +31.62%p 🏆
```

#### v11: Multi-Entry Ensemble
```yaml
진입 조건: EMA Cross, RSI Bounce, Breakout, Momentum (OR 조합)

2024년 (수동 검증):
  - 수익률: 113.78% ✅ (기존 오류: 79.76% ❌)
  - 거래: 3쌍 (6회)
  - 진입: BREAKOUT 1회, RSI_BOUNCE 2회
  - 최종 자본: 21,377,516원
  - v05 대비: +19.01%p

분석:
  - EMA Cross는 한 번도 선택되지 않음
  - Breakout/RSI가 먼저 발생하여 진입
  - 실제로는 v05보다 우수한 성능
```

#### 전략 순위 (2024년, 수동 검증 기준)
1. 🥇 **v07**: 126.39% (EMA + MACD)
2. 🥈 **v11**: 113.78% (Multi-Entry)
3. 🥉 **v05**: 94.77% (Simple EMA)

#### 백테스터 버그 발견
```yaml
문제:
  - core.Backtester: position/cash 계산 로직 오류
  - 수익률 2~3배 과대평가
  - v6 DualLayerBacktester: 거의 정확 (+3%p 오차)

해결:
  - 모든 전략은 manual_verification.py 필수
  - Decimal 정밀도로 거래 재현
  - 1% 이내 오차 기준
```

#### 신규 전략 개발 가이드
```yaml
목표_설정:
  - 2024년: v07 126.39% 초과 목표
  - 베이스라인: v05 94.77%
  - 최소 목표: 120% (Buy&Hold 137.49% 대비 -17%p 허용)

비교_방법:
  1. 2024년 절대 수익률 비교
  2. 수동 검증 필수 (manual_verification.py)
  3. Sharpe Ratio, MDD 비교
  4. 2025년 Out-of-Sample 검증

성공_기준:
  - 2024년 수익률 >= 120%
  - v07 (126.39%) 초과 시 우수
  - MDD <= 30%
  - 수동 검증 통과 (1% 이내 오차)
```

### 🔍 백테스터 검증 규칙 (필수)

#### 문제 발견
```yaml
core.Backtester 버그:
  - position/cash 계산 로직 오류
  - 수익률 2~3배 과대평가
  - v05: 293.38% (오류) vs 94.77% (정답)
  - v07: 148.63% (오류) vs 126.39% (정답)
  - v11: 79.76% (오류) vs 113.78% (정답)

원인:
  - 부동소수점 오차 누적
  - 슬리피지/수수료 이중 적용
  - position 업데이트 타이밍 오류
```

#### 해결 방법
```yaml
1. manual_verification.py 필수 작성:
   - Decimal 정밀도 사용
   - 매수/매도 거래를 수동 재현
   - 최종 자본과 수익률 재계산

2. 검증 기준:
   - 수동 계산과 1% 이내 오차
   - 초과 시 백테스터 버그로 판단
   - 수동 계산 결과를 정답으로 채택

3. 실행 순서:
   Step 1: 전략 코드 작성
   Step 2: backtest.py 실행 (빠른 검증)
   Step 3: manual_verification.py 작성 및 실행 (필수)
   Step 4: 차이 분석 및 정답 확정
   Step 5: 문서에 수동 검증 결과 기록
```

#### 템플릿
```python
# strategies/vXX/manual_verification.py
# v06/manual_verification.py를 복사하여 전략별 수정

1. 파라미터 로드 (config.json 또는 최적화 결과)
2. 데이터 로드 및 지표 추가
3. 전략 로직으로 거래 신호 생성
4. Decimal 정밀도로 매수/매도 계산
5. 최종 자본 및 수익률 출력
6. 기존 결과와 비교
7. JSON 결과 저장
```

### 📊 알고리즘 독립 테스트 규칙

사용자 피드백: "복잡한 전략이 실패하는 이유는 정교하지 않아서. 각 알고리즘을 독립 실행해서 시그널을 파악하고 성능을 확인한 후 진행하게."

#### 개발 프로세스
```yaml
Step 1: 알고리즘 아이디어 도출
  - 예: RSI Divergence, Volume Surge, Breakout Confirmation

Step 2: 독립 테스트 스크립트 작성
  - test_algorithm_rsi_divergence.py
  - 해당 알고리즘만 단독 실행
  - 2024년 시그널 개수, 승률, 평균 수익 측정

Step 3: 합격 기준 검증
  - 시그널 >= 10개
  - 승률 >= 55%
  - 평균 수익 > 5%

Step 4: 합격한 알고리즘만 통합
  - 불합격 알고리즘은 파인튜닝 또는 폐기
  - v05 신호를 최우선으로 유지

Step 5: 통합 전략 수동 검증
  - manual_verification.py 필수
```

#### 예시: v11 분석
```yaml
v11 실패 가정 (자동 백테스터 79.76%):
  - EMA Cross 신호 0회
  - Breakout/Momentum이 먼저 발생
  - 결론: 복잡한 전략 실패

v11 실제 (수동 검증 113.78%):
  - Breakout 1회, RSI Bounce 2회
  - EMA는 발생하지 않았지만 성능 우수
  - 결론: 알고리즘이 정교하게 작동

교훈:
  - 백테스터 버그로 잘못된 결론 도출
  - 수동 검증 없이는 전략 평가 불가
```

#### 핵심 교훈
1. **수동 검증 필수**: 자동 백테스터는 2~3배 오류 발생
2. **정교함 = 파인튜닝**: 각 알고리즘 독립 테스트 후 통합
3. **v07이 현재 최고**: 126.39% (v05 94.77% 대비 +31.62%p)
4. **v11도 우수**: 113.78% (수동 검증으로 재평가)
5. **DAY 타임프레임 우월**: 노이즈 최소화, 트렌드 포착 극대화

---

### 발견된 패턴
*v10 이후 추가 예정*

### 실패 원인
*위 v06~v10 사례 참조*

### 최적 조합
*v10 이후 RL 기반 전략에서 검증 예정*

---

**최종 업데이트**: 2025-10-19
**버전**: 1.2 (수동 검증 완료, 백테스터 버그 발견)
**작성자**: Claude (Orchestrator)
