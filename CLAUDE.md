# 비트코인 트레이딩 봇 - 프로젝트 가이드

**최종 업데이트**: 2025-12-18

---

## 현재 최고 전략: v35 Optimized

**상태**: Production Ready

### 성과 (Optuna 최적화 후)

| 지표 | 값 |
|------|-----|
| 누적 수익률 | +261.87% (6년) |
| CAGR | 23.91% |
| 2025 수익률 | +23.16% |
| Sharpe Ratio | 2.62 |
| MDD | -2.39% |

### 핵심 설정

```yaml
타임프레임: Day (일봉)
진입 조건: 7-Level 시장 분류 + 동적 전략
익절/손절: 동적 (시장별 TP 5~20%)
포지션 크기: 67.7%
Stop Loss: -2.1%
```

**위치**: `strategies/v35_optimized/`

---

## 프로젝트 구조

```
bitcoin-trading-bot/
├── run.py                    # 단일 진입점
│
├── trading_engine_v2/        # 메인 트레이딩 엔진 (Redis 기반)
│   ├── trading_engine.py     # DualPaperTradingEngine 클래스
│   ├── core/                 # 핵심 인프라
│   │   ├── redis_client.py   # Redis Streams
│   │   ├── config.py         # 설정
│   │   ├── message_types.py  # 메시지 정의
│   │   ├── risk_controls.py  # 위험 관리
│   │   └── trade_logger.py   # 거래 로그
│   ├── adapters/             # 거래소 어댑터
│   │   ├── upbit_trader.py   # Upbit API
│   │   ├── binance_trader.py # Binance Futures API
│   │   ├── paper_account.py  # Paper Trading 계좌
│   │   └── live_adapters.py  # Live 계좌 어댑터
│   ├── modules/              # 실행 모듈
│   │   ├── regime_router.py  # 시장 상태 라우팅
│   │   ├── strategies/       # 전략 모듈
│   │   │   └── sideways_v2.py
│   │   ├── feed_handler.py   # 가격 수집
│   │   ├── risk_manager.py   # 신호 검증
│   │   ├── execution_manager.py
│   │   └── position_manager.py
│   ├── notifications/        # 알림 시스템
│   │   ├── telegram_notifier.py
│   │   └── telegram_commands.py
│   └── scripts/              # 유틸리티 스크립트
│       ├── backtest_operational_portfolio.py
│       ├── tune_operational_router.py
│       └── setup_redis.py
│
├── strategies/               # 전략 설정/백테스트
│   ├── v35_optimized/        # 현재 최고 전략
│   ├── SHORT_V1/             # 바이낸스 숏 전략
│   ├── v-a-01 ~ v-a-15/      # Perfect Signal 연구
│   └── _archive/             # 폐기 전략
│
├── core/                     # 공통 라이브러리
│   ├── data_loader.py        # 시장 데이터 로드
│   └── backtester.py         # 백테스팅 엔진
│
├── web/                      # 대시보드
│   └── app.py
│
├── analysis/                 # 분석 결과
│   └── selected_candidate.json  # 튜닝된 운영 설정
│
└── _archive/                 # 레거시 백업
    └── live_trading_legacy/  # 구 live_trading 폴더
```

---

## 실행 방법

### 로컬 실행

```bash
# Paper Trading (기본)
python run.py --mode paper

# Live Trading (실거래)
ENABLE_LIVE_TRADING=1 python run.py --mode live

# 옵션
python run.py --mode paper \
  --upbit-capital 10000000 \
  --binance-capital 10000 \
  --interval 60 \
  --telegram-commands \
  --candidate-json analysis/selected_candidate.json
```

### Docker 배포

```bash
# .env 파일 생성
cp .env.example .env
nano .env

# 실행
docker-compose up -d

# 로그 확인
docker-compose logs -f paper-trading

# 중지
docker-compose down
```

---

## 환경 설정

```bash
# 가상환경
source venv/bin/activate

# 필수 라이브러리
brew install ta-lib  # macOS
pip install -r requirements.txt
```

**DB 구조**:
- `upbit_bitcoin.db`: 원본 데이터 (읽기 전용)
- `trading_results.db`: 백테스팅/거래 결과

---

## 트레이딩 엔진 아키텍처

### 실행 흐름

```
run.py
  └─ DualPaperTradingEngine (trading_engine_v2/trading_engine.py)
      ├─ RegimeRouter: 시장 상태 분류 (BULL/SIDEWAYS/BEAR)
      ├─ Upbit 전략: v35 또는 sideways_v2
      ├─ Binance 전략: SHORT_V1 (BEAR 시장만)
      └─ 텔레그램 알림/명령어
```

### 시장 상태 분류 (RegimeRouter)

| 상태 | 조건 | Upbit 전략 | Binance 전략 |
|------|------|------------|--------------|
| BULL_STRONG | MFI >= 52, ADX >= 25 | v35 | - |
| BULL_MODERATE | MFI >= 52, ADX >= 20 | v35 | - |
| SIDEWAYS_* | 48 < MFI < 52 | sideways_v2 | - |
| BEAR_MODERATE | MFI <= 48, ADX >= 20 | - | - |
| BEAR_STRONG | MFI <= 48, ADX >= 25 | - | short_v1 |

