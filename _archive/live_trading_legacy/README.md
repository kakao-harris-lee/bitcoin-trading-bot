# 🤖 실시간 트레이딩 시스템

v35 전략 기반 비트코인 자동/수동 트레이딩 시스템

## 📋 목차

- [특징](#특징)
- [시스템 구조](#시스템-구조)
- [설치](#설치)
- [설정](#설정)
- [사용법](#사용법)
- [주의사항](#주의사항)

---

## ✨ 특징

### 전략
- **v35_optimized** 전략 기반
- **타임프레임**: Day (일봉)
- **검증된 성과**: 2025년 +24.38%, Sharpe 2.61

### 기능
✅ **텔레그램 알림**
- 매매 신호 실시간 알림
- 거래 체결 알림
- 일일 리포트
- 에러 알림

✅ **자동/수동 모드**
- 알림만 받기 (수동 모드)
- 자동 거래 (자동 모드)

✅ **안전 장치**
- API 키 암호화 저장 (.env)
- 최소 주문 금액 체크
- 에러 핸들링

---

## 🏗️ 시스템 구조

```
live_trading/
├── main.py                    # 메인 실행 스크립트
├── live_trading_engine.py     # 트레이딩 엔진
├── upbit_trader.py            # 업비트 거래 모듈
├── telegram_notifier.py       # 텔레그램 알림 모듈
└── README.md                  # 사용 설명서
```

### 컴포넌트

1. **LiveTradingEngine**
   - v35 전략 로드
   - 매일 오전 9시 신호 체크
   - 자동/수동 거래 실행

2. **UpbitTrader**
   - 업비트 API 연동
   - 시장가 매수/매도
   - 잔고 조회

3. **TelegramNotifier**
   - 텔레그램 봇 연동
   - 매매 신호 알림
   - 거래 결과 알림

---

## 🔧 설치

### 1. 필수 라이브러리 확인

```bash
pip list | grep -E "(pyupbit|telegram)"
```

이미 설치되어 있습니다:
- `pyupbit 0.2.14`
- `python-telegram-bot 13.4.1`

### 2. API 키 설정 확인

`.env` 파일이 루트 디렉토리에 생성되어 있습니다:

```bash
cat .env
```

---

## ⚙️ 설정

### .env 파일

```env
# 업비트 API 키
UPBIT_ACCESS_KEY=N3Tu6nHKL4l6dMzB4KOpYUQPycFd4Wfrv3zT61dq
UPBIT_SECRET_KEY=YzYJkqRBwM3EOfMxbk1DlvAojsx3Bj065G7ZgDcj

# 텔레그램 봇 정보
TELEGRAM_BOT_TOKEN=1940841881:AAF76QDtDg4-uYXfC7qiVayqt9Y4euh9QbQ
TELEGRAM_CHAT_ID=1594710346

# 거래 설정
INITIAL_CAPITAL=10000000
AUTO_TRADE=False
```

### v35 전략 설정

`strategies/v35_optimized/config_optimized.json` 파일에 저장되어 있습니다.
- Optuna 최적화 완료 (500 trials)
- 포지션 크기: 70%
- 동적 익절/손절

---

## 🚀 사용법

### 1. 알림만 받기 (수동 모드) - 추천

텔레그램으로 매매 신호만 받고 직접 거래합니다.

```bash
cd live_trading
python main.py
```

**실행 내용**:
- 매일 오전 9시에 신호 체크
- 매수/매도 신호를 텔레그램으로 전송
- **거래는 직접 실행**

### 2. 한 번만 실행 (테스트)

지금 당장 신호를 체크하고 알림만 받습니다.

```bash
python main.py --once
```

### 3. 자동 거래 모드 (신중하게)

⚠️ **위험**: 실제 거래가 자동으로 실행됩니다!

```bash
python main.py --auto
```

**실행 전 체크리스트**:
- [ ] 업비트 API 키가 거래 권한이 있는지 확인
- [ ] 초기 자본이 충분한지 확인 (최소 500만원 권장)
- [ ] 백테스트 결과 이해
- [ ] 손실 감수 가능 금액인지 확인

### 4. 자동 거래 + 한 번만 실행

```bash
python main.py --auto --once
```

---

## 📱 텔레그램 알림 예시

### 매수 신호
```
🟢 매매 신호: 매수

📅 날짜: 2025-11-09 09:00:00
💵 현재가: 172,450,000 KRW
📊 시장 상태: BULL_STRONG
📈 전략: trend_following

💰 매수 금액: 7,000,000 KRW
📊 포지션 크기: 70.0%
🎯 목표가 1: 182,630,000 KRW (+5.91%)
🎯 목표가 2: 191,340,000 KRW (+11.00%)
🎯 목표가 3: 203,240,000 KRW (+17.86%)
🛑 손절가: 168,810,000 KRW (-2.11%)
```

### 매도 신호
```
🔴 매매 신호: 매도

📅 날짜: 2025-11-15 09:00:00
💵 현재가: 185,200,000 KRW
💰 매도 금액: 7,520,000 KRW
📊 수익률: +7.39%
💵 수익: +517,000 KRW
📈 보유 일수: 6일
✅ 청산 이유: BULL_STRONG_TP1
```

---

## ⚠️ 주의사항

### 보안
1. **.env 파일 절대 공유 금지**
   - Git에 커밋되지 않도록 .gitignore 설정됨
   - API 키 유출 시 즉시 재발급

2. **업비트 API 권한 설정**
   - 필요한 권한만 부여 (조회, 거래)
   - 출금 권한은 부여하지 말 것

### 거래
1. **소액으로 시작**
   - 처음엔 100만원 이하로 테스트
   - 시스템 안정성 확인 후 증액

2. **알림 모드 먼저 사용**
   - 최소 1주일은 알림만 받으며 신호 검증
   - 신뢰가 생기면 자동 모드 고려

3. **정기적으로 모니터링**
   - 매일 텔레그램 확인
   - 주간 성과 리뷰
   - 이상 징후 발견 시 즉시 중단

### 전략
1. **v35는 일봉 전략**
   - 하루에 1회만 체크 (오전 9시)
   - 거래 빈도 낮음 (연 5-10회)
   - 장기 보유 (평균 10일+)

2. **시장 상황 변화 주의**
   - 백테스트는 과거 데이터
   - 미래 성과 보장 안 됨
   - 손실 가능성 항상 존재

---

## 🔍 문제 해결

### API 연결 실패
```
❌ 업비트 연결 실패: ...
```

**해결**:
1. .env 파일의 API 키 확인
2. 업비트 API 키 권한 확인
3. 네트워크 연결 확인

### 텔레그램 알림 안 옴
```
❌ 텔레그램 전송 실패: ...
```

**해결**:
1. .env 파일의 TELEGRAM_BOT_TOKEN 확인
2. TELEGRAM_CHAT_ID 확인
3. 봇과 대화 시작했는지 확인

### 거래 실패
```
❌ 주문 실패
```

**해결**:
1. KRW 잔고 충분한지 확인 (최소 5,000 KRW)
2. 업비트 API 거래 권한 확인
3. 네트워크 연결 확인

---

## 📊 성과 추적

### 로그 확인
```bash
# 실행 로그 보기
tail -f logs/trading.log
```

### 수동으로 잔고 확인
```python
from live_trading.upbit_trader import UpbitTrader

trader = UpbitTrader()
krw, btc = trader.get_balance()
total = trader.get_total_value()

print(f"KRW: {krw:,.0f}")
print(f"BTC: {btc:.8f}")
print(f"총 평가액: {total:,.0f}")
```

---

## 🛑 긴급 중단

### 프로그램 중단
```
Ctrl + C
```

### 모든 포지션 즉시 청산
```python
from live_trading.upbit_trader import UpbitTrader

trader = UpbitTrader()
trader.sell_market_order()  # 전량 매도
```

---

## 📞 지원

문제가 발생하면:
1. 로그 확인
2. 텔레그램 에러 메시지 확인
3. `.env` 파일 설정 재확인
4. 필요시 수동으로 포지션 정리

---

**면책 조항**: 이 시스템은 교육 목적으로 제공됩니다. 실제 거래에서 발생하는 손실에 대해 책임지지 않습니다. 투자는 본인 책임입니다.
