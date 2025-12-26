# Trading Engine V2 - 설계 문서

## 1. 개요

### 1.1 목표

- **동시성**: 여러 모듈이 동시에 실시간 데이터를 처리
- **멀티 거래소**: Upbit(Long) + Binance(Short) 동시 운영
- **시장 대응**: 상승장/하락장 모두 대응 가능한 헤지 전략
- **확장성**: 새로운 전략/거래소 추가 용이

### 1.2 현재 구조의 문제점

```
현재: Sequential Processing
┌─────────────┐
│ Main Loop   │ → 60분마다 순차 실행
├─────────────┤
│ 1. 가격조회  │
│ 2. Upbit    │ → 블로킹
│ 3. Binance  │ → 블로킹
│ 4. 상태출력  │
└─────────────┘
```

- 순차 처리로 인한 지연
- 실시간 대응 불가
- 모듈 간 강한 결합

### 1.3 목표 구조

```
목표: Event-Driven Concurrent Processing
┌─────────────────────────────────────────────────────────────┐
│                     Redis Streams                           │
│  ┌─────────┐  ┌─────────┐  ┌─────────┐  ┌─────────┐        │
│  │ prices  │  │ signals │  │ orders  │  │ positions│       │
│  └─────────┘  └─────────┘  └─────────┘  └─────────┘        │
└─────────────────────────────────────────────────────────────┘
       ↑              ↑↓            ↑↓           ↑↓
┌──────┴──────┐ ┌─────┴─────┐ ┌─────┴─────┐ ┌────┴────┐
│ Feed Handler│ │ Strategy  │ │ Execution │ │Position │
│             │ │ Engines   │ │ Manager   │ │ Manager │
└─────────────┘ └───────────┘ └───────────┘ └─────────┘
                      ↓
               ┌─────────────┐
               │Risk Manager │
               └─────────────┘
```

---

## 2. 아키텍처

### 2.1 Redis Streams 구조

```
Stream Name              Purpose                    Consumers
─────────────────────────────────────────────────────────────
market:prices           실시간 가격 데이터          Strategy Engines, Risk Manager
market:orderbook        호가창 데이터               Execution Manager
strategy:signals        매매 신호                   Risk Manager → Execution
orders:pending          대기 주문                   Execution Manager
orders:executed         체결 완료                   Position Manager
positions:updates       포지션 변경                 Risk Manager, Dashboard
system:events           시스템 이벤트               All Modules
```

### 2.2 Consumer Groups

```python
# 각 모듈은 Consumer Group으로 동작
CONSUMER_GROUPS = {
    "market:prices": [
        "strategy-v35",      # Upbit Long 전략
        "strategy-short-v1", # Binance Short 전략
        "risk-manager",      # 위험 관리
        "dashboard"          # 모니터링
    ],
    "strategy:signals": [
        "risk-manager",      # 위험 검증 후 주문 전달
    ],
    "orders:pending": [
        "executor-upbit",    # Upbit 주문 실행
        "executor-binance",  # Binance 주문 실행
    ]
}
```

---

## 3. 모듈 상세 설계

### 3.1 Feed Handler (실시간 데이터 수신기)

```
┌─────────────────────────────────────────────────────────────┐
│                     Feed Handler                            │
├─────────────────────────────────────────────────────────────┤
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────┐  │
│  │ Upbit WS     │    │ Binance WS   │    │ DB Loader    │  │
│  │ (실시간)     │    │ (실시간)     │    │ (일봉/4H)    │  │
│  └──────┬───────┘    └──────┬───────┘    └──────┬───────┘  │
│         │                   │                   │          │
│         └───────────────────┼───────────────────┘          │
│                             ↓                              │
│                    ┌─────────────────┐                     │
│                    │ Data Normalizer │                     │
│                    └────────┬────────┘                     │
│                             ↓                              │
│                    ┌─────────────────┐                     │
│                    │ Redis Publisher │                     │
│                    └─────────────────┘                     │
└─────────────────────────────────────────────────────────────┘
```

**책임:**

- Upbit/Binance WebSocket 연결 관리
- 가격 데이터 정규화 (timestamp, exchange, symbol, ohlcv)
- Redis Stream에 실시간 발행
- 연결 끊김 시 자동 재연결

**메시지 포맷:**

