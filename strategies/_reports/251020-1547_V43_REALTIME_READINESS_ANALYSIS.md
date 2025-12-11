# v43 실시간 거래 가능성 분석

**작성일**: 2025-10-20 15:47
**대상**: v43_supreme_scalping (= v41_scalping_voting)
**목적**: 실시간 프로덕션 거래 시스템 전환 가능성 검토

---

## 🎯 Executive Summary

**결론**: ⚠️ **현재 불가능, 구현 필요**

```
현재 상태: 백테스팅 전용 (100%)
실시간 준비도: 0%

필요 작업: 전체 실시간 시스템 구축
예상 소요: 2-4주 (개발) + 2-4주 (검증)
```

---

## 📊 현재 v43 구조 분석

### 1. 프로젝트 구성
```
v43_supreme_scalping/
├── config/
│   └── v41_replica_config.json  # 백테스트 설정만
├── core/
│   └── (비어있음)              # 실시간 로직 없음
├── backtest/
│   ├── v41_replica_backtest.py  # 백테스트 엔진
│   └── run_comprehensive_backtest.py  # 대량 테스트
└── results/
    └── *.json                    # 백테스트 결과
```

**핵심 문제**:
- ✅ 백테스팅: 완벽 (2020-2025 검증 완료)
- ❌ 실시간: 구현 안 됨 (0%)

### 2. 의존성 분석

v43은 **v42 core 엔진을 사용**:
```python
# v43_supreme_scalping/backtest/v41_replica_backtest.py
sys.path.insert(0, '../../v42_ultimate_scalping/core')

from data_loader import MultiTimeframeDataLoader  # v42
from score_engine import UnifiedScoreEngine       # v42
```

**v42 core 구성**:
```
v42_ultimate_scalping/core/
├── data_loader.py        # SQLite 기반 (과거 데이터만)
├── score_engine.py       # 점수 계산 (실시간 가능)
├── exit_manager.py       # 청산 로직 (실시간 가능)
├── position_manager.py   # 포지션 관리 (실시간 가능)
└── confluence.py         # 다중 TF 필터 (실시간 가능)
```

**가용성**:
- ✅ `score_engine.py`: 실시간 사용 가능 (데이터만 넣으면 점수 계산)
- ✅ `exit_manager.py`: 실시간 사용 가능 (청산 조건 판단)
- ✅ `position_manager.py`: 실시간 사용 가능 (포지션 추적)
- ❌ `data_loader.py`: **SQLite 전용**, 실시간 데이터 수집 없음

---

## ❌ 실시간 거래 불가능한 이유

### 1. 데이터 수집 시스템 없음
```python
# 현재 (백테스트)
data_loader.load_timeframe('day', '2024-01-01', '2025-01-01')
→ SQLite에서 과거 데이터 읽기

# 필요 (실시간)
realtime_collector.get_current_candle('day')
→ Upbit API에서 실시간 데이터 수집
```

**문제**:
- Upbit API 연동 없음
- 실시간 WebSocket 연결 없음
- 최신 캔들 자동 업데이트 없음

### 2. 자동 매매 시스템 없음
```python
# 필요 기능
- 시그널 탐지 (Score >= 40)
- 자동 주문 실행 (Upbit API)
- 포지션 모니터링 (청산 조건 체크)
- 자동 청산 (TP/SL 도달 시)
```

**현재 상태**: 모두 구현 안 됨

### 3. 실시간 모니터링 없음
```python
# 필요 기능
- 현재 포지션 상태
- 손익 실시간 계산
- 알림 (시그널, 청산, 오류)
- 긴급 중단 버튼
```

**현재 상태**: 백테스트 결과만 출력

### 4. 리스크 관리 시스템 없음
```python
# 필요 기능
- 일일 최대 손실 체크 (-5%)
- 연속 손실 제한 (3회)
- 강제 청산 (-10%)
- 냉각 기간 (3연속 손실 시 24h)
```

**현재 상태**: 백테스트에서만 시뮬레이션

---

## ✅ 실시간 전환을 위한 필수 구현 사항

