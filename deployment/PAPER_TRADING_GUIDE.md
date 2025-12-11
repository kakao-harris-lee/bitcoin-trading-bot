# 🚀 Dual Exchange Paper Trading 배포 가이드

## 개요

Upbit(v35_optimized) + Binance(SHORT_V1) Dual Exchange Paper Trading 시스템

### 구성

- **Upbit**: v35_optimized 전략 (Long 포지션, 일봉)
- **Binance**: SHORT_V1 전략 (Short 포지션, 4시간봉)
- **Dashboard**: 실시간 모니터링 웹 대시보드
- **Mode**: Paper Trading (실제 거래 없음, 시뮬레이션)

---

## 📋 사전 준비

### 1. 데이터 준비

```bash
# 자동 데이터 수집
./prepare_data.sh
```

자동으로:

- ✅ Upbit 데이터 수집 (upbit_history_db 사용)
- ✅ Binance 4시간봉 + Funding Rate 수집
- ✅ 데이터 검증

### 2. 환경 변수 설정

```bash
# .env 파일 생성
cp .env.example .env
nano .env
```

Paper Trading이므로 API 키는 알림용만 필요:

```env
# 텔레그램 (선택, 알림용)
TELEGRAM_BOT_TOKEN=your_token
TELEGRAM_CHAT_ID=your_chat_id

# Upbit/Binance API 키 (Paper Trading에서는 불필요)
# UPBIT_ACCESS_KEY=not_needed_for_paper
# UPBIT_SECRET_KEY=not_needed_for_paper
```

---

## 🚀 로컬 테스트

### Docker Compose로 실행

```bash
# 빌드 및 실행
docker compose up -d

# 로그 확인
docker compose logs -f paper-trading

# 대시보드 접속
open http://localhost:8080
```

### 개별 실행 (테스트용)

```bash
# Paper Trading 엔진
python live_trading/dual_paper_trading.py \
  --upbit-capital 10000000 \
  --binance-capital 10000 \
  --interval 60

# 대시보드
cd web
python app.py
```

---

## 🖥️ 서버 배포

### 1. 데이터 준비 (로컬)

```bash
# DB 및 Binance 데이터 수집
./prepare_data.sh

# 확인
ls -lh upbit_bitcoin.db
ls -lh strategies/SHORT_V1/results/btcusdt_4h_with_funding*.csv
```

### 2. 서버로 배포

```bash
cd deployment
./deploy_to_server.sh
```

자동으로:

- ✅ 모든 파일 전송 (DB, 전략, 코드)
- ✅ Docker Compose 빌드
- ✅ 컨테이너 시작
  - paper-trading (듀얼 전략)
  - dashboard (웹 대시보드)

### 3. 모니터링

```bash
# 대화형 모니터링
./monitor_server.sh

# 또는 직접 접속
ssh deploy@49.247.171.64
cd /home/deploy/bitcoin-trading-bot

# 로그 확인
docker compose logs -f paper-trading
docker compose logs -f dashboard

# 대시보드 접속
# http://49.247.171.64:8080
```

---

## 📊 웹 대시보드

### 접속

- **로컬**: <http://localhost:8080>
- **서버**: <http://49.247.171.64:8080>

### 기능

1. **실시간 상태**
   - Upbit 포지션 및 잔고
   - Binance 포지션 및 잔고
   - 총 자산 가치

2. **통계**
   - 총 거래 횟수
   - 승률
   - 순손익
   - 수익률

3. **거래 기록**
   - 최근 거래 50개
   - 진입/청산 내역
   - 손익 내역

---

## 🔧 설정 조정

### Paper Trading 자본 변경

```yaml
# docker-compose.yml
command: python live_trading/dual_paper_trading.py \
  --upbit-capital 20000000 \      # 20M KRW
  --binance-capital 20000 \       # 20K USDT
  --interval 60                   # 60분마다 실행
```

### 실행 간격 변경

```yaml
# docker-compose.yml
command: python live_trading/dual_paper_trading.py \
  --interval 30  # 30분마다 (기본: 60분)
```

### 텔레그램 알림 비활성화

