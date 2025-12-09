# Paper Trading AWS 배포 가이드

**작성일**: 2025-11-18
**목적**: v35 Optimized S-Tier 전략을 Paper Trading 모드로 AWS에서 실행

---

## 📋 개요

Paper Trading (모의 거래)로 v35 S-Tier 전략을 실전과 동일한 환경에서 검증합니다.

**목표**:
- 실거래 없이 전략 성과 검증
- 실시간 데이터로 백테스트 결과 확인
- 리스크 없이 시스템 안정성 테스트

---

## 🚀 배포 방법

### 방법 1: 기존 서비스 업데이트 (권장)

**로컬에서 실행**:

```bash
cd deployment

# EC2에 연결 (IP와 키 파일 경로 수정)
EC2_IP="13.218.242.96"
KEY_FILE="~/Downloads/bitcoin-trading-bot-key.pem"

# 서비스 파일 업로드
scp -i $KEY_FILE bitcoin-trading-bot.service ubuntu@$EC2_IP:/tmp/

# EC2에 SSH 접속
ssh -i $KEY_FILE ubuntu@$EC2_IP
```

**EC2에서 실행**:

```bash
# 서비스 중지
sudo systemctl stop bitcoin-trading-bot

# 서비스 파일 업데이트
sudo cp /tmp/bitcoin-trading-bot.service /etc/systemd/system/
sudo systemctl daemon-reload

# 서비스 시작
sudo systemctl start bitcoin-trading-bot

# 상태 확인
sudo systemctl status bitcoin-trading-bot

# 로그 확인 (Paper Trading 동작 확인)
tail -f ~/bitcoin-trading-bot/logs/trading.log
```

### 방법 2: 별도 서비스 추가 (병행 실행)

v35 실거래(알림만)와 Paper Trading을 동시에 실행하려면:

**로컬에서**:

```bash
# Paper Trading 서비스 파일 업로드
scp -i $KEY_FILE bitcoin-trading-bot-paper.service ubuntu@$EC2_IP:/tmp/
```

**EC2에서**:

```bash
# Paper Trading 서비스 설치
sudo cp /tmp/bitcoin-trading-bot-paper.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable bitcoin-trading-bot-paper
sudo systemctl start bitcoin-trading-bot-paper

# 상태 확인
sudo systemctl status bitcoin-trading-bot-paper

# 로그 확인
tail -f ~/bitcoin-trading-bot/logs/paper_trading.log
```

**두 서비스 관리**:

```bash
# 실거래(알림) 서비스
sudo systemctl status bitcoin-trading-bot
sudo systemctl restart bitcoin-trading-bot

# Paper Trading 서비스
sudo systemctl status bitcoin-trading-bot-paper
sudo systemctl restart bitcoin-trading-bot-paper
```

---

## 📊 Paper Trading 설정

### 현재 설정

**systemd 서비스 파일** (`bitcoin-trading-bot.service`):

```bash
ExecStart=/home/ubuntu/bitcoin-trading-bot/venv/bin/python main.py --paper --auto --capital 10000000
```

**옵션 설명**:
- `--paper`: Paper Trading 모드 (실거래 없음)
- `--auto`: 자동 거래 활성화 (시그널 발생 시 자동 실행)
- `--capital 10000000`: 초기 가상 자본 1천만원

### 설정 변경

**초기 자본 변경**:

```bash
# 100만원
--capital 1000000

# 1억원
--capital 100000000
```

**자동 거래 비활성화** (알림만):

```bash
# --auto 제거
ExecStart=... python main.py --paper --capital 10000000
```

---

## 📈 성과 모니터링

### 1. 실시간 로그

```bash
# SSH 접속
ssh -i $KEY_FILE ubuntu@$EC2_IP

# 실시간 로그
tail -f ~/bitcoin-trading-bot/logs/trading.log

# 에러 로그
tail -f ~/bitcoin-trading-bot/logs/error.log
```

**로그 예시**:

```
📊 Paper Trading 모드 시작
💰 초기 자본: 10,000,000 KRW
💵 현재 잔고: 10,000,000 KRW
📈 총 거래: 0건

🤖 실시간 트레이딩 엔진 시작
전략: v35_optimized (Paper Trading)
모드: 자동 거래
초기 자본: 10,000,000 KRW

[2025-11-18 12:00:00] BUY 신호 발생
  가격: 120,000,000 KRW
  전략: MOMENTUM_STRONG
  시장: BULL_STRONG

✅ [Paper] 매수: 0.05833333 BTC @ 120,000,000 KRW
💰 잔고: 3,000,000 KRW
📊 BTC: 0.05833333
💎 총 평가액: 10,000,000 KRW
```

### 2. 텔레그램 알림

Paper Trading 모드에서도 텔레그램 알림이 발송됩니다:

**매수 알림**:
```
🤖 [Paper Trading] 매수 신호

전략: v35_optimized
시장 상태: BULL_STRONG
신호: MOMENTUM_STRONG

💰 매수 가격: 120,000,000 KRW
📊 수량: 0.05833333 BTC
💵 투입 금액: 7,000,000 KRW
💎 총 평가액: 10,000,000 KRW
```

**매도 알림**:
```
💰 [Paper Trading] 매도 완료

진입 가격: 120,000,000 KRW
청산 가격: 126,000,000 KRW
보유 기간: 2일

📊 수익: +500,000 KRW (+5.00%)
💵 현재 잔고: 10,500,000 KRW
📈 총 수익률: +5.00%
```

### 3. Paper Trading 이력 파일

**위치**: `~/bitcoin-trading-bot/live_trading/paper_trading_history.json`

**내용**:

```json
{
  "initial_capital": 10000000,
  "cash": 10500000,
  "btc_balance": 0.0,
  "position": null,
  "trades": [
    {
      "type": "BUY",
      "time": "2025-11-18 12:00:00",
      "price": 120000000,
      "volume": 0.05833333,
      "amount": 7000000,
      "fee": 3500,
      "strategy": "momentum",
      "market_state": "BULL_STRONG"
    },
    {
      "type": "SELL",
      "time": "2025-11-20 14:30:00",
      "price": 126000000,
      "volume": 0.05833333,
      "amount": 7350000,
      "fee": 3675,
      "entry_price": 120000000,
      "entry_time": "2025-11-18 12:00:00",
      "profit": 500000,
      "profit_pct": 5.0,
      "hold_days": 2,
      "hold_hours": 50.5,
      "exit_reason": "TP1"
    }
  ],
  "last_updated": "2025-11-20 14:30:00"
}
```

**이력 확인**:

```bash
# EC2에서
cat ~/bitcoin-trading-bot/live_trading/paper_trading_history.json | python3 -m json.tool
```

### 4. 성과 통계

Paper Trading Manager가 자동으로 성과 통계를 계산합니다:

```python
performance = paper_trader.get_performance(current_price)

# 출력 예시:
{
  'initial_capital': 10000000,
  'current_cash': 10500000,
  'btc_balance': 0.0,
  'current_price': 126000000,
  'total_value': 10500000,
  'total_return': 5.0,          # +5.0%
  'total_profit': 500000,        # +500,000 KRW
  'total_trades': 1,
  'winning_trades': 1,
  'losing_trades': 0,
  'win_rate': 100.0,             # 100%
  'avg_profit_pct': 5.0,
  'has_position': False
}
```

---

## 🔍 모니터링 대시보드

### monitor.sh 사용

**로컬에서**:

```bash
cd deployment
./monitor.sh $EC2_IP $KEY_FILE
```

**메뉴**:
```
1. 서비스 상태 확인
2. 실시간 로그
3. 에러 로그
4. 시스템 리소스
5. Paper Trading 이력
6. 서비스 재시작
```

### 성과 확인 스크립트

**로컬에서**:

```bash
# Paper Trading 성과 조회
ssh -i $KEY_FILE ubuntu@$EC2_IP "cat ~/bitcoin-trading-bot/live_trading/paper_trading_history.json" | python3 -m json.tool
```

---

## 📊 예상 성과 (v35 S-Tier 기준)

### 월간 예상

**2025년 목표: +24.38%**

월 평균: +24.38% / 12 = **+2.03%/월**

**시나리오**:

| 기간 | 보수적 | 현실적 | 낙관적 |
|------|--------|--------|--------|
| 1주 | +0.3% | +0.5% | +0.8% |
| 2주 | +0.7% | +1.0% | +1.5% |
| 1개월 | +1.5% | +2.0% | +3.0% |

### 검증 지표

**1주 후 확인**:
- [ ] 거래 발생 (최소 1회)
- [ ] 텔레그램 알림 정상
- [ ] 이력 파일 생성
- [ ] 에러 없음

**2주 후 확인**:
- [ ] 수익률 >= +0.5%
- [ ] 거래 2-3회
- [ ] 승률 확인
- [ ] 시스템 안정성

**1개월 후 결정**:
- [ ] 수익률 >= +1.5%
- [ ] v35 S-Tier 예측과 비교
- [ ] 실거래 전환 여부 결정

---

## 🛠️ 트러블슈팅

### Paper Trading이 동작하지 않을 때

**1. 로그 확인**:

```bash
tail -100 ~/bitcoin-trading-bot/logs/trading.log
tail -100 ~/bitcoin-trading-bot/logs/error.log
```

**2. 수동 실행 테스트**:

```bash
cd ~/bitcoin-trading-bot/live_trading
source ../venv/bin/activate
python main.py --paper --capital 10000000 --once
```

**3. 모듈 확인**:

```bash
python -c "from paper_trading_manager import PaperTradingManager; print('OK')"
```

### 이력 파일 손상

**백업에서 복구**:

```bash
# 백업 (매일 자동)
cp paper_trading_history.json paper_trading_history.backup.json

# 복구
cp paper_trading_history.backup.json paper_trading_history.json
sudo systemctl restart bitcoin-trading-bot
```

**초기화** (주의: 모든 이력 삭제):

```bash
cd ~/bitcoin-trading-bot/live_trading
rm paper_trading_history.json
sudo systemctl restart bitcoin-trading-bot
```

---

## 🔐 보안 체크리스트

- [x] Paper Trading은 실거래 API 호출 없음
- [x] .env 파일 API 키 읽기 전용
- [x] 이력 파일 권한 600
- [x] 로그 파일 정기 로테이션
- [x] systemd 보안 설정 적용

---

## 📞 다음 단계

### 즉시 실행

1. **서비스 업데이트**:
   ```bash
   cd deployment
   ./deploy.sh $EC2_IP $KEY_FILE
   ```

2. **모니터링 시작**:
   ```bash
   ./monitor.sh $EC2_IP $KEY_FILE
   ```

3. **텔레그램 확인**:
   - Paper Trading 시작 알림
   - 첫 신호 대기

### 1-2주 검증

- 일일 로그 확인
- 주간 성과 리포트
- 이상 징후 모니터링

### 1개월 후 결정

**성공 시** (수익률 >= +1.5%):
- v-a-15 개발 계속 진행
- 실거래 전환 고려

**미달 시**:
- v35 S-Tier 유지
- Paper Trading 파라미터 조정

---

**작성자**: Claude Code
**배포 대상**: AWS EC2 (13.218.242.96)
**예상 소요 시간**: 10분
**위험도**: 낮음 (가상 거래만)