### Phase 1: 데이터 수집 (1주)

#### 1.1 Upbit API 연동
```python
# 구현 필요: realtime_data_collector.py

import pyupbit
import websocket
import json
from datetime import datetime, timedelta

class RealtimeDataCollector:
    def __init__(self):
        self.ws = None
        self.current_price = 0
        self.current_candles = {
            'minute5': None,
            'minute15': None,
            'minute60': None,
            'minute240': None,
            'day': None
        }

    def connect_websocket(self):
        """WebSocket 연결 (실시간 가격)"""
        self.ws = websocket.WebSocketApp(
            "wss://api.upbit.com/websocket/v1",
            on_message=self.on_message,
            on_error=self.on_error
        )

    def fetch_latest_candles(self, timeframe):
        """최신 캔들 가져오기"""
        if timeframe == 'day':
            return pyupbit.get_ohlcv("KRW-BTC", interval="day", count=100)
        elif timeframe == 'minute60':
            return pyupbit.get_ohlcv("KRW-BTC", interval="minute60", count=200)
        # ... 나머지 타임프레임

    def update_candles(self):
        """1분마다 모든 타임프레임 업데이트"""
        for tf in self.current_candles:
            self.current_candles[tf] = self.fetch_latest_candles(tf)

    def get_current_data(self, timeframe):
        """현재 데이터 반환 (score_engine에 전달)"""
        return self.current_candles[timeframe]
```

**우선순위**: ⭐⭐⭐ 최상 (실시간의 핵심)

#### 1.2 데이터 검증
```python
# 구현 필요: data_validator.py

class DataValidator:
    def validate_candle(self, candle):
        """캔들 데이터 무결성 체크"""
        - OHLC 순서 검증
        - 거래량 양수 검증
        - 타임스탬프 순차 검증
        - 결측치 처리
```

**우선순위**: ⭐⭐ 높음

---

### Phase 2: 자동 매매 (1주)

#### 2.1 시그널 탐지
```python
# 구현 필요: signal_detector.py

class SignalDetector:
    def __init__(self):
        self.score_engine = UnifiedScoreEngine(config)
        self.data_collector = RealtimeDataCollector()

    def check_signal(self, timeframe='day', min_score=40):
        """시그널 체크 (1분마다 실행)"""
        # 1. 최신 데이터 수집
        data = self.data_collector.get_current_data(timeframe)

        # 2. 지표 계산
        data_with_indicators = self.calculate_indicators(data)

        # 3. 점수 계산
        scored = self.score_engine.calculate_score(data_with_indicators)

        # 4. 시그널 판단
        latest = scored.iloc[-1]
        if latest['tier'] == 'S' and latest['score'] >= min_score:
            return {
                'action': 'BUY',
                'price': latest['close'],
                'score': latest['score'],
                'timestamp': latest['timestamp']
            }

        return None
```

**우선순위**: ⭐⭐⭐ 최상

#### 2.2 주문 실행
```python
# 구현 필요: order_executor.py

class OrderExecutor:
    def __init__(self, api_key, api_secret):
        self.upbit = pyupbit.Upbit(api_key, api_secret)
        self.current_position = None

    def execute_buy(self, signal):
        """매수 주문 실행"""
        # 1. 잔고 확인
        balance = self.upbit.get_balance("KRW")

        # 2. 주문 실행
        result = self.upbit.buy_market_order("KRW-BTC", balance * 0.9995)

        # 3. 포지션 저장
        self.current_position = {
            'buy_price': signal['price'],
            'buy_time': signal['timestamp'],
            'amount': result['executed_volume'],
            'score': signal['score']
        }

        # 4. 알림
        self.notify(f"✅ 매수 완료: {signal['price']:,}원, Score {signal['score']}")

        return result

    def execute_sell(self, reason):
        """매도 주문 실행"""
        if not self.current_position:
            return

        # 1. 주문 실행
        result = self.upbit.sell_market_order("KRW-BTC", self.current_position['amount'])

        # 2. 손익 계산
        pnl = self._calculate_pnl(result)

        # 3. 알림
        self.notify(f"💰 매도 완료: {reason}, 수익률 {pnl:.2f}%")

        # 4. 포지션 초기화
        self.current_position = None

        return result
```