### 위험 관리

- **Kill-Switch**: `/kill_on`, `/kill_off` (텔레그램 명령)
- **일일 손실 한도**: 기본 5%
- **최대 포지션**: Upbit 80%, Binance 50%

---

## 백테스팅 표준

**기간**:
- 학습: 2020-01-01 ~ 2024-12-31 (5년)
- 검증: 2025-01-01 ~ 현재 (Out-of-Sample)

**Buy&Hold 기준선**:
| 연도 | 수익률 |
|------|--------|
| 2020 | +286.05% |
| 2021 | +75.82% |
| 2022 | -63.60% |
| 2023 | +170.07% |
| 2024 | +136.67% |
| 5년 누적 | +1,479.09% (CAGR 73.65%) |

**성공 기준**:
- Out-of-Sample 수익률: >= 15%
- Sharpe Ratio: >= 1.5
- Max Drawdown: <= 20%

---

## 핵심 지표 (v41 분석 기반)

1. **MFI (Money Flow Index)**: day 상관 0.170 (가장 강력)
2. **Local Minima**: 상관 0.063-0.088 (바닥 반등)
3. **Low Volatility**: minute60 역상관 -0.123 (변동성 폭발 직전)

---

## 수수료 계산

```
거래당 비용 = 0.05% (진입) + 0.05% (청산) + 0.04% (슬리피지) = 0.14%

목표 수익 >= 10 × 수수료 → 최소 1.4% 목표 필요
```

---

## 전략 개발 규칙

### 1. 계획 → 승인 → 구현

```
1. _plans/{DATE}.v{NN}.{name}.plan.md 작성
2. 사용자 승인 대기
3. 코드 작성 (strategies/v{NN}_{name}/)
4. 백테스팅 실행
5. 결과 분석 및 문서화
```

### 2. 필수 파일

```
strategies/v{NN}_{name}/
├── config.json      # 하이퍼파라미터
├── strategy.py      # 전략 로직
├── backtest.py      # 백테스팅 스크립트
└── results.json     # 결과 (자동 생성)
```

---

## 권장/금지 사항

**권장**:
- 반응형 전략 (모멘텀 추종)
- 단순한 조건 (2-3개)
- 시장 필터링 (BULL만 거래)
- 큰 타겟 (1.5%+, 수수료 극복)
- Minute60 이상 (노이즈 감소)

**금지**:
- 예측 기반 전략 (RSI < 30 → 매수)
- 복잡한 지표 조합 (3개 이상)
- 과도한 최적화 (overfitting)
- 분할 매매 (수수료 폭증)
- Day 레벨 능동 거래

---

## 참고 문서

- **배포**: `docs/DEPLOYMENT.md`
- **전략 보고서**: `strategies/_reports/`
- **Perfect Signals**: `strategies/v41_scalping_voting/analysis/perfect_signals/`
- **아카이브 문서**: `docs/_archived/`

---

## 개발 로드맵: SHORT_V1 하락장 숏 전략

### 전략 개요
- **명칭**: EMA/ADX 추세 추종 기반 비트코인 선물 단독 숏 전략
- **거래소**: 바이낸스 BTC/USDT 무기한 선물
- **목표**: 하락장에서 독립적 수익 창출, 포트폴리오 안정성 확보

### 진입 조건 (숏)
1. EMA(50)이 EMA(200) 하향 돌파 (데드 크로스)
2. ADX >= 25 (강한 추세)
3. -DI > +DI (하락 추세 우위)

### 청산 조건
- 손절: 스윙 하이 (최대 3~5%)
- 익절: R:R = 1:2.5
- 추세 반전: 골든 크로스 시 강제 청산

### 리스크 관리
- 마진: 격리 마진 (Isolated)
- 레버리지: 초기 3x 이하
- 단일 거래 최대 손실: 자금의 1%
- MDD 한도: 20%

### 개발 단계
| Phase | 내용 | 상태 |
|-------|------|------|
| 1 | 바이낸스 데이터 수집 (캔들, 펀딩비) | 완료 |
| 2 | EMA/ADX 지표 계산 로직 | 완료 |
| 3 | 백테스트 시뮬레이터 구축 | 완료 |
| 4 | 성과 분석 및 최적화 | 완료 |

### 성공 기준 (KPI)
- Profit Factor >= 1.5
- Expectancy >= 0.2
- Sharpe Ratio >= 1.0
- MDD <= 20%
- R:R Ratio >= 1:2

**상세 계획서**: `strategies/_plans/251210.SHORT_V1.plan.md`

---

## v-a 시리즈 (연구 진행 중)

**목표**: Perfect Signal 45,254개 재현 (70%+ S-Tier)

| 버전 | 상태 | 재현율 |
|------|------|--------|
| v-a-01 | 완료 (폐기) | 7.74% |
| v-a-02 | 완료 (S-Tier) | 74.12% |
| v-a-03~15 | 진행 중 | - |

---

**문서 버전**: v4.0 (2025-12-18 아키텍처 재구성)