```yaml
command: python live_trading/dual_paper_trading.py \
  --no-telegram  # 텔레그램 알림 끄기
```

---

## 📝 로그 확인

### Paper Trading 로그

```bash
# 서버에서
cd /home/deploy/bitcoin-trading-bot

# JSON 로그
cat logs/paper_trading_upbit.json
cat logs/paper_trading_binance.json

# Docker 로그
docker compose logs paper-trading --tail=100
```

### 대시보드 로그

```bash
docker compose logs dashboard --tail=100
```

---

## 🔄 업데이트

### 코드 업데이트

```bash
# 로컬에서
cd deployment
./deploy_to_server.sh

# 서버에서 재시작
ssh deploy@49.247.171.64
cd /home/deploy/bitcoin-trading-bot
docker compose restart
```

### 데이터 업데이트

```bash
# 로컬에서 최신 데이터 수집
./prepare_data.sh

# 서버로 전송
rsync -avz upbit_bitcoin.db deploy@49.247.171.64:/home/deploy/bitcoin-trading-bot/
rsync -avz strategies/SHORT_V1/results/ deploy@49.247.171.64:/home/deploy/bitcoin-trading-bot/strategies/SHORT_V1/results/

# 서버에서 재시작
ssh deploy@49.247.171.64 "cd /home/deploy/bitcoin-trading-bot && docker compose restart"
```

---

## ⚠️ 주의사항

### Paper Trading 제한

- ✅ 실제 자금 없이 시뮬레이션
- ✅ 전략 검증 및 모니터링
- ❌ 실제 시장 슬리피지 미반영
- ❌ 체결 지연 미반영
- ❌ 극단적 시장 상황 대응 제한

### 실전 전환 시

Paper Trading 결과가 만족스러울 경우:

```bash
# Paper Trading 중지
docker compose down

# docker-compose.yml 수정
# paper-trading → trading-bot
# dual_paper_trading.py → dual_exchange_engine.py

# 실전 모드로 재시작
docker compose up -d
```

---

## 📞 문제 해결

### 컨테이너 시작 실패

```bash
# 로그 확인
docker compose logs paper-trading

# 일반적인 원인:
# 1. DB 파일 없음 → ./prepare_data.sh 실행
# 2. Binance CSV 없음 → cd strategies/SHORT_V1 && python data_collector.py
# 3. 전략 설정 파일 없음 → config_optimized.json 확인
```

### 대시보드 연결 안 됨

```bash
# 포트 확인
docker compose ps

# 방화벽 확인 (서버)
sudo ufw allow 8080/tcp

# 대시보드 재시작
docker compose restart dashboard
```

### 데이터 업데이트 안 됨

```bash
# Paper Trading 재시작
docker compose restart paper-trading

# 로그 확인
docker compose logs -f paper-trading
```

---

## 📊 성과 분석

### 통계 확인

```bash
# JSON 로그에서 통계 추출
cat logs/paper_trading_upbit.json | jq '.statistics'
cat logs/paper_trading_binance.json | jq '.statistics'
```

### 거래 기록 분석

```python
import json

# Upbit
with open('logs/paper_trading_upbit.json', 'r') as f:
    upbit = json.load(f)

print(f"총 거래: {upbit['statistics']['total_trades']}")
print(f"승률: {upbit['statistics']['win_rate']*100:.1f}%")
print(f"수익률: {upbit['statistics']['return_pct']:.2f}%")

# Binance
with open('logs/paper_trading_binance.json', 'r') as f:
    binance = json.load(f)

print(f"총 거래: {binance['statistics']['total_trades']}")
print(f"승률: {binance['statistics']['win_rate']*100:.1f}%")
print(f"수익률: {binance['statistics']['return_pct']:.2f}%")
```

---

## 🎯 다음 단계

1. **1주일 Paper Trading 운영**
   - 데이터 수집
   - 전략 안정성 확인
   - 수익성 검증

2. **결과 분석**
   - 승률, MDD, Sharpe Ratio
   - Upbit/Binance 상관관계
   - 포트폴리오 효과

3. **실전 전환 고려**
   - 소액 실전 테스트
   - 리스크 관리 강화
   - 모니터링 체계 구축