**우선순위**: ⭐⭐⭐ 최상

#### 2.3 포지션 모니터링
```python
# 구현 필요: position_monitor.py

class PositionMonitor:
    def __init__(self, executor, config):
        self.executor = executor
        self.take_profit = config['take_profit']  # 0.05
        self.stop_loss = config['stop_loss']      # -0.02
        self.max_hold_hours = config['max_hold_hours']  # 72

    def check_exit_conditions(self):
        """청산 조건 체크 (1분마다 실행)"""
        if not self.executor.current_position:
            return None

        pos = self.executor.current_position
        current_price = self.get_current_price()

        # 1. 수익률 계산
        return_pct = (current_price - pos['buy_price']) / pos['buy_price']

        # 2. 익절
        if return_pct >= self.take_profit:
            return {'action': 'SELL', 'reason': f'익절 +{return_pct*100:.2f}%'}

        # 3. 손절
        if return_pct <= self.stop_loss:
            return {'action': 'SELL', 'reason': f'손절 {return_pct*100:.2f}%'}

        # 4. 시간 초과
        hold_hours = (datetime.now() - pos['buy_time']).total_seconds() / 3600
        if hold_hours >= self.max_hold_hours:
            return {'action': 'SELL', 'reason': f'시간초과 {hold_hours:.1f}h'}

        return None
```

**우선순위**: ⭐⭐⭐ 최상

---

### Phase 3: 리스크 관리 (3일)

```python
# 구현 필요: risk_manager.py

class RiskManager:
    def __init__(self):
        self.daily_pnl = 0
        self.consecutive_losses = 0
        self.trade_history = []
        self.is_trading_allowed = True
        self.cooldown_until = None

    def check_daily_loss_limit(self):
        """일일 최대 손실 체크"""
        if self.daily_pnl <= -0.05:  # -5%
            self.stop_trading("일일 최대 손실 도달")
            return False
        return True

    def check_consecutive_losses(self):
        """연속 손실 체크"""
        if self.consecutive_losses >= 3:
            self.cooldown_until = datetime.now() + timedelta(hours=24)
            self.stop_trading("3연속 손실, 24시간 냉각")
            return False
        return True

    def record_trade(self, pnl):
        """거래 기록 및 분석"""
        self.daily_pnl += pnl

        if pnl < 0:
            self.consecutive_losses += 1
        else:
            self.consecutive_losses = 0

        self.trade_history.append({
            'timestamp': datetime.now(),
            'pnl': pnl,
            'daily_pnl': self.daily_pnl
        })

    def is_trading_allowed(self):
        """거래 허용 여부"""
        # 냉각 기간 체크
        if self.cooldown_until and datetime.now() < self.cooldown_until:
            return False

        # 일일 손실 한도
        if not self.check_daily_loss_limit():
            return False

        # 연속 손실
        if not self.check_consecutive_losses():
            return False

        return True
```

**우선순위**: ⭐⭐⭐ 최상 (안전장치)

---

### Phase 4: 알림 시스템 (2일)

```python
# 구현 필요: notification_service.py

import requests

class NotificationService:
    def __init__(self, telegram_token, chat_id):
        self.token = telegram_token
        self.chat_id = chat_id

    def send_signal_alert(self, signal):
        """시그널 발생 알림"""
        message = f"""
🔔 시그널 발생!

타임프레임: {signal['timeframe']}
가격: {signal['price']:,}원
점수: {signal['score']}점
시간: {signal['timestamp']}
        """
        self.send_telegram(message)

    def send_exit_alert(self, exit_info):
        """청산 알림"""
        message = f"""
💰 청산 완료

이유: {exit_info['reason']}
수익률: {exit_info['pnl']:.2f}%
보유시간: {exit_info['hold_hours']:.1f}시간
        """
        self.send_telegram(message)

    def send_emergency_alert(self, reason):
        """긴급 알림"""
        message = f"""
🚨 긴급 상황!

{reason}

즉시 확인 필요!
        """
        self.send_telegram(message)

    def send_telegram(self, message):
        """Telegram 전송"""
        url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        requests.post(url, data={
            'chat_id': self.chat_id,
            'text': message
        })
```