```json
{
  "id": "1702345678901-0",
  "timestamp": 1702345678901,
  "exchange": "upbit",
  "symbol": "BTC-KRW",
  "price": 134500000,
  "volume_24h": 1234.56,
  "ohlcv": {
    "open": 134000000,
    "high": 135000000,
    "low": 133500000,
    "close": 134500000,
    "volume": 100.5
  }
}
```

---

### 3.2 Strategy Engine (전략 엔진)

```
┌─────────────────────────────────────────────────────────────┐
│                    Strategy Engine                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Base Strategy (Abstract)                │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ + subscribe_streams()                                │   │
│  │ + process_tick(data)                                 │   │
│  │ + generate_signal() → Signal                         │   │
│  │ + publish_signal(Signal)                             │   │
│  └─────────────────────────────────────────────────────┘   │
│              ↑                          ↑                   │
│    ┌─────────┴─────────┐      ┌────────┴────────┐         │
│    │ V35LongStrategy   │      │ ShortV1Strategy │         │
│    ├───────────────────┤      ├─────────────────┤         │
│    │ exchange: upbit   │      │ exchange: binance│        │
│    │ direction: long   │      │ direction: short │        │
│    │ timeframe: day    │      │ timeframe: 4h    │        │
│    └───────────────────┘      └─────────────────┘         │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**책임:**

- 실시간 가격 데이터 구독 (Redis Consumer)
- 기술적 지표 계산
- 매매 신호 생성
- 신호를 Redis Stream에 발행

**신호 포맷:**

```json
{
  "id": "sig-1702345678901",
  "timestamp": 1702345678901,
  "strategy": "v35-long",
  "exchange": "upbit",
  "symbol": "BTC-KRW",
  "action": "buy",
  "direction": "long",
  "fraction": 0.5,
  "confidence": 0.85,
  "reason": "BULL_STRONG+RSI_OVERSOLD",
  "metadata": {
    "market_state": "BULL_STRONG",
    "rsi": 28.5,
    "adx": 32.1
  }
}
```

---

### 3.3 Risk Manager (위험 관리자)

```
┌─────────────────────────────────────────────────────────────┐
│                     Risk Manager                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────┐  ┌─────────────────┐                  │
│  │ Signal Consumer │  │ Position Monitor│                  │
│  └────────┬────────┘  └────────┬────────┘                  │
│           ↓                    ↓                            │
│  ┌─────────────────────────────────────────────────────┐   │
│  │                  Risk Checks                         │   │
│  ├─────────────────────────────────────────────────────┤   │
│  │ □ Max Drawdown Check (< 20%)                        │   │
│  │ □ Position Size Limit                                │   │
│  │ □ Correlation Check (Long/Short 헤지 비율)          │   │
│  │ □ Volatility Check                                   │   │
│  │ □ Daily Loss Limit                                   │   │
│  │ □ Concurrent Position Limit                          │   │
│  └─────────────────────────────────────────────────────┘   │
│           ↓                                                 │
│  ┌─────────────────┐                                       │
│  │ Approved Orders │ → orders:pending                      │
│  └─────────────────┘                                       │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**책임:**

- 모든 신호를 검증
- 위험 한도 체크
- 포지션 크기 조정
- Long/Short 헤지 비율 관리
- 승인된 주문만 실행기로 전달

**위험 파라미터:**

```python
RISK_PARAMS = {
    "max_drawdown_pct": 20.0,       # 최대 낙폭
    "max_position_pct": 50.0,       # 최대 포지션 비율
    "daily_loss_limit_pct": 5.0,    # 일일 손실 한도
    "min_hedge_ratio": 0.3,         # 최소 헤지 비율
    "max_hedge_ratio": 0.7,         # 최대 헤지 비율
    "max_leverage": 3,              # 최대 레버리지
    "volatility_threshold": 0.05,   # 변동성 임계값
}
```

**헤지 전략 로직:**

```
상승장 (BULL):
  - Long 비중 ↑ (60-70%)
  - Short 비중 ↓ (30-40%) - 보험 역할

하락장 (BEAR):
  - Long 비중 ↓ (30-40%) - 방어적
  - Short 비중 ↑ (60-70%) - 수익 추구

횡보장 (SIDEWAYS):
  - Long 비중 = Short 비중 (50:50)
  - 변동성 낮을 시 대기
```

---

### 3.4 Position Manager (포지션 관리자)