**우선순위**: ⭐⭐ 높음

---

### Phase 5: 메인 실행 루프 (2일)

```python
# 구현 필요: main_realtime.py

import time
from threading import Thread

class RealtimeTradingBot:
    def __init__(self, config):
        self.data_collector = RealtimeDataCollector()
        self.signal_detector = SignalDetector()
        self.order_executor = OrderExecutor(API_KEY, API_SECRET)
        self.position_monitor = PositionMonitor(self.order_executor, config)
        self.risk_manager = RiskManager()
        self.notifier = NotificationService(TELEGRAM_TOKEN, CHAT_ID)

        self.is_running = False

    def start(self):
        """봇 시작"""
        self.is_running = True

        # 1. 데이터 수집 스레드
        Thread(target=self.data_collection_loop, daemon=True).start()

        # 2. 시그널 탐지 스레드
        Thread(target=self.signal_detection_loop, daemon=True).start()

        # 3. 포지션 모니터링 스레드
        Thread(target=self.position_monitoring_loop, daemon=True).start()

        print("✅ 실시간 거래 봇 시작")
        self.notifier.send_telegram("✅ 거래 봇 시작됨")

    def data_collection_loop(self):
        """데이터 수집 루프 (1분마다)"""
        while self.is_running:
            try:
                self.data_collector.update_candles()
                time.sleep(60)
            except Exception as e:
                self.notifier.send_emergency_alert(f"데이터 수집 오류: {e}")

    def signal_detection_loop(self):
        """시그널 탐지 루프 (1분마다)"""
        while self.is_running:
            try:
                # 거래 허용 여부
                if not self.risk_manager.is_trading_allowed():
                    time.sleep(60)
                    continue

                # 포지션 없을 때만
                if not self.order_executor.current_position:
                    signal = self.signal_detector.check_signal(
                        timeframe='day',
                        min_score=40
                    )

                    if signal:
                        # 매수 실행
                        self.order_executor.execute_buy(signal)
                        self.notifier.send_signal_alert(signal)

                time.sleep(60)

            except Exception as e:
                self.notifier.send_emergency_alert(f"시그널 탐지 오류: {e}")

    def position_monitoring_loop(self):
        """포지션 모니터링 루프 (1분마다)"""
        while self.is_running:
            try:
                exit_signal = self.position_monitor.check_exit_conditions()

                if exit_signal:
                    # 청산 실행
                    result = self.order_executor.execute_sell(exit_signal['reason'])

                    # 리스크 관리에 기록
                    pnl = self._calculate_pnl(result)
                    self.risk_manager.record_trade(pnl)

                    # 알림
                    self.notifier.send_exit_alert({
                        'reason': exit_signal['reason'],
                        'pnl': pnl,
                        'hold_hours': result['hold_hours']
                    })

                time.sleep(60)

            except Exception as e:
                self.notifier.send_emergency_alert(f"포지션 모니터링 오류: {e}")

    def stop(self):
        """봇 중지"""
        self.is_running = False

        # 포지션 있으면 청산
        if self.order_executor.current_position:
            self.order_executor.execute_sell("봇 중지")

        print("❌ 실시간 거래 봇 중지")
        self.notifier.send_telegram("❌ 거래 봇 중지됨")


if __name__ == "__main__":
    # Config 로드
    with open('config.json') as f:
        config = json.load(f)

    # 봇 생성 및 시작
    bot = RealtimeTradingBot(config)

    try:
        bot.start()

        # 무한 대기
        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n사용자 중지 요청")
        bot.stop()
```

**우선순위**: ⭐⭐⭐ 최상 (통합)

---

## 📋 실시간 전환 체크리스트