```
┌─────────────────────────────────────────────────────────────┐
│                   Position Manager                          │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │                Position State Store                   │  │
│  ├──────────────────────────────────────────────────────┤  │
│  │ Upbit:                                                │  │
│  │   BTC-KRW: {qty: 0.05, entry: 134M, pnl: +2.5%}     │  │
│  │                                                       │  │
│  │ Binance:                                              │  │
│  │   BTCUSDT: {qty: -0.02, entry: $90K, pnl: +1.2%}    │  │
│  │            (Short Position)                           │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐  │
│  │              Position Functions                       │  │
│  ├──────────────────────────────────────────────────────┤  │
│  │ • update_position(order_result)                       │  │
│  │ • calculate_pnl()                                     │  │
│  │ • get_exposure() → {long: 60%, short: 40%}           │  │
│  │ • get_hedge_ratio() → 0.67                           │  │
│  │ • check_stop_loss()                                   │  │
│  │ • check_take_profit()                                 │  │
│  └──────────────────────────────────────────────────────┘  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**책임:**

- 실시간 포지션 추적
- PnL 계산
- 헤지 비율 계산
- Stop Loss / Take Profit 모니터링
- 포지션 상태를 Redis에 발행

**포지션 상태:**

```json
{
  "timestamp": 1702345678901,
  "total_equity_krw": 23500000,
  "positions": {
    "upbit": {
      "symbol": "BTC-KRW",
      "side": "long",
      "quantity": 0.05,
      "entry_price": 134000000,
      "current_price": 135500000,
      "unrealized_pnl": 75000,
      "unrealized_pnl_pct": 1.12
    },
    "binance": {
      "symbol": "BTCUSDT",
      "side": "short",
      "quantity": 0.02,
      "entry_price": 90500,
      "current_price": 90100,
      "leverage": 2,
      "unrealized_pnl": 8.0,
      "unrealized_pnl_pct": 0.88
    }
  },
  "hedge_ratio": 0.67,
  "total_pnl_pct": 2.13
}
```

---

### 3.5 Execution Manager (주문 실행기)

```
┌─────────────────────────────────────────────────────────────┐
│                   Execution Manager                         │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌─────────────────────────────────────────────────────┐   │
│  │              Order Router                            │   │
│  └────────────────────┬────────────────────────────────┘   │
│                       ↓                                     │
│    ┌─────────────────────────────────────────────────┐     │
│    │          Exchange Adapters                       │     │
│    ├─────────────────────────────────────────────────┤     │
│    │  ┌─────────────┐        ┌─────────────┐         │     │
│    │  │ UpbitAdapter│        │BinanceAdapter│        │     │
│    │  ├─────────────┤        ├─────────────┤         │     │
│    │  │ • buy()     │        │ • open_short│         │     │
│    │  │ • sell()    │        │ • close_short│        │     │
│    │  │ • get_balance│       │ • set_leverage│       │     │
│    │  └─────────────┘        └─────────────┘         │     │
│    └─────────────────────────────────────────────────┘     │
│                       ↓                                     │
│    ┌─────────────────────────────────────────────────┐     │
│    │         Order State Machine                      │     │
│    ├─────────────────────────────────────────────────┤     │
│    │ PENDING → SUBMITTED → PARTIAL → FILLED          │     │
│    │                    ↘ REJECTED                    │     │
│    │                    ↘ CANCELLED                   │     │
│    └─────────────────────────────────────────────────┘     │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

**책임:**

- 거래소별 주문 실행
- 주문 상태 추적
- 슬리피지 관리
- 재시도 로직
- 체결 결과를 Position Manager에 전달

**주문 흐름:**

```
orders:pending → Execution Manager → Exchange API
                       ↓
              orders:executed → Position Manager
```

---

## 4. 데이터 흐름

### 4.1 매수 시나리오 (Upbit Long)

```
1. Feed Handler
   └─→ market:prices {upbit, BTC-KRW, 134.5M}

2. V35 Strategy (Consumer)
   ├─ 가격 데이터 수신
   ├─ 지표 계산 (RSI, MACD, etc.)
   ├─ 시장 상태: BULL_STRONG
   └─→ strategy:signals {buy, long, 0.5, upbit}

3. Risk Manager (Consumer)
   ├─ 신호 수신
   ├─ 위험 체크 통과
   ├─ 포지션 크기 조정
   └─→ orders:pending {buy, 5M KRW, upbit}

4. Execution Manager (Consumer)
   ├─ 주문 수신
   ├─ Upbit API 호출
   └─→ orders:executed {filled, 0.037 BTC}

5. Position Manager (Consumer)
   ├─ 체결 결과 수신
   ├─ 포지션 업데이트
   └─→ positions:updates {long 0.037 BTC}

6. Telegram Notifier (Consumer)
   └─ 알림 전송
```

### 4.2 숏 진입 시나리오 (Binance Short)

```
1. Feed Handler
   └─→ market:prices {binance, BTCUSDT, $90,500}

2. SHORT_V1 Strategy (Consumer)
   ├─ 가격 + 펀딩비 데이터 수신
   ├─ 지표 계산 (EMA, ADX, -DI)
   ├─ 조건 충족: DEATH_CROSS + ADX>25 + DI_BEAR
   └─→ strategy:signals {open_short, 2x, binance}

3. Risk Manager (Consumer)
   ├─ 헤지 비율 체크
   ├─ 레버리지 검증
   └─→ orders:pending {short, $5000, 2x, binance}

4. Execution Manager (Consumer)
   ├─ Binance Futures API 호출
   └─→ orders:executed {filled, 0.055 BTC short}

5. Position Manager (Consumer)
   └─→ positions:updates {short 0.055 BTC, leverage 2x}
```

---

## 5. 시장 상황별 동작

### 5.1 상승장 (Bull Market)

```
시장 감지: ADX > 25, +DI > -DI, EMA_fast > EMA_slow

┌─────────────────────────────────────────────────────┐
│ V35 Strategy (Upbit Long)                           │
├─────────────────────────────────────────────────────┤
│ • 적극적 매수 (fraction: 0.6-0.8)                  │
│ • Stop Loss: 느슨하게 (-5%)                        │
│ • Take Profit: 높게 (+15%)                         │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ SHORT_V1 Strategy (Binance Short)                   │
├─────────────────────────────────────────────────────┤
│ • 숏 진입 억제 (ADX 조건 강화)                     │
│ • 기존 숏 청산 고려                                │
│ • 헤지 목적으로 최소 포지션만 유지 (20-30%)        │
└─────────────────────────────────────────────────────┘

Risk Manager 조정:
  hedge_ratio_target: 0.3 (Long 70%, Short 30%)
```

### 5.2 하락장 (Bear Market)

```
시장 감지: ADX > 25, -DI > +DI, EMA_fast < EMA_slow

┌─────────────────────────────────────────────────────┐
│ V35 Strategy (Upbit Long)                           │
├─────────────────────────────────────────────────────┤
│ • 매수 억제 (횡보/하락 필터)                       │
│ • 기존 롱 청산 고려                                │
│ • Stop Loss: 타이트하게 (-3%)                      │
└─────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────┐
│ SHORT_V1 Strategy (Binance Short)                   │
├─────────────────────────────────────────────────────┤
│ • 적극적 숏 진입 (fraction: 0.5-0.7)               │
│ • 펀딩비 고려한 포지션 사이징                      │
│ • Take Profit: R:R 2.5:1                           │
└─────────────────────────────────────────────────────┘

Risk Manager 조정:
  hedge_ratio_target: 0.7 (Long 30%, Short 70%)
```

### 5.3 횡보장 (Sideways)

```
시장 감지: ADX < 20, 볼린저 밴드 좁아짐

┌─────────────────────────────────────────────────────┐
│ 양쪽 전략 모두 대기                                │
├─────────────────────────────────────────────────────┤
│ • 신규 진입 억제                                   │
│ • 기존 포지션 유지 or 축소                         │
│ • 돌파 대기                                        │
└─────────────────────────────────────────────────────┘

Risk Manager 조정:
  hedge_ratio_target: 0.5 (Long 50%, Short 50%)
  max_position_pct: 30% (축소)
```

---

## 6. 기술 스택

### 6.1 Core Technologies

| Component | Technology | Purpose |
|-----------|------------|---------|
| Message Queue | Redis Streams | 실시간 이벤트 파이프라인 |
| State Store | Redis Hash | 포지션/상태 저장 |
| Historical DB | SQLite | 과거 데이터 저장 |
| Process Manager | Python asyncio | 비동기 동시 처리 |
| Container | Docker Compose | 배포 및 관리 |

### 6.2 Python Libraries