### 필수 구현 (Phase 1-5)
- [ ] `realtime_data_collector.py` (WebSocket + pyupbit)
- [ ] `data_validator.py` (데이터 무결성)
- [ ] `signal_detector.py` (시그널 탐지)
- [ ] `order_executor.py` (Upbit API 주문)
- [ ] `position_monitor.py` (청산 조건 체크)
- [ ] `risk_manager.py` (리스크 관리)
- [ ] `notification_service.py` (Telegram 알림)
- [ ] `main_realtime.py` (메인 루프)

### 설정 파일
- [ ] `realtime_config.json` (API 키, 파라미터)
- [ ] `.env` (비밀키 관리)

### 테스트
- [ ] 데이터 수집 테스트 (1시간 이상)
- [ ] API 주문 테스트 (소액)
- [ ] 알림 시스템 테스트
- [ ] 긴급 중단 테스트
- [ ] Paper Trading (2주)

### 인프라
- [ ] 24시간 운영 서버 (AWS/GCP)
- [ ] 데이터베이스 (SQLite → PostgreSQL)
- [ ] 로깅 시스템
- [ ] 모니터링 대시보드

---

## ⏱️ 예상 개발 일정

| Phase | 작업 | 소요 | 우선순위 |
|-------|------|------|----------|
| Phase 1 | 데이터 수집 | 1주 | ⭐⭐⭐ |
| Phase 2 | 자동 매매 | 1주 | ⭐⭐⭐ |
| Phase 3 | 리스크 관리 | 3일 | ⭐⭐⭐ |
| Phase 4 | 알림 시스템 | 2일 | ⭐⭐ |
| Phase 5 | 메인 루프 | 2일 | ⭐⭐⭐ |
| **합계** | **개발** | **2-3주** | - |
| Testing | Paper Trading | 2-4주 | ⭐⭐⭐ |
| Deploy | 소액 실거래 | 4-8주 | ⭐⭐⭐ |
| **총** | **프로덕션 배포** | **8-15주** | - |

**최소 배포 시점**: 2025-12-15 (8주 후)
**권장 배포 시점**: 2026-01-05 (12주 후)

---

## 💡 최종 결론

### ❌ 현재 상태: 실시간 거래 불가능

**이유**:
1. 데이터 수집 시스템 없음 (0%)
2. 자동 매매 시스템 없음 (0%)
3. 리스크 관리 시스템 없음 (0%)
4. 알림 시스템 없음 (0%)
5. 실시간 모니터링 없음 (0%)

### ✅ 전환 가능성: 높음

**근거**:
- v42 core 엔진 재사용 가능 (score_engine, exit_manager 등)
- 백테스트 검증 완료 (2020-2025, 522% 평균)
- 명확한 Entry/Exit 조건 (TP 5%, SL -2%, 72h)
- pyupbit 라이브러리 활용 가능

### 📅 권장 로드맵

```
Week 1-2: Phase 1 (데이터 수집)
Week 3-4: Phase 2-3 (자동 매매 + 리스크 관리)
Week 5: Phase 4-5 (알림 + 메인 루프)
Week 6-9: Paper Trading (가상 거래 검증)
Week 10-17: 소액 실거래 (100만원 → 1,000만원)
Week 18+: 본격 운영 (1억원+)
```

**최소 시작 가능 시점**: 2025-12-15 (8주 후)
**안전 시작 시점**: 2026-01-19 (12주 후)

### 🎯 우선 조치사항

1. **즉시 시작** (오늘부터):
   - pyupbit 설치 및 API 키 발급
   - Telegram Bot 생성
   - `realtime_data_collector.py` 초안 작성

2. **1주 내**:
   - Phase 1 완성 (데이터 수집)
   - 실시간 데이터 수집 1시간 테스트

3. **2주 내**:
   - Phase 2 완성 (자동 매매)
   - Paper Trading 시작

4. **4주 내**:
   - Phase 3-5 완성
   - Paper Trading 2주 검증

---

**작성자**: Claude
**최종 업데이트**: 2025-10-20 15:47
**다음 리뷰**: Phase 1 완성 후 (2025-10-27 예상)