```python
DEPENDENCIES = {
    "redis": ">=5.0.0",          # Redis Streams 지원
    "aioredis": ">=2.0.0",       # Async Redis
    "websockets": ">=12.0",      # WebSocket 클라이언트
    "asyncio": "built-in",       # 비동기 처리
    "pydantic": ">=2.0",         # 데이터 검증
    "pyupbit": ">=0.2.34",       # Upbit API
    "python-binance": ">=1.0.0", # Binance API
}
```

---

## 7. 디렉토리 구조

```
trading/
├── core/
│   ├── __init__.py
│   ├── base_module.py          # 기본 모듈 클래스
│   ├── redis_client.py         # Redis 연결 관리
│   ├── message_types.py        # Pydantic 메시지 모델
│   └── config.py               # 설정 관리
│
├── feed_handler/
│   ├── __init__.py
│   ├── handler.py              # 메인 핸들러
│   ├── upbit_ws.py             # Upbit WebSocket
│   ├── binance_ws.py           # Binance WebSocket
│   └── data_normalizer.py      # 데이터 정규화
│
├── strategy_engine/
│   ├── __init__.py
│   ├── base_strategy.py        # 추상 전략 클래스
│   ├── v35_long_strategy.py    # Upbit Long 전략
│   ├── short_v1_strategy.py    # Binance Short 전략
│   └── indicators/
│       ├── __init__.py
│       ├── trend.py            # 추세 지표
│       ├── momentum.py         # 모멘텀 지표
│       └── volatility.py       # 변동성 지표
│
├── risk_manager/
│   ├── __init__.py
│   ├── manager.py              # 위험 관리자
│   ├── checks/
│   │   ├── drawdown.py
│   │   ├── position_size.py
│   │   ├── hedge_ratio.py
│   │   └── volatility.py
│   └── hedge_controller.py     # 헤지 비율 관리
│
├── position_manager/
│   ├── __init__.py
│   ├── manager.py              # 포지션 관리자
│   ├── pnl_calculator.py       # PnL 계산
│   └── stop_loss_monitor.py    # SL/TP 모니터
│
├── execution/
│   ├── __init__.py
│   ├── manager.py              # 실행 관리자
│   ├── order_router.py         # 주문 라우터
│   ├── adapters/
│   │   ├── base_adapter.py
│   │   ├── upbit_adapter.py
│   │   └── binance_adapter.py
│   └── order_state.py          # 주문 상태 머신
│
├── notifier/
│   ├── __init__.py
│   ├── telegram.py             # 텔레그램 알림
│   └── formatters.py           # 메시지 포맷터
│
├── dashboard/
│   ├── __init__.py
│   ├── api.py                  # FastAPI 서버
│   └── templates/
│
├── tests/
│   ├── unit/
│   └── integration/
│
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
└── main.py                     # 엔트리포인트
```

---

## 8. 실행 흐름

### 8.1 시작 순서

```python
async def main():
    # 1. Redis 연결
    redis = await create_redis_connection()

    # 2. Consumer Groups 생성
    await create_consumer_groups(redis)

    # 3. 모듈 초기화 (병렬)
    modules = await asyncio.gather(
        FeedHandler(redis).start(),
        V35LongStrategy(redis).start(),
        ShortV1Strategy(redis).start(),
        RiskManager(redis).start(),
        PositionManager(redis).start(),
        ExecutionManager(redis).start(),
        TelegramNotifier(redis).start(),
    )

    # 4. 시작 알림
    await notify_startup(modules)

    # 5. 무한 대기 (각 모듈은 독립 실행)
    await asyncio.gather(*[m.run_forever() for m in modules])
```

### 8.2 Graceful Shutdown

```python
async def shutdown():
    # 1. 신규 주문 중단
    await stop_accepting_signals()

    # 2. 대기 주문 처리 완료
    await drain_pending_orders()

    # 3. 상태 저장
    await save_state_to_disk()

    # 4. 연결 종료
    await close_all_connections()

    # 5. 종료 알림
    await notify_shutdown()
```

---

## 9. 모니터링 및 알림

### 9.1 텔레그램 알림 이벤트

| Event | Priority | Message |
|-------|----------|---------|
| 시스템 시작 | INFO | 🚀 Trading Engine V2 시작 |
| 매수/매도 체결 | HIGH | 🟢/🔴 거래 체결 알림 |
| 숏 진입/청산 | HIGH | 🔻/🔺 숏 포지션 알림 |
| 위험 경고 | CRITICAL | ⚠️ Drawdown 15% 도달 |
| 시스템 오류 | CRITICAL | ❌ 연결 끊김/오류 |
| Kill Switch 권장 | CRITICAL | ⚠️ Kill Switch 권장 (운영자 /kill_on) |
| 6시간 리포트 | INFO | 📊 정기 상태 보고 |

### 9.2 Dashboard API

```
GET  /api/status           전체 상태
GET  /api/positions        포지션 목록
GET  /api/orders           주문 이력
GET  /api/pnl              수익률
POST /api/commands/stop    긴급 정지
```

---

## 10. 마이그레이션 계획

### Phase 1: 인프라 (1주) ✅ 완료

- [x] Redis 서버 설정 (chsvr.duckdns.org, Redis 7.0.15)
- [x] Stream/Consumer Group 생성 (7 Streams, 15 Consumer Groups)
- [x] Core 모듈 기본 구조 생성 (trading/core/)

### Phase 2: Core 모듈 (2주) ✅ 완료

- [x] Base Module 구현 (base_module.py)
- [x] Feed Handler 구현 (trading/modules/feed_handler.py)
  - Upbit/Binance WebSocket 핸들러
  - 데이터 정규화 및 Redis 발행
  - 자동 재연결 로직
- [x] 단위 테스트 (tests/trading/)
  - test_feed_handler.py - 24 테스트
  - test_message_types.py - 24 테스트
  - test_redis_client.py - 16 테스트
  - 총 64개 테스트 통과

### Phase 3: 전략 마이그레이션 (2주) ✅ 완료

- [x] V35 Strategy 이식 (trading/modules/v35_long_strategy.py)
  - MarketClassifier: 7-level 시장 상태 분류
  - DynamicExitManager: 동적 익절/손절 관리
  - BaseStrategy 상속, RSI/MACD/BB/ADX/MFI 지표
- [x] SHORT_V1 Strategy 이식 (trading/modules/short_v1_strategy.py)
  - EMA(50/200) 데드크로스/골든크로스
  - ADX/+DI/-DI 추세 강도 판단
- [x] Risk Manager 구현 (trading/modules/risk_manager.py)
  - 신호 검증 (일일 손실/최대 낙폭/거래 횟수 제한)
  - 포지션 추적 및 헤지 비율 관리
  - 쿨다운 시행 및 주문 생성
- [x] 단위 테스트 37개 통과 (tests/trading/test_phase3_strategies.py)

### Phase 4: 실행/포지션 (1주) ✅ 완료

- [x] Execution Manager 구현 (trading/modules/execution_manager.py)
  - UpbitAdapter: Upbit 시장가/지정가 주문
  - BinanceAdapter: Binance Futures 레버리지 주문
  - OrderTracker: 주문 상태 추적 (CREATED → SUBMITTED → FILLED)
  - 자동 재시도 및 취소 기능
- [x] Position Manager 구현 (trading/modules/position_manager.py)
  - PositionEntry: Long/Short 포지션 추적 및 PnL 계산
  - Stop Loss / Take Profit / Trailing Stop 모니터링
  - 헤지 비율 계산 및 포트폴리오 요약
- [x] 단위 테스트 37개 통과 (tests/trading/test_phase4_execution.py)

### Phase 5: 통합 테스트 (1주)

- [ ] Paper Trading 검증
- [ ] 성능 테스트
- [ ] 장애 시나리오 테스트

### Phase 6: 배포 (1주)

- [ ] 프로덕션 배포
- [ ] 모니터링 설정
- [ ] 문서화

---

## 11. 예상 이점

| 항목 | 현재 | V2 |
|------|------|-----|
| 데이터 처리 | 60분 주기 | 실시간 (~1초) |
| 신호 반응 | 순차 처리 | 동시 처리 |
| 확장성 | 하드코딩 | 플러그인 방식 |
| 장애 복구 | 수동 | 자동 재시작 |
| 모니터링 | 로그 기반 | 실시간 대시보드 |
| 헤지 관리 | 수동 | 자동 비율 조정 |

---

## 12. 참고 자료

- Redis Streams Documentation: <https://redis.io/docs/data-types/streams/>
- Python asyncio: <https://docs.python.org/3/library/asyncio.html>
- Upbit API: <https://docs.upbit.com/>
- Binance Futures API: <https://binance-docs.github.io/apidocs/futures/en/>
